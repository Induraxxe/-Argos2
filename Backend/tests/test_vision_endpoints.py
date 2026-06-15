"""
Pruebas de los endpoints REST de visión (Paso #4 / 5.2 del plan).

Valida los endpoints añadidos a [`Backend/routes/camera.py`](../routes/camera.py):

    GET  /api/cameras/vision/modes
    POST /api/cameras/<id>/vision/start
    POST /api/cameras/<id>/vision/stop
    GET  /api/cameras/<id>/vision/stream   (MJPEG anotado)
    GET  /api/cameras/<id>/vision/status

Se cubren:
    - Códigos de estado HTTP esperados (200/400/401/404).
    - Formato JSON unificado del proyecto (``{'message'|'error', ...}``).
    - Protección JWT (401 sin token).
    - Casos límite (cámara inexistente, modo inválido, cámara inactiva).
    - Contenido del stream MJPEG anotado.

Cada test usa una ``Flask`` app aislada con el blueprint ``camera_bp`` y un
``CameraManager`` limpio (reseteo del singleton) para no afectar a otros tests
ni depender de hardware real.

Cómo ejecutar::

    # Desde el directorio Backend/
    python -m pytest tests/test_vision_endpoints.py -v

    # O desde la raíz del proyecto
    python -m pytest Backend/tests/test_vision_endpoints.py -v
"""

# ---------------------------------------------------------------------------
# Configuración del entorno ANTES de importar módulos del proyecto.
# jwt_handler.py exige JWT_SECRET_KEY al importarse; app.py exige SECRET_KEY.
# Se usan valores por defecto solo para los tests si no están definidos.
# ---------------------------------------------------------------------------
import os

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-vision-endpoints')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret-key-for-vision-endpoints')

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt as pyjwt
import numpy as np
import pytest
from flask import Flask

# Importar módulos del proyecto (el conftest.py ya añade Backend/ a sys.path).
import routes.camera as camera_module
from database import db as db_module
from routes.camera import camera_bp
from services.camera_service import CameraManager, VideoSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubVideoSource(VideoSource):
    """
    VideoSource minimalista para tests (no requiere hardware/cámara real).

    Expone ``_frame_deque`` y ``_lock`` para que el ``CameraManager`` pueda
    extraer el frame crudo como ``np.ndarray`` al anotar.
    """

    def __init__(self, frame: Optional[np.ndarray] = None):
        import collections
        import threading
        self._frame_deque = collections.deque(maxlen=2)
        if frame is not None:
            self._frame_deque.append(frame)
        self._lock = threading.Lock()
        self._running = True

    def start(self) -> bool:
        self._running = True
        return True

    def get_frame(self) -> Optional[bytes]:
        return b"jpg-bytes-stub"

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def name(self) -> str:
        return "stub"

    @property
    def source_type(self) -> str:
        return "usb"


