"""
Endpoints de configuración de ajustes (settings) para Argos2.

Blueprint con ``url_prefix='/api/settings'`` que expone endpoints para leer y
modificar la configuración de visión computacional (Roboflow) en runtime.

Endpoints:

    GET  /api/settings/vision       — Devuelve la config de visión (API key
                                      enmascarada). Cualquier usuario autenticado.
    PUT  /api/settings/vision       — Actualiza variables de visión (solo admin).
                                      Recarga los motores activos y registra el
                                      cambio en ``logs_sistema``.
    GET  /api/settings/vision/test  — Prueba la conectividad con Roboflow
                                      con la configuración actual (solo admin).

Seguridad:
    - La API key **nunca** se devuelve en texto plano (se enmascara con
      ``****`` + últimos 4 caracteres).
    - El PUT requiere rol admin.
    - Si el PUT recibe la API key vacía o enmascarada (``"****..."``), no
      se sobrescribe el valor existente.
    - Todos los cambios se registran con ``crear_log()``.
"""

import logging
import os

from flask import Blueprint, request, jsonify

from auth.jwt_handler import token_required, admin_required
from database.db import crear_log
from services.settings_service import (
    get_masked_vision_settings,
    get_vision_settings,
    update_vision_settings,
    is_api_key_masked_or_empty,
    mask_api_key,
    VALID_VISION_MODES,
    API_KEY_SETTING,
)

logger = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__, url_prefix='/api/settings')


