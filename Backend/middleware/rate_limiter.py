"""
Configuración de Rate Limiting para Argos2.
Usa Flask-Limiter con almacenamiento en memoria y limitación por IP.
"""

from flask import jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configurar limiter con almacenamiento en memoria (default)
# Se inicializa con la app en app.py mediante limiter.init_app(app)
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
    headers_enabled=True,
)


@limiter.error_handler
def rate_limit_exceeded(error):
    """Manejador personalizado para HTTP 429 (Too Many Requests)."""
    retry_after = 60  # Valor por defecto en segundos
    description = getattr(error, 'description', '')
    if description:
        try:
            retry_after = int(str(description).split()[-2]) if 'second' in str(description).lower() or 'minute' in str(description).lower() else 60
        except (ValueError, IndexError):
            retry_after = 60
    return jsonify({
        "error": "Demasiadas solicitudes. Intenta de nuevo más tarde.",
        "retry_after": retry_after
    }), 429
