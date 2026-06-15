"""
Capa de abstracción para motores de visión computacional — Argos2.

Implementa el patrón **Strategy + Factory** descrito en la sección #4 del
documento [`docs/plan-vision-local-cloud.md`](../docs/plan-vision-local-cloud.md),
permitiendo seleccionar dinámicamente entre:

- **Cloud** (Opción 2): inferencia en la nube de Roboflow vía HTTP REST usando
  ``inference_sdk``. Soporta **dos modos polimórficos**:
    * **Workflow** (``client.run_workflow()``): workflows personalizados que
      devuelven salidas estructuradas (``tracked_predictions``,
      ``counts_by_label``, ``total_count``, ``output_image``).
    * **Modelo estándar** (``client.infer()``): modelos clásicos que devuelven
      ``{"predictions": [...]}``.
- **Local** (Opción 3): inferencia local/edge con el paquete ``inference`` de
  Roboflow. Degradación *graceful* si el paquete no está instalado.
- **Off / None**: visión desactivada (se devuelve el frame crudo sin anotar).

La interfaz común de todos los motores es:

    frame (np.ndarray) -> VisionEngine.process_frame(frame) -> frame anotado (np.ndarray)

Seguridad: la API key de Roboflow se lee **exclusivamente** de variables de
entorno (``ROBOFLOW_API_KEY``). Nunca se hardcodea.
"""

import base64
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Importes opcionales (degradación graceful si faltan dependencias)
# -----------------------------------------------------------------------------

# OpenCV es necesario para dibujar los overlays. Es dependencia del proyecto,
# pero se protege la importación por consistencia con el resto del códigobase.
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:  # pragma: no cover - cv2 es dependencia del proyecto
    CV2_AVAILABLE = False
    logger.warning(
        "OpenCV (cv2) no está disponible. No se podrán dibujar los overlays "
        "de las predicciones sobre los frames."
    )

# Paleta de colores (BGR) para las clases detectadas.
_BOX_COLORS = [
    (0, 255, 0),    # Verde
    (0, 0, 255),    # Rojo
    (255, 0, 0),    # Azul
    (0, 255, 255),  # Amarillo
    (255, 0, 255),  # Magenta
    (255, 255, 0),  # Cian
    (0, 165, 255),  # Naranja
]


def _color_for_class(class_name: str):
    """Asigna un color determinístico (BGR) a partir del nombre de la clase."""
    idx = abs(hash(class_name)) % len(_BOX_COLORS)
    return _BOX_COLORS[idx]


def _draw_label(
    img: np.ndarray,
    text: str,
    org: tuple,
    color,
) -> None:
    """Dibuja una etiqueta de texto con fondo de color sobre la imagen."""
    if not CV2_AVAILABLE:
        return
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thickness = 1
    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    x, y = org
    # Rectángulo de fondo
    cv2.rectangle(img, (x, y - th - baseline), (x + tw, y + baseline), color, -1)
    # Texto en negro para contraste
    cv2.putText(
        img, text, (x, y - baseline + 2), font, scale, (0, 0, 0), thickness, cv2.LINE_AA
    )


def draw_predictions(
    frame: np.ndarray, predictions: List[dict]
) -> np.ndarray:
    """
    Dibuja bounding boxes + etiquetas sobre una copia del frame.

    Cada predicción es un dict con claves tipo Roboflow:
    ``x``, ``y`` (centro), ``width``, ``height``, ``confidence``, ``class``.
    Devuelve el frame anotado (nuevo array); el original no se modifica.
    """
    if not CV2_AVAILABLE or frame is None:
        return frame

    annotated = frame.copy()

    for pred in predictions or []:
        try:
            cx = float(pred.get("x", 0))
            cy = float(pred.get("y", 0))
            w = float(pred.get("width", 0))
            h = float(pred.get("height", 0))
            conf = pred.get("confidence")
            cls = pred.get("class", pred.get("class_name", "object"))

            x1 = int(round(cx - w / 2))
            y1 = int(round(cy - h / 2))
            x2 = int(round(cx + w / 2))
            y2 = int(round(cy + h / 2))

            color = _color_for_class(str(cls))
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            if conf is not None:
                label = f"{cls} {float(conf) * 100:.0f}%"
            else:
                label = str(cls)
            _draw_label(annotated, label, (x1, max(y1 - 2, 10)), color)
        except Exception as exc:  # noqa: BLE001
            logger.debug("No se pudo dibujar una predicción: %s", exc)

    return annotated


