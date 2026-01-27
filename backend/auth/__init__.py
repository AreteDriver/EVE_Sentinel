"""Authentication and authorization."""

# Re-export from the original auth.py (now apikey.py)
from backend.auth.apikey import (
    APIKeyInfo,
    api_key_header,
    api_key_query,
    generate_api_key,
    get_api_key,
    hash_api_key,
    optional_api_key,
    validate_api_key,
)
from backend.auth.apikey import (
    require_api_key as require_api_key_auth,
)

# Export role-based access control
from backend.auth.permissions import (
    PermissionChecker,
    Role,
    get_current_user,
    has_role_level,
    permissions,
    require_admin,
    require_auth,
    require_recruiter,
    require_role,
    require_viewer,
)

__all__ = [
    # API key auth
    "APIKeyInfo",
    "api_key_header",
    "api_key_query",
    "generate_api_key",
    "get_api_key",
    "hash_api_key",
    "optional_api_key",
    "require_api_key_auth",
    "validate_api_key",
    # Role-based access
    "PermissionChecker",
    "Role",
    "get_current_user",
    "has_role_level",
    "permissions",
    "require_admin",
    "require_auth",
    "require_recruiter",
    "require_role",
    "require_viewer",
]
