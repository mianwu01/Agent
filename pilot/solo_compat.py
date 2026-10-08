"""Constructor compatibility for the pinned runner's DummyUser mismatch."""

from tau2.registry import registry
from tau2.user.user_simulator import DummyUser


class PilotDummyUser(DummyUser):
    """Accept builder kwargs while retaining the native no-op dummy behavior."""

    def __init__(
        self,
        tools=None,
        instructions=None,
        llm=None,
        llm_args=None,
        persona_config=None,
    ):
        super().__init__()


def register_pilot_dummy_user():
    """Register the adapter without replacing any built-in component."""
    name = "pilot_dummy_user"
    if name not in registry.get_info().users:
        registry.register_user(PilotDummyUser, name)
    assert registry.get_user_constructor(name) is PilotDummyUser
    return name
