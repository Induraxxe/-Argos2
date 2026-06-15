"""
Pruebas de entrada/salida para la arquitectura VisionEngine (Paso #4 + Workflow).

Valida el patrón Strategy + Factory implementado en
[`Backend/services/vision_engine.py`](../services/vision_engine.py).

Cobertura:
    - La fábrica devuelve el tipo de motor correcto según el modo.
    - La fábrica devuelve ``None`` para modos desactivados.
    - La fábrica rechaza modos inválidos.
    - ``process_frame()`` degrada *gracefully* cuando el motor no está
      disponible.
    - ``process_frame()`` del motor Cloud procesa un frame de prueba y
      devuelve un numpy array válido (solo si hay API key y conectividad;
      en caso contrario se omite con ``pytest.skip``).
    - Helpers de dibujo y normalización de predicciones (modo modelo estándar
      **y** modo workflow con ``run_workflow``).
    - Selección polimórfica del modo (workflow vs modelo estándar).
    - Decodificación de ``output_image`` del workflow (server overlay).

Cómo ejecutar::

    # Desde el directorio Backend/
    python -m pytest tests/test_vision_engine.py -v

    # O desde la raíz del proyecto
    python -m pytest Backend/tests/test_vision_engine.py -v

Requisitos: ``pip install pytest numpy`` (y ``inference-sdk`` para probar la
inicialización real del modo cloud).
"""

import base64
import os
from typing import Optional
from unittest.mock import MagicMock

import numpy as np
import pytest

from services.vision_engine import (
    CloudVisionEngine,
    LocalVisionEngine,
    VisionEngine,
    VisionEngineFactory,
    draw_predictions,
    extract_workflow_output_image,
    normalize_predictions,
)
from services.camera_service import CameraManager, VideoSource

# cv2 es dependencia del proyecto; se protege el import para los tests que
# codifican/decodifican imágenes (server overlay).
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover
    CV2_AVAILABLE = False


