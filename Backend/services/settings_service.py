"""
Servicio de gestión de ajustes (settings) para Argos2.

Proporciona una capa de abstracción sobre la tabla ``settings`` (clave-valor)
de la base de datos, con funciones específicas para la configuración de
visión computacional (Roboflow).

La base de datos es la **fuente de verdad**: al arrancar la aplicación los
valores de la DB se sincronizan con ``os.environ`` (ver
[`sync_settings_to_env()`](../services/settings_service.py)) para que los
motores de visión —que leen de ``os.environ`` en su constructor— tomen la
configuración correcta.

Seguridad: la API key de Roboflow **nunca** se devuelve en texto plano por
los endpoints; se utiliza [`mask_api_key()`](../services/settings_service.py)
para enmascararla.
"""

import logging
import os
from typing import Dict, List, Optional

from database.db import get_db, row_to_dict

logger = logging.getLogger(__name__)


# =============================================================================
# Mapeo de claves de visión: DB key -> (variable de entorno, default)
# =============================================================================

#: Diccionario que mapea cada clave de la DB con su variable de entorno
#: correspondiente y su valor por defecto (cuando la variable de entorno
#: no esté definida). Este mapping es la única fuente de verdad para la
#: traducción DB <-> os.environ.
VISION_SETTINGS_MAP: Dict[str, tuple] = {
    'vision_default_mode': ('VISION_DEFAULT_MODE', 'off'),
    'roboflow_api_key': ('ROBOFLOW_API_KEY', ''),
    'roboflow_api_url': ('ROBOFLOW_API_URL', ''),
    'roboflow_workspace': ('ROBOFLOW_WORKSPACE', ''),
    'roboflow_workflow_id': ('ROBOFLOW_WORKFLOW_ID', ''),
    'roboflow_workflow_image_input': ('ROBOFLOW_WORKFLOW_IMAGE_INPUT', 'image'),
    'roboflow_workflow_use_cache': ('ROBOFLOW_WORKFLOW_USE_CACHE', 'true'),
    'roboflow_use_server_overlay': ('ROBOFLOW_USE_SERVER_OVERLAY', 'false'),
    'roboflow_model_id': ('ROBOFLOW_MODEL_ID', ''),
}

#: Modos de visión válidos (para validación del PUT).
VALID_VISION_MODES = ('off', 'cloud', 'local')

#: Clave que contiene la API key sensible.
API_KEY_SETTING = 'roboflow_api_key'