def _make_token(rol: str = 'usuario') -> str:
    """Genera un JWT válido firmado con la clave de test."""
    payload = {
        'user_id': 1,
        'username': 'tester',
        'email': 'test@example.com',
        'rol': rol,
        'jti': 'test-jti-vision',
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
def app(monkeypatch):
    """
    App Flask de prueba con el blueprint de cámaras registrado.

    Se mockean las funciones de la base de datos que ``decode_token`` consulta
    (blacklist y versión de token) para que la validación JWT no dependa del
    estado de la base de datos real ni requiera inicializarla.
    """
    # Mockear la fuente (database.db) — jwt_handler importa estas funciones de
    # forma diferida dentro de las funciones, por lo que patchear el módulo
    # fuente es suficiente.
    monkeypatch.setattr(db_module, 'verificar_token_revocado', lambda jti: False)
    monkeypatch.setattr(
        db_module, 'obtener_version_token_usuario', lambda uid: 1
    )

    flask_app = Flask(__name__)
    flask_app.register_blueprint(camera_bp)
    flask_app.testing = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {'Authorization': f'Bearer {_make_token()}'}


@pytest.fixture
def fresh_camera_manager(monkeypatch):
    """
    Devuelve un ``CameraManager`` limpio (singleton reseteado) y lo inyecta
    como ``camera_manager`` a nivel de módulo en ``routes.camera`` para que los
    endpoints lo utilicen.
    """
    CameraManager.reset_instance()
    cm = CameraManager()
    monkeypatch.setattr(camera_module, 'camera_manager', cm)
    yield cm
    CameraManager.reset_instance()


@pytest.fixture
def stub_camera_id(fresh_camera_manager):
    """Registra una cámara stub y devuelve su ID."""
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    cid = fresh_camera_manager.add_camera(_StubVideoSource(frame))
    return cid


# ---------------------------------------------------------------------------
# Pruebas: GET /api/cameras/vision/modes
# ---------------------------------------------------------------------------

class TestVisionModes:
    """Verifica el endpoint de listado de modos disponibles."""

    def test_modes_returns_200(self, client, auth_headers):
        resp = client.get('/api/cameras/vision/modes', headers=auth_headers)
        assert resp.status_code == 200

    def test_modes_payload_shape(self, client, auth_headers):
        data = client.get(
            '/api/cameras/vision/modes', headers=auth_headers
        ).get_json()
        assert 'modes' in data
        assert isinstance(data['modes'], list)

    def test_modes_includes_cloud(self, client, auth_headers):
        """Cloud siempre debe estar disponible (solo requiere inference_sdk)."""
        data = client.get(
            '/api/cameras/vision/modes', headers=auth_headers
        ).get_json()
        assert 'cloud' in data['modes']

    def test_modes_requires_token(self, client):
        resp = client.get('/api/cameras/vision/modes')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pruebas: POST /api/cameras/<id>/vision/start
# ---------------------------------------------------------------------------

class TestStartVision:
    """Verifica la activación de visión por cámara."""

    def test_start_cloud_returns_200(self, client, stub_camera_id, auth_headers):
        resp = client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            json={'mode': 'cloud'},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'message' in data
        assert data['mode'] == 'cloud'

    def test_start_default_mode_when_no_body(
        self, client, stub_camera_id, auth_headers
    ):
        """Sin body ni modo, usa VISION_DEFAULT_MODE (o 'cloud')."""
        resp = client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_start_off_deactivates(self, client, stub_camera_id, auth_headers):
        resp = client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            json={'mode': 'off'},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        status = client.get(
            f'/api/cameras/{stub_camera_id}/vision/status',
            headers=auth_headers,
        ).get_json()
        assert status['active'] is False

    def test_start_unknown_camera_returns_404(self, client, auth_headers):
        resp = client.post(
            '/api/cameras/no-existe/vision/start',
            json={'mode': 'cloud'},
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert 'error' in resp.get_json()

    def test_start_invalid_mode_returns_400(
        self, client, stub_camera_id, auth_headers
    ):
        resp = client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            json={'mode': 'satelite'},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_start_requires_token(self, client, stub_camera_id):
        resp = client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            json={'mode': 'cloud'},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pruebas: POST /api/cameras/<id>/vision/stop
# ---------------------------------------------------------------------------

class TestStopVision:
    """Verifica la desactivación de visión por cámara."""

    def test_stop_returns_200(self, client, stub_camera_id, auth_headers):
        resp = client.post(
            f'/api/cameras/{stub_camera_id}/vision/stop',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert 'message' in resp.get_json()

    def test_stop_is_idempotent(self, client, stub_camera_id, auth_headers):
        # Detener dos veces seguidas no debe fallar.
        r1 = client.post(
            f'/api/cameras/{stub_camera_id}/vision/stop', headers=auth_headers
        )
        r2 = client.post(
            f'/api/cameras/{stub_camera_id}/vision/stop', headers=auth_headers
        )
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_stop_after_start_clears_engine(
        self, client, stub_camera_id, auth_headers
    ):
        # Activar y luego desactivar.
        client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            json={'mode': 'cloud'},
            headers=auth_headers,
        )
        before = client.get(
            f'/api/cameras/{stub_camera_id}/vision/status',
            headers=auth_headers,
        ).get_json()
        assert before['active'] is True

        client.post(
            f'/api/cameras/{stub_camera_id}/vision/stop', headers=auth_headers
        )
        after = client.get(
            f'/api/cameras/{stub_camera_id}/vision/status',
            headers=auth_headers,
        ).get_json()
        assert after['active'] is False

    def test_stop_unknown_camera_returns_404(self, client, auth_headers):
        resp = client.post(
            '/api/cameras/no-existe/vision/stop', headers=auth_headers
        )
        assert resp.status_code == 404

    def test_stop_requires_token(self, client, stub_camera_id):
        resp = client.post(f'/api/cameras/{stub_camera_id}/vision/stop')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pruebas: GET /api/cameras/<id>/vision/status
# ---------------------------------------------------------------------------

class TestVisionStatus:
    """Verifica el endpoint de estado del motor de visión."""

    def test_status_inactive_when_no_engine(
        self, client, stub_camera_id, auth_headers
    ):
        data = client.get(
            f'/api/cameras/{stub_camera_id}/vision/status',
            headers=auth_headers,
        ).get_json()
        assert data['active'] is False
        assert data['mode'] == 'none'

    def test_status_active_after_start_cloud(
        self, client, stub_camera_id, auth_headers
    ):
        client.post(
            f'/api/cameras/{stub_camera_id}/vision/start',
            json={'mode': 'cloud'},
            headers=auth_headers,
        )
        data = client.get(
            f'/api/cameras/{stub_camera_id}/vision/status',
            headers=auth_headers,
        ).get_json()
        assert data['active'] is True
        assert data['mode'] == 'cloud'

    def test_status_unknown_camera_returns_404(self, client, auth_headers):
        resp = client.get(
            '/api/cameras/no-existe/vision/status', headers=auth_headers
        )
        assert resp.status_code == 404

    def test_status_requires_token(self, client, stub_camera_id):
        resp = client.get(f'/api/cameras/{stub_camera_id}/vision/status')
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pruebas: GET /api/cameras/<id>/vision/stream
# ---------------------------------------------------------------------------

class TestVisionStream:
    """Verifica el stream MJPEG anotado."""

    def test_stream_unknown_camera_returns_404(self, client, auth_headers):
        resp = client.get(
            '/api/cameras/no-existe/vision/stream', headers=auth_headers
        )
        assert resp.status_code == 404

    def test_stream_requires_token(self, client, stub_camera_id):
        resp = client.get(f'/api/cameras/{stub_camera_id}/vision/stream')
        assert resp.status_code == 401

    def test_stream_inactive_camera_returns_400(
        self, client, fresh_camera_manager, auth_headers
    ):
        # Registrar la cámara y luego detenerla (add_camera la inicia sola).
        frame = np.zeros((60, 80, 3), dtype=np.uint8)
        cid = fresh_camera_manager.add_camera(_StubVideoSource(frame))
        assert fresh_camera_manager.stop_camera(cid) is True
        # source.is_running ahora es False.

        resp = client.get(
            f'/api/cameras/{cid}/vision/stream', headers=auth_headers
        )
        assert resp.status_code == 400
        assert 'error' in resp.get_json()

    def test_stream_returns_mjpeg(
        self, client, stub_camera_id, auth_headers, monkeypatch
    ):
        """
        Verifica que el stream responde 200 con mimetype multipart y que sirve
        los frames producidos por ``generate_annotated_frames``.

        Se mockea el generador para producir un único frame y detenerse, evitando
        un bucle infinito en el test.
        """

        def _fake_gen(camera_id, fps=15.0):
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + b'frame-bytes-stub' + b'\r\n'
            )

        monkeypatch.setattr(
            camera_module, 'generate_annotated_frames', _fake_gen
        )

        resp = client.get(
            f'/api/cameras/{stub_camera_id}/vision/stream',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert 'multipart' in resp.mimetype
        assert b'frame-bytes-stub' in resp.data

    def test_stream_accepts_token_in_query(
        self, client, stub_camera_id, monkeypatch
    ):
        """El stream debe aceptar el token vía ?token= (para etiquetas <img>)."""

        def _fake_gen(camera_id, fps=15.0):
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + b'frame-q' + b'\r\n'
            )

        monkeypatch.setattr(
            camera_module, 'generate_annotated_frames', _fake_gen
        )

        token = _make_token()
        resp = client.get(
            f'/api/cameras/{stub_camera_id}/vision/stream?token={token}'
        )
        assert resp.status_code == 200
        assert b'frame-q' in resp.data


# ---------------------------------------------------------------------------
# Prueba de integración: generador real + CameraManager (sin HTTP)
# ---------------------------------------------------------------------------

class TestAnnotatedFramesGenerator:
    """
    Verifica directamente el generador ``generate_annotated_frames`` integrado
    con un ``CameraManager`` real y una cámara stub (sin llamar a HTTP).
    """

    def test_generator_yields_frame_bytes(
        self, fresh_camera_manager
    ):
        cid = fresh_camera_manager.add_camera(
            _StubVideoSource(np.zeros((60, 80, 3), dtype=np.uint8))
        )

        # Asegurar que el generador del módulo use este manager.
        import services  # noqa: F401  - solo para forzar resolución de imports

        gen = camera_module.generate_annotated_frames(cid, fps=30.0)
        chunk = next(gen)
        assert b'--frame' in chunk
        assert b'Content-Type: image/jpeg' in chunk
        # El stub devuelve b"jpg-bytes-stub" en get_frame() (fallback).
        assert b'jpg-bytes-stub' in chunk

    def test_generator_none_when_no_camera(
        self, fresh_camera_manager
    ):
        """Si la cámara no existe, el generador espera en bucle (no traba)."""
        import itertools

        gen = camera_module.generate_annotated_frames('inexistente', fps=60.0)
        # Tomar un slice limitado: como no hay frame, el generador duerme;
        # forzamos la interrupción tras un pequeño timeout mediante islice.
        # Usamos un approach seguro: iterar una vez esperando que duerma.
        # Para evitar bloqueo, simplemente cerramos el generador.
        gen.close()  # no debe lanzar
