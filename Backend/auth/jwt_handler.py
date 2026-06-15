"""
Middleware de autenticación JWT para Argos2.
Validación stateless con soporte para Token Revocation via SQLite.
"""

import jwt
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify
from typing import Optional, Dict, Any, Callable
import os
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Configuración JWT
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

# Validar que el secreto JWT esté definido
if not JWT_SECRET_KEY:
    raise EnvironmentError(
        "JWT_SECRET_KEY no está configurada. "
        "Ejecute install.bat (Windows) o install.sh (Linux) para configurar las variables de entorno."
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
JWT_REFRESH_EXPIRATION_DAYS = 7


# =====================
# FUNCIONES DE BLACKLIST
# =====================

def add_token_to_blacklist(jti: str, user_id: int, expires_at: datetime, motivo: str = 'logout') -> bool:
    """
    Agrega un token a la blacklist en SQLite.
    
    Args:
        jti: JWT ID único del token
        user_id: ID del usuario
        expires_at: Fecha de expiración del token
        motivo: Razón de la revocación
    
    Returns:
        bool: True si se agregó correctamente
    """
    from database.db import agregar_token_revocado
    
    return agregar_token_revocado(jti, user_id, expires_at, motivo)


def is_token_revoked(jti: str) -> bool:
    """
    Verifica si un token está en la blacklist.
    
    Args:
        jti: JWT ID único del token
    
    Returns:
        bool: True si el token está revocado
    """
    from database.db import verificar_token_revocado
    
    return verificar_token_revocado(jti)


def revoke_all_user_tokens(user_id: int, motivo: str = 'security') -> int:
    """
    Marca todos los tokens de un usuario como revocados cambiando su versión.
    Se usa cuando: cambio de password, cuenta deshabilitada, etc.
    
    Args:
        user_id: ID del usuario
        motivo: Razón de la revocación
    
    Returns:
        int: Nueva versión del token
    """
    from database.db import revocar_todos_tokens_usuario
    
    return revocar_todos_tokens_usuario(user_id, motivo)


def get_user_token_version(user_id: int) -> int:
    """
    Obtiene la versión actual de tokens de un usuario.
    Si no existe, retorna 1 (versión inicial).
    """
    from database.db import obtener_version_token_usuario
    
    return obtener_version_token_usuario(user_id)


def cleanup_expired_revoked_tokens():
    """
    Elimina tokens revocados que ya han expirado.
    Debe ejecutarse periódicamente (ej: cada hora).
    """
    from database.db import limpiar_tokens_expirados
    
    limpiar_tokens_expirados()


# =====================
# GENERACIÓN DE TOKENS
# =====================

def generate_token(
    user_id: int,
    username: str,
    email: str,
    rol: str,
    expires_in_hours: int = JWT_EXPIRATION_HOURS
) -> str:
    """
    Genera un token JWT con la información del usuario.
    Incluye jti único para soporte de revocación.
    
    Args:
        user_id: ID del usuario
        username: Nombre de usuario
        email: Correo electrónico
        rol: Rol del usuario
        expires_in_hours: Tiempo de expiración en horas
    
    Returns:
        str: Token JWT firmado
    """
    # Obtener versión actual del token del usuario
    token_version = get_user_token_version(user_id)
    
    payload = {
        'user_id': user_id,
        'username': username,
        'email': email,
        'rol': rol,
        'jti': str(uuid.uuid4()),  # ID único para este token
        'ver': token_version,  # Versión para revocación masiva
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(hours=expires_in_hours),
        'type': 'access'
    }
    
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def generate_refresh_token(user_id: int) -> str:
    """
    Genera un refresh token de larga duración.
    Incluye jti único para revocación individual.
    
    Returns:
        str: Refresh token JWT
    """
    token_version = get_user_token_version(user_id)
    
    payload = {
        'user_id': user_id,
        'jti': str(uuid.uuid4()),
        'ver': token_version,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRATION_DAYS),
        'type': 'refresh'
    }
    
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


# =====================
# VALIDACIÓN DE TOKENS
# =====================

