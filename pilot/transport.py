"""Pilot-only HTTP pool configuration for sustained concurrent native runs."""

import httpx
import litellm


def configure_transport(concurrency):
    """Match the HTTP pool to workers; use normal TLS and proxy environment."""
    old = litellm.client_session
    litellm.client_session = httpx.Client(
        limits=httpx.Limits(
            max_connections=concurrency, max_keepalive_connections=concurrency
        ),
        timeout=httpx.Timeout(120.0, connect=30.0, pool=120.0),
    )
    if old is not None:
        old.close()