# -----------------------------------------------------------------------------
# Normalización de resultados de inferencia
# -----------------------------------------------------------------------------

def _prediction_to_dict(pred: Any) -> dict:
    """Convierte un objeto/dict de predicción a un dict plano normalizado."""
    if isinstance(pred, dict):
        return {
            "x": pred.get("x", 0),
            "y": pred.get("y", 0),
            "width": pred.get("width", 0),
            "height": pred.get("height", 0),
            "confidence": pred.get("confidence"),
            "class": pred.get("class", pred.get("class_name", "object")),
        }
    # Objeto (modelos del paquete `inference` local pueden devolver objetos)
    return {
        "x": getattr(pred, "x", 0),
        "y": getattr(pred, "y", 0),
        "width": getattr(pred, "width", getattr(pred, "w", 0)),
        "height": getattr(pred, "height", getattr(pred, "h", 0)),
        "confidence": getattr(pred, "confidence", None),
        "class": getattr(
            pred, "class_name", getattr(pred, "class", "object")
        ),
    }


def _extract_predictions_from_item(item: Any) -> List[dict]:
    """Extrae la lista de predicciones de un único resultado de inferencia."""
    if item is None:
        return []
    if isinstance(item, dict):
        if "predictions" in item:
            return [_prediction_to_dict(p) for p in item["predictions"]]
        if "x" in item:  # ya es una predicción individual
            return [item]
        return []
    # Objeto con atributo `.predictions`
    preds = getattr(item, "predictions", None)
    if preds is not None:
        return [_prediction_to_dict(p) for p in preds]
    return []


def _env_bool(
    explicit: Optional[bool],
    raw: Optional[str],
    default: bool = False,
) -> bool:
    """
    Resuelve un valor booleano desde un argumento explícito o una variable de
    entorno.

    Prioridad: argumento explícito > variable de entorno > ``default``.
    """
    if explicit is not None:
        return bool(explicit)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def _extract_workflow_predictions(result: Any) -> List[dict]:
    """
    Extrae predicciones del formato de salida de ``run_workflow()``.

    El workflow devuelve una lista de *outputs*, donde el primer elemento
    contiene claves como ``tracked_predictions`` (con tracking), ``predictions``,
    ``counts_by_label``, ``total_count``, ``output_image``, etc.

    Se prioriza ``tracked_predictions`` y, si no existe, se busca
    ``predictions`` como fallback.
    """
    # El workflow devuelve normalmente una lista; algunos SDK pueden envolverla.
    items = result if isinstance(result, (list, tuple)) else [result]
    if not items:
        return []
    first = items[0]
    if not isinstance(first, dict):
        # Si el formato varía, delegar al extractor genérico.
        return _extract_predictions_from_item(first)

    raw_preds = first.get("tracked_predictions")
    if raw_preds is None:
        raw_preds = first.get("predictions")
    if raw_preds is None:
        return []
    return [_prediction_to_dict(p) for p in raw_preds]


def extract_workflow_output_image(result: Any) -> Optional[np.ndarray]:
    """
    Extrae y decodifica ``output_image`` de la salida de un workflow.

    Si el workflow devuelve ``output_image`` (imagen ya anotada por el servidor,
    en base64), la decodifica a un numpy array BGR. Devuelve ``None`` si no hay
    ``output_image`` o la decodificación falla.

    Formatos soportados::

        {"output_image": {"value": "<base64>", "type": "base64"}}
        {"output_image": "<base64>"}
    """
    if not CV2_AVAILABLE:
        return None
    items = result if isinstance(result, (list, tuple)) else [result]
    if not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None

    output = first.get("output_image")
    if not output:
        return None
    try:
        if isinstance(output, dict):
            b64 = output.get("value") or output.get("base64")
        else:
            b64 = output
        if not b64:
            return None
        img_bytes = base64.b64decode(b64)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        decoded = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return decoded
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "No se pudo decodificar output_image del workflow: %s", exc
        )
        return None


