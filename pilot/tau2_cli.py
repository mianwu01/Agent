"""Native tau2 CLI with the pilot-only dummy constructor adapter registered."""

from solo_compat import register_pilot_dummy_user

from tau2.cli import main

if __name__ == "__main__":
    register_pilot_dummy_user()
    main()