def decode_token(token: str) -> Dict[str, Any]:
    """
    Decodifica y valida un token JWT.
    Verifica blacklist y versión de usuario.
    
    Returns:
        Dict: Payload del token o error
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        
        # Verificar si el token está en la blacklist (por jti)
        jti = payload.get('jti')
        if jti and is_token_revoked(jti):
            return {
                'valid': False,
                'error': 'Token revocado',
                'code': 'TOKEN_REVOKED'
            }
        
        # Verificar versión del token del usuario (revocación masiva)
        user_id = payload.get('user_id')
        token_version = payload.get('ver', 1)
        current_version = get_user_token_version(user_id)
        
        if token_version < current_version:
            return {
                'valid': False,
                'error': 'Token obsoleto - sesión invalidada',
                'code': 'TOKEN_VERSION_INVALID'
            }
        
        return {'valid': True, 'payload': payload}
        
    except jwt.ExpiredSignatureError:
        return {'valid': False, 'error': 'Token expirado', 'code': 'TOKEN_EXPIRED'}
    except jwt.InvalidTokenError as e:
        return {'valid': False, 'error': f'Token inválido: {str(e)}', 'code': 'TOKEN_INVALID'}


def token_required(f: Callable) -> Callable:
    """
    Decorador para proteger rutas que requieren autenticación.
    Valida el token verificando: firma, expiración, blacklist y versión.
    
    Usage:
        @app.route('/api/protected')
        @token_required
        def protected_route(current_user):
            return jsonify({'user': current_user['username']})
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Buscar token en header Authorization
        auth_header = request.headers.get('Authorization')
        if auth_header:
            try:
                # Formato: "Bearer <token>"
                token = auth_header.split(' ')[1]
            except IndexError:
                return jsonify({
                    'error': 'Formato de token inválido',
                    'code': 'TOKEN_FORMAT_ERROR'
                }), 401
        
        # Fallback: buscar token en query parameter (para streams MJPEG via <img>)
        if not token:
            token = request.args.get('token')
        
        if not token:
            return jsonify({
                'error': 'Token de autenticación requerido',
                'code': 'TOKEN_MISSING'
            }), 401
        
        # Validar token (incluye verificación de blacklist)
        result = decode_token(token)
        
        if not result['valid']:
            return jsonify({
                'error': result['error'],
                'code': result['code']
            }), 401
        
        # Token válido, extraer información del usuario
        current_user = result['payload']
        
        return f(current_user=current_user, *args, **kwargs)
    
    return decorated


def admin_required(f: Callable) -> Callable:
    """
    Decorador para rutas que requieren rol de administrador.
    Debe usarse después de @token_required.
    
    Usage:
        @app.route('/api/admin/users')
        @token_required
        @admin_required
        def admin_route(current_user):
            return jsonify({'message': 'Admin access'})
    """
    @wraps(f)
    def decorated(current_user, *args, **kwargs):
        if current_user.get('rol') != 'admin':
            return jsonify({
                'error': 'Acceso denegado. Se requiere rol de administrador',
                'code': 'INSUFFICIENT_PERMISSIONS'
            }), 403
        
        return f(current_user=current_user, *args, **kwargs)
    
    return decorated


def optional_token(f: Callable) -> Callable:
    """
    Decorador para rutas donde el token es opcional.
    Si existe, valida y proporciona current_user; si no, current_user es None.
    
    Disponible para endpoints públicos que ofrecen funcionalidad adicional
    a usuarios autenticados. Ejemplos de uso futuro:
    - Endpoint público de estadísticas que muestra datos extra para usuarios autenticados
    - Feed público que personaliza contenido si el usuario está logueado
    - Cualquier endpoint que necesite comportamiento dual público/autenticado
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        current_user = None
        auth_header = request.headers.get('Authorization')
        
        if auth_header:
            try:
                token = auth_header.split(' ')[1]
                result = decode_token(token)
                if result['valid']:
                    current_user = result['payload']
            except IndexError:
                pass  # Token mal formado, continuar como anónimo
        
        return f(current_user=current_user, *args, **kwargs)
    
    return decorated


# =====================
# CLEANUP SCHEDULER
# =====================

import threading
import logging

logger = logging.getLogger(__name__)


def start_cleanup_scheduler(interval_hours: int = 1):
    """
    Inicia un scheduler en segundo plano que ejecuta la limpieza
    de tokens expirados cada `interval_hours` horas.
    
    Args:
        interval_hours: Intervalo en horas entre ejecuciones (default: 1)
    """
    def _run_cleanup():
        try:
            cleanup_expired_revoked_tokens()
            logger.info("Limpieza de tokens expirados ejecutada exitosamente")
        except Exception as e:
            logger.error(f"Error en limpieza de tokens: {e}")
        finally:
            # Programar la siguiente ejecución
            timer = threading.Timer(interval_hours * 3600, _run_cleanup)
            timer.daemon = True
            timer.start()
    
    # Ejecutar inmediatamente la primera vez
    _run_cleanup()
