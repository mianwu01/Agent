"""OpenRouter routing for the isolated cost-controlled pilot only."""

import copy
import json
import os
import random
import re
import threading
import time
from pathlib import Path

RATE_LIMIT_RETRIES = 8
TRANSIENT_ERRORS = (
    "network connection lost",
    "connection reset",
    "server disconnected",
    "unexpected_eof_while_reading",
    "eof occurred in violation of protocol",
    "remote end closed connection",
)


def load_secret(path):
    """Read one OpenRouter key; tolerate a notes file containing the key."""
    raw = Path(path).read_text(encoding="utf-8")
    match = re.search(r"sk-or-[A-Za-z0-9\-_]+", raw)
    return match.group(0) if match else raw.strip()


def target_settings(provider, model):
    """Per-target request settings (provider pin, reasoning, usage) if configured."""
    return copy.deepcopy(provider.get("model_settings", {}).get(model, {}))


def install(c, workers, provider):
    """Keep routing, credentials and stop markers scoped to the new provider."""
    import c2_auth_transport as stops

    p4 = c.x.p4
    secret = load_secret(c.ROOT / provider["credential_file"])
    p4.SECRETS = [secret]
    os.environ["OPENROUTER_API_KEY"] = secret
    p4.BASE = provider["api_base"]
    p4.configure_transport(workers)
    p4.KEY_LIMITS = [threading.BoundedSemaphore(workers) for _ in range(4)]
    original = p4.audited_completion
    state = {"consecutive401": 0}
    lock = threading.Lock()

    def audited(**kwargs):
        if (c.OUT / "authentication_stop.json").exists():
            raise stops.AuthenticationStop("Persistent401: no new requests")
        if (c.OUT / "balance_stop.json").exists():
            raise stops.ServiceBalanceStop("Provider balance stop: no new requests")
        kwargs.update(num_retries=0, timeout=600.0)
        try:
            result = rate_limited(original, kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            text = str(exc).lower()
            if (
                status == 402
                or "insufficient credits" in text
                or "insufficient account balance" in text
            ):
                c.save(
                    c.OUT / "balance_stop.json",
                    {
                        "provider": "openrouter",
                        "requests_stopped": True,
                        "reason": "insufficient credits",
                    },
                )
                raise stops.ServiceBalanceStop("OpenRouter credits exhausted") from None
            if status == 401:
                with lock:
                    state["consecutive401"] += 1
                    if state["consecutive401"] >= 2:
                        c.save(
                            c.OUT / "authentication_stop.json",
                            {
                                "provider": "openrouter",
                                "consecutive401": state["consecutive401"],
                            },
                        )
                        raise stops.AuthenticationStop(
                            "Two consecutive OpenRouter401"
                        ) from None
            raise
        with lock:
            state["consecutive401"] = 0
        return result

    p4.audited_completion = audited

    def rate_limited(call, kwargs):
        """Back off on upstream 429s only: the request was not served or charged."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return call(**kwargs)
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                text = str(exc).lower()
                limited = status == 429 or "rate-limited" in text
                # Transient transport failures; the call may have been charged,
                # so these retries are logged separately.
                transient = status in (502, 503, 504) or any(
                    t in text for t in TRANSIENT_ERRORS
                )
                if not (limited or transient) or attempt == RATE_LIMIT_RETRIES:
                    raise
                wait = min(120.0, 10.0 * 2**attempt) * (1 + random.random() / 2)
                with lock:
                    with open(c.OUT / "rate_limit_retries.jsonl", "a") as f:
                        f.write(
                            json.dumps(
                                {
                                    "time": time.time(),
                                    "attempt": attempt,
                                    "wait": wait,
                                    "kind": "rate_limit" if limited else "transient",
                                }
                            )
                            + "\n"
                        )
                time.sleep(wait)

    def routed(**kwargs):
        original_model = kwargs["model"]
        target = provider.get("model_aliases", {}).get(original_model, original_model)
        target = target.removeprefix("openrouter/")
        kwargs["model"] = "openrouter/" + target
        kwargs["api_base"] = provider["api_base"]
        kwargs["api_key"] = "os.environ/OPENROUTER_API_KEY"
        settings = target_settings(provider, target)
        for name in settings.get("drop_params", []):
            kwargs.pop(name, None)
        if settings.get("extra_body"):
            body = dict(kwargs.get("extra_body") or {})
            body.update(settings["extra_body"])
            kwargs["extra_body"] = body
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
