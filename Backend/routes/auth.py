"""
Endpoints de autenticación para Argos2.
Incluye login, logout, refresh y gestión de tokens.
"""

import re
from flask import Blueprint, request, jsonify
from datetime import datetime
import jwt

from auth.jwt_handler import (
    generate_token,
    generate_refresh_token,
    decode_token,
    token_required,
    add_token_to_blacklist,
    revoke_all_user_tokens,
    JWT_SECRET_KEY,
    JWT_ALGORITHM
)
from database.db import (
    obtener_usuario_por_username,
    obtener_usuario_por_id,
    registrar_intento_login,
    crear_usuario,
    obtener_usuario_por_email,
    verificar_documento_existe,
    crear_codigo_verificacion,
    verificar_codigo,
    verificar_email_usuario,
    actualizar_password
)
from services.email_service import (
    enviar_correo_verificacion,
    enviar_correo_recuperacion
)
from middleware.rate_limiter import limiter
import bcrypt

# Constantes de validación
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
USERNAME_REGEX = re.compile(r'^[a-zA-Z0-9_]{3,20}$')

auth_bp = Blueprint('auth', __name__, url_prefix='/api')


def _get_json_body():
    """Obtiene y valida el body JSON de la petición."""
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError("Se requiere un cuerpo JSON válido")
    return data


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5/minute")
def login():
    """Endpoint de login que retorna JWT con jti único."""
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username y password requeridos'}), 400
    
    # Buscar usuario en BD
    user = obtener_usuario_por_username(username)
    
    if not user:
        registrar_intento_login(username, False, motivo_fallo='Usuario no existe')
        return jsonify({'error': 'Credenciales inválidas'}), 401
    
    # Verificar password
    if not bcrypt.checkpw(password.encode(), user['password_hash'].encode()):
        registrar_intento_login(username, False, usuario_id=user['id'], motivo_fallo='Password incorrecto')
        return jsonify({'error': 'Credenciales inválidas'}), 401
    
    if not user['activo']:
        return jsonify({'error': 'Cuenta desactivada'}), 403
    
    if not user['email_verificado']:
        return jsonify({'error': 'Email no verificado'}), 403
    
    # Generar tokens (cada uno con jti único)
    access_token = generate_token(
        user_id=user['id'],
        username=user['username'],
        email=user['email'],
        rol=user['rol']
    )
    refresh_token = generate_refresh_token(user['id'])
    
    # Registrar login exitoso
    registrar_intento_login(username, True, usuario_id=user['id'])
    
    return jsonify({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'expires_in': 86400,  # 24 horas en segundos
        'user': {
            'id': user['id'],
            'username': user['username'],
            'email': user['email'],
            'rol': user['rol']
        }
    }), 200


@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    """
    Endpoint de logout que revoca el token actual.
    Agrega el jti del token a la tabla de tokens revocados.
    """
    auth_header = request.headers.get('Authorization')
    token = auth_header.split(' ')[1]
    
    # Decodificar para obtener jti y exp
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    
    jti = payload.get('jti')
    exp = datetime.fromtimestamp(payload.get('exp'))
    user_id = payload.get('user_id')
    
    # Agregar a blacklist
    if jti:
        add_token_to_blacklist(jti, user_id, exp, 'logout')
    
    return jsonify({
        'message': 'Logout exitoso',
        'revoked': True
    }), 200


@auth_bp.route('/logout-all', methods=['POST'])
@token_required
def logout_all(current_user):
    """
    Revoca TODOS los tokens del usuario actual.
    Útil cuando el usuario cambia password o detecta actividad sospechosa.
    """
    user_id = current_user.get('user_id')
    new_version = revoke_all_user_tokens(user_id)
    
    return jsonify({
        'message': 'Todos los dispositivos han sido desconectados',
        'new_token_version': new_version
    }), 200


