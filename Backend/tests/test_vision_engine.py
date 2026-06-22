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
      devuelve un numpy array válido. La llamada al SDK se intercepta con
      ``unittest.mock`` (no requiere ``ROBOFLOW_API_KEY`` real ni
      conectividad de red).
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
import logging
import os
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from services.vision_engine import (
    CloudVisionEngine,
    LocalVisionEngine,
    VisionEngine,
    VisionEngineFactory,
    _extract_workflow_predictions,
    _normalize_confidence,
    _prediction_to_dict,
    _safe_normalize_list,
    _unwrap_predictions,
    draw_predictions,
    extract_workflow_output_image,
    normalize_predictions,
)
import services.vision_engine as vision_engine  # reset del throttle de alertas en tests
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
            "predictions": [
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

    def test_process_frame_workflow_count_ignores_json_total_count(
        self, sample_frame
    ):
        """Regresión (badge "congelado" con datos basura): el conteo se basa
        EXCLUSIVAMENTE en ``len(predictions)`` y NO en los metadatos
        ``total_count`` / ``counts_by_label`` del JSON del workflow, que el
        mecanismo de Tracking interno de Roboflow corrompe manteniendo
        detecciones fantasma (el badge nunca bajaba a 0).

        Aquí el workflow envía ``total_count=0`` y ``counts_by_label={}``
        (valores corruptos) pero 2 ``predictions`` reales: el conteo
        debe basarse en la detección instantánea (2) e ignorar por completo los
        metadatos del JSON.
        """
        engine = self._make_workflow_engine(use_server_overlay=False)
        engine._client.run_workflow.return_value = [
            {
                # predictions reales del frame actual -> base del conteo.
                "predictions": [
                    {"x": 100, "y": 100, "width": 50, "height": 50,
                     "class": "person", "confidence": 0.9},
                    {"x": 300, "y": 220, "width": 60, "height": 120,
                     "class": "person", "confidence": 0.81},
                ],
                # Metadatos corruptos del JSON que DEBEN ignorarse por completo:
                "counts_by_label": {},
                "total_count": 0,
                "vision_events_status": "ok",
            }
        ]

        engine.process_frame(sample_frame)

        det = engine.get_detections()
        # El conteo se basa en len(predictions) == 2, ignorando el
        # total_count=0 / counts_by_label={} corruptos del JSON.
        assert det["count"] == 2
        assert det["labels"] == {"person": 2}
        assert det["timestamp"] is not None

    def test_process_frame_workflow_empty_predictions_count_zero(
        self, sample_frame
    ):
        """Atomicidad: cuando ``predictions`` es una lista vacía, el
        conteo es ``0`` de forma inmediata (sin mantener el conteo anterior ni
        aplicar ``max()``). Aunque el JSON traiga metadatos basura, estos se
        ignoran."""
        engine = self._make_workflow_engine(use_server_overlay=False)
        engine._client.run_workflow.return_value = [
            {
                "predictions": [],
                # Metadatos basura que DEBEN ignorarse:
                "counts_by_label": {"ghost": 99},
                "total_count": 99,
            }
        ]

        engine.process_frame(sample_frame)

        det = engine.get_detections()
        assert det["count"] == 0
        assert det["labels"] == {}
        assert det["timestamp"] is not None

    def test_process_frame_workflow_count_from_predictions_when_counts_missing(
        self, sample_frame
    ):
        """Regresión: si el workflow NO incluye ``counts_by_label`` ni
        ``total_count`` (pero sí ``predictions``), el conteo se
        reconstruye a partir de las predicciones."""
        engine = self._make_workflow_engine(use_server_overlay=False)
        engine._client.run_workflow.return_value = [
            {
                "predictions": [
                    {"x": 100, "y": 100, "width": 50, "height": 50,
                     "class": "car", "confidence": 0.9},
                ],
            }
        ]

        engine.process_frame(sample_frame)

        det = engine.get_detections()
        assert det["count"] == 1
        assert det["labels"] == {"car": 1}

    def test_process_frame_workflow_count_matches_tracked_predictions(
        self, sample_frame, sample_workflow_output
    ):
        """Happy path: el conteo se deriva de ``len(predictions)`` y
        ``counts_by_label`` se recalcula localmente (coincide con los metadatos
        del JSON solo porque este fixture es consistente)."""
        engine = self._make_workflow_engine(use_server_overlay=False)
        engine._client.run_workflow.return_value = sample_workflow_output

        engine.process_frame(sample_frame)

        det = engine.get_detections()
        # 2 predictions -> conteo 2 (calculado en código, no del JSON).
        assert det["count"] == 2
        assert det["labels"] == {"person": 2}

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
        # El frame debe llegar como string base64 (no como numpy array):
        # inference_sdk 1.3.1 no serializa numpy arrays en run_workflow().
        assert isinstance(kwargs["images"]["image"], str)
        assert not isinstance(kwargs["images"]["image"], np.ndarray)


# -----------------------------------------------------------------------------
# Prueba del motor Cloud con el SDK mockeado (sin API key real ni red)
# -----------------------------------------------------------------------------
#
# Estrategia de mocking elegida: **método del cliente del SDK** (no ``requests``).
# Se crea el motor normalmente y se llama a ``initialize()`` (lo que construye un
# ``InferenceHTTPClient`` REAL), y a continuación se reemplaza el método del
# cliente que dispara la inferencia (``run_workflow`` / ``infer``) por un
# ``MagicMock`` que devuelve un payload JSON simulado. Así:
#   - ``initialize()`` corre de verdad (crea el cliente, valida config/modo).
#   - La inferencia NO toca la red: el código del SDK que haría la petición HTTP
#     nunca se ejecuta porque el método está sustituido por un Mock.
#   - No se necesita ``ROBOFLOW_API_KEY`` real: se pasa una clave ficticia al
#     constructor (el constructor solo la guarda; no la valida contra el servidor).
# Como doble seguridad, además se espira ``requests.sessions.Session.request`` y
# se afirma que nunca se invoca durante ``process_frame``.

class TestCloudInferenceIntegration:
    """
    Prueba del motor Cloud con la llamada al SDK interceptada por mocking.

    Estos tests **NO** requieren ``ROBOFLOW_API_KEY`` real ni conectividad de
    red: el método del cliente del SDK (``run_workflow`` / ``infer``) se
    reemplaza por un ``MagicMock`` que devuelve un payload JSON simulado,
    permitiendo verificar la lógica de validación, filtrado por confianza y
    normalización de forma determinista y aislada del estado de la red.

    Cobertura:
        - Modo **workflow** (rama default/prioritaria) vía ``client.run_workflow``.
        - Modo **modelo estándar** vía ``client.infer``.
        - Observabilidad: log DEBUG de confianzas entrantes
          (``_log_confianzas``) y alerta WARNING de confianzas sospechosas
          (``_alertar_confianzas_sospechosas``, umbral
          ``CONFIANZA_SOSPECHOSA_MIN = 0.40``). Ya NO hay filtrado local (el
          modelo pre-filtra a 0.40 en el servidor).
        - Normalización de las predicciones a dicts con las claves
          ``x, y, width, height, confidence, class``.
    """

    # Payload del WORKFLOW con 5 predicciones de confianza variada:
    #   - 0.95  -> normal (>= 0.40, presente).
    #   - 0.60  -> normal (>= 0.40, presente).
    #   - 0.42  -> normal (>= 0.40: NO debe alertar aunque esté cerca del piso;
    #              confirma que el umbral de alerta es 0.40, no 0.60).
    #   - None  -> SOSPECHOSA (ausente/None -> dispara WARNING de observabilidad).
    #   - 0.25  -> SOSPECHOSA (< 0.40, "sospechosamente baja" -> WARNING).
    # Sin filtrado local: las 5 pasan íntegras a conteo/dibujado. Las 2
    # sospechosas disparan UN WARNING (throttleado) sin descartarse.
    # Los metadatos ``counts_by_label``/``total_count`` se incluyen a propósito
    # para verificar que el conteo se basa EXCLUSIVAMENTE en las
    # ``predictions`` (no en el JSON del workflow).
    WORKFLOW_PAYLOAD = [
        {
            "predictions": [
                {"x": 100.0, "y": 100.0, "width": 50.0, "height": 50.0,
                 "class": "person", "confidence": 0.95},
                {"x": 200.0, "y": 200.0, "width": 60.0, "height": 60.0,
                 "class": "person", "confidence": 0.60},
                {"x": 300.0, "y": 300.0, "width": 40.0, "height": 40.0,
                 "class": "car", "confidence": 0.42},
                {"x": 400.0, "y": 400.0, "width": 30.0, "height": 30.0,
                 "class": "dog", "confidence": None},
                {"x": 500.0, "y": 500.0, "width": 25.0, "height": 25.0,
                 "class": "cat", "confidence": 0.25},
            ],
            # Metadatos del JSON (DEBEN ignorarse: el conteo se calcula en
            # código a partir de las predictions, sin filtrado).
            "counts_by_label": {"person": 2, "car": 1, "dog": 1, "cat": 1},
            "total_count": 5,
        }
    ]

    # Payload del MODELO ESTÁNDAR: mismo conjunto de confianzas, pero la cuarta
    # predicción NO lleva la clave ``confidence`` (caso "ausente" distinto del
    # ``None`` explícito del workflow, para cubrir ambas ramas defensivas del
    # helper de observabilidad ``_alertar_confianzas_sospechosas``). Se añade
    # una quinta predicción con 0.25 (< 0.40) para evidenciar la alerta de
    # "sospechosamente baja".
    STANDARD_PAYLOAD = {
        "predictions": [
            {"x": 100.0, "y": 100.0, "width": 50.0, "height": 50.0,
             "class": "person", "confidence": 0.95},
            {"x": 200.0, "y": 200.0, "width": 60.0, "height": 60.0,
             "class": "person", "confidence": 0.60},
            {"x": 300.0, "y": 300.0, "width": 40.0, "height": 40.0,
             "class": "car", "confidence": 0.42},
            {"x": 400.0, "y": 400.0, "width": 30.0, "height": 30.0,
             "class": "dog"},  # confidence AUSENTE -> sospechosa (WARNING)
            {"x": 500.0, "y": 500.0, "width": 25.0, "height": 25.0,
             "class": "cat", "confidence": 0.25},  # < 0.40 -> sospechosa
        ]
    }

    def test_cloud_process_frame_returns_ndarray(
        self, monkeypatch, sample_frame, caplog
    ):
        """Modo WORKFLOW (rama default/prioritaria).

        Se mockea ``client.run_workflow`` para devolver ``WORKFLOW_PAYLOAD`` y
        se verifica: invocación única, ausencia de peticiones HTTP reales,
        AUSENCIA de filtrado local (todas las predicciones se cuentan), log
        DEBUG de confianzas entrantes, alerta WARNING ante confianzas
        sospechosas, normalización y retorno de un ``np.ndarray``.

        NOTA: el modo workflow requiere ``cv2`` para codificar el frame a JPEG
        y escribirlo en un archivo temporal antes de invocar al SDK (ver
        ``process_frame``). Si ``cv2`` no estuviera disponible, este test se
        omite; las demás aserciones de lógica ya están cubiertas por el modo
        modelo estándar (ver
        ``test_cloud_process_frame_standard_mode_returns_ndarray``).
        """
        if not CV2_AVAILABLE:
            pytest.skip(
                "cv2 no disponible: el modo workflow requiere codificar el "
                "frame a JPEG antes de llamar a run_workflow."
            )

        # Reset del throttle de alertas para garantizar que el WARNING se emite
        # en esta llamada (la inferencia a FPS throttlea los WARNING por
        # cooldown). caplog a DEBUG para capturar también el log de confianzas.
        vision_engine._alerta_conf_last_ts.clear()
        caplog.set_level(logging.DEBUG, logger="services.vision_engine")

        # Aislar el test de credenciales reales del entorno (no las necesitamos).
        _clear_roboflow_env(monkeypatch)

        # Crear el motor en modo workflow con credenciales FICTICIAS.
        # ``initialize()`` crea un ``InferenceHTTPClient`` REAL, pero no lanza
        # ninguna petición de red hasta que se invoque un método del cliente.
        engine = CloudVisionEngine(
            api_key="test-key-ficticia",  # clave ficticia: no toca la red
            workspace="test-workspace",
            workflow_id="test-workflow",
        )
        engine.initialize()
        # Sanity: initialize() creó el cliente y resolvió modo workflow.
        assert engine.is_available is True, (
            "initialize() debió dejar el motor disponible con credenciales ficticias"
        )
        assert engine._use_workflow is True

        # INTERCEPCIÓN: reemplazar el método del cliente del SDK por un Mock.
        # Así ``initialize()`` ya corrió (cliente real creado) pero la
        # inferencia NO toca la red.
        engine._client.run_workflow = MagicMock(
            return_value=self.WORKFLOW_PAYLOAD
        )

        # Doble seguridad: espiar ``requests`` para garantizar que NO se hace
        # ninguna petición HTTP real aunque el mock del cliente fallara.
        with patch("requests.sessions.Session.request") as spy_request:
            result = engine.process_frame(sample_frame)
        spy_request.assert_not_called()

        # El método del cliente se invocó exactamente una vez.
        engine._client.run_workflow.assert_called_once()

        # ``process_frame`` devuelve un ``np.ndarray`` (no ``None``).
        assert isinstance(result, np.ndarray), (
            "process_frame debe devolver un np.ndarray"
        )
        assert result.shape == sample_frame.shape
        assert result.dtype == sample_frame.dtype

        # SIN filtrado local: TODAS las predicciones normalizadas se cuentan
        # (el modelo pre-filtra a 0.40 en el servidor; aquí no se descarta
        # nada). El payload trae 5 predictions.
        det = engine.get_detections()
        assert det["count"] == 5, (
            "Sin filtrado local, las 5 predicciones deben contarse"
        )
        labels = det["labels"]
        # 'car' (0.42 >= 0.40), 'dog' (None) y 'cat' (0.25) SÍ aparecen: ya no
        # se filtran por confianza.
        assert labels == {"person": 2, "car": 1, "dog": 1, "cat": 1}
        assert "car" in labels, (
            "La predicción 'car' (0.42) ya NO debe filtrarse (sin filtrado local)"
        )
        assert "dog" in labels, (
            "La predicción 'dog' (confidence=None) ya NO debe filtrarse"
        )
        assert "cat" in labels, (
            "La predicción 'cat' (0.25) ya NO debe filtrarse"
        )
        assert det["timestamp"] is not None

        # Observabilidad (caplog): log DEBUG de confianzas entrantes.
        assert any(
            r.levelno == logging.DEBUG
            and "_log_confianzas" in r.getMessage()
            for r in caplog.records
        ), "Debe registrarse el DEBUG de confianzas entrantes"
        # Observabilidad (caplog): WARNING ante confianzas sospechosas
        # (dog=None y cat=0.25). NOTA: car=0.42 NO es sospechosa (>= 0.40) y
        # por tanto no contribuye al WARNING.
        assert any(
            r.levelno == logging.WARNING
            and "_alertar_confianzas_sospechosas" in r.getMessage()
            for r in caplog.records
        ), (
            "Debe emitirse un WARNING ante confianzas sospechosas "
            "(ausente/None o < 0.40)"
        )

        # Verificar que la normalización produce dicts con TODAS las claves
        # esperadas (sobre el mismo payload que consume ``process_frame``).
        normalized = normalize_predictions(
            self.WORKFLOW_PAYLOAD, workflow=True
        )
        expected_keys = {"x", "y", "width", "height", "confidence", "class"}
        assert len(normalized) == 5
        assert all(set(p.keys()) == expected_keys for p in normalized), (
            "Cada predicción normalizada debe tener las claves "
            "x, y, width, height, confidence, class"
        )

    def test_cloud_process_frame_standard_mode_returns_ndarray(
        self, monkeypatch, sample_frame, caplog
    ):
        """Modo MODELO ESTÁNDAR (rama fallback).

        Se mockea ``client.infer`` para devolver ``STANDARD_PAYLOAD`` y se
        aplican las mismas aserciones de AUSENCIA de filtrado/normalización/
        conteo y de observabilidad (DEBUG + WARNING). Este modo NO codifica el
        frame a JPEG antes de inferir (pasa el array directo a ``infer``), por
        lo que es robusto a la presencia o no de ``cv2``; las aserciones se
        centran en la lógica de observabilidad/normalización/conteo.
        """
        # Reset del throttle de alertas + caplog a DEBUG.
        vision_engine._alerta_conf_last_ts.clear()
        caplog.set_level(logging.DEBUG, logger="services.vision_engine")

        # Aislar el test de credenciales reales del entorno.
        _clear_roboflow_env(monkeypatch)

        # Crear el motor en modo modelo estándar con credenciales FICTICIAS.
        engine = CloudVisionEngine(
            api_key="test-key-ficticia",  # clave ficticia: no toca la red
            model_id="test-project/1",
        )
        engine.initialize()
        assert engine.is_available is True
        assert engine._use_workflow is False

        # INTERCEPCIÓN de los métodos del cliente del SDK. Se mockea ``infer``
        # (que es el que se usa en modo modelo estándar) y también
        # ``run_workflow`` para poder espiar que NO fue invocado (verifica el
        # polimorfismo de selección de modo). Al ser ahora ambos Mocks, la
        # inferencia no toca la red.
        engine._client.infer = MagicMock(
            return_value=self.STANDARD_PAYLOAD
        )
        engine._client.run_workflow = MagicMock()

        # Doble seguridad: espiar ``requests`` para garantizar que NO se hace
        # ninguna petición HTTP real.
        with patch("requests.sessions.Session.request") as spy_request:
            result = engine.process_frame(sample_frame)
        spy_request.assert_not_called()

        # El método del cliente se invocó exactamente una vez; en modo modelo
        # estándar NO se llama a ``run_workflow``.
        engine._client.infer.assert_called_once()
        engine._client.run_workflow.assert_not_called()

        # ``process_frame`` devuelve un ``np.ndarray`` (no ``None``).
        assert isinstance(result, np.ndarray), (
            "process_frame debe devolver un np.ndarray"
        )
        assert result.shape == sample_frame.shape
        assert result.dtype == sample_frame.dtype

        # SIN filtrado local: TODAS las predicciones se cuentan (5).
        det = engine.get_detections()
        assert det["count"] == 5, (
            "Sin filtrado local, las 5 predicciones deben contarse"
        )
        labels = det["labels"]
        assert labels == {"person": 2, "car": 1, "dog": 1, "cat": 1}
        assert "car" in labels, (
            "La predicción 'car' (0.42) ya NO debe filtrarse"
        )
        assert "dog" in labels, (
            "La predicción 'dog' (confidence ausente) ya NO debe filtrarse"
        )
        assert "cat" in labels, (
            "La predicción 'cat' (0.25) ya NO debe filtrarse"
        )
        assert det["timestamp"] is not None

        # Observabilidad (caplog): DEBUG de confianzas entrantes.
        assert any(
            r.levelno == logging.DEBUG
            and "_log_confianzas" in r.getMessage()
            for r in caplog.records
        ), "Debe registrarse el DEBUG de confianzas entrantes"
        # Observabilidad (caplog): WARNING ante confianzas sospechosas
        # (dog: confidence ausente y cat=0.25).
        assert any(
            r.levelno == logging.WARNING
            and "_alertar_confianzas_sospechosas" in r.getMessage()
            for r in caplog.records
        ), (
            "Debe emitirse un WARNING ante confianzas sospechosas "
            "(ausente/None o < 0.40)"
        )

        # Verificar la normalización del payload del modelo estándar.
        normalized = normalize_predictions(
            self.STANDARD_PAYLOAD, workflow=False
        )
        expected_keys = {"x", "y", "width", "height", "confidence", "class"}
        assert len(normalized) == 5
        assert all(set(p.keys()) == expected_keys for p in normalized), (
            "Cada predicción normalizada debe tener las claves "
            "x, y, width, height, confidence, class"
        )

    def test_cloud_no_warning_on_healthy_confidences(
        self, monkeypatch, sample_frame, caplog
    ):
        """Payload "sano" (todas las confianzas >= 0.40 y presentes): NO debe
        emitirse ningún WARNING de confianzas sospechosas, pero SÍ debe
        registrarse el DEBUG de confianzas entrantes. Cubre la rama negativa
        de ``_alertar_confianzas_sospechosas`` (detección de ausencia de
        anomalías).
        """
        # Reset del throttle + limpiar registros para aislar la aserción.
        vision_engine._alerta_conf_last_ts.clear()
        caplog.set_level(logging.DEBUG, logger="services.vision_engine")

        _clear_roboflow_env(monkeypatch)
        engine = CloudVisionEngine(
            api_key="test-key-ficticia",  # clave ficticia: no toca la red
            model_id="test-project/2",
        )
        engine.initialize()

        # Payload sano: confianzas 0.95, 0.60 y 0.42 (todas >= 0.40 y presentes).
        engine._client.infer = MagicMock(
            return_value={
                "predictions": [
                    {"x": 10.0, "y": 10.0, "width": 50.0, "height": 50.0,
                     "class": "person", "confidence": 0.95},
                    {"x": 20.0, "y": 20.0, "width": 60.0, "height": 60.0,
                     "class": "person", "confidence": 0.60},
                    {"x": 30.0, "y": 30.0, "width": 40.0, "height": 40.0,
                     "class": "car", "confidence": 0.42},
                ]
            }
        )

        engine.process_frame(sample_frame)

        # Sin sospechosas -> NO hay WARNING de confianzas.
        assert not any(
            r.levelno == logging.WARNING
            and "_alertar_confianzas_sospechosas" in r.getMessage()
            for r in caplog.records
        ), "Un payload sano (>= 0.40 y presente) no debe generar WARNING"
        # El DEBUG de confianzas entrantes sí se registra siempre.
        assert any(
            r.levelno == logging.DEBUG
            and "_log_confianzas" in r.getMessage()
            for r in caplog.records
        ), "Debe registrarse el DEBUG de confianzas entrantes"


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
        result = {"predictions": [{"x": 1, "y": 1, "width": 1,
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

    # --- Normalización defensiva de ``confidence`` (None/ausente -> 0.0) ----

    def test_normalize_confidence_none_becomes_zero(self):
        """``_normalize_confidence`` convierte ``None``/ausente/no numérico a
        ``0.0`` y NUNCA lanza, para que el filtrado numérico no se rompa."""
        assert _normalize_confidence(None) == 0.0
        assert _normalize_confidence(0.92) == 0.92
        assert _normalize_confidence("0.75") == 0.75
        assert _normalize_confidence("no-numero") == 0.0
        assert _normalize_confidence([1, 2]) == 0.0  # no convertible
        assert isinstance(_normalize_confidence(None), float)

    def test_prediction_to_dict_confidence_none_becomes_zero(self):
        """Regresión: una predicción con ``confidence=None`` debe normalizar el
        campo a ``0.0`` (no propagar ``None``). Cubre también el caso de clave
        ausente (distinto de ``None`` explícito)."""
        pred = _prediction_to_dict(
            {"x": 1, "y": 2, "width": 10, "height": 20,
             "class": "dog", "confidence": None}
        )
        assert pred["confidence"] == 0.0
        assert pred["class"] == "dog"
        # Clave ausente -> también 0.0.
        pred2 = _prediction_to_dict(
            {"x": 1, "y": 2, "width": 10, "height": 20, "class": "cat"}
        )
        assert pred2["confidence"] == 0.0

    def test_normalize_predictions_workflow_none_confidence_becomes_zero(self):
        """Integración: el workflow de Roboflow puede entregar
        ``predictions`` con ``confidence=None`` (típico del tracking).
        La normalización debe entregar ``0.0`` en su lugar para que el
        conteo/dibujado no fallen con un ``None``."""
        result = [
            {
                "predictions": [
                    {"x": 1, "y": 1, "width": 10, "height": 10,
                     "class": "dog", "confidence": None},
                    {"x": 2, "y": 2, "width": 20, "height": 20,
                     "class": "car", "confidence": 0.8},
                    {"x": 3, "y": 3, "width": 30, "height": 30,
                     "class": "cat"},  # sin clave confidence
                ]
            }
        ]
        normalized = normalize_predictions(result, workflow=True)
        assert len(normalized) == 3
        assert normalized[0]["confidence"] == 0.0  # None -> 0.0
        assert normalized[1]["confidence"] == 0.8
        assert normalized[2]["confidence"] == 0.0  # ausente -> 0.0
        # El tipo debe ser ``float`` (no ``None``) para el filtrado numérico.
        assert isinstance(normalized[0]["confidence"], float)

    # --- Tolerancia a fallos: predictions vacío/malformado -> [] ----

    def test_normalize_predictions_workflow_malformed_never_raises(self):
        """Regresión: ``predictions`` vacío, ``None`` o un tipo
        inesperado (``int``/``str``) NUNCA lanza; devuelve ``[]``.

        Además valida el fallback de retrocompatibilidad: un payload con SOLO
        ``tracked_predictions`` (clave legada, sin ``predictions``) aún extrae
        datos vía el mecanismo de fallback del extractor del workflow."""
        # Lista vacía.
        assert normalize_predictions(
            [{"predictions": []}], workflow=True
        ) == []
        # None explícito.
        assert normalize_predictions(
            [{"predictions": None}], workflow=True
        ) == []
        # Escalar donde iría la lista (salida corrupta del workflow).
        assert normalize_predictions(
            [{"predictions": 42}], workflow=True
        ) == []
        assert normalize_predictions(
            [{"predictions": "corrupto"}], workflow=True
        ) == []
        # Retrocompatibilidad: si solo existe ``tracked_predictions`` (clave
        # legada) y ``predictions`` no está, se extrae vía fallback.
        assert len(normalize_predictions(
            [{"tracked_predictions": [{"x": 1, "y": 1, "width": 1,
                                       "height": 1, "class": "dog"}]}],
            workflow=True,
        )) == 1

    def test_normalize_predictions_workflow_skips_corrupt_elements(self):
        """Un elemento corrupto (``None`` o escalar) dentro de
        ``predictions`` no tira la extracción: se omite y se devuelven
        los válidos (sin inflar el conteo con detecciones fantasma)."""
        result = [
            {
                "predictions": [
                    {"x": 1, "y": 1, "width": 10, "height": 10,
                     "class": "dog", "confidence": 0.9},
                    None,  # elemento corrupto -> se omite
                    123,   # elemento corrupto (escalar) -> se omite
                    {"x": 3, "y": 3, "width": 30, "height": 30,
                     "class": "cat", "confidence": 0.5},
                ]
            }
        ]
        normalized = normalize_predictions(result, workflow=True)
        # Quedan los 2 dicts válidos (None y 123 se descartan).
        assert len(normalized) == 2
        assert sorted(p["class"] for p in normalized) == ["cat", "dog"]

    def test_safe_normalize_list_empty_and_none(self):
        """``_safe_normalize_list`` con ``None``/vacío/``{}`` -> ``[]``."""
        assert _safe_normalize_list(None) == []
        assert _safe_normalize_list([]) == []
        assert _safe_normalize_list({}) == []
        assert _safe_normalize_list(0) == []


# -----------------------------------------------------------------------------
# Regresión: wrapper { "predictions": [...] } NO debe contar como detección
# -----------------------------------------------------------------------------
#
# Bug original: ``_extract_workflow_predictions`` (vía el fallback anidado) podía
# devolver un dict *wrapper* ``{ "predictions": [...] }`` en lugar de la lista
# directa. Ese dict caía en ``_safe_normalize_list`` como "predicción individual"
# -> conteo falso de 1 + advertencias de "confianza 0.0" (el wrapper no tiene
# ``confidence``). ``_unwrap_predictions`` des-envuelve el wrapper; el conteo
# pasa a ser ``len(predictions)`` sobre la lista plana.

class TestUnwrapPredictions:
    """Tests unitarios de ``_unwrap_predictions`` (des-envoltorio del wrapper)."""

    def test_dict_wrapper_returns_inner_list(self):
        """Un dict wrapper { "predictions": [...] } -> la lista interior."""
        preds = [
            {"x": 1, "y": 1, "width": 10, "height": 10, "class": "dog"},
            {"x": 2, "y": 2, "width": 20, "height": 20, "class": "cat"},
        ]
        assert _unwrap_predictions({"predictions": preds}) == preds

    def test_list_is_returned_as_is(self):
        """Una lista (ya plana) se retorna directamente como ``list``."""
        preds = [{"x": 1, "y": 1, "class": "a"}]
        result = _unwrap_predictions(preds)
        assert result == preds
        assert isinstance(result, list)

    def test_tuple_is_returned_as_list(self):
        """Una tupla se normaliza a ``list``."""
        preds = ({"x": 1, "class": "a"}, {"x": 2, "class": "b"})
        result = _unwrap_predictions(preds)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_dict_without_predictions_key_returns_empty(self):
        """Un dict SIN la clave ``predictions`` -> ``[]``."""
        assert _unwrap_predictions({"foo": [1, 2, 3]}) == []
        assert _unwrap_predictions({}) == []

    def test_nested_wrapper_is_unwrapped_recursively(self):
        """Wrapper anidado { "predictions": { "predictions": [...] } } -> lista
        plana (unwrap recursivo seguro)."""
        preds = [
            {"x": 1, "y": 1, "class": "a"},
            {"x": 2, "y": 2, "class": "b"},
            {"x": 3, "y": 3, "class": "c"},
        ]
        nested = {"predictions": {"predictions": preds}}
        assert _unwrap_predictions(nested) == preds

    def test_none_and_scalars_return_empty(self):
        """``None`` y escalares (salida corrupta) -> ``[]``."""
        assert _unwrap_predictions(None) == []
        assert _unwrap_predictions(42) == []
        assert _unwrap_predictions("corrupto") == []
        assert _unwrap_predictions(3.14) == []
        assert _unwrap_predictions(True) == []

    def test_never_raises_on_garbage(self):
        """NUNCA lanza, ni siquiera con objetos que rompen ``.get()``."""
        # Un objeto sin ``.get`` (no es dict ni secuencia) -> [].
        assert _unwrap_predictions(object()) == []


class TestWorkflowWrapperRegression:
    """Regresión del wrapper ``{ "predictions": [...] }``: el conteo debe ser el
    número REAL de detecciones (no 1), y no debe generarse advertencia de
    "confianza 0.0" por el wrapper procesado como detección fantasma."""

    def _dets(self, n: int) -> list:
        return [
            {"x": i, "y": i, "width": 10, "height": 10,
             "class": f"c{i}", "confidence": 0.9}
            for i in range(n)
        ]

    def test_extract_top_level_wrapper_dict(self):
        """``predictions`` a nivel top-level es el wrapper dict en sí mismo
        (caso raro pero posible) -> se des-envuelve a N detecciones."""
        dets = self._dets(3)
        # El output trae "predictions": { "predictions": [dets] } (wrapper).
        result = [{"predictions": {"predictions": dets}}]
        assert len(_extract_workflow_predictions(result)) == 3

    def test_extract_wrapper_nested_in_block(self):
        """Caso REAL del bug: un output { "<block>": { "predictions": <wrapper> } }.
        El fallback anidado extraía el wrapper dict; ahora se des-envuelve."""
        dets = self._dets(2)
        result = [{"my_block": {"predictions": {"predictions": dets}}}]
        assert len(_extract_workflow_predictions(result)) == 2

    def test_normalize_top_level_wrapper_not_counted_as_detection(self):
        """``normalize_predictions(workflow=True)`` con wrapper top-level NO
        cuenta el wrapper como 1 detección: devuelve las N reales."""
        dets = self._dets(4)
        result = [{"predictions": {"predictions": dets}}]
        normalized = normalize_predictions(result, workflow=True)
        # ANTES del fix esto devolvía 1 (el wrapper normalizado como detección
        # fantasma con confianza 0.0). Ahora devuelve las 4 reales.
        assert len(normalized) == 4
        assert {p["class"] for p in normalized} == {"c0", "c1", "c2", "c3"}

    def test_normalize_wrapper_nested_in_block_not_counted_as_one(self):
        """Caso del bug: wrapper dentro de un bloque. El conteo es el número
        real de detecciones, NO 1."""
        dets = self._dets(3)
        result = [{"roboflow_workflow": {"predictions": {"predictions": dets}}}]
        normalized = normalize_predictions(result, workflow=True)
        assert len(normalized) == 3
        assert {p["class"] for p in normalized} == {"c0", "c1", "c2"}

    def test_process_frame_wrapper_count_is_real_not_one(self, sample_frame, caplog):
        """Integración: con un workflow que devuelve el wrapper anidado en un
        bloque, ``get_detections()['count']`` es el nº real de detecciones (no 1)
        y NO se emite WARNING de confianza 0.0 por el wrapper fantasma."""
        if not CV2_AVAILABLE:
            pytest.skip("cv2 no disponible: el modo workflow requiere codificar el frame.")

        vision_engine._alerta_conf_last_ts.clear()
        caplog.set_level(logging.DEBUG, logger="services.vision_engine")

        engine = CloudVisionEngine(
            api_key="test-key", workspace="ws", workflow_id="wf",
        )
        engine._client = MagicMock()
        engine._available = True
        engine._use_workflow = True

        dets = [
            {"x": 100, "y": 100, "width": 50, "height": 50,
             "class": "person", "confidence": 0.9},
            {"x": 200, "y": 200, "width": 50, "height": 50,
             "class": "person", "confidence": 0.85},
            {"x": 300, "y": 300, "width": 50, "height": 50,
             "class": "car", "confidence": 0.7},
        ]
        # El workflow devuelve el wrapper DENTRO de un bloque (formato real de
        # run_workflow con un único bloque de output): el fallback anidado lo
        # atrapaba como dict y lo contaba como 1 detección fantasma.
        engine._client.run_workflow.return_value = [
            {"my_detection_block": {"predictions": {"predictions": dets}}}
        ]

        engine.process_frame(sample_frame)

        det = engine.get_detections()
        # ANTES del fix: count == 1 (el wrapper como detección fantasma).
        # DESPUÉS: count == 3 (las detecciones reales, lista ya unwrapeada).
        assert det["count"] == 3, (
            "El wrapper NO debe contar como 1 detección: el conteo es "
            "len(predictions) sobre la lista plana unwrapeada."
        )
        assert det["labels"] == {"person": 2, "car": 1}
        assert det["timestamp"] is not None

        # Regresión de observabilidad: como el wrapper YA NO se procesa como
        # detección, NO debe emitirse el WARNING de "confianza 0.0" que antes
        # disparaba el wrapper fantasma (las 3 detecciones reales tienen
        # confianza >= 0.40, todas sanas).
        wrapper_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "_alertar_confianzas_sospechosas" in r.getMessage()
        ]
        assert not wrapper_warnings, (
            "No debe emitirse WARNING de confianzas sospechosas: el wrapper ya "
            "no se procesa como detección y las 3 reales son sanas (>= 0.40)."
        )

    def test_process_frame_wrapper_top_level_count_is_real(self, sample_frame):
        """Variante: el wrapper aparece directamente como valor de la clave
        ``predictions`` a nivel top-level del output."""
        if not CV2_AVAILABLE:
            pytest.skip("cv2 no disponible: el modo workflow requiere codificar el frame.")

        engine = CloudVisionEngine(
            api_key="test-key", workspace="ws", workflow_id="wf",
        )
        engine._client = MagicMock()
        engine._available = True
        engine._use_workflow = True

        dets = [
            {"x": 100, "y": 100, "width": 50, "height": 50,
             "class": "dog", "confidence": 0.9},
            {"x": 200, "y": 200, "width": 50, "height": 50,
             "class": "dog", "confidence": 0.8},
        ]
        engine._client.run_workflow.return_value = [
            {"predictions": {"predictions": dets}}
        ]

        engine.process_frame(sample_frame)

        det = engine.get_detections()
        assert det["count"] == 2
        assert det["labels"] == {"dog": 2}


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
