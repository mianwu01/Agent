"""OpenRouter routing for the isolated cost-controlled pilot only."""

import os
import threading


def install(c, workers, provider):
    """Keep routing, credentials and stop markers scoped to the new provider."""
    import c2_auth_transport as stops

    p4 = c.x.p4
    secret = (c.ROOT / provider["credential_file"]).read_text().strip()
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
            result = original(**kwargs)
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

    def routed(**kwargs):
        original_model = kwargs["model"]
        target = provider.get("model_aliases", {}).get(original_model, original_model)
        kwargs["model"] = "openrouter/" + target.removeprefix("openrouter/")
        kwargs["api_base"] = provider["api_base"]
        kwargs["api_key"] = "os.environ/OPENROUTER_API_KEY"
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
