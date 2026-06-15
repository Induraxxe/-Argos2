"""
Pruebas de los endpoints y servicio de settings de visión (Argos2).

Valida:

    - GET  /api/settings/vision  — devuelve todas las variables + API key
      enmascarada.
    - PUT  /api/settings/vision  — validación, actualización, sincronización
      con ``os.environ``, permisos admin, protección de API key.
    - Funciones helper del ``settings_service`` (get/update/init/sync/mask).

Se usa una base de datos temporal (SQLite en ``tmp_path``) para cada test,
evitando afectar la DB real del proyecto.

Cómo ejecutar::

    # Desde el directorio Backend/
    python -m pytest tests/test_settings.py -v

    # O desde la raíz del proyecto
    python -m pytest Backend/tests/test_settings.py -v
"""

# ---------------------------------------------------------------------------
# Configuración del entorno ANTES de importar módulos del proyecto.
# jwt_handler.py exige JWT_SECRET_KEY; app.py exige SECRET_KEY.
# ---------------------------------------------------------------------------
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-settings')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret-key-settings')

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from flask import Flask

# Importar módulos del proyecto (conftest.py ya añade Backend/ a sys.path).
import database.db as db_module
from database.db import init_database, close_connection
from routes.settings import settings_bp
from services.settings_service import (
    API_KEY_SETTING,
    VALID_VISION_MODES,
    VISION_SETTINGS_MAP,
    get_masked_vision_settings,
    get_setting,
    get_vision_settings,
    init_settings_from_env,
    is_api_key_masked_or_empty,
    mask_api_key,
    sync_settings_to_env,
    update_setting,
    update_vision_settings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_token(rol: str = 'usuario', user_id: int = 1) -> str:
    """Genera un JWT válido firmado con la clave de test."""
    payload = {
        'user_id': user_id,
        'username': 'tester',
        'email': 'test@example.com',
        'rol': rol,
        'jti': 'test-jti-settings',
        'ver': 1,
        'iat': datetime.now(timezone.utc),
        'exp': datetime.now(timezone.utc) + timedelta(hours=1),
        'type': 'access',
    }
    return pyjwt.encode(
        payload, os.environ['JWT_SECRET_KEY'], algorithm='HS256'
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """
    Crea una base de datos SQLite temporal en ``tmp_path`` y parchea
    ``DB_PATH`` para que todas las operaciones de DB usen este archivo.

    También inserta un usuario de prueba (ID=1) para que las foreign keys
    de ``logs_sistema`` (que referencia ``usuarios.id``) se satisfagan al
    registrar logs desde los endpoints.

    **Aislamiento de entorno:** guarda y restaura todas las variables de
    entorno de visión, ya que ``update_vision_settings()`` las modifica
    directamente en ``os.environ`` y los cambios persistirían entre tests
    (contaminando ``test_vision_engine.py``).
    """
    # ---- Guardar variables de entorno originales ----
    env_backup = {}
    for _db_key, (env_var, _default) in VISION_SETTINGS_MAP.items():
        env_backup[env_var] = os.environ.get(env_var)

    db_path = str(tmp_path / 'test_settings.db')
    monkeypatch.setattr(db_module, 'DB_PATH', db_path)
    # Limpiar cualquier conexión cacheada del thread.
    close_connection()
    # Crear todas las tablas (incluida settings con defaults).
    init_database()
    # Insertar un usuario de prueba para satisfacer FKs (logs_sistema).
    with db_module.get_db() as db:
        db.execute(
            '''INSERT INTO usuarios
               (id, username, email, password_hash, nombre_completo,
                fecha_nacimiento, tipo_documento, numero_documento, rol)
               VALUES (1, 'tester', 'test@example.com', 'hash',
                       'Tester', '2000-01-01', 'V', '12345678', 'admin')'''
        )
    yield
    close_connection()
    # ---- Restaurar variables de entorno originales ----
    for env_var, original in env_backup.items():
        if original is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = original


@pytest.fixture
def app(temp_db):
    """App Flask de prueba con el blueprint de settings registrado."""
    flask_app = Flask(__name__)
    flask_app.register_blueprint(settings_bp)
    flask_app.testing = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Headers con token de usuario normal."""
    return {'Authorization': f'Bearer {_make_token()}'}


@pytest.fixture
def admin_headers():
    """Headers con token de admin."""
    return {'Authorization': f'Bearer {_make_token(rol="admin")}'}


# ===========================================================================
# Tests del settings_service (unit tests)
# ===========================================================================

class TestSettingsService:
    """Pruebas de las funciones helper del settings_service."""

    def test_get_setting_returns_value(self, temp_db):
        """get_setting devuelve el valor almacenado."""
        update_setting('test_key', 'test_value')
        assert get_setting('test_key') == 'test_value'

    def test_get_setting_default(self, temp_db):
        """get_setting devuelve el default si la clave no existe."""
        assert get_setting('no_existe', 'fallback') == 'fallback'

    def test_get_setting_none_if_missing(self, temp_db):
        """get_setting devuelve None si la clave no existe y no hay default."""
        assert get_setting('no_existe') is None

    def test_update_setting_upsert(self, temp_db):
        """update_setting crea y luego actualiza (UPSERT)."""
        update_setting('mi_key', 'v1')
        assert get_setting('mi_key') == 'v1'
        update_setting('mi_key', 'v2')
        assert get_setting('mi_key') == 'v2'

    def test_get_vision_settings_has_all_keys(self, temp_db):
        """get_vision_settings devuelve las 9 claves de visión."""
        vision = get_vision_settings()
        for expected_key in VISION_SETTINGS_MAP:
            assert expected_key in vision, f"Falta la clave {expected_key}"

    def test_update_vision_settings_updates_db_and_env(self, temp_db):
        """update_vision_settings actualiza DB y os.environ simultáneamente."""
        update_vision_settings({'roboflow_workspace': 'mi-workspace'})
        # DB
        assert get_setting('roboflow_workspace') == 'mi-workspace'
        # os.environ
        assert os.environ.get('ROBOFLOW_WORKSPACE') == 'mi-workspace'

    def test_update_vision_settings_ignores_unknown_keys(self, temp_db):
        """Las claves que no pertenecen al mapping de visión se ignoran."""
        update_vision_settings({'clave_desconocida': 'valor'})
        assert get_setting('clave_desconocida') is None

    def test_update_vision_settings_api_key_empty_not_overwritten(self, temp_db):
        """Una API key vacía no sobrescribe el valor existente."""
        update_setting(API_KEY_SETTING, 'original-key-12345678')
        update_vision_settings({API_KEY_SETTING: ''})
        assert get_setting(API_KEY_SETTING) == 'original-key-12345678'

    def test_update_vision_settings_api_key_masked_not_overwritten(self, temp_db):
        """Una API key enmascarada no sobrescribe el valor existente."""
        update_setting(API_KEY_SETTING, 'original-key-12345678')
        update_vision_settings({API_KEY_SETTING: '****5678'})
        assert get_setting(API_KEY_SETTING) == 'original-key-12345678'

    def test_update_vision_settings_api_key_real_overwrites(self, temp_db):
        """Una API key real (no vacía, no enmascarada) sí sobrescribe."""
        update_setting(API_KEY_SETTING, 'old-key')
        update_vision_settings({API_KEY_SETTING: 'new-real-key-9999'})
        assert get_setting(API_KEY_SETTING) == 'new-real-key-9999'


class TestMaskApiKey:
    """Pruebas del helper mask_api_key."""

    def test_mask_long_key(self):
        """Una key larga se enmascara mostrando los últimos 4 caracteres."""
        assert mask_api_key('abcdef123456') == '****3456'

    def test_mask_short_key(self):
        """Una key muy corta se oculta completamente."""
        assert mask_api_key('abc') == '****abc'

    def test_mask_empty_key(self):
        """Una key vacía devuelve string vacío."""
        assert mask_api_key('') == ''

    def test_mask_none_key(self):
        """None devuelve string vacío."""
        assert mask_api_key(None) == ''

    def test_mask_exactly_4_chars(self):
        """Una key de exactamente 4 caracteres se oculta."""
        assert mask_api_key('1234') == '****1234'


class TestIsApiKeyMasked:
    """Pruebas del detector de valores enmascarados/vacíos."""

    def test_empty_is_ignored(self):
        assert is_api_key_masked_or_empty('') is True

    def test_none_is_ignored(self):
        assert is_api_key_masked_or_empty(None) is True

    def test_masked_is_ignored(self):
        assert is_api_key_masked_or_empty('****5678') is True

    def test_real_key_not_ignored(self):
        assert is_api_key_masked_or_empty('real-api-key') is False


class TestInitAndSync:
    """Pruebas de init_settings_from_env y sync_settings_to_env."""

    def test_init_settings_from_env_creates_defaults(self, temp_db, monkeypatch):
        """init_settings_from_env inserta defaults desde os.environ."""
        monkeypatch.setenv('ROBOFLOW_WORKSPACE', 'env-workspace')
        # Limpiar la tabla para forzar la inserción.
        with db_module.get_db() as db:
            db.execute('DELETE FROM settings')
        init_settings_from_env()
        assert get_setting('roboflow_workspace') == 'env-workspace'

    def test_init_settings_from_env_idempotent(self, temp_db):
        """init_settings_from_env no sobrescribe valores existentes."""
        update_setting('roboflow_workspace', 'valor-existente')
        init_settings_from_env()
        assert get_setting('roboflow_workspace') == 'valor-existente'

    def test_sync_settings_to_env(self, temp_db):
        """sync_settings_to_env carga valores de la DB en os.environ."""
        update_setting('roboflow_workspace', 'synced-workspace')
        sync_settings_to_env()
        assert os.environ.get('ROBOFLOW_WORKSPACE') == 'synced-workspace'


# ===========================================================================
# Tests del endpoint GET /api/settings/vision
# ===========================================================================

class TestGetVisionConfig:
    """Pruebas del endpoint GET /api/settings/vision."""

    def test_get_returns_200(self, client, auth_headers):
        """GET con token válido devuelve 200."""
        resp = client.get('/api/settings/vision', headers=auth_headers)
        assert resp.status_code == 200

    def test_get_requires_auth(self, client):
        """GET sin token devuelve 401."""
        resp = client.get('/api/settings/vision')
        assert resp.status_code == 401

    def test_get_returns_all_variables(self, client, auth_headers):
        """La respuesta contiene todas las claves de visión."""
        data = client.get(
            '/api/settings/vision', headers=auth_headers
        ).get_json()
        for expected_key in VISION_SETTINGS_MAP:
            assert expected_key in data, f"Falta la clave {expected_key}"

    def test_get_api_key_is_masked(self, client, auth_headers):
        """La API key se devuelve enmascarada (**** + últimos 4)."""
        # Establecer una API key conocida.
        update_setting(API_KEY_SETTING, 'secret-key-abcd1234')
        data = client.get(
            '/api/settings/vision', headers=auth_headers
        ).get_json()
        key_val = data[API_KEY_SETTING]
        assert key_val == '****1234'
        assert 'secret-key-abcd1234' not in key_val

    def test_get_api_key_empty_returns_empty(self, client, auth_headers):
        """Si no hay API key, se devuelve string vacío (no '****')."""
        update_setting(API_KEY_SETTING, '')
        data = client.get(
            '/api/settings/vision', headers=auth_headers
        ).get_json()
        assert data[API_KEY_SETTING] == ''

    def test_get_never_exposes_full_key(self, client, auth_headers):
        """El endpoint NUNCA expone la API key completa."""
        full_key = 'a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'
        update_setting(API_KEY_SETTING, full_key)
        data = client.get(
            '/api/settings/vision', headers=auth_headers
        ).get_json()
        assert full_key not in data[API_KEY_SETTING]
        assert data[API_KEY_SETTING].startswith('****')


# ===========================================================================
# Tests del endpoint PUT /api/settings/vision
# ===========================================================================

class TestUpdateVisionConfig:
    """Pruebas del endpoint PUT /api/settings/vision."""

    def test_put_requires_auth(self, client):
        """PUT sin token devuelve 401."""
        resp = client.put(
            '/api/settings/vision',
            json={'roboflow_workspace': 'test'},
        )
        assert resp.status_code == 401

    def test_put_requires_admin(self, client, auth_headers):
        """PUT con usuario no-admin devuelve 403."""
        resp = client.put(
            '/api/settings/vision',
            json={'roboflow_workspace': 'test'},
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_put_admin_succeeds(self, client, admin_headers):
        """PUT con admin devuelve 200."""
        resp = client.put(
            '/api/settings/vision',
            json={'roboflow_workspace': 'mi-workspace'},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    def test_put_no_json_body(self, client, admin_headers):
        """PUT sin body JSON devuelve 400."""
        resp = client.put('/api/settings/vision', headers=admin_headers)
        assert resp.status_code == 400

    def test_put_updates_value(self, client, admin_headers):
        """PUT actualiza el valor en la DB."""
        client.put(
            '/api/settings/vision',
            json={'roboflow_workspace': 'updated-workspace'},
            headers=admin_headers,
        )
        assert get_setting('roboflow_workspace') == 'updated-workspace'

    def test_put_response_has_masked_key(self, client, admin_headers):
        """La respuesta del PUT tiene la API key enmascarada."""
        update_setting(API_KEY_SETTING, 'secret-key-abcd1234')
        resp = client.put(
            '/api/settings/vision',
            json={'roboflow_model_id': 'test/1'},
            headers=admin_headers,
        )
        data = resp.get_json()
        assert data['config'][API_KEY_SETTING] == '****1234'

    def test_put_invalid_mode_returns_400(self, client, admin_headers):
        """Un modo inválido devuelve 400."""
        resp = client.put(
            '/api/settings/vision',
            json={'vision_default_mode': 'invalid_mode'},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_put_valid_modes_accepted(self, client, admin_headers):
        """Todos los modos válidos son aceptados."""
        for mode in VALID_VISION_MODES:
            resp = client.put(
                '/api/settings/vision',
                json={'vision_default_mode': mode},
                headers=admin_headers,
            )
            assert resp.status_code == 200, f"Modo {mode} debería ser válido"

    def test_put_normalizes_mode_lowercase(self, client, admin_headers):
        """El modo se normaliza a minúsculas."""
        resp = client.put(
            '/api/settings/vision',
            json={'vision_default_mode': 'CLOUD'},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert get_setting('vision_default_mode') == 'cloud'

    def test_put_updates_os_environ(self, client, admin_headers):
        """PUT actualiza os.environ con los nuevos valores."""
        client.put(
            '/api/settings/vision',
            json={'roboflow_workflow_id': 'wf-123'},
            headers=admin_headers,
        )
        assert os.environ.get('ROBOFLOW_WORKFLOW_ID') == 'wf-123'

    def test_put_api_key_empty_not_overwritten(self, client, admin_headers):
        """Una API key vacía en el PUT no sobrescribe la existente."""
        update_setting(API_KEY_SETTING, 'original-key-12345678')
        client.put(
            '/api/settings/vision',
            json={API_KEY_SETTING: ''},
            headers=admin_headers,
        )
        assert get_setting(API_KEY_SETTING) == 'original-key-12345678'

    def test_put_api_key_masked_not_overwritten(self, client, admin_headers):
        """Una API key enmascarada en el PUT no sobrescribe la existente."""
        update_setting(API_KEY_SETTING, 'original-key-12345678')
        client.put(
            '/api/settings/vision',
            json={API_KEY_SETTING: '****5678'},
            headers=admin_headers,
        )
        assert get_setting(API_KEY_SETTING) == 'original-key-12345678'

    def test_put_api_key_real_overwrites(self, client, admin_headers):
        """Una API key real en el PUT sí sobrescribe la existente."""
        update_setting(API_KEY_SETTING, 'old-key-12345678')
        client.put(
            '/api/settings/vision',
            json={API_KEY_SETTING: 'new-real-key-9999'},
            headers=admin_headers,
        )
        assert get_setting(API_KEY_SETTING) == 'new-real-key-9999'

    def test_put_logs_to_db(self, client, admin_headers):
        """El PUT registra el cambio en logs_sistema."""
        from database.db import obtener_logs

        client.put(
            '/api/settings/vision',
            json={'roboflow_workspace': 'logged-change'},
            headers=admin_headers,
        )
        logs = obtener_logs(componente='settings', limite=5)
        assert any(
            'actualizada' in (log.get('mensaje', '') or '').lower()
            for log in logs
        )

    def test_put_response_has_reloaded_cameras(self, client, admin_headers):
        """La respuesta incluye la lista de cámaras recargadas."""
        resp = client.put(
            '/api/settings/vision',
            json={'roboflow_workspace': 'test'},
            headers=admin_headers,
        )
        data = resp.get_json()
        assert 'reloaded_cameras' in data
        assert isinstance(data['reloaded_cameras'], list)

    def test_put_partial_update(self, client, admin_headers):
        """PUT actualiza solo las variables enviadas (no requiere todas)."""
        # Guardar un valor previo.
        update_setting('roboflow_workspace', 'prev-workspace')
        # Actualizar solo una variable distinta.
        client.put(
            '/api/settings/vision',
            json={'roboflow_model_id': 'modelo/2'},
            headers=admin_headers,
        )
        # La variable no enviada se mantiene.
        assert get_setting('roboflow_workspace') == 'prev-workspace'
        # La variable enviada se actualizó.
        assert get_setting('roboflow_model_id') == 'modelo/2'
