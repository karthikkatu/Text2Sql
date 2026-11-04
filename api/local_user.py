"""The single, implicit user every request runs as.

SQLTexter has no login: anyone who can reach the server is the same user. The
rest of the code still namespaces graphs and usage by a ``user_id`` (the base64
of an email), so this supplies one constant identity rather than changing every
caller.

Attached as a router-level dependency, not middleware, because the MCP tools
call the routes through a separate app object that middleware on the served app
would never wrap.
"""

import base64

from fastapi import Request

LOCAL_USER_EMAIL = "local@sqltexter.local"
LOCAL_USER_NAME = "Local User"
LOCAL_USER_ID = base64.b64encode(LOCAL_USER_EMAIL.encode()).decode()


async def attach_local_user(request: Request) -> None:
    """Set the ``request.state`` identity the routes read."""
    request.state.user_id = LOCAL_USER_ID
    request.state.user_email = LOCAL_USER_EMAIL
