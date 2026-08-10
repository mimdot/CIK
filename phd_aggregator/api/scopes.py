"""api.scopes — API-key scope vocabulary (Sprint 08, Track B1).

Scopes gate access to individual /api/v1 resources. They are granted when a
key is created and enforced by ``api.deps.require_scope``.

    read:*       read-only access to the named resource
    write:*      create/delete access to the named resource
    admin        operator-only; never grantable to a user-created key
"""

from __future__ import annotations

ALL_SCOPES: tuple[str, ...] = (
    "read:profile",
    "read:matches",
    "read:opportunities",
    "read:supervisors",
    "write:bookmarks",
    "write:feedback",
    "admin",
)

# Scopes a developer may request for their own key (admin is role-gated).
USER_SCOPES: tuple[str, ...] = tuple(s for s in ALL_SCOPES if s != "admin")

# Default scope set for a new key when the caller does not specify any.
DEFAULT_SCOPES: tuple[str, ...] = ("read:profile", "read:matches",
                                   "read:opportunities", "read:supervisors")

# Scopes a user-JWT principal gets implicitly (admin only if the account role
# is admin); used to make /api/v1 principals consistent across auth methods.
def user_jwt_scopes(role: str) -> tuple[str, ...]:
    scopes = list(ALL_SCOPES)
    if role != "admin":
        scopes.remove("admin")
    return tuple(scopes)