# =============================================================================
# Funciones CRUD genéricas
# =============================================================================

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    Lee un valor de la tabla ``settings``.

    Args:
        key: Clave a consultar.
        default: Valor a retornar si la clave no existe.

    Returns:
        El valor almacenado, o ``default`` si no existe.
    """
    with get_db() as db:
        cursor = db.execute(
            'SELECT value FROM settings WHERE key = ?', (key,)
        )
        row = cursor.fetchone()
        if row is None:
            return default
        result = row_to_dict(row)
        return result['value'] if result else default


def update_setting(key: str, value: str) -> None:
    """
    Actualiza (o crea) un valor en la tabla ``settings`` (UPSERT).

    Args:
        key: Clave a actualizar.
        value: Nuevo valor (se convierte a ``str``).
    """
    with get_db() as db:
        db.execute(
            '''INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = CURRENT_TIMESTAMP''',
            (key, str(value)),
        )


def get_all_settings() -> Dict[str, str]:
    """
    Retorna todos los ajustes de la tabla ``settings`` como un diccionario.
    """
    with get_db() as db:
        cursor = db.execute('SELECT key, value FROM settings')
        return {row['key']: row['value'] for row in cursor.fetchall()}


# =============================================================================
# Funciones específicas de visión
# =============================================================================

def get_vision_settings() -> Dict[str, str]:
    """
    Retorna todas las variables de configuración de visión desde la DB.

    Si una clave no existe en la DB, se usa el valor por defecto del mapping.

    Returns:
        Dict con las claves de visión y sus valores.
    """
    with get_db() as db:
        cursor = db.execute(
            'SELECT key, value FROM settings WHERE key IN ({})'.format(
                ','.join('?' * len(VISION_SETTINGS_MAP))
            ),
            tuple(VISION_SETTINGS_MAP.keys()),
        )
        stored = {row['key']: row['value'] for row in cursor.fetchall()}

    # Asegurar que todas las claves estén presentes (con default si faltan).
    result: Dict[str, str] = {}
    for db_key, (_env_var, default_val) in VISION_SETTINGS_MAP.items():
        result[db_key] = stored.get(db_key, default_val)
    return result


def get_vision_env_settings() -> Dict[str, str]:
    """
    Retorna las variables de visión usando los **nombres de variables de
    entorno** como claves (en vez de las claves internas de la DB).

    Útil para pasar configuración directamente a los motores de visión.

    Returns:
        Dict ``{VARIABLE_ENTORNO: valor}``.
    """
    vision = get_vision_settings()
    env_settings: Dict[str, str] = {}
    for db_key, value in vision.items():
        env_var = VISION_SETTINGS_MAP[db_key][0]
        env_settings[env_var] = value
    return env_settings


def update_vision_settings(data: Dict[str, str]) -> Dict[str, str]:
    """
    Actualiza múltiples variables de visión en la DB y sincroniza
    ``os.environ``.

    Solo se actualizan las claves presentes en ``data`` que pertenezcan al
    mapping de visión. Las claves desconocidas se ignoran silenciosamente.

    **Seguridad — API key:** si ``roboflow_api_key`` llega como cadena vacía
    o como un valor enmascarado (que empiece con ``"****"``), **no se
    sobrescribe** el valor existente (se mantiene el anterior).

    Args:
        data: Diccionario ``{db_key: nuevo_valor}`` con los cambios.

    Returns:
        Dict con la configuración de visión **completa y actualizada**.
    """
    current = get_vision_settings()

    for key, value in data.items():
        if key not in VISION_SETTINGS_MAP:
            logger.debug("Clave de settings desconocida ignorada: %s", key)
            continue

        # Protección de la API key: no sobrescribir con vacío ni enmascarado.
        if key == API_KEY_SETTING:
            raw = str(value).strip() if value is not None else ''
            if raw == '' or raw.startswith('****'):
                logger.info(
                    "API key no modificada (valor recibido vacío o "
                    "enmascarado). Se mantiene el valor existente."
                )
                continue

        update_setting(key, str(value))
        # Sincronizar os.environ para que futuras instanciaciones de motores
        # tomen el valor actualizado.
        env_var = VISION_SETTINGS_MAP[key][0]
        os.environ[env_var] = str(value)
        logger.debug("Setting actualizado: %s -> %s", key, value)

    return get_vision_settings()


def init_settings_from_env() -> None:
    """
    Puebla la tabla ``settings`` con los valores por defecto de visión
    leyendo de ``os.environ`` como fallback.

    Usa ``INSERT OR IGNORE`` por lo que es **idempotente**: no sobrescribe
    valores ya existentes. Pensado para llamarse al arrancar la aplicación
    (desde ``init_database()`` o desde ``app.py``).
    """
    defaults: List[tuple] = []
    for db_key, (env_var, default_val) in VISION_SETTINGS_MAP.items():
        defaults.append((db_key, os.environ.get(env_var, default_val)))

    with get_db() as db:
        db.executemany(
            'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
            defaults,
        )
    logger.debug("Defaults de settings sincronizados desde entorno (%d claves).",
                 len(defaults))


def sync_settings_to_env() -> None:
    """
    Carga todos los valores de visión desde la DB y los escribe en
    ``os.environ``.

    Esto convierte a la **DB en la fuente de verdad**: al arrancar, los
    valores persistidos en la DB tienen prioridad sobre los del ``.env``.
    Debe llamarse después de ``init_database()``/``init_settings_from_env()``.
    """
    vision = get_vision_settings()
    for db_key, value in vision.items():
        env_var = VISION_SETTINGS_MAP[db_key][0]
        os.environ[env_var] = value if value is not None else ''
    logger.debug("Variables de visión sincronizadas DB -> os.environ (%d).",
                 len(vision))


# =============================================================================
# Helpers de seguridad (API key)
# =============================================================================

def mask_api_key(key: Optional[str]) -> str:
    """
    Enmascara una API key mostrando solo los últimos 4 caracteres.

    - ``"abcdef123456"`` -> ``"****3456"``
    - ``"abc"``          -> ``"****abc"``  (key muy corta: todo oculto)
    - ``""`` / ``None``  -> ``""``

    Args:
        key: La API key en texto plano.

    Returns:
        La versión enmascarada.
    """
    if not key:
        return ''
    key_str = str(key)
    if len(key_str) <= 4:
        return '****' + key_str
    return '****' + key_str[-4:]


def get_masked_vision_settings() -> Dict[str, str]:
    """
    Retorna la configuración de visión con la API key **enmascarada**.

    Pensado para los endpoints GET que devuelven la configuración al cliente.
    **Nunca** expone la API key completa.

    Returns:
        Dict con las claves de visión; ``roboflow_api_key`` viene enmascarada.
    """
    vision = get_vision_settings()
    vision[API_KEY_SETTING] = mask_api_key(vision.get(API_KEY_SETTING))
    return vision


def is_api_key_masked_or_empty(value: Optional[str]) -> bool:
    """
    Determina si un valor de API key recibido en un PUT debe ser ignorado
    (porque está vacío o es un valor enmascarado devuelto previamente por el
    GET).

    Args:
        value: El valor recibido para ``roboflow_api_key``.

    Returns:
        ``True`` si el valor debe ignorarse (no sobrescribir la key existente).
    """
    if value is None:
        return True
    raw = str(value).strip()
    return raw == '' or raw.startswith('****')
