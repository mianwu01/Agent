"""Responses relay adapter for isolated P4 experiments, never Codex CLI config."""

import json
import threading
import time
import uuid
from pathlib import Path

import httpx


class RelayProtocolError(RuntimeError):
    """The relay did not preserve a required experimental setting."""


def responses_payload(kwargs):
    """Convert native chat history and schemas without adding instructions."""
    systems = []
    inputs = []
    seen_non_system = False
    for message in kwargs["messages"]:
        role = message["role"]
        if role in {"system", "developer"}:
            if seen_non_system:
                raise RelayProtocolError(
                    "Interleaved system instructions cannot be flattened"
                )
            systems.append(message.get("content") or "")
            continue
        seen_non_system = True
        if role == "tool":
            inputs.append(
                {
                    "type": "function_call_output",
                    "call_id": message["tool_call_id"],
                    "output": message.get("content") or "",
                }
            )
            continue
        if message.get("content") is not None:
            inputs.append({"role": role, "content": message["content"]})
        for call in message.get("tool_calls") or []:
            function = call["function"]
            inputs.append(
                {
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": function["name"],
                    "arguments": function["arguments"],
                }
            )
    if not systems:
        raise RelayProtocolError(
            "Explicit native system prompt required; relay injects Codex defaults otherwise"
        )
    payload = {
        "model": kwargs["model"].removeprefix("openai/"),
        "instructions": "\n\n".join(systems),
        "input": inputs,
        "store": False,
        "stream": True,
        "max_output_tokens": kwargs.get("max_completion_tokens") or 8192,
    }
    if kwargs.get("temperature") is not None:
        payload["temperature"] = kwargs["temperature"]
    if kwargs.get("reasoning_effort") is not None:
        payload["reasoning"] = {"effort": kwargs["reasoning_effort"]}
    if kwargs.get("tools"):
        payload["tools"] = [
            {"type": "function", **tool["function"]} for tool in kwargs["tools"]
        ]
    if kwargs.get("tool_choice") is not None:
        choice = kwargs["tool_choice"]
        payload["tool_choice"] = (
            {"type": "function", "name": choice["function"]["name"]}
            if isinstance(choice, dict)
            else choice
        )
    if kwargs.get("response_format"):
        payload["text"] = {"format": kwargs["response_format"]}
    return payload


def completion_response(raw):
    """Convert text, native function calls and actual usage to LiteLLM's shape."""
    from litellm import ModelResponse

    content = []
    calls = []
    for item in raw.get("output", []):
        if item["type"] == "message":
            content.extend(
                part["text"]
                for part in item.get("content", [])
                if part["type"] == "output_text"
            )
        elif item["type"] == "function_call":
            calls.append(
                {
                    "id": item["call_id"],
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "arguments": item["arguments"],
                    },
                }
            )
    usage = raw.get("usage")
    converted_usage = (
        {
            "prompt_tokens": usage["input_tokens"],
            "completion_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "prompt_tokens_details": usage.get("input_tokens_details") or {},
            "completion_tokens_details": usage.get("output_tokens_details") or {},
        }
        if usage
        else None
    )
    if usage and isinstance(usage.get("cost"), (int, float)):
        converted_usage["cost"] = usage["cost"]
    return ModelResponse(
        id=raw["id"],
        model=raw["model"],
        choices=[
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "".join(content) if content else None,
                    "tool_calls": calls or None,
                },
                "finish_reason": "length"
                if raw.get("status") == "incomplete"
                else "tool_calls"
                if calls
                else "stop",
            }
        ],
        usage=converted_usage,
    )


def validate_response(payload, raw):
    """Check settings that define the experiment and its dollar reservation."""
    for field in ["model", "instructions", "temperature", "max_output_tokens", "store"]:
        if field in payload and raw.get(field) != payload[field]:
            raise RelayProtocolError(
                f"Relay changed {field}; no experiment continuation permitted"
            )
    if payload.get("reasoning"):
        if (raw.get("reasoning") or {}).get("effort") != payload["reasoning"]["effort"]:
            raise RelayProtocolError("Relay changed reasoning effort")
    if (raw.get("usage") or {}).get("output_tokens", 0) > payload["max_output_tokens"]:
        raise RelayProtocolError("Relay exceeded requested output-token cap")


