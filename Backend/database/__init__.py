"""
Módulo de base de datos para Argos2.
Proporciona conexión a SQLite con WAL mode y operaciones CRUD.
"""

from .db import (
    get_connection,
    get_db,
    close_connection,
    init_database,
    row_to_dict,
    rows_to_list,
    DB_PATH
)

from .utils import (
    generate_image_filename,
    get_image_path,
    ensure_directories,
    UPLOAD_FOLDER,
    PROCESSED_FOLDER
)

__all__ = [
    # db.py
    'get_connection',
    'get_db',
    'close_connection',
    'init_database',
    'row_to_dict',
    'rows_to_list',
    'DB_PATH',
    # utils.py
    'generate_image_filename',
    'get_image_path',
    'ensure_directories',
    'UPLOAD_FOLDER',
    'PROCESSED_FOLDER',
]
