"""
Endpoints de Visión Computacional para Argos2.
Procesamiento de imágenes con OpenCV.
"""

import os
import uuid
import time
import threading
from flask import Blueprint, request, jsonify
from auth.jwt_handler import token_required
from database.utils import UPLOAD_FOLDER, PROCESSED_FOLDER
from middleware.rate_limiter import limiter

vision_bp = Blueprint('vision', __name__, url_prefix='/api/vision')

# Almacenamiento en memoria de tareas (stub - en producción usar Redis/DB)
TASKS = {}


def _get_json_body():
    """Obtiene y valida el body JSON de la petición."""
    data = request.get_json(silent=True)
    if data is None:
        raise ValueError("Se requiere un cuerpo JSON válido")
    return data


def _simulate_processing(task_id, operation, filepath):
    """
    Simula el procesamiento de una imagen.
    TODO: Reemplazar con procesamiento real usando OpenCV.
    """
    TASKS[task_id]['estado'] = 'PROCESSING'
    
    # Simular progreso
    for progress in range(0, 101, 20):
        time.sleep(0.5)
        TASKS[task_id]['progreso'] = progress
    
    # Resultado mock
    TASKS[task_id]['estado'] = 'COMPLETED'
    TASKS[task_id]['progreso'] = 100
    TASKS[task_id]['resultados'] = {
        'Operación': operation.capitalize(),
        'Estado': 'Completado (modo stub)',
        'Archivo': os.path.basename(filepath),
        'Nota': 'El procesamiento real con OpenCV será implementado próximamente'
    }
    TASKS[task_id]['imagen_salida'] = None


@vision_bp.route('/process', methods=['POST'])
@token_required
@limiter.limit('10/minute')
def process_image(current_user):
    """
    Endpoint para procesar una imagen.
    Acepta upload de archivo con operación especificada.
    Retorna un task_id para consultar el estado.
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No se encontró archivo en la petición'}), 400
    
    file = request.files['file']
    operation = request.form.get('operation', 'deteccion')
    
    if file.filename == '':
        return jsonify({'error': 'No se seleccionó archivo'}), 400
    
    if operation not in ['deteccion', 'clasificacion', 'mejora']:
        return jsonify({'error': 'Operación no válida. Use: deteccion, clasificacion, mejora'}), 400
    
    # Guardar archivo
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    # Crear tarea
    task_id = uuid.uuid4().hex
    TASKS[task_id] = {
        'task_id': task_id,
        'estado': 'PENDING',
        'progreso': 0,
        'operacion': operation,
        'archivo': filepath,
        'resultados': None,
        'imagen_salida': None,
        'mensaje_error': None
    }
    
    # Iniciar procesamiento en hilo separado (stub)
    thread = threading.Thread(
        target=_simulate_processing,
        args=(task_id, operation, filepath)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'task_id': task_id,
        'message': 'Imagen recibida. Procesando...'
    }), 202


@vision_bp.route('/status/<task_id>', methods=['GET'])
@token_required
def get_task_status(current_user, task_id):
    """
    Endpoint para consultar el estado de una tarea de procesamiento.
    """
    if task_id not in TASKS:
        return jsonify({'error': 'Tarea no encontrada'}), 404
    
    task = TASKS[task_id]
    
    response = {
        'task_id': task['task_id'],
        'estado': task['estado'],
        'progreso': task['progreso'],
        'resultados': task['resultados'],
        'imagen_salida': task['imagen_salida'],
        'mensaje_error': task['mensaje_error']
    }
    
    return jsonify(response), 200
