"""
Endpoints de administración para Argos2.
Incluye gestión de usuarios: listar, cambiar rol, activar/desactivar, eliminar.
"""

from flask import Blueprint, request, jsonify
from auth.jwt_handler import token_required, admin_required
from database.db import (
    listar_usuarios,
    actualizar_rol_usuario,
    toggle_estado_usuario,
    eliminar_usuario,
    obtener_usuario_por_id
)

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


def _get_json_body():
    """Obtiene y valida el body JSON de la petición."""
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError("Se requiere un cuerpo JSON válido")
    return data


@admin_bp.route('/users', methods=['GET'])
@token_required
@admin_required
def get_users(current_user):
    """
    Endpoint para listar todos los usuarios.
    Requiere rol de administrador.
    """
    try:
        users = listar_usuarios()
        return jsonify(users), 200
    except Exception as e:
        return jsonify({'error': f'Error al obtener usuarios: {str(e)}'}), 500


@admin_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@token_required
@admin_required
def update_user_role(current_user, user_id):
    """
    Endpoint para cambiar el rol de un usuario.
    Requiere rol de administrador.
    """
    try:
        data = _get_json_body()
        nuevo_rol = data.get('rol')
        
        if not nuevo_rol or nuevo_rol not in ['admin', 'usuario']:
            return jsonify({'error': 'Rol inválido. Debe ser "admin" o "usuario"'}), 400
        
        # No permitir cambiar el rol del propio admin
        if user_id == current_user.get('user_id'):
            return jsonify({'error': 'No puedes cambiar tu propio rol'}), 400
        
        # Verificar que el usuario existe
        usuario = obtener_usuario_por_id(user_id)
        if not usuario:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        
        # Actualizar rol
        actualizar_rol_usuario(user_id, nuevo_rol)
        
        return jsonify({
            'message': f'Rol del usuario actualizado a {nuevo_rol}',
            'user_id': user_id,
            'nuevo_rol': nuevo_rol
        }), 200
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    except Exception as e:
        return jsonify({'error': f'Error al actualizar rol: {str(e)}'}), 500


@admin_bp.route('/users/<int:user_id>/status', methods=['PUT'])
@token_required
@admin_required
def update_user_status(current_user, user_id):
    """
    Endpoint para activar o desactivar un usuario.
    Requiere rol de administrador.
    """
    try:
        data = _get_json_body()
        activo = data.get('activo')
        
        if activo is None:
            return jsonify({'error': 'El campo "activo" es requerido'}), 400
        
        # No permitir desactivar la propia cuenta del admin
        if user_id == current_user.get('user_id') and not activo:
            return jsonify({'error': 'No puedes desactivar tu propia cuenta'}), 400
        
        # Verificar que el usuario existe
        usuario = obtener_usuario_por_id(user_id)
        if not usuario:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        
        # Actualizar estado
        if activo != usuario['activo']:
            toggle_estado_usuario(user_id)
        
        return jsonify({
            'message': f'Usuario {"activado" if activo else "desactivado"} exitosamente',
            'user_id': user_id,
            'activo': activo
        }), 200
    except ValueError:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400
    except Exception as e:
        return jsonify({'error': f'Error al actualizar estado: {str(e)}'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_user(current_user, user_id):
    """
    Endpoint para eliminar un usuario.
    Requiere rol de administrador.
    """
    try:
        # No permitir eliminar la propia cuenta del admin
        if user_id == current_user.get('user_id'):
            return jsonify({'error': 'No puedes eliminar tu propia cuenta'}), 400
        
        # Verificar que el usuario existe
        usuario = obtener_usuario_por_id(user_id)
        if not usuario:
            return jsonify({'error': 'Usuario no encontrado'}), 404
        
        # Eliminar usuario
        eliminar_usuario(user_id)
        
        return jsonify({
            'message': 'Usuario eliminado exitosamente',
            'user_id': user_id
        }), 200
    except Exception as e:
        return jsonify({'error': f'Error al eliminar usuario: {str(e)}'}), 500
