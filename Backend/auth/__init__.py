"""
Módulo de autenticación para Argos2.
Contiene el middleware JWT para validación de tokens.
"""

from .jwt_handler import (
    generate_token,
    generate_refresh_token,
    decode_token,
    token_required,
    admin_required,
    optional_token,
    add_token_to_blacklist,
    is_token_revoked,
    revoke_all_user_tokens,
    get_user_token_version,
    cleanup_expired_revoked_tokens,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
    JWT_REFRESH_EXPIRATION_DAYS
)

__all__ = [
    'generate_token',
    'generate_refresh_token',
    'decode_token',
    'token_required',
    'admin_required',
    'optional_token',
    'add_token_to_blacklist',
    'is_token_revoked',
    'revoke_all_user_tokens',
    'get_user_token_version',
    'cleanup_expired_revoked_tokens',
    'JWT_SECRET_KEY',
    'JWT_ALGORITHM',
    'JWT_EXPIRATION_HOURS',
    'JWT_REFRESH_EXPIRATION_DAYS'
]
