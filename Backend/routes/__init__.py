"""
Módulo de rutas API para Argos2.
Contiene los blueprints de Flask para los diferentes endpoints.
"""

from .auth import auth_bp
from .admin import admin_bp
from .vision import vision_bp

__all__ = ['auth_bp', 'admin_bp', 'vision_bp']


# =====================
# DOCUMENTACIÓN DE RUTAS
# =====================

# RUTAS DEL FRONTEND (Páginas HTML)
# ===================================
# Estas rutas son servidas por el servidor frontend (Live Server en puerto 5500)
#
# - index.html          - Página de Login (http://localhost:5500/index.html)
# - registro.html       - Página de Registro (http://localhost:5500/registro.html)
# - verificacion.html   - Página de Verificación de Correo (http://localhost:5500/verificacion.html)
# - recuperar.html      - Página de Recuperación de Contraseña (http://localhost:5500/recuperar.html)
# - reset-password.html - Página de Reset de Contraseña (http://localhost:5500/reset-password.html)


# ENDPOINTS DEL BACKEND (API REST)
# =================================
# Estos endpoints son servidos por Flask en puerto 5000
#
# Blueprint: auth_bp (prefijo: /api)
# -----------------------------------
#
# AUTENTICACIÓN:
# - POST /api/login           - Iniciar sesión
#   Body: { username, password }
#   Response: { access_token, refresh_token, user }
#
# - POST /api/logout          - Cerrar sesión (requiere token)
#   Headers: Authorization: Bearer <token>
#
# - POST /api/logout-all      - Cerrar sesión en todos los dispositivos (requiere token)
#   Headers: Authorization: Bearer <token>
#
# - POST /api/refresh         - Renovar access token
#   Body: { refresh_token }
#   Response: { access_token, refresh_token }
#
# - GET  /api/me              - Obtener información del usuario actual (requiere token)
#   Headers: Authorization: Bearer <token>
#   Response: { user }
#
# - GET  /api/health          - Health check del servicio
#   Response: { status, service, timestamp }
#
# REGISTRO Y VERIFICACIÓN:
# - POST /api/register        - Registrar nuevo usuario
#   Body: { username, email, password, nombre_completo, fecha_nacimiento,
#           tipo_documento, numero_documento, telefono (opcional) }
#   Response: { message, email }
#   Envía código de verificación por email
#
# - POST /api/verify-code     - Verificar código de correo
#   Body: { email, code }
#   Response: { message }
#
# - POST /api/resend-code     - Reenviar código de verificación o recuperación
#   Body: { email, type: 'verificacion' | 'recuperacion' }
#   Response: { message }
#
# RECUPERACIÓN DE CONTRASEÑA:
# - POST /api/forgot-password - Iniciar recuperación de contraseña
#   Body: { email }
#   Response: { message }
#   Envía código de recuperación por email
#
# - POST /api/reset-password  - Restablecer contraseña con código
#   Body: { email, code, new_password }
#   Response: { message }
#
# VALIDACIÓN:
# - POST /api/validate-document - Validar unicidad de documento
#   Body: { tipo_documento, numero_documento }
#   Response: { valid, message }
