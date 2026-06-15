"""
Configuración de Rate Limiting para Argos2.
Usa Flask-Limiter con almacenamiento en memoria y limitación por IP.
"""

import time

from flask import jsonify, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _handle_rate_limit_exceeded(request_limit):
    """Manejador personalizado para HTTP 429 (Too Many Requests).

    En Flask-Limiter 4.x se usa el parámetro `on_breach` del constructor
    en lugar del decorador `@limiter.error_handler` (eliminado en 3.x+).

    Args:
        request_limit: objeto RequestLimit con atributos reset_at, remaining, etc.
    """
    retry_after = 60  # Valor por defecto en segundos
    reset_at = getattr(request_limit, 'reset_at', None)
    if reset_at:
        retry_after = max(1, int(reset_at - time.time()))

    return make_response(
        jsonify({
            "error": "Demasiadas solicitudes. Intenta de nuevo más tarde.",
            "retry_after": retry_after
        }),
        429
    )


# Configurar limiter con almacenamiento en memoria (default)
# Se inicializa con la app en app.py mediante limiter.init_app(app)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
    headers_enabled=True,
    on_breach=_handle_rate_limit_exceeded,
)