@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    """
    Renueva el access token usando un refresh token.
    El refresh token anterior se agrega a la blacklist.
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    refresh_token = data.get('refresh_token')
    
    if not refresh_token:
        return jsonify({'error': 'Refresh token requerido'}), 400
    
    result = decode_token(refresh_token)
    
    if not result['valid'] or result['payload'].get('type') != 'refresh':
        return jsonify({'error': 'Refresh token inválido'}), 401
    
    # Obtener datos del refresh token
    payload = result['payload']
    user_id = payload['user_id']
    old_jti = payload.get('jti')
    old_exp = datetime.fromtimestamp(payload.get('exp'))
    
    # Revocar el refresh token usado (one-time use)
    if old_jti:
        add_token_to_blacklist(old_jti, user_id, old_exp, 'refresh_rotation')
    
    # Generar nuevo access token
    user = obtener_usuario_por_id(user_id)
    
    if not user or not user['activo']:
        return jsonify({'error': 'Usuario no válido'}), 401
    
    new_access_token = generate_token(
        user_id=user['id'],
        username=user['username'],
        email=user['email'],
        rol=user['rol']
    )
    
    # Generar nuevo refresh token
    new_refresh_token = generate_refresh_token(user['id'])
    
    return jsonify({
        'access_token': new_access_token,
        'refresh_token': new_refresh_token,
        'token_type': 'Bearer',
        'expires_in': 86400
    }), 200


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    """Obtiene información del usuario actual desde el token."""
    return jsonify({
        'user': {
            'id': current_user['user_id'],
            'username': current_user['username'],
            'email': current_user['email'],
            'rol': current_user['rol']
        }
    }), 200


# =====================
# Endpoints de Registro y Verificación
# =====================

@auth_bp.route('/register', methods=['POST'])
@limiter.limit("3/hour")
def register():
    """
    Endpoint de registro de usuarios.
    Crea un usuario con email no verificado y envía código de verificación.
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    # Validar campos requeridos
    required_fields = [
        'username', 'email', 'password', 'nombre_completo',
        'fecha_nacimiento', 'tipo_documento', 'numero_documento'
    ]
    
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'El campo {field} es requerido'}), 400
    
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    nombre_completo = data.get('nombre_completo')
    fecha_nacimiento = data.get('fecha_nacimiento')
    tipo_documento = data.get('tipo_documento')
    numero_documento = data.get('numero_documento')
    telefono = data.get('telefono')
    
    # Validar formato de email
    if not EMAIL_REGEX.match(email):
        return jsonify({'error': 'Formato de correo electrónico inválido'}), 400

    # Sanitizar y validar username
    username = username.strip()
    if not USERNAME_REGEX.match(username):
        return jsonify({
            'error': 'El nombre de usuario debe tener entre 3 y 20 caracteres alfanuméricos (letras, números y _)'
        }), 400

    # Validar tipo de documento
    if tipo_documento not in ['V', 'P']:
        return jsonify({'error': 'Tipo de documento inválido. Debe ser V o P'}), 400
    
    # Validar formato de documento
    if tipo_documento == 'V':
        if not numero_documento.isdigit() or len(numero_documento) not in [7, 8]:
            return jsonify({'error': 'La cédula debe tener 7 u 8 dígitos'}), 400
    else:  # Pasaporte
        if len(numero_documento) < 6 or len(numero_documento) > 12:
            return jsonify({'error': 'El pasaporte debe tener entre 6 y 12 caracteres'}), 400
    
    # Validar contraseña
    if len(password) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres'}), 400
    if not any(c.isupper() for c in password):
        return jsonify({'error': 'La contraseña debe contener al menos una mayúscula'}), 400
    if not any(c.islower() for c in password):
        return jsonify({'error': 'La contraseña debe contener al menos una minúscula'}), 400
    if not any(c.isdigit() for c in password):
        return jsonify({'error': 'La contraseña debe contener al menos un número'}), 400
    if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/' for c in password):
        return jsonify({'error': 'La contraseña debe contener al menos un carácter especial (!@#$%^&* etc.)'}), 400
    
    # Validar unicidad de email
    if obtener_usuario_por_email(email):
        return jsonify({'error': 'Ya existe una cuenta con este correo electrónico'}), 400
    
    # Validar unicidad de username
    if obtener_usuario_por_username(username):
        return jsonify({'error': 'El nombre de usuario ya está en uso'}), 400
    
    # Validar unicidad de documento
    if verificar_documento_existe(tipo_documento, numero_documento):
        return jsonify({'error': 'Ya existe una cuenta con este documento de identidad'}), 400
    
    # Hashear contraseña
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    
    # Crear usuario
    try:
        usuario_id = crear_usuario(
            username=username,
            email=email,
            password_hash=password_hash,
            nombre_completo=nombre_completo,
            fecha_nacimiento=fecha_nacimiento,
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            telefono=telefono,
            rol='usuario'
        )
    except Exception as e:
        return jsonify({'error': f'Error al crear usuario: {str(e)}'}), 500
    
    # Generar código de verificación
    codigo = crear_codigo_verificacion(
        email=email,
        tipo='verificacion',
        usuario_id=usuario_id,
        duracion_minutos=2
    )
    
    # Enviar correo de verificación
    exito, mensaje = enviar_correo_verificacion(email, codigo)
    
    if not exito:
        print(f'Error al enviar correo: {mensaje}')
        # En caso de error, mostramos el código en consola para desarrollo
        print(f'CÓDIGO DE VERIFICACIÓN para {email}: {codigo}')
    
    return jsonify({
        'message': 'Registro exitoso. Se ha enviado un código de verificación a su correo.',
        'email': email
    }), 201


