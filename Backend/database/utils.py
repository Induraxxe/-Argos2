"""
Utilidades para gestión de archivos y nombres únicos con UUIDs.
"""

import uuid
import os
from datetime import datetime
from typing import Optional

# Directorio base para imágenes procesadas
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
PROCESSED_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'processed')


def ensure_directories():
    """Asegura que los directorios de imágenes existan."""
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(PROCESSED_FOLDER, exist_ok=True)


def generate_image_filename(
    original_filename: str,
    operation: str,
    user_id: Optional[int] = None,
    extension: Optional[str] = None
) -> str:
    """
    Genera un nombre de archivo único usando UUID v4 para evitar colisiones.
    
    Args:
        original_filename: Nombre original del archivo
        operation: Tipo de operación (deteccion, clasificacion, etc.)
        user_id: ID del usuario (opcional, para trazabilidad)
        extension: Extensión deseada (si es None, usa la original)
    
    Returns:
        str: Nombre de archivo único en formato: {operation}_{user_id}_{uuid}.{ext}
    
    Example:
        >>> generate_image_filename("foto.jpg", "deteccion", user_id=5)
        'deteccion_5_a1b2c3d4-e5f6-7890-abcd-ef1234567890.jpg'
    """
    # Obtener extensión
    if extension is None:
        _, ext = os.path.splitext(original_filename)
        extension = ext.lstrip('.') if ext else 'jpg'
    
    # Generar UUID v4
    unique_id = uuid.uuid4()
    
    # Construir nombre
    if user_id is not None:
        filename = f"{operation}_{user_id}_{unique_id}.{extension}"
    else:
        filename = f"{operation}_{unique_id}.{extension}"
    
    return filename


def get_image_path(filename: str, processed: bool = False) -> str:
    """
    Obtiene la ruta completa de una imagen.
    
    Args:
        filename: Nombre del archivo
        processed: True para imágenes procesadas, False para originales
    
    Returns:
        str: Ruta completa al archivo
    """
    folder = PROCESSED_FOLDER if processed else UPLOAD_FOLDER
    return os.path.join(folder, filename)