def _safe_log(**kwargs) -> None:
    """
    Wrapper resiliente de ``crear_log``.

    Registra un log en ``logs_sistema`` pero **nunca** propaga excepciones
    (p.ej. si el ``usuario_id`` no existe y la FK falla). El logging es una
    operación secundaria que no debe romper el flujo principal del endpoint.
    """
    try:
        crear_log(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo registrar el log de settings: %s", exc)


# ---------------------------------------------------------------------------
# GET /api/settings/vision — Devuelve la configuración de visión
# ---------------------------------------------------------------------------

@settings_bp.route('/vision', methods=['GET'])
@token_required
def get_vision_config(current_user):
    """
    Devuelve la configuración de visión desde la base de datos.

    La API key se devuelve **enmascarada** (``****abcd``) por seguridad.
    Disponible para cualquier usuario autenticado.
    """
    try:
        config = get_masked_vision_settings()
        return jsonify(config), 200
    except Exception as e:
        logger.error("Error al obtener configuración de visión: %s", e)
        return jsonify({'error': f'Error al obtener configuración: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# PUT /api/settings/vision — Actualiza la configuración de visión (admin)
# ---------------------------------------------------------------------------

@settings_bp.route('/vision', methods=['PUT'])
@token_required
@admin_required
def update_vision_config(current_user):
    """
    Actualiza las variables de configuración de visión.

    Solo se actualizan las variables enviadas en el body JSON (no requiere
    todas). Variables reconocidas::

        vision_default_mode              (off | cloud | local)
        roboflow_api_key
        roboflow_api_url
        roboflow_workspace
        roboflow_workflow_id
        roboflow_workflow_image_input
        roboflow_workflow_use_cache      (true | false)
        roboflow_use_server_overlay      (true | false)
        roboflow_model_id

    Tras actualizar:
        1. Los valores se guardan en la DB (UPSERT).
        2. Los valores se sincronizan con ``os.environ``.
        3. Los motores de visión activos se recargan (disable + enable).
        4. Se registra el cambio en ``logs_sistema``.

    **Seguridad — API key:** si ``roboflow_api_key`` llega vacía o como un
    valor enmascarado (``"****..."``), **no se sobrescribe** el valor
    existente.

    Requiere rol admin.
    """
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400

    # ---- Validación del modo de visión (si viene en el payload) -----------
    if 'vision_default_mode' in data:
        mode = str(data['vision_default_mode']).strip().lower()
        if mode not in VALID_VISION_MODES:
            return jsonify({
                'error': f'Modo de visión inválido: {data["vision_default_mode"]!r}. '
                         f'Modos válidos: {", ".join(VALID_VISION_MODES)}'
            }), 400
        # Normalizar a minúsculas.
        data['vision_default_mode'] = mode

    # ---- Detectar si hubo cambios reales (para logging) -------------------
    # Construir un resumen de los cambios sin exponer la API key completa.
    changes_summary = {}
    for key, new_value in data.items():
        if key == API_KEY_SETTING:
            # No loguear el valor real de la API key.
            if is_api_key_masked_or_empty(new_value):
                changes_summary[key] = '(sin cambios)'
            else:
                changes_summary[key] = mask_api_key(str(new_value))
        else:
            changes_summary[key] = new_value

    try:
        # ---- 1+2. Guardar en DB + sincronizar os.environ -----------------
        updated_config = update_vision_settings(data)

        # ---- 3. Recargar motores de visión activos -----------------------
        reloaded_cameras = []
        try:
            from services.camera_service import CameraManager
            cm = CameraManager()
            reloaded_cameras = cm.reload_vision_engines()
        except Exception as exc:
            # La recarga no debe bloquear el guardado de la configuración.
            logger.warning(
                "No se pudieron recargar los motores de visión: %s", exc
            )

        # ---- 4. Registrar el cambio en logs_sistema ----------------------
        _safe_log(
            nivel='INFO',
            componente='settings',
            mensaje='Configuración de visión actualizada',
            datos_adicionales={
                'cambios': changes_summary,
                'camaras_recargadas': reloaded_cameras,
                'usuario': current_user.get('username'),
            },
            usuario_id=current_user.get('user_id'),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

        # ---- Devolver configuración actualizada (API key enmascarada) ----
        return jsonify({
            'message': 'Configuración de visión actualizada exitosamente.',
            'config': get_masked_vision_settings(),
            'reloaded_cameras': reloaded_cameras,
        }), 200

    except Exception as e:
        logger.error("Error al actualizar configuración de visión: %s", e)
        _safe_log(
            nivel='ERROR',
            componente='settings',
            mensaje=f'Error al actualizar configuración de visión: {e}',
            usuario_id=current_user.get('user_id'),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return jsonify({
            'error': f'Error al actualizar configuración: {str(e)}'
        }), 500


# ---------------------------------------------------------------------------
# GET /api/settings/vision/test — Prueba conectividad con Roboflow (admin)
# ---------------------------------------------------------------------------

@settings_bp.route('/vision/test', methods=['GET'])
@token_required
@admin_required
def test_vision_connectivity(current_user):
    """
    Prueba la conectividad con Roboflow usando la configuración actual.

    Hace una inferencia de prueba con una imagen sintética (frame negro)
    usando los valores actuales de la DB (sincronizados en ``os.environ``).
    Devuelve ``{"success": true/false, "message": "..."}``.

    Requiere rol admin.
    """
    import numpy as np

    try:
        # Asegurar que os.environ tenga los valores de la DB.
        from services.settings_service import sync_settings_to_env
        sync_settings_to_env()

        vision = get_vision_settings()
        api_key = vision.get('roboflow_api_key', '')

        if not api_key:
            return jsonify({
                'success': False,
                'message': 'No hay API key configurada.'
            }), 200

        # Determinar el modo a probar (workflow o modelo estándar).
        has_workflow = bool(
            vision.get('roboflow_workspace') and vision.get('roboflow_workflow_id')
        )
        has_model = bool(vision.get('roboflow_model_id'))

        if not has_workflow and not has_model:
            return jsonify({
                'success': False,
                'message': 'No hay WORKFLOW_ID/WORKSPACE ni MODEL_ID configurados.'
            }), 200

        # Crear un motor cloud temporal para la prueba.
        from services.vision_engine import CloudVisionEngine

        engine = CloudVisionEngine()
        engine.initialize()

        if not engine.is_available:
            return jsonify({
                'success': False,
                'message': 'El motor cloud no está disponible. '
                           'Verifique la API key y la configuración.'
            }), 200

        # Frame de prueba (imagen negra 64x64).
        test_frame = np.zeros((64, 64, 3), dtype=np.uint8)

        try:
            result_frame = engine.process_frame(test_frame)
            if result_frame is not None:
                mode_desc = 'workflow' if has_workflow else 'modelo estándar'
                return jsonify({
                    'success': True,
                    'message': f'Conectividad exitosa con Roboflow (modo {mode_desc}).'
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'message': 'La inferencia no devolvió un frame válido.'
                }), 200
        finally:
            engine.shutdown()

    except ImportError:
        return jsonify({
            'success': False,
            'message': 'El paquete inference_sdk no está instalado.'
        }), 200
    except Exception as e:
        logger.error("Error en test de conectividad de visión: %s", e)
        return jsonify({
            'success': False,
            'message': f'Error durante la prueba: {str(e)}'
        }), 200