@auth_bp.route('/verify-code', methods=['POST'])
def verify_code():
    """
    Endpoint de verificación de código de correo.
    Verifica el código y marca el email como verificado.
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    email = data.get('email')
    code = data.get('code')
    
    if not email or not code:
        return jsonify({'error': 'Email y código son requeridos'}), 400
    
    # Verificar código
    resultado = verificar_codigo(email, code, 'verificacion')
    
    if not resultado['valido']:
        return jsonify({'error': resultado['mensaje']}), 400
    
    # Obtener usuario y marcar email como verificado
    usuario = obtener_usuario_por_email(email)
    
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    
    verificar_email_usuario(usuario['id'])
    
    return jsonify({
        'message': 'Correo verificado exitosamente. Ya puede iniciar sesión.'
    }), 200


@auth_bp.route('/resend-code', methods=['POST'])
@limiter.limit("3/hour")
def resend_code():
    """
    Endpoint para reenviar código de verificación.
    Puede ser para registro ('verificacion') o recuperación ('recuperacion').
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    email = data.get('email')
    code_type = data.get('type', 'verificacion')
    
    if not email:
        return jsonify({'error': 'Email es requerido'}), 400
    
    if code_type not in ['verificacion', 'recuperacion']:
        return jsonify({'error': 'Tipo de código inválido'}), 400
    
    # Verificar que el email existe (para verificación)
    if code_type == 'verificacion':
        usuario = obtener_usuario_por_email(email)
        if not usuario:
            return jsonify({'error': 'Email no registrado'}), 404
        if usuario['email_verificado']:
            return jsonify({'error': 'El email ya está verificado'}), 400
    
    # Generar nuevo código
    codigo = crear_codigo_verificacion(
        email=email,
        tipo=code_type,
        duracion_minutos=2
    )
    
    # Enviar correo según el tipo
    if code_type == 'verificacion':
        exito, mensaje = enviar_correo_verificacion(email, codigo)
    else:
        exito, mensaje = enviar_correo_recuperacion(email, codigo)
    
    if not exito:
        print(f'Error al enviar correo: {mensaje}')
        # En caso de error, mostramos el código en consola para desarrollo
        print(f'NUEVO CÓDIGO DE {code_type.upper()} para {email}: {codigo}')
    
    return jsonify({
        'message': 'Se ha enviado un nuevo código de verificación a su correo.'
    }), 200


