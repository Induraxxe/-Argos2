"""
Endpoints de gestión de cámaras para Argos2.
Blueprint con url_prefix='/api/cameras' que expone endpoints de
descubrimiento, registro, streaming, captura y control de cámaras.
"""

import logging
import os
import socket
import struct
import threading
import time
import uuid
from functools import wraps

from flask import Blueprint, request, jsonify, Response

from auth.jwt_handler import token_required, admin_required
from services.camera_service import (
    CameraManager,
    CamerasConfig,
    create_camera_from_config,
)

# Importar la fábrica de motores de visión con degradación graceful.
# Paso #4 / 5.2 del plan docs/plan-vision-local-cloud.md.
try:
    from services.vision_engine import VisionEngineFactory
    VISION_FACTORY_AVAILABLE = True
except ImportError:  # pragma: no cover - dependencia opcional
    VISION_FACTORY_AVAILABLE = False
    VisionEngineFactory = None  # type: ignore[assignment,misc]
    logger = logging.getLogger(__name__)
    logger.warning(
        "El módulo de visión (services.vision_engine) no está disponible. "
        "Los endpoints de visión estarán limitados."
    )

camera_bp = Blueprint('camera', __name__, url_prefix='/api/cameras')
logger = logging.getLogger(__name__)

# Instancias singleton / helpers
camera_manager = CameraManager()
cameras_config = CamerasConfig()

# Carpeta para capturas
UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads'
)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ---------------------------------------------------------------------------
# Generador de frames MJPEG
# ---------------------------------------------------------------------------

def generate_frames(camera_id: str, fps: float = 15.0):
    """
    Generador que produce frames MJPEG para streaming.

    Se detiene cuando el cliente se desconecta (el yield sobre un Response
    con mimetype multipart produce GeneratorExit al cerrar la conexión).
    """
    interval = 1.0 / fps if fps > 0 else 1.0 / 15.0

    while True:
        frame_data = camera_manager.get_frame(camera_id)

        if frame_data is None:
            # Cámara no disponible — enviar frame dummy y reintentar
            time.sleep(interval)
            continue

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n'
        )
        time.sleep(interval)


# ---------------------------------------------------------------------------
# GET  /api/cameras/discover  — Descubre cámaras USB locales
# ---------------------------------------------------------------------------

