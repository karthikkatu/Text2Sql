"""Metadata routes (``/version``, ``/auth-status``) for the QueryWeaver API.

Their tag is not mapped to any MCP type, so FastMCP's default EXCLUDE route
map keeps them out of the MCP tool surface.
"""

from importlib.metadata import version, PackageNotFoundError

from fastapi import APIRouter

from api.local_user import LOCAL_USER_EMAIL, LOCAL_USER_ID, LOCAL_USER_NAME

# Router
meta_router = APIRouter(tags=["Meta"])


def app_version() -> str:
    """Return the running QueryWeaver version.

    Prefers installed distribution metadata; falls back to the package's
    ``__version__`` when running from a source checkout without dist metadata.
    """
    try:
        return version("queryweaver")
    except PackageNotFoundError:
        from queryweaver import __version__  # pylint: disable=import-outside-toplevel
        return __version__


@meta_router.get("/version")
async def get_version() -> dict[str, str]:
    """Public endpoint returning the application name and version."""
    return {"name": "queryweaver", "version": app_version()}


@meta_router.get("/auth-status")
async def auth_status() -> dict:
    """Report the implicit local user as signed in.

    There is no login, so the frontend's session check always succeeds. The
    ``providers`` flags are all false: no sign-in method is offered.
    """
    return {
        "authenticated": True,
        "providers": {
            "email_auth_enabled": False,
            "google_auth_enabled": False,
            "github_auth_enabled": False,
        },
        "user": {
            "id": LOCAL_USER_ID,
            "email": LOCAL_USER_EMAIL,
            "name": LOCAL_USER_NAME,
            "picture": None,
            "provider": "api",
        },
    }