def normalize_predictions(result: Any, workflow: bool = False) -> List[dict]:
    """
    Normaliza el resultado de inferencia (cloud, local o workflow) a una lista
    de dicts.

    Args:
        result: Resultado crudo de inferencia.
        workflow: Si ``True``, trata ``result`` como la salida estructurada de
            ``run_workflow()`` de Roboflow (lista de *outputs* donde el primer
            elemento contiene ``tracked_predictions``).

    - Cloud SDK (``client.infer``): dict con clave ``predictions``.
    - Local (``model.infer``): lista de objetos/respuestas con ``.predictions``.
    - Workflow (``run_workflow``): lista de dicts con ``tracked_predictions``
      (o ``predictions`` como fallback).
    """
    if result is None:
        return []
    if workflow:
        return _extract_workflow_predictions(result)
    if isinstance(result, dict) and "predictions" in result:
        return [_prediction_to_dict(p) for p in result["predictions"]]
    if isinstance(result, (list, tuple)):
        preds: List[dict] = []
        for item in result:
            preds.extend(_extract_predictions_from_item(item))
        return preds
    return _extract_predictions_from_item(result)


# =============================================================================
# VisionEngine — Clase base abstracta (Strategy)
# =============================================================================

class VisionEngine(ABC):
    """
    Interfaz común para todos los motores de visión computacional.

    Cada motor recibe un frame (numpy array BGR, como el que produce OpenCV) y
    devuelve el frame anotado (numpy array del mismo *shape* y *dtype*).
    """

    @abstractmethod
    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Procesa un frame y devuelve el frame anotado.

        Args:
            frame: Frame crudo como numpy array (H, W, 3) en formato BGR.

        Returns:
            Frame anotado como numpy array con el mismo *shape* y *dtype*.
            Si el frame es ``None`` o el motor no está disponible, se devuelve
            el frame original sin modificar (degradación *graceful*).
        """
        ...

    # ------------------------- Ciclo de vida (opcional) ---------------------

    def initialize(self) -> None:
        """
        Inicializa el motor (crea cliente, carga modelo, etc.).

        Implementación por defecto: no-op. Las subclases pueden sobrescribirlo.
        Debe ser seguro llamarlo varias veces.
        """
        return None

    def shutdown(self) -> None:
        """
        Libera los recursos del motor.

        Implementación por defecto: no-op. Las subclases pueden sobrescribirlo.
        """
        return None

    # ------------------------- Metadatos ------------------------------------

    @property
    def mode(self) -> str:
        """Identificador del modo (ej: 'cloud', 'local')."""
        return "unknown"

    @property
    def is_available(self) -> bool:
        """``True`` si el motor está listo para procesar frames."""
        return True

    def get_status(self) -> dict:
        """Retorna un dict con el estado del motor."""
        return {
            "mode": self.mode,
            "available": self.is_available,
        }

    # ------------------------- Helper interno -------------------------------

    def _safe_return(self, frame: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """Devuelve el frame original si el motor no está disponible."""
        if not self.is_available or frame is None:
            return frame
        return frame


# =============================================================================
# CloudVisionEngine — Opción 2 (Roboflow Cloud vía inference_sdk)
# =============================================================================

class CloudVisionEngine(VisionEngine):
    """
    Motor de visión Cloud usando ``inference_sdk``.

    Soporta **dos modos** de inferencia según la configuración:

    - **Modo Workflow** (prioritario): usa ``client.run_workflow()`` con un
      workflow personalizado de Roboflow. Requiere ``ROBOFLOW_WORKFLOW_ID`` y
      ``ROBOFLOW_WORKSPACE``. El workflow devuelve salidas estructuradas
      (``tracked_predictions``, ``counts_by_label``, ``total_count``,
      ``output_image``).

    - **Modo Modelo Estándar**: usa ``client.infer()`` con un modelo estándar.
      Requiere ``ROBOFLOW_MODEL_ID``. Devuelve ``{"predictions": [...]}``.

    Si ambos están configurados, se prioriza el **modo workflow** (con log de
    advertencia).

    Opcionalmente, si ``ROBOFLOW_USE_SERVER_OVERLAY=true`` y el workflow
    devuelve ``output_image``, se decodifica y devuelve esa imagen anotada por
    el servidor (ahorra CPU local a cambio de más ancho de banda).

    La API key se lee de la variable de entorno ``ROBOFLOW_API_KEY``.

    Flujo (workflow)::

        frame -> client.run_workflow(workspace, workflow_id, images)
              -> normalize_predictions(result, workflow=True)
              -> draw_predictions(frame, predictions)  # o output_image
              -> frame anotado

    Flujo (modelo estándar)::

        frame -> client.infer(frame, model_id)
              -> normalize_predictions(result, workflow=False)
              -> draw_predictions(frame, predictions)
              -> frame anotado
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model_id: Optional[str] = None,
        workspace: Optional[str] = None,
        workflow_id: Optional[str] = None,
        workflow_image_input: Optional[str] = None,
        workflow_use_cache: Optional[bool] = None,
        use_server_overlay: Optional[bool] = None,
    ) -> None:
        # La API key NUNCA se hardcodea: solo se lee de variables de entorno.
        self._api_key: Optional[str] = api_key or os.environ.get("ROBOFLOW_API_KEY")
        self._api_url: str = (
            api_url
            or os.environ.get("ROBOFLOW_API_URL")
            or "https://serverless.roboflow.com"
        )
        self._model_id: Optional[str] = (
            model_id or os.environ.get("ROBOFLOW_MODEL_ID")
        )
        self._workspace: Optional[str] = (
            workspace or os.environ.get("ROBOFLOW_WORKSPACE")
        )
        self._workflow_id: Optional[str] = (
            workflow_id or os.environ.get("ROBOFLOW_WORKFLOW_ID")
        )
        self._image_input: str = (
            workflow_image_input
            or os.environ.get("ROBOFLOW_WORKFLOW_IMAGE_INPUT")
            or "image"
        )
        self._use_cache: bool = _env_bool(
            workflow_use_cache,
            os.environ.get("ROBOFLOW_WORKFLOW_USE_CACHE"),
            default=True,
        )
        self._use_server_overlay: bool = _env_bool(
            use_server_overlay,
            os.environ.get("ROBOFLOW_USE_SERVER_OVERLAY"),
            default=False,
        )
        # Modo de inferencia: se resuelve en initialize().
        self._use_workflow: bool = False
        self._client = None  # type: ignore[assignment]
        self._available = False
        self._logger = logging.getLogger(f"{__name__}.CloudVisionEngine")

    # ------------------------- Ciclo de vida --------------------------------

    def initialize(self) -> None:
        """Crea el ``InferenceHTTPClient`` si la configuración está completa."""
        if self._client is not None:
            return  # ya inicializado

        # Resolver el modo de inferencia: workflow tiene prioridad.
        has_workflow = bool(self._workflow_id and self._workspace)
        has_model = bool(self._model_id)

        if has_workflow:
            self._use_workflow = True
            if has_model:
                self._logger.warning(
                    "Configurados tanto ROBOFLOW_WORKFLOW_ID como "
                    "ROBOFLOW_MODEL_ID. Se prioriza el modo WORKFLOW "
                    "(run_workflow); el model_id se ignorará a menos que se "
                    "elimine workflow_id/workspace."
                )
        elif has_model:
            self._use_workflow = False
        else:
            self._logger.warning(
                "No hay WORKFLOW_ID/WORKSPACE ni MODEL_ID configurados. "
                "CloudVisionEngine no estará disponible. Defina "
                "ROBOFLOW_WORKFLOW_ID+ROBOFLOW_WORKSPACE (workflow) o "
                "ROBOFLOW_MODEL_ID (modelo estándar)."
            )
            self._available = False
            return

        if not self._api_key:
            self._logger.warning(
                "ROBOFLOW_API_KEY no configurada. CloudVisionEngine no estará "
                "disponible. Defina la variable de entorno ROBOFLOW_API_KEY."
            )
            self._available = False
            return

        if self._use_workflow and not self._workspace:
            self._logger.warning(
                "ROBOFLOW_WORKSPACE no configurado (requerido por el modo "
                "workflow). CloudVisionEngine no estará disponible."
            )
            self._available = False
            return

        try:
            from inference_sdk import InferenceHTTPClient
        except ImportError:
            self._logger.error(
                "El paquete 'inference_sdk' no está instalado. "
                "Instálelo con: pip install inference-sdk"
            )
            self._available = False
            return

        try:
            self._client = InferenceHTTPClient(
                api_url=self._api_url,
                api_key=self._api_key,
            )
            self._available = True
            mode_desc = "workflow" if self._use_workflow else "modelo estándar"
            extra = (
                f", workspace={self._workspace}, workflow_id={self._workflow_id}"
                if self._use_workflow
                else f", model_id={self._model_id}"
            )
            self._logger.info(
                "CloudVisionEngine inicializado (api_url=%s, modo=%s%s).",
                self._api_url,
                mode_desc,
                extra,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error("Error al inicializar CloudVisionEngine: %s", exc)
            self._client = None
            self._available = False

    def shutdown(self) -> None:
        """Libera el cliente HTTP."""
        self._client = None
        self._available = False
        self._logger.info("CloudVisionEngine detenido.")

    # ------------------------- Metadatos ------------------------------------

    @property
    def mode(self) -> str:
        return "cloud"

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    # ------------------------- Procesamiento --------------------------------

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Envía el frame a Roboflow Cloud y devuelve el frame anotado.

        Usa ``run_workflow()`` o ``infer()`` según la configuración (modo
        polimórfico). Si ``ROBOFLOW_USE_SERVER_OVERLAY=true`` y el workflow
        devuelve ``output_image``, se decodifica y devuelve esa imagen (ahorra
        CPU local).

        Degradación *graceful*: si el motor no está disponible o la inferencia
        falla (sin conectividad, error de API, etc.), se devuelve el frame
        original sin anotar.
        """
        if frame is None:
            return frame  # type: ignore[return-value]

        if not self.is_available:
            self._logger.debug(
                "CloudVisionEngine no disponible: devolviendo frame sin anotar."
            )
            return frame

        try:
            if self._use_workflow:
                result = self._client.run_workflow(
                    workspace_name=self._workspace,
                    workflow_id=self._workflow_id,
                    images={self._image_input: frame},
                    use_cache=self._use_cache,
                )

                # Opción: usar la imagen anotada por el servidor del workflow.
                if self._use_server_overlay:
                    server_frame = extract_workflow_output_image(result)
                    if server_frame is not None:
                        return server_frame

                predictions = normalize_predictions(result, workflow=True)
            else:
                result = self._client.infer(frame, model_id=self._model_id)
                predictions = normalize_predictions(result, workflow=False)

            return draw_predictions(frame, predictions)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "Fallo en la inferencia Cloud (%s). Devolviendo frame sin anotar.",
                exc,
            )
            return frame


# =============================================================================
# LocalVisionEngine — Opción 3 (Inferencia local/edge con paquete `inference`)
# =============================================================================

class LocalVisionEngine(VisionEngine):
    """
    Motor de visión Local usando el paquete ``inference`` de Roboflow.

    Ejecuta el modelo localmente (CPU o GPU) con cero costo cloud y máxima
    privacidad (los frames nunca salen del servidor).

    Si el paquete ``inference`` no está instalado, el motor degrada
    *gracefully* marcándose como no disponible y devolviendo los frames sin
    anotar.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        self._api_key: Optional[str] = (
            api_key
            or os.environ.get("ROBOFLOW_API_KEY")
        )
        # El modelo local puede usar un ID distinto del cloud.
        self._model_id: Optional[str] = (
            model_id
            or os.environ.get("ROBOFLOW_LOCAL_MODEL_ID")
            or os.environ.get("ROBOFLOW_MODEL_ID")
        )
        self._device: str = device or os.environ.get("INFERENCE_DEVICE", "cpu")
        self._model = None
        self._available = False
        self._logger = logging.getLogger(f"{__name__}.LocalVisionEngine")

    # ------------------------- Ciclo de vida --------------------------------

    def initialize(self) -> None:
        """Carga el modelo local si el paquete ``inference`` está disponible."""
        if self._model is not None:
            return  # ya inicializado

        try:
            import inference  # noqa: F401  - verifica disponibilidad del paquete
            from inference import get_model
        except ImportError:
            self._logger.error(
                "LocalVisionEngine: el paquete 'inference' no está instalado. "
                "Instálelo con: pip install inference "
                "(requiere dependencias pesadas como torch/onnxruntime)."
            )
            self._available = False
            return

        if not self._api_key:
            self._logger.warning(
                "ROBOFLOW_API_KEY no configurada. LocalVisionEngine no estará "
                "disponible (necesaria para descargar/cargar el modelo local)."
            )
            self._available = False
            return

        if not self._model_id:
            self._logger.warning(
                "No hay MODEL_ID local configurado (ROBOFLOW_LOCAL_MODEL_ID o "
                "ROBOFLOW_MODEL_ID). LocalVisionEngine no estará disponible."
            )
            self._available = False
            return

        # El paquete `inference` lee la API key de la variable de entorno.
        os.environ.setdefault("INFERENCE_API_KEY", self._api_key)

        try:
            self._model = get_model(model_id=self._model_id, api_key=self._api_key)
            self._available = True
            self._logger.info(
                "LocalVisionEngine inicializado (model_id=%s, device=%s).",
                self._model_id,
                self._device,
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.error("Error al cargar el modelo local: %s", exc)
            self._model = None
            self._available = False

    def shutdown(self) -> None:
        """Libera el modelo local."""
        self._model = None
        self._available = False
        self._logger.info("LocalVisionEngine detenido.")

    # ------------------------- Metadatos ------------------------------------

    @property
    def mode(self) -> str:
        return "local"

    @property
    def is_available(self) -> bool:
        return self._available and self._model is not None

    # ------------------------- Procesamiento --------------------------------

    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Procesa el frame localmente y devuelve el frame anotado.

        Degradación *graceful*: si el motor no está disponible (paquete
        ``inference`` ausente, modelo no cargado) o la inferencia falla, se
        devuelve el frame original sin anotar.
        """
        if frame is None:
            return frame  # type: ignore[return-value]

        if not self.is_available:
            self._logger.debug(
                "LocalVisionEngine no disponible: devolviendo frame sin anotar."
            )
            return frame

        try:
            result = self._model.infer(frame)
            predictions = normalize_predictions(result)
            return draw_predictions(frame, predictions)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "Fallo en la inferencia local (%s). Devolviendo frame sin anotar.",
                exc,
            )
            return frame


# =============================================================================
# VisionEngineFactory — Fábrica (Factory)
# =============================================================================

class VisionEngineFactory:
    """
    Fábrica que instancia el motor de visión adecuado según el modo.

    Modos válidos:
        - ``"cloud"`` -> :class:`CloudVisionEngine`
        - ``"local"`` -> :class:`LocalVisionEngine`
        - ``"off"`` / ``"none"`` / ``None`` -> ``None`` (visión desactivada)
    """

    VALID_MODES = ("cloud", "local", "off", "none")

    @staticmethod
    def create(
        mode: Optional[str],
        *,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model_id: Optional[str] = None,
        device: Optional[str] = None,
        auto_initialize: bool = True,
    ) -> Optional[VisionEngine]:
        """
        Crea el motor de visión apropiado.

        Args:
            mode: Modo de visión (``"cloud"``, ``"local"``, ``"off"``,
                ``"none"`` o ``None``).
            api_key: API key de Roboflow (opcional; por defecto de entorno).
            api_url: URL del servidor de inferencia (solo cloud).
            model_id: ID del modelo (opcional; por defecto de entorno).
            device: Dispositivo de inferencia ``cpu``/``cuda`` (solo local).
            auto_initialize: Si ``True`` (por defecto), llama a ``initialize()``
                del motor creado. Útil para tests que solo quieren verificar el
                tipo de instancia sin inicializar.

        Returns:
            Una instancia de :class:`VisionEngine` o ``None`` si el modo es
            ``off``/``none``/``None``.

        Raises:
            ValueError: Si el modo no es válido.
        """
        normalized = (mode or "off").strip().lower()

        if normalized in ("off", "none", ""):
            return None

        kwargs_common: dict = {}
        if api_key is not None:
            kwargs_common["api_key"] = api_key
        if model_id is not None:
            kwargs_common["model_id"] = model_id

        if normalized == "cloud":
            engine: VisionEngine = CloudVisionEngine(
                **kwargs_common,
                **({"api_url": api_url} if api_url is not None else {}),
            )
        elif normalized == "local":
            local_kwargs = dict(kwargs_common)
            if device is not None:
                local_kwargs["device"] = device
            engine = LocalVisionEngine(**local_kwargs)
        else:
            raise ValueError(
                f"Modo de visión no válido: {mode!r}. "
                f"Modos válidos: cloud, local, off."
            )

        if auto_initialize:
            try:
                engine.initialize()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "No se pudo inicializar el motor de visión (%s): %s. "
                    "El motor se devolverá en estado no disponible.",
                    engine.mode,
                    exc,
                )

        return engine

    @staticmethod
    def get_available_modes() -> List[str]:
        """
        Retorna los modos disponibles según las dependencias instaladas.

        Siempre incluye ``cloud`` y ``off``. Incluye ``local`` solo si el
        paquete ``inference`` está instalado.
        """
        modes: List[str] = ["cloud", "local", "off"]
        try:
            import inference  # noqa: F401
        except ImportError:
            modes = ["cloud", "off"]
        return modes