# ----------------------------------------------------------------------------- 
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_frame() -> np.ndarray:
    """Frame de prueba BGR 640x480 (patrón de gradiente sobre fondo negro)."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # Patrón de gradiente simple para que no sea un frame totalmente vacío.
    frame[:, :, 1] = np.linspace(0, 255, 640, dtype=np.uint8)  # canal verde
    return frame


@pytest.fixture
def sample_predictions() -> list:
    """Predicciones de ejemplo en formato Roboflow (centro + tamaño)."""
    return [
        {"x": 200.0, "y": 200.0, "width": 100.0, "height": 150.0,
         "confidence": 0.92, "class": "person"},
        {"x": 450.0, "y": 300.0, "width": 80.0, "height": 80.0,
         "confidence": 0.77, "class": "car"},
    ]


@pytest.fixture
def sample_workflow_output() -> list:
    """Salida típica de ``run_workflow()`` (lista con un output)."""
    return [
        {
            "tracked_predictions": [
                {"x": 100, "y": 100, "width": 50, "height": 50,
                 "class": "person", "confidence": 0.9},
                {"x": 300, "y": 220, "width": 60, "height": 120,
                 "class": "person", "confidence": 0.81},
            ],
            "counts_by_label": {"person": 2},
            "total_count": 2,
            "vision_events_status": "ok",
        }
    ]


def _encode_frame_b64(frame: np.ndarray) -> str:
    """Codifica un frame a JPEG base64 (mismo formato que ``output_image``)."""
    assert CV2_AVAILABLE, "cv2 es necesario para codificar frames en tests"
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return base64.b64encode(buf.tobytes()).decode("ascii")


@pytest.fixture
def mock_inference_sdk(monkeypatch):
    """
    Inyecta un mock de ``inference_sdk`` para poder inicializar el motor cloud
    sin tener el paquete real instalado ni realizar llamadas de red.
    """
    import sys
    import types

    class _FakeClient:
        def __init__(self, api_url=None, api_key=None, **kwargs):
            self.api_url = api_url
            self.api_key = api_key

    module = types.ModuleType("inference_sdk")
    module.InferenceHTTPClient = _FakeClient
    monkeypatch.setitem(sys.modules, "inference_sdk", module)
    return module


def _clear_roboflow_env(monkeypatch):
    """Limpia todas las variables de entorno de Roboflow para aislar el test."""
    for var in (
        "ROBOFLOW_API_KEY",
        "ROBOFLOW_WORKSPACE",
        "ROBOFLOW_WORKFLOW_ID",
        "ROBOFLOW_MODEL_ID",
    ):
        monkeypatch.delenv(var, raising=False)


# -----------------------------------------------------------------------------
# Pruebas de la Fábrica (tipos de motor por modo)
# -----------------------------------------------------------------------------

class TestVisionEngineFactory:
    """Verifica que VisionEngineFactory.create() devuelve el motor correcto."""

    def test_create_cloud_returns_cloud_engine(self):
        engine = VisionEngineFactory.create("cloud", auto_initialize=False)
        assert isinstance(engine, CloudVisionEngine)

    def test_create_cloud_is_vision_engine(self):
        engine = VisionEngineFactory.create("cloud", auto_initialize=False)
        assert isinstance(engine, VisionEngine)

    def test_create_local_returns_local_engine(self):
        engine = VisionEngineFactory.create("local", auto_initialize=False)
        assert isinstance(engine, LocalVisionEngine)

    def test_create_local_is_vision_engine(self):
        engine = VisionEngineFactory.create("local", auto_initialize=False)
        assert isinstance(engine, VisionEngine)

    def test_create_off_returns_none(self):
        assert VisionEngineFactory.create("off") is None

    def test_create_none_returns_none(self):
        assert VisionEngineFactory.create(None) is None

    def test_create_none_string_returns_none(self):
        assert VisionEngineFactory.create("none") is None

    def test_create_empty_string_returns_none(self):
        assert VisionEngineFactory.create("") is None

    def test_create_is_case_insensitive(self):
        engine = VisionEngineFactory.create("CLOUD", auto_initialize=False)
        assert isinstance(engine, CloudVisionEngine)

    def test_create_invalid_mode_raises_value_error(self):
        with pytest.raises(ValueError):
            VisionEngineFactory.create("satelite")

    def test_get_available_modes_always_includes_cloud_and_off(self):
        modes = VisionEngineFactory.get_available_modes()
        assert "cloud" in modes
        assert "off" in modes


# -----------------------------------------------------------------------------
# Pruebas de degradación graceful (sin dependencias/credenciales)
# -----------------------------------------------------------------------------

class TestGracefulDegradation:
    """Verifica que los motores no disponibles devuelven el frame sin anotar."""

    def test_cloud_unavailable_returns_original_frame(self, sample_frame):
        """Sin API key, el motor cloud no está disponible y devuelve el frame tal cual."""
        engine = CloudVisionEngine(api_key=None, model_id=None)
        engine.initialize()
        assert engine.is_available is False

        result = engine.process_frame(sample_frame)
        assert isinstance(result, np.ndarray)
        assert result.shape == sample_frame.shape
        # El frame no debe estar anotado (es idéntico al original).
        np.testing.assert_array_equal(result, sample_frame)

    def test_local_unavailable_returns_original_frame(self, sample_frame):
        """Sin paquete/carga de modelo, el motor local devuelve el frame tal cual."""
        engine = LocalVisionEngine(api_key=None, model_id=None)
        engine.initialize()
        # No garantizamos is_available (depende de si `inference` está instalado),
        # pero process_frame nunca debe lanzar.
        result = engine.process_frame(sample_frame)
        assert isinstance(result, np.ndarray)
        assert result.shape == sample_frame.shape

    def test_process_frame_none_returns_none(self):
        """Si se pasa None, se devuelve None sin lanzar excepción."""
        engine = CloudVisionEngine(api_key=None, model_id=None)
        engine.initialize()
        assert engine.process_frame(None) is None

    def test_get_status_contract(self):
        engine = CloudVisionEngine(api_key=None, model_id=None)
        engine.initialize()
        status = engine.get_status()
        assert "mode" in status
        assert "available" in status
        assert status["mode"] == "cloud"


# -----------------------------------------------------------------------------
# Selección polimórfica del modo (workflow vs modelo estándar)
# -----------------------------------------------------------------------------

class TestCloudVisionEngineModeSelection:
    """Verifica que CloudVisionEngine resuelve el modo correcto en initialize()."""

    def test_engine_detects_workflow_mode(self, monkeypatch, mock_inference_sdk):
        _clear_roboflow_env(monkeypatch)
        monkeypatch.setenv("ROBOFLOW_API_KEY", "test-key")
        monkeypatch.setenv("ROBOFLOW_WORKSPACE", "oswaldos-workspace-0ikuh")
        monkeypatch.setenv("ROBOFLOW_WORKFLOW_ID", "custom-workflow-4")

        engine = CloudVisionEngine()
        engine.initialize()

        assert engine.is_available is True
        assert engine._use_workflow is True

    def test_engine_prioritizes_workflow_when_both_configured(
        self, monkeypatch, mock_inference_sdk
    ):
        _clear_roboflow_env(monkeypatch)
        monkeypatch.setenv("ROBOFLOW_API_KEY", "test-key")
        monkeypatch.setenv("ROBOFLOW_WORKSPACE", "ws")
        monkeypatch.setenv("ROBOFLOW_WORKFLOW_ID", "wf")
        monkeypatch.setenv("ROBOFLOW_MODEL_ID", "project/1")

        engine = CloudVisionEngine()
        engine.initialize()

        assert engine.is_available is True
        # El modo workflow tiene prioridad aunque haya model_id.
        assert engine._use_workflow is True

    def test_engine_uses_standard_when_only_model_id(
        self, monkeypatch, mock_inference_sdk
    ):
        _clear_roboflow_env(monkeypatch)
        monkeypatch.setenv("ROBOFLOW_API_KEY", "test-key")
        monkeypatch.setenv("ROBOFLOW_MODEL_ID", "project/1")

        engine = CloudVisionEngine()
        engine.initialize()

        assert engine.is_available is True
        assert engine._use_workflow is False

    def test_engine_unavailable_without_any_config(
        self, monkeypatch, mock_inference_sdk
    ):
        _clear_roboflow_env(monkeypatch)
        engine = CloudVisionEngine()
        engine.initialize()
        assert engine.is_available is False

    def test_engine_unavailable_without_api_key(
        self, monkeypatch, mock_inference_sdk
    ):
        _clear_roboflow_env(monkeypatch)
        monkeypatch.setenv("ROBOFLOW_WORKSPACE", "ws")
        monkeypatch.setenv("ROBOFLOW_WORKFLOW_ID", "wf")

        engine = CloudVisionEngine()
        engine.initialize()
        assert engine.is_available is False

    def test_engine_unavailable_without_workspace(
        self, monkeypatch, mock_inference_sdk
    ):
        _clear_roboflow_env(monkeypatch)
        monkeypatch.setenv("ROBOFLOW_API_KEY", "test-key")
        monkeypatch.setenv("ROBOFLOW_WORKFLOW_ID", "wf")

        engine = CloudVisionEngine()
        engine.initialize()
        assert engine.is_available is False


# -----------------------------------------------------------------------------
# Procesamiento polimórfico (cliente mockeado, sin red)
# -----------------------------------------------------------------------------

class TestCloudWorkflowProcessing:
    """Verifica process_frame() en ambos modos usando un cliente mock."""

    def _make_workflow_engine(self, **overrides) -> CloudVisionEngine:
        """Crea un engine en modo workflow con cliente mock ya conectado."""
        engine = CloudVisionEngine(
            api_key="test-key",
            workspace="ws",
            workflow_id="wf",
            **overrides,
        )
        engine._client = MagicMock()
        engine._available = True
        engine._use_workflow = True
        return engine

    def _make_standard_engine(self) -> CloudVisionEngine:
        """Crea un engine en modo modelo estándar con cliente mock conectado."""
        engine = CloudVisionEngine(api_key="test-key", model_id="project/1")
        engine._client = MagicMock()
        engine._available = True
        engine._use_workflow = False
        return engine

    def test_process_frame_workflow_draws_locally(
        self, sample_frame, sample_workflow_output
    ):
        engine = self._make_workflow_engine(use_server_overlay=False)
        engine._client.run_workflow.return_value = sample_workflow_output

        result = engine.process_frame(sample_frame)

        assert isinstance(result, np.ndarray)
        assert result.shape == sample_frame.shape
        # Se dibujaron cajas -> el frame difiere del original.
        assert not np.array_equal(result, sample_frame)
        engine._client.run_workflow.assert_called_once()

    def test_process_frame_workflow_graceful_on_error(self, sample_frame):
        engine = self._make_workflow_engine()
        engine._client.run_workflow.side_effect = RuntimeError("API down")

        result = engine.process_frame(sample_frame)

        # Degradación graceful: devuelve el frame original sin anotar.
        np.testing.assert_array_equal(result, sample_frame)

    def test_process_frame_workflow_uses_server_overlay(
        self, sample_frame
    ):
        if not CV2_AVAILABLE:
            pytest.skip("cv2 no disponible: test de server overlay omitido.")

        b64 = _encode_frame_b64(sample_frame)
        engine = self._make_workflow_engine(use_server_overlay=True)
        engine._client.run_workflow.return_value = [
            {"output_image": {"value": b64, "type": "base64"}}
        ]

        result = engine.process_frame(sample_frame)

        # Se devuelve la imagen decodificada del workflow (no el dibujo local).
        assert isinstance(result, np.ndarray)
        assert result.ndim == 3
        assert result.shape[2] == 3
        engine._client.run_workflow.assert_called_once()

    def test_process_frame_workflow_server_overlay_fallback_when_no_image(
        self, sample_frame, sample_workflow_output
    ):
        """Si use_server_overlay=True pero no hay output_image, dibuja local."""
        engine = self._make_workflow_engine(use_server_overlay=True)
        engine._client.run_workflow.return_value = sample_workflow_output

        result = engine.process_frame(sample_frame)

        assert isinstance(result, np.ndarray)
        assert result.shape == sample_frame.shape
        assert not np.array_equal(result, sample_frame)

    def test_process_frame_standard_model_mode(self, sample_frame):
        engine = self._make_standard_engine()
        engine._client.infer.return_value = {
            "predictions": [
                {"x": 100, "y": 100, "width": 50, "height": 50,
                 "class": "car", "confidence": 0.8},
            ]
        }

        result = engine.process_frame(sample_frame)

        assert isinstance(result, np.ndarray)
        assert not np.array_equal(result, sample_frame)
        engine._client.infer.assert_called_once()
        # En modo modelo estándar no se llama a run_workflow.
        engine._client.run_workflow.assert_not_called()

    def test_process_frame_standard_model_graceful_on_error(self, sample_frame):
        engine = self._make_standard_engine()
        engine._client.infer.side_effect = RuntimeError("API down")

        result = engine.process_frame(sample_frame)
        np.testing.assert_array_equal(result, sample_frame)

    def test_process_frame_workflow_passes_expected_kwargs(
        self, sample_frame, sample_workflow_output
    ):
        """Verifica que run_workflow recibe workspace, workflow_id, images, cache."""
        engine = self._make_workflow_engine()
        engine._client.run_workflow.return_value = sample_workflow_output

        engine.process_frame(sample_frame)

        kwargs = engine._client.run_workflow.call_args.kwargs
        assert kwargs["workspace_name"] == "ws"
        assert kwargs["workflow_id"] == "wf"
        assert kwargs["use_cache"] is True
        assert isinstance(kwargs["images"], dict)
        assert "image" in kwargs["images"]


# -----------------------------------------------------------------------------
# Prueba de integración con la nube (requiere API key + conectividad)
# -----------------------------------------------------------------------------

class TestCloudInferenceIntegration:
    """
    Prueba end-to-end del motor Cloud con un frame real.

    Se omite (``pytest.skip``) si no hay ``ROBOFLOW_API_KEY`` configurada o si
    no hay ``inference_sdk`` instalado / conectividad.
    """

    def test_cloud_process_frame_returns_ndarray(self, sample_frame):
        api_key = os.environ.get("ROBOFLOW_API_KEY")
        if not api_key:
            pytest.skip(
                "ROBOFLOW_API_KEY no configurada: prueba de inferencia cloud omitida."
            )

        # Se necesita workflow_id+workspace (modo workflow) o model_id (modelo
        # estándar) para inicializar; si no hay ninguno, omitir.
        workspace = os.environ.get("ROBOFLOW_WORKSPACE")
        workflow_id = os.environ.get("ROBOFLOW_WORKFLOW_ID")
        model_id = os.environ.get("ROBOFLOW_MODEL_ID")
        if not (workflow_id and workspace) and not model_id:
            pytest.skip(
                "No hay WORKFLOW_ID/WORKSPACE ni MODEL_ID: prueba cloud omitida."
            )

        engine = CloudVisionEngine()
        engine.initialize()

        if not engine.is_available:
            pytest.skip(
                "CloudVisionEngine no disponible (¿inference_sdk ausente?): prueba omitida."
            )

        result = None
        try:
            result = engine.process_frame(sample_frame)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"La inferencia cloud falló (¿sin conectividad?): {exc}")

        # Contrato: siempre devuelve un numpy array del mismo shape.
        assert isinstance(result, np.ndarray)
        assert result.shape == sample_frame.shape
        assert result.dtype == sample_frame.dtype


# -----------------------------------------------------------------------------
# Pruebas de los helpers de dibujo y normalización
# -----------------------------------------------------------------------------

class TestHelpers:
    """Pruebas unitarias de draw_predictions, normalize_predictions y extract."""

    def test_draw_predictions_returns_same_shape(self, sample_frame, sample_predictions):
        annotated = draw_predictions(sample_frame, sample_predictions)
        assert isinstance(annotated, np.ndarray)
        assert annotated.shape == sample_frame.shape
        # El frame anotado debe diferir del original (se dibujaron cajas).
        assert not np.array_equal(annotated, sample_frame)

    def test_draw_predictions_empty_list_returns_copy(self, sample_frame):
        annotated = draw_predictions(sample_frame, [])
        assert isinstance(annotated, np.ndarray)
        assert annotated.shape == sample_frame.shape
        # Sin predicciones, el contenido es igual pero es una copia (no el mismo obj).
        np.testing.assert_array_equal(annotated, sample_frame)
        assert annotated is not sample_frame

    def test_draw_predictions_none_frame(self):
        assert draw_predictions(None, []) is None

    def test_normalize_predictions_cloud_dict(self, sample_predictions):
        result = {"predictions": sample_predictions}
        normalized = normalize_predictions(result)
        assert len(normalized) == 2
        assert normalized[0]["class"] == "person"
        assert normalized[0]["confidence"] == 0.92

    def test_normalize_predictions_list(self, sample_predictions):
        # Formato local: lista de respuestas con .predictions
        normalized = normalize_predictions([{"predictions": sample_predictions}])
        assert len(normalized) == 2

    def test_normalize_predictions_empty(self):
        assert normalize_predictions(None) == []
        assert normalize_predictions([]) == []
        assert normalize_predictions({}) == []

    # --- Modo workflow ---

    def test_normalize_predictions_workflow_tracked(self, sample_workflow_output):
        normalized = normalize_predictions(sample_workflow_output, workflow=True)
        assert len(normalized) == 2
        assert normalized[0]["class"] == "person"
        assert normalized[0]["confidence"] == 0.9

    def test_normalize_predictions_workflow_fallback_predictions(self):
        # Sin tracked_predictions, debe caer en 'predictions' del output.
        result = [{"predictions": [{"x": 1, "y": 1, "width": 1, "height": 1,
                                    "class": "dog"}]}]
        normalized = normalize_predictions(result, workflow=True)
        assert len(normalized) == 1
        assert normalized[0]["class"] == "dog"

    def test_normalize_predictions_workflow_empty(self):
        assert normalize_predictions([], workflow=True) == []
        assert normalize_predictions([{}], workflow=True) == []
        assert normalize_predictions(None, workflow=True) == []

    def test_normalize_predictions_workflow_dict_not_list(self):
        # Algunas versiones del SDK pueden devolver un dict envuelto.
        result = {"tracked_predictions": [{"x": 1, "y": 1, "width": 1,
                                           "height": 1, "class": "cat"}]}
        normalized = normalize_predictions(result, workflow=True)
        assert len(normalized) == 1
        assert normalized[0]["class"] == "cat"

    def test_extract_workflow_output_image_base64(self, sample_frame):
        if not CV2_AVAILABLE:
            pytest.skip("cv2 no disponible: test de output_image omitido.")
        b64 = _encode_frame_b64(sample_frame)
        result = [{"output_image": {"value": b64, "type": "base64"}}]
        img = extract_workflow_output_image(result)
        assert img is not None
        assert isinstance(img, np.ndarray)
        assert img.ndim == 3

    def test_extract_workflow_output_image_string_base64(self, sample_frame):
        if not CV2_AVAILABLE:
            pytest.skip("cv2 no disponible: test de output_image omitido.")
        b64 = _encode_frame_b64(sample_frame)
        result = [{"output_image": b64}]
        img = extract_workflow_output_image(result)
        assert img is not None
        assert isinstance(img, np.ndarray)

    def test_extract_workflow_output_image_none_when_missing(self):
        assert extract_workflow_output_image([{}]) is None
        assert extract_workflow_output_image([]) is None
        assert extract_workflow_output_image(None) is None

    def test_extract_workflow_output_image_invalid_b64(self):
        result = [{"output_image": {"value": "no-es-base64-valido!!!"}}]
        assert extract_workflow_output_image(result) is None


# -----------------------------------------------------------------------------
# Pruebas de integración con CameraManager (Zona C del plan)
# -----------------------------------------------------------------------------

class _StubVideoSource(VideoSource):
    """VideoSource minimalista para tests (no requiere hardware/cámara real)."""

    def __init__(self, frame: Optional[np.ndarray] = None):
        import collections
        import threading
        self._frame_deque = collections.deque(maxlen=2)
        if frame is not None:
            self._frame_deque.append(frame)
        self._lock = threading.Lock()

    def start(self) -> bool:
        return True

    def get_frame(self) -> Optional[bytes]:
        return b"jpg-bytes-stub"

    def stop(self) -> None:
        pass

    @property
    def is_running(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "stub"

    @property
    def source_type(self) -> str:
        return "usb"


@pytest.fixture
def isolated_camera_manager():
    """Devuelve un CameraManager con estado limpio (resetea el singleton)."""
    CameraManager.reset_instance()
    yield CameraManager()
    CameraManager.reset_instance()


class TestCameraManagerVisionIntegration:
    """Verifica la integración aditiva de visión en CameraManager."""

    def test_enable_vision_cloud_registers_engine(
        self, isolated_camera_manager, sample_frame
    ):
        cm = isolated_camera_manager
        cid = cm.add_camera(_StubVideoSource(sample_frame))

        ok = cm.enable_vision(cid, "cloud")
        assert ok is True

        status = cm.get_vision_status(cid)
        assert status["active"] is True
        assert status["mode"] == "cloud"

    def test_enable_vision_off_is_inactive(
        self, isolated_camera_manager, sample_frame
    ):
        cm = isolated_camera_manager
        cid = cm.add_camera(_StubVideoSource(sample_frame))

        ok = cm.enable_vision(cid, "off")
        assert ok is True
        assert cm.get_vision_status(cid)["active"] is False

    def test_disable_vision_clears_engine(
        self, isolated_camera_manager, sample_frame
    ):
        cm = isolated_camera_manager
        cid = cm.add_camera(_StubVideoSource(sample_frame))

        cm.enable_vision(cid, "cloud")
        assert cm.get_vision_status(cid)["active"] is True

        cm.disable_vision(cid)
        assert cm.get_vision_status(cid)["active"] is False

    def test_get_annotated_frame_fallback_to_raw(
        self, isolated_camera_manager, sample_frame
    ):
        """Sin motor disponible, get_annotated_frame devuelve el frame crudo."""
        cm = isolated_camera_manager
        cid = cm.add_camera(_StubVideoSource(sample_frame))

        frame = cm.get_annotated_frame(cid)
        # Como el motor cloud no tiene API key -> no disponible -> fallback a get_frame().
        assert frame == b"jpg-bytes-stub"

    def test_enable_vision_unknown_camera_returns_false(
        self, isolated_camera_manager
    ):
        cm = isolated_camera_manager
        assert cm.enable_vision("no-existe", "cloud") is False

    def test_shutdown_all_stops_vision_engines(
        self, isolated_camera_manager, sample_frame
    ):
        cm = isolated_camera_manager
        cid = cm.add_camera(_StubVideoSource(sample_frame))
        cm.enable_vision(cid, "cloud")
        assert cm.get_vision_status(cid)["active"] is True

        cm.shutdown_all()
        # Tras el shutdown, la cámara y el motor ya no están.
        assert cm.get_camera(cid) is None