@camera_bp.route('/discover', methods=['GET'])
@token_required
def discover_cameras(current_user):
    """Descubre cámaras USB conectadas localmente."""
    try:
        cameras = camera_manager.discover_local_cameras()
        return jsonify({
            'cameras': cameras,
            'count': len(cameras)
        }), 200
    except Exception as e:
        logger.error("Error en discover_cameras: %s", e)
        return jsonify({'error': f'Error al descubrir cámaras: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# GET  /api/cameras  — Lista todas las cámaras activas
# ---------------------------------------------------------------------------

@camera_bp.route('', methods=['GET'])
@token_required
def list_cameras(current_user):
    """Lista todas las cámaras registradas en el sistema."""
    try:
        cameras = camera_manager.list_cameras()
        return jsonify({
            'cameras': cameras,
            'count': len(cameras)
        }), 200
    except Exception as e:
        logger.error("Error en list_cameras: %s", e)
        return jsonify({'error': f'Error al listar cámaras: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# POST /api/cameras  — Registra nueva cámara IP/ESP32 (admin)
# ---------------------------------------------------------------------------

@camera_bp.route('', methods=['POST'])
@token_required
@admin_required
def register_camera(current_user):
    """
    Registra una nueva cámara (IP o ESP32).

    Body JSON:
        - type: "usb" | "ip" | "esp32"
        - name: str
        - url: str (para IP)
        - ip: str, port: int (para ESP32)
        - fps: int (opcional)
        - resolution: [w, h] (opcional, solo USB)
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400

    camera_type = data.get('type', '').lower()
    if camera_type not in ('usb', 'ip', 'esp32'):
        return jsonify({
            'error': "Tipo de cámara inválido. Use: 'usb', 'ip', 'esp32'."
        }), 400

    name = data.get('name')
    if not name:
        return jsonify({'error': 'El campo "name" es obligatorio.'}), 400

    # Validaciones específicas por tipo
    if camera_type == 'ip' and not data.get('url'):
        return jsonify({'error': 'Las cámaras IP requieren el campo "url".'}), 400
    if camera_type == 'esp32' and not data.get('ip'):
        return jsonify({'error': 'Las cámaras ESP32 requieren el campo "ip".'}), 400

    try:
        # Crear la fuente de video
        source = create_camera_from_config(data)

        # Agregar al manager (la inicia automáticamente)
        camera_id = camera_manager.add_camera(source)

        # Persistir configuración
        config_entry = {
            'id': camera_id,
            'type': camera_type,
            'name': name,
        }
        # Incluir parámetros específicos
        if camera_type == 'ip':
            config_entry['url'] = data['url']
            config_entry['fps'] = data.get('fps', 15)
        elif camera_type == 'esp32':
            config_entry['ip'] = data['ip']
            config_entry['port'] = data.get('port', 80)
            config_entry['stream_path'] = data.get('stream_path', '/stream')
            config_entry['capture_path'] = data.get('capture_path', '/capture')
        elif camera_type == 'usb':
            config_entry['camera_index'] = data.get('camera_index', 0)
            config_entry['fps'] = data.get('fps', 30)
            config_entry['resolution'] = data.get('resolution', [640, 480])

        cameras_config.add_camera(config_entry)

        return jsonify({
            'message': 'Cámara registrada exitosamente.',
            'camera_id': camera_id,
            'name': name,
            'type': camera_type
        }), 201

    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logger.error("Error en register_camera: %s", e)
        return jsonify({'error': f'Error al registrar cámara: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# DELETE /api/cameras/<id>  — Elimina cámara registrada (admin)
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_camera(current_user, camera_id):
    """Elimina una cámara del sistema."""
    try:
        removed = camera_manager.remove_camera(camera_id)
        if not removed:
            return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

        # Eliminar de la configuración persistida
        cameras_config.remove_camera(camera_id)

        return jsonify({
            'message': f'Cámara {camera_id} eliminada correctamente.'
        }), 200

    except Exception as e:
        logger.error("Error en delete_camera: %s", e)
        return jsonify({'error': f'Error al eliminar cámara: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# PUT /api/cameras/<id>  — Actualiza configuración (admin)
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>', methods=['PUT'])
@token_required
@admin_required
def update_camera(current_user, camera_id):
    """
    Actualiza la configuración de una cámara.

    La actualización implica detener la cámara, crear una nueva instancia
    con la configuración modificada y reiniciarla.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Se requiere un cuerpo JSON válido'}), 400

    # Verificar que la cámara existe
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    try:
        # Detener y eliminar la cámara actual
        camera_manager.remove_camera(camera_id)

        # Construir nueva configuración combinando la existente con los cambios
        existing_configs = cameras_config.load()
        existing = next(
            (c for c in existing_configs if c.get('id') == camera_id), None
        )

        if existing is None:
            existing = {'id': camera_id, 'type': source.source_type, 'name': source.name}

        # Aplicar cambios
        for key, value in data.items():
            if key != 'id':  # No permitir cambiar el ID
                existing[key] = value

        # Crear nueva instancia y agregar al manager
        new_source = create_camera_from_config(existing)
        new_id = camera_manager.add_camera(new_source)

        # Actualizar el ID en la config si cambió (no debería)
        existing['id'] = new_id

        # Actualizar configuración persistida
        updated_configs = [
            c for c in existing_configs if c.get('id') != camera_id
        ]
        updated_configs.append(existing)
        cameras_config.save(updated_configs)

        return jsonify({
            'message': 'Cámara actualizada exitosamente.',
            'camera_id': new_id,
            'name': existing.get('name')
        }), 200

    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logger.error("Error en update_camera: %s", e)
        return jsonify({'error': f'Error al actualizar cámara: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# GET /api/cameras/<id>/stream  — Stream MJPEG
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/stream', methods=['GET'])
@token_required
def stream_camera(current_user, camera_id):
    """Retorna un stream MJPEG de la cámara especificada."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    if not source.is_running:
        return jsonify({'error': f'Cámara {camera_id} no está activa.'}), 400

    fps = request.args.get('fps', default=15.0, type=float)

    return Response(
        generate_frames(camera_id, fps=fps),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true',
            'X-Accel-Buffering': 'no',
        }
    )


# ---------------------------------------------------------------------------
# POST /api/cameras/<id>/capture  — Captura frame actual
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/capture', methods=['POST'])
@token_required
def capture_frame(current_user, camera_id):
    """Captura el frame actual de la cámara y lo guarda como archivo JPEG."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    frame_data = camera_manager.get_frame(camera_id)
    if frame_data is None:
        return jsonify({'error': 'No se pudo obtener frame de la cámara.'}), 503

    try:
        # Generar nombre único y guardar
        filename = f"{uuid.uuid4().hex}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        with open(filepath, 'wb') as f:
            f.write(frame_data)

        return jsonify({
            'message': 'Frame capturado exitosamente.',
            'filename': filename,
            'path': f'/uploads/{filename}',
            'size_bytes': len(frame_data)
        }), 200

    except Exception as e:
        logger.error("Error guardando captura: %s", e)
        return jsonify({'error': f'Error al guardar captura: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# GET /api/cameras/<id>/status  — Estado detallado
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/status', methods=['GET'])
@token_required
def camera_status(current_user, camera_id):
    """Retorna el estado detallado de una cámara."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    try:
        status = {
            'id': camera_id,
            'name': source.name,
            'type': source.source_type,
            'is_running': source.is_running,
            'source_info': CameraManager._get_source_info(source),
        }
        return jsonify(status), 200

    except Exception as e:
        logger.error("Error en camera_status: %s", e)
        return jsonify({'error': f'Error al obtener estado: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# POST /api/cameras/<id>/start  — Inicia cámara
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/start', methods=['POST'])
@token_required
def start_camera(current_user, camera_id):
    """Inicia la captura de una cámara registrada."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    if source.is_running:
        return jsonify({'message': f'Cámara {camera_id} ya está en ejecución.'}), 200

    success = camera_manager.start_camera(camera_id)
    if success:
        return jsonify({'message': f'Cámara {camera_id} iniciada correctamente.'}), 200
    else:
        return jsonify({'error': f'No se pudo iniciar la cámara {camera_id}.'}), 500


# ---------------------------------------------------------------------------
# POST /api/cameras/<id>/stop  — Detiene cámara
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/stop', methods=['POST'])
@token_required
def stop_camera(current_user, camera_id):
    """Detiene la captura de una cámara sin eliminarla."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    if not source.is_running:
        return jsonify({'message': f'Cámara {camera_id} ya está detenida.'}), 200

    success = camera_manager.stop_camera(camera_id)
    if success:
        return jsonify({'message': f'Cámara {camera_id} detenida correctamente.'}), 200
    else:
        return jsonify({'error': f'No se pudo detener la cámara {camera_id}.'}), 500


# ---------------------------------------------------------------------------
# POST /api/cameras/<id>/restart  — Reinicia conexión (admin)
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/restart', methods=['POST'])
@token_required
@admin_required
def restart_camera(current_user, camera_id):
    """Reinicia la conexión de una cámara (detener + iniciar)."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    success = camera_manager.restart_camera(camera_id)
    if success:
        return jsonify({'message': f'Cámara {camera_id} reiniciada correctamente.'}), 200
    else:
        return jsonify({'error': f'No se pudo reiniciar la cámara {camera_id}.'}), 500


# ---------------------------------------------------------------------------
# GET /api/cameras/esp32/scan  — Escanea red buscando ESP32s (admin)
# ---------------------------------------------------------------------------

@camera_bp.route('/esp32/scan', methods=['GET'])
@token_required
@admin_required
def scan_esp32(current_user):
    """
    Escanea la red local buscando dispositivos ESP32-CAM.

    Obtiene la IP del host, escanea el subrange /24 en el puerto 80
    buscando respuestas HTTP que contengan patrones de ESP32.
    """
    try:
        import requests as req_lib
    except ImportError:
        return jsonify({
            'error': 'La librería requests no está disponible.'
        }), 500

    timeout = request.args.get('timeout', default=2, type=int)
    timeout = min(max(timeout, 1), 10)  # Entre 1 y 10 segundos

    try:
        # Obtener IP local y subnet
        local_ip = _get_local_ip()
        if not local_ip:
            return jsonify({'error': 'No se pudo determinar la IP local.'}), 500

        subnet = '.'.join(local_ip.split('.')[:3])
        logger.info("Escaneando red %s.0/24 buscando ESP32s...", subnet)

        found_devices = []
        scan_threads = []
        results_lock = threading.Lock()

        def check_host(ip_addr: str):
            """Verifica si un host responde como ESP32-CAM."""
            try:
                resp = req_lib.get(
                    f'http://{ip_addr}',
                    timeout=timeout,
                    allow_redirects=True,
                )
                body = resp.text.lower()
                if 'esp32' in body or 'esp-32' in body or 'esp cam' in body:
                    with results_lock:
                        found_devices.append({
                            'ip': ip_addr,
                            'port': 80,
                            'status': resp.status_code,
                            'type': 'esp32',
                            'name': f'ESP32-CAM ({ip_addr})',
                        })
            except Exception:
                pass  # Host no disponible o no responde

        # Escanear rango /24 con threads
        for host_num in range(1, 255):
            ip = f'{subnet}.{host_num}'
            t = threading.Thread(target=check_host, args=(ip,), daemon=True)
            scan_threads.append(t)
            t.start()

            # Limitar concurrencia a 50 threads simultáneos
            if len(scan_threads) >= 50:
                for t in scan_threads:
                    t.join(timeout=timeout + 1)
                scan_threads = []

        # Esperar threads restantes
        for t in scan_threads:
            t.join(timeout=timeout + 1)

        logger.info("Escaneo completado: %s ESP32(s) encontrado(s).", len(found_devices))

        return jsonify({
            'devices': found_devices,
            'count': len(found_devices),
            'subnet': f'{subnet}.0/24',
            'scanned_from': local_ip
        }), 200

    except Exception as e:
        logger.error("Error en scan_esp32: %s", e)
        return jsonify({'error': f'Error al escanear red: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------

def _get_local_ip() -> str:
    """
    Obtiene la IP local del host creando una conexión UDP
    a una dirección pública (no envía datos).
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        # No necesita ser alcanzable, solo para determinar la IP de salida
        s.connect(('8.8.8.8', 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return ''


# ===========================================================================
# Visión Computacional — Generador MJPEG anotado + Endpoints de control
# Paso #4 / 5.2 del plan docs/plan-vision-local-cloud.md.
#
# Los endpoints siguen las mismas convenciones que el resto del blueprint
# (protección con @token_required, manejo de errores consistente, formato
# JSON unificado). El decorador ``token_required`` también acepta el token
# como query parameter ``?token=`` (ver auth.jwt_handler), lo que permite
# consumir el stream MJPEG anotado desde una etiqueta ``<img>``.
# ===========================================================================

def generate_annotated_frames(camera_id: str, fps: float = 15.0):
    """
    Generador MJPEG que sirve frames anotados por el motor de visión.

    Si hay un motor de visión activo y disponible para la cámara, se sirve el
    frame anotado (bounding boxes dibujados). En caso contrario (visión
    desactivada o motor no disponible), el ``CameraManager`` sirve el frame
    crudo como *fallback* interno.

    Se detiene cuando el cliente se desconecta (GeneratorExit al cerrar la
    conexión multipart), igual que :func:`generate_frames`.
    """
    interval = 1.0 / fps if fps > 0 else 1.0 / 15.0

    while True:
        # Frame anotado (o crudo por fallback interno del CameraManager).
        frame_data = camera_manager.get_annotated_frame(camera_id)

        if frame_data is None:
            # Cámara no disponible — reintentar sin consumir CPU.
            time.sleep(interval)
            continue

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n'
        )
        time.sleep(interval)


# ---------------------------------------------------------------------------
# GET  /api/cameras/vision/modes  — Modos de visión disponibles
# ---------------------------------------------------------------------------
# Nota: esta ruta estática se declara ANTES que las rutas dinámicas
# ``/<camera_id>/vision/*`` para que Werkzeug la resuelva con prioridad.

@camera_bp.route('/vision/modes', methods=['GET'])
@token_required
def vision_modes(current_user):
    """Lista los modos de visión disponibles según las dependencias instaladas."""
    try:
        if VISION_FACTORY_AVAILABLE and VisionEngineFactory is not None:
            modes = VisionEngineFactory.get_available_modes()
        else:
            modes = ['off']
        return jsonify({'modes': modes}), 200
    except Exception as e:
        logger.error("Error en vision_modes: %s", e)
        return jsonify({'error': f'Error al obtener modos de visión: {str(e)}'}), 500


# ---------------------------------------------------------------------------
# POST /api/cameras/<id>/vision/start  — Activa visión en una cámara
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/vision/start', methods=['POST'])
@token_required
def start_vision(current_user, camera_id):
    """
    Activa el motor de visión para una cámara.

    Body JSON opcional:
        - mode: ``'cloud'`` | ``'local'`` | ``'off'``
          (por defecto ``VISION_DEFAULT_MODE`` del entorno o ``'cloud'``).
    """
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    data = request.get_json(silent=True) or {}
    mode = data.get('mode') or os.environ.get('VISION_DEFAULT_MODE', 'cloud')

    try:
        success = camera_manager.enable_vision(camera_id, mode)
    except ValueError as ve:
        # Modo inválido (validado por VisionEngineFactory).
        return jsonify({'error': str(ve)}), 400
    except Exception as e:
        logger.error("Error en start_vision (%s): %s", camera_id, e)
        return jsonify({'error': f'Error al activar la visión: {str(e)}'}), 500

    if not success:
        return jsonify({
            'error': 'No se pudo activar la visión (¿capa de visión no disponible?).'
        }), 400

    status = camera_manager.get_vision_status(camera_id)
    active_mode = status.get('mode', mode)
    available = status.get('available', False)
    detections = status.get('detections', {
        'count': 0, 'labels': {}, 'timestamp': None
    })

    if not available:
        # Motor creado pero no disponible: feedback accionable para el usuario.
        return jsonify({
            'message': (
                f'Motor {active_mode} creado pero no disponible. '
                'Verifica la API key y modelo en Ajustes.'
            ),
            'camera_id': camera_id,
            'mode': active_mode,
            'active': status.get('active', False),
            'available': False,
            'detections': detections,
        }), 200

    return jsonify({
        'message': f'Visión activada en modo {active_mode}',
        'camera_id': camera_id,
        'mode': active_mode,
        'active': status.get('active', False),
        'available': True,
        'detections': detections,
    }), 200


# ---------------------------------------------------------------------------
# POST /api/cameras/<id>/vision/stop  — Desactiva visión en una cámara
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/vision/stop', methods=['POST'])
@token_required
def stop_vision(current_user, camera_id):
    """Desactiva el motor de visión de una cámara (idempotente)."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    try:
        camera_manager.disable_vision(camera_id)
    except Exception as e:
        logger.error("Error en stop_vision (%s): %s", camera_id, e)
        return jsonify({'error': f'Error al desactivar la visión: {str(e)}'}), 500

    return jsonify({
        'message': 'Visión desactivada',
        'camera_id': camera_id,
    }), 200


# ---------------------------------------------------------------------------
# GET  /api/cameras/<id>/vision/stream  — Stream MJPEG anotado
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/vision/stream', methods=['GET'])
@token_required
def vision_stream(current_user, camera_id):
    """Stream MJPEG con frames anotados (o crudos como fallback)."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    if not source.is_running:
        return jsonify({'error': f'Cámara {camera_id} no está activa.'}), 400

    fps = request.args.get('fps', default=15.0, type=float)

    return Response(
        generate_annotated_frames(camera_id, fps=fps),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Credentials': 'true',
            'X-Accel-Buffering': 'no',
        }
    )


# ---------------------------------------------------------------------------
# GET  /api/cameras/<id>/vision/status  — Estado del motor de visión
# ---------------------------------------------------------------------------

@camera_bp.route('/<camera_id>/vision/status', methods=['GET'])
@token_required
def vision_status(current_user, camera_id):
    """Retorna el estado del motor de visión de una cámara."""
    source = camera_manager.get_camera(camera_id)
    if source is None:
        return jsonify({'error': f'Cámara {camera_id} no encontrada.'}), 404

    try:
        status = camera_manager.get_vision_status(camera_id)
        return jsonify(status), 200
    except Exception as e:
        logger.error("Error en vision_status (%s): %s", camera_id, e)
        return jsonify({'error': f'Error al obtener estado de visión: {str(e)}'}), 500