@auth_bp.route('/forgot-password', methods=['POST'])
@limiter.limit("3/hour")
def forgot_password():
    """
    Endpoint para iniciar recuperación de contraseña.
    Envía un código de recuperación al email del usuario.
    Por seguridad, no revela si el email existe.
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    email = data.get('email')
    
    if not email:
        return jsonify({'error': 'Email es requerido'}), 400
    
    # Verificar si el email existe
    usuario = obtener_usuario_por_email(email)
    
    if usuario:
        # Generar código de recuperación
        codigo = crear_codigo_verificacion(
            email=email,
            tipo='recuperacion',
            usuario_id=usuario['id'],
            duracion_minutos=2
        )
        
        # Enviar correo de recuperación
        exito, mensaje = enviar_correo_recuperacion(email, codigo)
        
        if not exito:
            print(f'Error al enviar correo: {mensaje}')
            # En caso de error, mostramos el código en consola para desarrollo
            print(f'CÓDIGO DE RECUPERACIÓN para {email}: {codigo}')
    
    # Por seguridad, siempre retornamos el mismo mensaje
    return jsonify({
        'message': 'Si el correo está registrado, recibirá un código de recuperación.'
    }), 200


@auth_bp.route('/reset-password', methods=['POST'])
@limiter.limit("5/minute")
def reset_password():
    """
    Endpoint para restablecer contraseña con código de recuperación.
    Verifica el código y actualiza la contraseña.
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    email = data.get('email')
    code = data.get('code')
    new_password = data.get('new_password')
    
    if not email or not code or not new_password:
        return jsonify({'error': 'Email, código y nueva contraseña son requeridos'}), 400
    
    # Validar nueva contraseña
    if len(new_password) < 8:
        return jsonify({'error': 'La contraseña debe tener al menos 8 caracteres'}), 400
    if not any(c.isupper() for c in new_password):
        return jsonify({'error': 'La contraseña debe contener al menos una mayúscula'}), 400
    if not any(c.islower() for c in new_password):
        return jsonify({'error': 'La contraseña debe contener al menos una minúscula'}), 400
    if not any(c.isdigit() for c in new_password):
        return jsonify({'error': 'La contraseña debe contener al menos un número'}), 400
    if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?/' for c in new_password):
        return jsonify({'error': 'La contraseña debe contener al menos un carácter especial (!@#$%^&* etc.)'}), 400
    
    # Verificar código
    resultado = verificar_codigo(email, code, 'recuperacion')
    
    if not resultado['valido']:
        return jsonify({'error': resultado['mensaje']}), 400
    
    # Obtener usuario
    usuario = obtener_usuario_por_email(email)
    
    if not usuario:
        return jsonify({'error': 'Usuario no encontrado'}), 404
    
    # Hashear nueva contraseña
    password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    
    # Actualizar contraseña
    actualizar_password(usuario['id'], password_hash)
    
    return jsonify({
        'message': 'Contraseña restablecida exitosamente. Ya puede iniciar sesión.'
    }), 200


@auth_bp.route('/validate-document', methods=['POST'])
def validate_document():
    """
    Endpoint para validar si un documento de identidad ya está registrado.
    Se usa durante el registro para validar en tiempo real.
    """
    try:
        data = _get_json_body()
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    
    tipo_documento = data.get('tipo_documento')
    numero_documento = data.get('numero_documento')
    
    if not tipo_documento or not numero_documento:
        return jsonify({'error': 'Tipo y número de documento son requeridos'}), 400
    
    if tipo_documento not in ['V', 'P']:
        return jsonify({'error': 'Tipo de documento inválido'}), 400
    
    existe = verificar_documento_existe(tipo_documento, numero_documento)
    
    return jsonify({
        'valid': not existe,
        'message': 'Documento disponible' if not existe else 'Documento ya registrado'
    }), 200