class ResponsesRelay:
    """Send audited Responses requests using a private, process-local credential."""

    def __init__(self, api_base, credential_file, ledger_dir, workers=1):
        self.api_base = api_base.rstrip("/")
        self.secret = Path(credential_file).read_text().strip()
        self.ledger_dir = Path(ledger_dir)
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(
            timeout=httpx.Timeout(120, connect=30),
            limits=httpx.Limits(
                max_connections=workers, max_keepalive_connections=workers
            ),
        )

    def complete(self, **kwargs):
        """No hidden retries, environment exports, CLI configuration or prompt additions."""
        payload = responses_payload(kwargs)
        entry = {"request": payload, "started_at": time.time(), "status": "started"}
        path = self.ledger_dir / (uuid.uuid4().hex + ".json")
        raw = None
        try:
            with self.client.stream(
                "POST",
                self.api_base + "/responses",
                headers={"Authorization": "Bearer " + self.secret},
                json=payload,
            ) as response:
                entry["status_code"] = response.status_code
                if response.is_error:
                    response.read()
                    entry["error_body"] = response.text[:2000]
                    response.raise_for_status()
                if "text/event-stream" in response.headers.get("content-type", ""):
                    for line in response.iter_lines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        event = json.loads(line[6:])
                        if event.get("type") in {
                            "response.completed",
                            "response.incomplete",
                        }:
                            raw = event["response"]
                        elif event.get("type") in {"error", "response.failed"}:
                            entry["provider_error"] = event
                            raise RelayProtocolError("Relay returned failed response")
                else:
                    raw = json.loads(response.read())
            if raw is None:
                raise RelayProtocolError(
                    "Relay ended without a completed response or usage"
                )
            entry.update(response=raw, usage=raw.get("usage"), status="response")
            validate_response(payload, raw)
            return completion_response(raw)
        except Exception as exc:
            entry.update(
                status="error",
                error_type=type(exc).__name__,
                error_message=str(exc)[:2000],
            )
            raise
        finally:
            entry["seconds"] = time.time() - entry["started_at"]
            path.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2).replace(
                    self.secret, "[REDACTED]"
                )
                + "\n"
            )


def install(c, workers, provider):
    """Install only in an isolated P4 process after capability and pricing checks."""
    import c2_auth_transport as stops
    from p4_cost_control import BudgetStop

    if provider.get("capabilities_verified") is not True:
        raise BudgetStop("Relay output-limit capability not verified; no batch calls")
    p4 = c.x.p4
    relay = ResponsesRelay(
        provider["api_base"],
        c.ROOT / provider["credential_file"],
        c.OUT / "relay_requests",
        workers,
    )
    p4.SECRETS = [relay.secret]
    p4.BASE = provider["api_base"]
    p4.KEY_LIMITS = [threading.BoundedSemaphore(workers) for _ in range(4)]
    p4.ORIGINAL_COMPLETION = relay.complete
    original = p4.audited_completion
    state = {"consecutive401": 0}
    lock = threading.Lock()

    def audited(**kwargs):
        for marker in [
            "authentication_stop.json",
            "balance_stop.json",
            "protocol_stop.json",
        ]:
            if (c.OUT / marker).exists():
                raise BudgetStop(f"Relay stopped: {marker}")
        try:
            result = original(**kwargs)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                with lock:
                    state["consecutive401"] += 1
                    if state["consecutive401"] >= 2:
                        c.save(
                            c.OUT / "authentication_stop.json",
                            {"provider": "vvvcode", "consecutive401": 2},
                        )
                        raise stops.AuthenticationStop(
                            "Two consecutive relay401; stopped"
                        ) from None
            elif status in {402, 403}:
                c.save(
                    c.OUT / "balance_stop.json",
                    {"provider": "vvvcode", "status": status},
                )
                raise stops.ServiceBalanceStop(f"Relay{status}; stopped") from None
            else:
                c.save(
                    c.OUT / "protocol_stop.json",
                    {"provider": "vvvcode", "status": status},
                )
                raise BudgetStop(f"Relay HTTP{status}; stopped without retry") from None
            raise
        except RelayProtocolError as exc:
            c.save(
                c.OUT / "protocol_stop.json",
                {"provider": "vvvcode", "reason": str(exc)},
            )
            raise BudgetStop(str(exc)) from None
        with lock:
            state["consecutive401"] = 0
        return result

    p4.audited_completion = audited

    def routed(**kwargs):
        kwargs.update(api_base=provider["api_base"], api_key="private relay credential")
        return p4.audited_completion(**kwargs)

    c.x.routed_completion = routed
    p4.llm_utils.completion = routed
    import tau2.agent.llm_agent as agent_module
    import tau2.user.user_simulator as user_module

    def role_generate(role):
        def generate(**kwargs):
            token = p4.ROLE.set(role)
            try:
                return p4.llm_utils.generate(**kwargs)
            finally:
                p4.ROLE.reset(token)

        return generate

    agent_module.generate = role_generate("agent")
    user_module.generate = role_generate("user")
