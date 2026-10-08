"""Audited single-credential transport with a process-wide authentication stop."""

import os
import threading

import litellm

AUTH_LOCK = threading.Lock()
AUTH_STOP = threading.Event()
AUTH_FAILURES = 0


class AuthenticationStop(BaseException):
    """Stop the controller rather than enqueueing further failed-auth jobs."""


class ServiceBalanceStop(BaseException):
    """Provider explicitly reports insufficient balance; stop without retrying."""


def install(c, workers):
    """Load the current key once; preserve the existing redacted request ledger."""
    p4 = c.x.p4
    keys = (c.ROOT / "api.txt").read_text().split()
    p4.SECRETS = keys
    for i in range(4):
        os.environ[f"P4_API_KEY_{i + 1}"] = keys[i % len(keys)]
    p4.configure_transport(workers)
    p4.KEY_LIMITS = [threading.BoundedSemaphore(workers) for _ in range(4)]
    original = p4.audited_completion

    def audited(**kwargs):
        global AUTH_FAILURES
        if AUTH_STOP.is_set() or (c.OUT / "authentication_stop.json").exists():
            raise AuthenticationStop("Persistent HTTP401: no further requests sent")
        if (c.OUT / "balance_stop.json").exists():
            raise ServiceBalanceStop("Insufficient provider balance; no new requests")
        kwargs["num_retries"] = 0
        kwargs["timeout"] = 600.0
        try:
            result = original(**kwargs)
        except Exception as exc:
            if "insufficient account balance" in str(exc).lower():
                c.save(
                    c.OUT / "balance_stop.json",
                    {
                        "reason": "Provider returned Insufficient account balance",
                        "requests_stopped": True,
                    },
                )
                raise ServiceBalanceStop("Insufficient provider balance; stopped")
            is_auth = getattr(exc, "status_code", None) == 401 or (
                "Invalid authentication credentials" in str(exc)
            )
            if is_auth:
                with AUTH_LOCK:
                    AUTH_FAILURES += 1
                    if AUTH_FAILURES >= 2:
                        AUTH_STOP.set()
                        c.save(
                            c.OUT / "authentication_stop.json",
                            {
                                "consecutive_401": AUTH_FAILURES,
                                "requests_stopped": True,
                            },
                        )
                        raise AuthenticationStop("Two consecutive HTTP401; stopped")
            raise
        with AUTH_LOCK:
            AUTH_FAILURES = 0
        return result

    p4.audited_completion = audited

    def routed(**kwargs):
        # A single current key: no fallback to obsolete credential routes.
        kwargs["api_key"] = "os.environ/P4_API_KEY_1"
        token = p4.KEY.set(0)
        try:
            return p4.audited_completion(**kwargs)
        finally:
            p4.KEY.reset(token)

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


def retry_timeout_once(call, kwargs):
    """Repeat one timed-out transport attempt; caller audits each attempt separately."""
    try:
        return call(**kwargs)
    except (TimeoutError, litellm.Timeout):
        return call(**kwargs)
