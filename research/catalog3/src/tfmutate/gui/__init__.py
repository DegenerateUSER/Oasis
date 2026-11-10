"""Loopback-only local Oasis user interface; no hosted service or user accounts."""


def serve(**options):
    """Load the HTTP backend only when the local GUI is explicitly requested."""
    from .server import serve as run_server

    return run_server(**options)
