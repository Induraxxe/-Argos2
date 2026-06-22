"""
Capa de abstracción para motores de visión computacional — Argos2.

Implementa el patrón **Strategy + Factory** descrito en la sección #4 del
documento [`docs/plan-vision-local-cloud.md`](../docs/plan-vision-local-cloud.md),
permitiendo seleccionar dinámicamente entre:

- **Cloud** (Opción 2): inferencia en la nube de Roboflow vía HTTP REST usando
  ``inference_sdk``. Soporta **dos modos polimórficos**:
    * **Workflow** (``client.run_workflow()``): workflows personalizados que
      devuelven salidas estructuradas (``predictions`` —clave primaria—,
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
import tempfile
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuración — Observabilidad de confianza (sin filtrado local)
# -----------------------------------------------------------------------------
# El modelo de Roboflow entrega las predicciones YA pre-filtradas a un piso de
# confianza 0.40 en el servidor. El filtrado LOCAL hardcoded a 0.60 que existía
# antes (``DEFAULT_CONFIDENCE_THRESHOLD`` + ``_filter_by_confidence``) resultaba
# REDUNDANTE y, peor, DESCARTABA detecciones válidas que el modelo sí quiso
# entregar (p. ej. una confianza 0.45–0.59 que superó el piso del modelo). Por
# eso se eliminó el filtrado local: las predicciones normalizadas pasan TAL
# CUAL a conteo/dibujado, sustituido por telemetría (log DEBUG de confianzas
# entrantes + alerta WARNING de confianzas sospechosas).
#
# Piso de confianza considerado "normal": el modelo garantiza entregar
# predicciones con ``confidence >= 0.40``. Recibir una confianza por DEBAJO de
# 0.40 (o ausente / None / no numérica) es, por tanto, ANÓMALO y debe
# señalizarse vía WARNING —sin descartar la predicción, solo observabilidad—.
CONFIANZA_SOSPECHOSA_MIN = 0.40

# Antigüedad máxima (en segundos) del cache de detecciones tras la cual se
# considera "stale" (sin datos recientes). Protege contra el estancamiento del
# badge cuando el stream se detiene SIN lanzar excepción, SIN recurrir al reset
# prematuro al inicio de ``process_frame()`` (que causaba parpadeo a 0 mientras
# la inferencia de red estaba en curso). Umbral holgado: el polling de la UI es
# cada ~10s, así que 30s tolera varios ciclos de polling sin generar señales
# falsas durante la latencia normal de Roboflow.
STALE_TIMEOUT_SECONDS = 30.0

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

def _normalize_confidence(value: Any) -> float:
    """
    Normaliza un valor de ``confidence`` a ``float``, NUNCA lanza.

    Roboflow puede entregar el campo ``confidence`` como ``None``/``null``
    (p. ej. en workflows con tracking, o cuando el servidor omite la puntuación).
    Eso rompía la lógica de filtrado/conteo/dibujado, que asume un numérico.
    Aquí se garantiza un ``float`` SIEMPRE: ``0.0`` si el valor es ``None``,
    está ausente o no es convertible a ``float``.

    Args:
        value: Valor crudo de ``confidence`` (numérico, ``None``, ``str``, ...).

    Returns:
        El valor como ``float``, o ``0.0`` si no es numérico.
    """
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _prediction_to_dict(pred: Any) -> dict:
    """
    Convierte un objeto/dict de predicción a un dict plano normalizado.

    Garantiza que ``confidence`` sea SIEMPRE un ``float`` (``0.0`` cuando llega
    como ``None``/``null`` o como un valor no numérico), de modo que la lógica
    de filtrado/conteo/dibujado posterior no se rompa.

    Soporta tanto dicts (formato ``inference_sdk``/workflow) como objetos con
    atributos (paquete ``inference`` local).
    """
    if isinstance(pred, dict):
        return {
            "x": pred.get("x", 0),
            "y": pred.get("y", 0),
            "width": pred.get("width", 0),
            "height": pred.get("height", 0),
            "confidence": _normalize_confidence(pred.get("confidence")),
            "class": pred.get("class", pred.get("class_name", "object")),
        }
    # Objeto (modelos del paquete `inference` local pueden devolver objetos)
    return {
        "x": getattr(pred, "x", 0),
        "y": getattr(pred, "y", 0),
        "width": getattr(pred, "width", getattr(pred, "w", 0)),
        "height": getattr(pred, "height", getattr(pred, "h", 0)),
        "confidence": _normalize_confidence(getattr(pred, "confidence", None)),
        "class": getattr(
            pred, "class_name", getattr(pred, "class", "object")
        ),
    }


def _safe_normalize_list(raw_preds: Any) -> List[dict]:
    """
    Normaliza una secuencia de predicciones crudas a una lista de dicts,
    OMITIENDO los elementos malformados. NUNCA lanza excepciones.

    Tolerancia a fallos ante salidas de Roboflow incompletas/malformadas:

      - ``None`` / vacío / ``[]`` / ``{}`` -> ``[]``.
      - Una lista/tupla -> cada elemento se normaliza; los que lancen una
        excepción al normalizarse se descartan con un log DEBUG (un elemento
        corrupto NO tira toda la extracción).
      - Un dict suelto (predicción individual) -> ``[_prediction_to_dict(dict)]``.
      - Un escalar (``int``/``float``/``str``/``bool``/``bytes``) u otro tipo
        no soportado donde iría la lista -> ``[]`` (salida malformada).

    Args:
        raw_preds: Lista cruda de predicciones (``predictions`` /
            ``tracked_predictions``), o ``None``.

    Returns:
        Lista de dicts de predicción normalizados (puede ser ``[]``).
    """
    if not raw_preds:
        return []
    # Secuencia de predicciones: normalizar elemento a elemento, descartando
    # los corruptos (un elemento malformado NO tira toda la extracción).
    if isinstance(raw_preds, (list, tuple)):
        normalized: List[dict] = []
        for p in raw_preds:
            # Descartar de antemano lo que claramente NO es una predicción
            # (``None`` o escalares): solo un dict u objeto puede normalizarse
            # a una predicción con sentido. Evita detecciones "fantasma".
            if p is None or isinstance(p, (int, float, str, bool, bytes)):
                logger.debug(
                    "_safe_normalize_list: elemento no-predicción omitido: %r", p
                )
                continue
            try:
                normalized.append(_prediction_to_dict(p))
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "_safe_normalize_list: elemento malformado omitido: %r (%s)",
                    p, exc,
                )
        return normalized
    # ¿Predicción individual suelta (un dict)? Intentar normalizarla. Un
    # escalar (int/float/str/bool/bytes) NO es una predicción válida -> [].
    if isinstance(raw_preds, dict):
        try:
            return [_prediction_to_dict(raw_preds)]
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "_safe_normalize_list: predicción malformada omitida: %r (%s)",
                raw_preds, exc,
            )
            return []
    logger.debug(
        "_safe_normalize_list: tipo no soportado como lista de predicciones "
        "(%s). Devolviendo [].",
        type(raw_preds).__name__,
    )
    return []


def _extract_predictions_from_item(item: Any) -> List[dict]:
    """Extrae la lista de predicciones de un único resultado de inferencia."""
    if item is None:
        return []
    if isinstance(item, dict):
        if "predictions" in item:
            return _safe_normalize_list(item["predictions"])
        if "x" in item:  # ya es una predicción individual
            return [_prediction_to_dict(item)]
        return []
    # Objeto con atributo `.predictions`
    preds = getattr(item, "predictions", None)
    if preds is not None:
        return _safe_normalize_list(preds)
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


def _unwrap_predictions(value: Any, _depth: int = 0) -> list:
    """
    Des-envuelve el *wrapper* ``{ "predictions": [...] }`` y devuelve SIEMPRE
    una lista plana de detecciones. NUNCA lanza excepción.

    Es la ``unwrap_predictions`` solicitada (prefijo ``_`` por ser interna del
    módulo, en línea con :func:`_safe_normalize_list` / :func:`_normalize_confidence`).

    Roboflow puede devolver las predicciones envueltas en un dict
    ``{ "predictions": [...] }`` en lugar de la lista directa (típico en los
    outputs anidados de ``run_workflow()`` con formato
    ``{ "<block>": { "predictions": {...} } }``). Antes este dict caía en
    :func:`_safe_normalize_list` como "predicción individual", produciendo un
    **conteo falso de 1** y **advertencias de "confianza 0.0"** (el *wrapper*
    no tiene campo ``confidence`` y :func:`_normalize_confidence` lo resolvía
    a ``0.0``). Esta función elimina ese *wrapper* de forma robusta.

    Reglas:

      - ``dict`` -> retorna ``value["predictions"]`` si existe y es una
        lista/tupla de detecciones. Si ``value["predictions"]`` es a su vez
        otro dict *wrapper* anidado ``{ "predictions": [...] }``, se
        des-envuelve recursivamente de forma segura (máx. 2 niveles de
        profundidad, para evitar recursión infinita ante payloads
        maliciosos/corruptos — ver ``_depth``). Si la clave no existe o el
        contenido no es procesable -> ``[]``.
      - ``list`` / ``tuple`` -> se retorna directamente como ``list`` (ya es
        una secuencia plana de detecciones).
      - Cualquier otra cosa (``None``, ``int``, ``str``, ``bool``, ...) ->
        ``[]`` (salida malformada).

    Args:
        value: Valor crudo extraído de la clave ``predictions`` /
            ``tracked_predictions`` del workflow (puede ser la lista de
            detecciones, un dict *wrapper*, o basura).
        _depth: Contador interno de profundidad de recursión (anti-loop).
            No pasar manualmente desde el llamador.

    Returns:
        Una ``list`` (posiblemente vacía) con las detecciones ya
        des-envueltas. NUNCA lanza.
    """
    try:
        # Una lista/tupla ya es una secuencia plana de detecciones.
        if isinstance(value, (list, tuple)):
            return list(value)
        # Un dict: extraer la clave "predictions" (unwrap del wrapper).
        if isinstance(value, dict):
            inner = value.get("predictions")
            # Contenido directo: lista/tupla de detecciones.
            if isinstance(inner, (list, tuple)):
                return list(inner)
            # Wrapper anidado { "predictions": { "predictions": [...] } }:
            # des-envolver recursivamente (máx. 2 niveles anti-loop).
            if isinstance(inner, dict) and _depth < 2:
                return _unwrap_predictions(inner, _depth=_depth + 1)
            # Clave ausente o contenido no procesable -> [].
            return []
        # None / escalares / otros tipos no soportados -> [].
        return []
    except Exception:  # noqa: BLE001 - tolerancia total, nunca lanza.
        return []


def _extract_workflow_predictions(result: Any) -> List[dict]:
    """
    Extrae predicciones del formato de salida de ``run_workflow()``.

    El workflow devuelve una lista de *outputs*, donde el primer elemento
    contiene claves como ``predictions``, ``tracked_predictions`` (con tracking),
    ``counts_by_label``, ``total_count``, ``output_image``, etc.

    Se prioriza ``predictions`` y, si no existe o está vacía, se busca
    ``tracked_predictions`` como fallback (retrocompatibilidad con workflows
    previos que usaban tracking).

    El valor extraído se pasa por :func:`_unwrap_predictions` para eliminar el
    *wrapper* ``{ "predictions": [...] }``: el resultado es SIEMPRE una lista
    plana de detecciones (nunca el dict *wrapper* ni una lista que lo contenga
    como elemento). Sin este paso, un dict *wrapper* caía en
    :func:`_safe_normalize_list` como "predicción individual", produciendo un
    **conteo falso de 1** y **advertencias de "confianza 0.0"** (el *wrapper*
    no tiene campo ``confidence``).
    """
    # El workflow devuelve normalmente una lista; algunos SDK pueden envolverla.
    items = result if isinstance(result, (list, tuple)) else [result]
    if not items:
        return []
    first = items[0]
    if not isinstance(first, dict):
        # Si el formato varía, delegar al extractor genérico.
        return _extract_predictions_from_item(first)

    # Clave primaria: "predictions". Fallback: "tracked_predictions".
    raw_preds = first.get("predictions")
    if raw_preds is None:
        raw_preds = first.get("tracked_predictions")
    # Fallback: buscar dentro de los valores anidados del dict (formato real
    # de ``run_workflow()``, donde el primer output es { "<block>": {...} }).
    if raw_preds is None:
        for value in first.values():
            if isinstance(value, dict):
                nested = value.get("predictions") or value.get("tracked_predictions")
                if nested:
                    raw_preds = nested
                    break
    if raw_preds is None:
        logger.debug(
            "_extract_workflow_predictions: no se encontraron predicciones. "
            "Claves del 1er output: %s",
            list(first.keys()) if isinstance(first, dict) else type(first).__name__,
        )
        return []
    # Des-envolver el wrapper { "predictions": [...] }: garantiza una lista
    # PLANA de detecciones. Sin este paso, un dict wrapper caía en
    # ``_safe_normalize_list`` como "predicción individual", produciendo un
    # conteo falso de 1 y advertencias de "confianza 0.0" (el wrapper no
    # tiene campo ``confidence``).
    unwrapped = _unwrap_predictions(raw_preds)
    if not unwrapped:
        return []
    # Normalización tolerante a fallos: ``unwrapped`` es ahora una lista plana
    # cuyos elementos pueden seguir estando vacíos/malformados.
    # ``_safe_normalize_list`` nunca lanza: descarta los elementos inválidos y
    # devuelve ``[]`` si todo falla.
    return _safe_normalize_list(unwrapped)


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
    # Fallback: buscar ``output_image``/``image`` dentro de los valores
    # anidados del dict (formato real de ``run_workflow()``: { "<block>": {...} }).
    if not output:
        for value in first.values():
            if isinstance(value, dict):
                nested = value.get("output_image") or value.get("image")
                if nested:
                    output = nested
                    break
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
            elemento contiene ``predictions``).

    - Cloud SDK (``client.infer``): dict con clave ``predictions``.
    - Local (``model.infer``): lista de objetos/respuestas con ``.predictions``.
    - Workflow (``run_workflow``): lista de dicts con ``predictions``
      (o ``tracked_predictions`` como fallback de retrocompatibilidad).
    """
    if result is None:
        return []
    if workflow:
        return _extract_workflow_predictions(result)
    if isinstance(result, dict) and "predictions" in result:
        # Normalización tolerante a fallos (vacío / malformado -> [] sin lanzar).
        return _safe_normalize_list(result["predictions"])
    if isinstance(result, (list, tuple)):
        preds: List[dict] = []
        for item in result:
            preds.extend(_extract_predictions_from_item(item))
        return preds
    return _extract_predictions_from_item(result)


def _count_predictions(predictions: List[dict]) -> Dict[str, int]:
    """
    Cuenta el número de detecciones agrupadas por clase.

    Recorre una lista de predicciones normalizadas (dicts con clave ``class``)
    y devuelve un dict ``{nombre_clase: cantidad}``.

    Args:
        predictions: Lista de dicts de predicción (ej: salida de
            :func:`normalize_predictions`).

    Returns:
        Dict ``{str: int}`` con el conteo por clase. Ej::
            ``{'person': 2, 'car': 1}``.
    """
    counts: Dict[str, int] = {}
    for pred in predictions or []:
        cls = str(pred.get("class", pred.get("class_name", "object")))
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def _log_confianzas(predictions: Optional[List[dict]], origen: str) -> None:
    """
    Registra a nivel DEBUG las confianzas entrantes de una lista de
    predicciones normalizadas.

    Equivale a un ``TRACE``: la stdlib de Python no define el nivel TRACE, así
    que se usa DEBUG como su equivalente de mayor granularidad. Es PURA
    observabilidad: no modifica ni descarta ninguna predicción. Defensiva frente
    a ``predictions`` ``None``/vacío y a confianzas ausentes / ``None`` / no
    numéricas (se reflejan explícitamente para que el flujo sea auditable).

    Args:
        predictions: Lista de predicciones normalizadas (cada una un dict con
            clave ``confidence``, posiblemente ausente o ``None``).
        origen: Identificador de la rama que invoca (p. ej.
            ``"cloud.workflow"``, ``"cloud.standard"``, ``"local"``) para
            contextualizar el log.
    """
    if not predictions:
        logger.debug("_log_confianzas[%s]: 0 predicciones entrantes.", origen)
        return
    pares: List[Tuple[Any, Any]] = []
    validas: List[float] = []
    for pred in predictions:
        if not isinstance(pred, dict):
            continue
        cls = pred.get("class", pred.get("class_name", "object"))
        conf = pred.get("confidence", None)
        pares.append((cls, conf))
        if conf is not None:
            try:
                validas.append(float(conf))
            except (TypeError, ValueError):
                # conf no numérica: queda fuera del resumen min/max/media pero
                # sí aparece en la lista de pares (clase, confianza).
                pass
    if validas:
        resumen = (
            f"min={min(validas):.3f}, max={max(validas):.3f}, "
            f"media={sum(validas) / len(validas):.3f}"
        )
    else:
        resumen = "sin confianzas numéricas válidas"
    logger.debug(
        "_log_confianzas[%s]: %d predicción(es) entrantes | %s | pares=%s",
        origen, len(predictions), resumen, pares,
    )


# Throttle de la alerta WARNING de confianzas sospechosas. La inferencia corre
# a FPS (varias veces por segundo por cámara), así que una anomalía persistente
# generaría un WARNING por frame. Para no inundar los logs, cada ``origen``
# (rama de process_frame) lleva su propio cooldown: la 1ª ocurrencia SIEMPRE se
# registra y las siguientes dentro de la ventana se suprimen. El estado vive a
# nivel de módulo para poder resetearlo fácilmente desde tests
# (``_alerta_conf_last_ts.clear()``).
_ALERTA_CONF_COOLDOWN_S: float = 60.0
_alerta_conf_last_ts: Dict[str, float] = {}


def _alertar_confianzas_sospechosas(
    predictions: Optional[List[dict]], origen: str
) -> None:
    """
    Emite UN único log WARNING si encuentra predicciones con confianza
    "sospechosa", SIN mutar, descartar ni alterar la lista de predicciones.

    Se considera SOSPECHOSA una predicción cuya ``confidence`` sea:
      - ausente / ``None`` / no numérica, **o**
      - un número en ``0.0 <= confidence < CONFIANZA_SOSPECHOSA_MIN`` (por
        debajo del piso 0.40 que el modelo garantiza entregar).

    El WARNING se emite como mucho una vez por ``origen`` dentro del cooldown
    ``_ALERTA_CONF_COOLDOWN_S`` (throttle anti-inundación).

    Args:
        predictions: Lista de predicciones normalizadas (solo lectura).
        origen: Identificador de la rama que invoca (contexto + clave de
            throttle).

    Note:
        PURA observabilidad. No devuelve nada y jamás modifica ``predictions``
        ni sus elementos.
    """
    if not predictions:
        return
    sospechosas: List[Tuple[Any, Any]] = []
    for pred in predictions:
        if not isinstance(pred, dict):
            continue
        cls = pred.get("class", pred.get("class_name", "object"))
        conf = pred.get("confidence", None)
        if conf is None:
            sospechosas.append((cls, conf))
            continue
        try:
            conf_val = float(conf)
        except (TypeError, ValueError):
            sospechosas.append((cls, conf))
            continue
        if 0.0 <= conf_val < CONFIANZA_SOSPECHOSA_MIN:
            sospechosas.append((cls, conf))
    if not sospechosas:
        return
    # Throttle: la 1ª ocurrencia siempre se loguea; las siguientes dentro del
    # cooldown se suprimen para no inundar los logs en anomalías persistentes.
    now = time.monotonic()
    if (now - _alerta_conf_last_ts.get(origen, 0.0)) >= _ALERTA_CONF_COOLDOWN_S:
        logger.warning(
            "_alertar_confianzas_sospechosas[%s]: %d predicción(es) con "
            "confianza sospechosa (ausente/None/no numérica o < %.2f): %s. "
            "No se descartan (el modelo pre-filtra en servidor): solo se "
            "reporta para observabilidad.",
            origen, len(sospechosas), CONFIANZA_SOSPECHOSA_MIN, sospechosas,
        )
        _alerta_conf_last_ts[origen] = now


def _extract_workflow_counts(result: Any) -> Tuple[Optional[dict], Optional[int]]:
    """
    Extrae ``counts_by_label`` y ``total_count`` de la salida de un workflow.

    Los workflows personalizados de Roboflow suelen devolver estas claves junto
    a ``predictions``/``tracked_predictions``. Esta función las localiza en el
    primer elemento de la lista de *outputs* de ``run_workflow()``.

    Args:
        result: Salida cruda de ``client.run_workflow()``.

    Returns:
        Tupla ``(counts_by_label, total_count)``. Ambos elementos son ``None``
        si no están presentes en el resultado (en cuyo caso el llamador debe
        calcularlos a partir de las predicciones).
    """
    items = result if isinstance(result, (list, tuple)) else [result]
    if not items:
        return None, None
    first = items[0]
    if not isinstance(first, dict):
        return None, None

    counts_by_label = first.get("counts_by_label")
    total_count = first.get("total_count")
    # Fallback: buscar dentro de los valores anidados del dict (formato real
    # de ``run_workflow()``, donde el primer output es { "<block>": {...} }).
    if counts_by_label is None and total_count is None:
        for value in first.values():
            if isinstance(value, dict):
                nested_counts = value.get("counts_by_label")
                nested_total = value.get("total_count")
                if nested_counts is not None or nested_total is not None:
                    counts_by_label = nested_counts
                    total_count = nested_total
                    break
    return counts_by_label, total_count


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

    # ------------------------- Detecciones ----------------------------------

    def get_detections(self) -> dict:
        """
        Retorna el conteo de detecciones del último frame procesado.

        Returns:
            Dict con la estructura::

                {
                    'count': int,              # total de objetos detectados
                    'labels': {str: int},      # ej: {'person': 2, 'car': 1}
                    'timestamp': float | None  # epoch del frame, o None
                }

            Implementación por defecto (sin datos): ``{'count': 0,
            'labels': {}, 'timestamp': None}``.
        """
        return {'count': 0, 'labels': {}, 'timestamp': None}

    def _store_detections(self, count: int, labels: dict) -> None:
        """
        Actualiza el cache de detecciones del último frame procesado.

        Las subclases deben inicializar ``self._last_detections`` en su
        ``__init__``/``initialize()`` antes de llamar a este método (típicamente
        en ``process_frame()`` tras una inferencia exitosa).

        Args:
            count: Total de objetos detectados.
            labels: Dict ``{clase: cantidad}``.
        """
        self._last_detections = {
            'count': int(count),
            'labels': dict(labels) if labels else {},
            'timestamp': time.time(),
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
      (``predictions``, ``counts_by_label``, ``total_count``,
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
        # Cache de detecciones del último frame procesado con éxito.
        self._last_detections: dict = {
            'count': 0, 'labels': {}, 'timestamp': None
        }
        # Contador de errores de inferencia (para throttle de logs).
        self._infer_error_count: int = 0
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
                "Cloud vision no disponible: falta WORKSPACE/WORKFLOW_ID o "
                "MODEL_ID. Defina ROBOFLOW_WORKFLOW_ID+ROBOFLOW_WORKSPACE "
                "(modo workflow) o ROBOFLOW_MODEL_ID (modelo estándar)."
            )
            self._available = False
            return

        if not self._api_key:
            self._logger.warning(
                "Cloud vision no disponible: falta ROBOFLOW_API_KEY. Defina "
                "la variable de entorno ROBOFLOW_API_KEY."
            )
            self._available = False
            return

        if self._use_workflow and not self._workspace:
            self._logger.warning(
                "Cloud vision no disponible: falta ROBOFLOW_WORKSPACE "
                "(requerido por el modo workflow)."
            )
            self._available = False
            return

        try:
            from inference_sdk import InferenceHTTPClient
        except ImportError:
            self._logger.warning(
                "Cloud vision no disponible: inference_sdk no instalado. "
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

        Tras cada inferencia exitosa se actualiza el cache de detecciones
        (``self._last_detections``), accesible vía :meth:`get_detections`.

        Degradación *graceful*: si el motor no está disponible o la inferencia
        falla (sin conectividad, error de API, etc.), se devuelve el frame
        original sin anotar **sin sobreescribir** el último cache de detecciones
        válido.
        """
        if frame is None:
            return frame  # type: ignore[return-value]

        if not self.is_available:
            self._logger.debug(
                "CloudVisionEngine no disponible: devolviendo frame sin anotar."
            )
            return frame

        # NOTA (P2 — anti-parpadeo): NO se resetea el cache de detecciones al
        # inicio. El reset prematuro hacía que el badge parpadease a 0 mientras
        # la inferencia de red de Roboflow estaba en curso (el polling de la UI
        # cada ~10s atrapaba ese 0 transitorio). Ahora el cache solo se
        # actualiza en dos puntos: (1) éxito de la inferencia (conteo real,
        # más abajo) y (2) bloque ``except`` (señal real de fallo → 0). La
        # protección contra el estancamiento indefinido se resuelve vía
        # antigüedad en :meth:`get_detections` (``STALE_TIMEOUT_SECONDS``), no
        # con un reset prematuro.

        try:
            if self._use_workflow:
                # ----------------------------------------------------------
                # LOG DE DIAGNÓSTICO (temporal): parámetros exactos enviados
                # al workflow. Útil para detectar workflow_id / workspace /
                # image_input_key incorrectos (causa #1 de resultados vacíos).
                # ----------------------------------------------------------
                self._logger.info(
                    "CloudVisionEngine.run_workflow params: workspace=%s, "
                    "workflow_id=%s, image_input_key=%s, image_shape=%s, use_cache=%s",
                    self._workspace,
                    self._workflow_id,
                    self._image_input,
                    getattr(frame, "shape", "unknown"),
                    self._use_cache,
                )

                # ----------------------------------------------------------
                # CODIFICACIÓN A BASE64 + LOG DE DIAGNÓSTICO: el
                # ``inference_sdk`` 1.3.1 NO serializa un numpy array cuando
                # se pasa a ``run_workflow()`` (a diferencia de ``infer()``).
                # Serializamos el frame a JPEG+base64 aquí y reutilizamos el
                # resultado (``_b64``) tanto para el log diagnóstico como
                # para el payload REAL del workflow. Si no se puede codificar,
                # se aborta con degradación graceful (ver más abajo).
                # ----------------------------------------------------------
                _b64 = None
                try:
                    if CV2_AVAILABLE:
                        _enc_ok, _enc_buf = cv2.imencode(".jpg", frame)
                        if _enc_ok:
                            _b64 = base64.b64encode(_enc_buf.tobytes()).decode("ascii")
                            self._logger.info(
                                "CloudVisionEngine.run_workflow image encoding OK: "
                                "key=%s, base64_len=%d, preview=%s",
                                self._image_input,
                                len(_b64),
                                _b64[:64],
                            )
                        else:
                            self._logger.warning(
                                "CloudVisionEngine.run_workflow image encoding FALLÓ "
                                "(cv2.imencode devolvió False). key=%s, frame_shape=%s",
                                self._image_input,
                                getattr(frame, "shape", "unknown"),
                            )
                    else:
                        self._logger.warning(
                            "CloudVisionEngine.run_workflow image encoding NO disponible: "
                            "cv2 no importado. key=%s, frame_shape=%s",
                            self._image_input,
                            getattr(frame, "shape", "unknown"),
                        )
                except Exception as _enc_err:  # noqa: BLE001
                    self._logger.warning(
                        "CloudVisionEngine.run_workflow image encoding ERROR: %s: %s "
                        "(key=%s, frame_shape=%s)",
                        type(_enc_err).__name__,
                        _enc_err,
                        self._image_input,
                        getattr(frame, "shape", "unknown"),
                    )

                # Si la codificación a base64 falló (cv2 ausente o
                # ``imencode`` devolvió False), no hay payload válido para
                # ``run_workflow()``: devolvemos el frame sin anotar (cache
                # vacío) en lugar de enviar el numpy array crudo, que el
                # ``inference_sdk`` 1.3.1 no serializa y produce ``[{}]``.
                if not _b64:
                    self._logger.warning(
                        "CloudVisionEngine: no se pudo codificar el frame a "
                        "base64 para run_workflow(); devolviendo frame sin "
                        "anotar. key=%s, frame_shape=%s",
                        self._image_input,
                        getattr(frame, "shape", "unknown"),
                    )
                    self._store_detections(0, {})
                    return frame

                # ----------------------------------------------------------
                # PAYLOAD DEL WORKFLOW — ARCHIVO TEMPORAL:
                # El código oficial de Roboflow pasa una **RUTA DE ARCHIVO**
                # en ``images`` (``images={"image": "YOUR_IMAGE.jpg"}``).
                # Hemos probado numpy array y base64 string con
                # ``inference_sdk`` 1.3.1 y ambos devolvieron ``[{}]``.
                # Replicamos aquí exactamente el formato de archivo que el
                # SDK garantiza que funciona: guardamos el frame en un
                # ``.jpg`` temporal y pasamos su RUTA. ``_b64`` se mantiene
                # exclusivamente para el log diagnóstico de tamaño (no se
                # usa como payload).
                # ----------------------------------------------------------
                _tmp_fd, _tmp_path = tempfile.mkstemp(suffix=".jpg")
                try:
                    os.close(_tmp_fd)
                    _imwrite_ok = cv2.imwrite(_tmp_path, frame)
                    self._logger.info(
                        "CloudVisionEngine.run_workflow image payload (archivo temporal): "
                        "path=%s, imwrite_ok=%s, key=%s, base64_len=%d (diagnóstico).",
                        _tmp_path,
                        _imwrite_ok,
                        self._image_input,
                        len(_b64) if _b64 else 0,
                    )
                    if not _imwrite_ok:
                        # No se pudo escribir el archivo temporal: no hay
                        # payload válido para ``run_workflow()``.
                        self._logger.warning(
                            "CloudVisionEngine: cv2.imwrite FALLÓ al escribir el "
                            "archivo temporal %s. Devolviendo frame sin anotar.",
                            _tmp_path,
                        )
                        self._store_detections(0, {})
                        return frame

                    result = self._client.run_workflow(
                        workspace_name=self._workspace,
                        workflow_id=self._workflow_id,
                        images={self._image_input: _tmp_path},
                        use_cache=self._use_cache,
                    )
                finally:
                    # Asegura que el archivo temporal se borre siempre,
                    # incluso si run_workflow() lanza una excepción.
                    try:
                        os.unlink(_tmp_path)
                    except OSError:
                        pass

                # ----------------------------------------------------------
                # LOG DE DIAGNÓSTICO (temporal): respuesta CRUDA del workflow.
                # ``json.dumps`` truncado a 2000 chars para no saturar la
                # consola. Si no es serializable, cae al ``repr``.
                # ----------------------------------------------------------
                try:
                    import json
                    _raw_str = json.dumps(result, default=str)[:2000]
                    self._logger.info(
                        "CloudVisionEngine.run_workflow RAW response: %s",
                        _raw_str,
                    )
                except Exception:  # noqa: BLE001
                    self._logger.info(
                        "CloudVisionEngine.run_workflow RAW response (repr): %r",
                        result,
                    )

                # ----------------------------------------------------------
                # VERIFICACIÓN DE RESULTADO VACÍO: si ``run_workflow()`` retorna
                # ``[{}]`` el workflow se ejecutó pero no produjo output.
                # ----------------------------------------------------------
                if (
                    isinstance(result, (list, tuple))
                    and result
                    and isinstance(result[0], dict)
                    and len(result[0]) == 0
                ):
                    self._logger.warning(
                        "Workflow devolvió resultado vacío [{}]. Posibles causas: "
                        "(1) workflow_id incorrecto, (2) workspace incorrecto, "
                        "(3) el workflow no tiene bloques de output configurados, "
                        "(4) el parámetro image_input='%s' no coincide con el "
                        "esperado por el workflow, (5) la API key no tiene acceso "
                        "a este workspace/workflow.",
                        self._image_input,
                    )

                # Predicciones normalizadas (para dibujar los overlays).
                predictions = normalize_predictions(result, workflow=True)
                # Observabilidad de confianza (sin filtrado local): el modelo
                # de Roboflow pre-filtra a 0.40 en el servidor, así que las
                # predicciones normalizadas pasan TAL CUAL a conteo/dibujado.
                # Aquí solo se registra (DEBUG) y se alerta (WARNING) de
                # confianzas sospechosas, sin descartar nada.
                _log_confianzas(predictions, "cloud.workflow")
                _alertar_confianzas_sospechosas(predictions, "cloud.workflow")

                self._logger.info(
                    "CloudVisionEngine.process_frame: workflow result claves=%s | predicciones=%d",
                    (list(result[0].keys()) if isinstance(result, (list, tuple)) and result and isinstance(result[0], dict) else type(result).__name__),
                    len(predictions),
                )

                # ----------------------------------------------------------
                # CONTEO INSTANTÁNEO ATÓMICO (basado en predictions):
                # NO se leen los metadatos ``total_count`` /
                # ``counts_by_label`` del JSON del workflow, porque el
                # mecanismo de Tracking interno de Roboflow los corrompe
                # manteniendo detecciones fantasma (el badge de conteo quedaba
                # "congelado" mostrando datos basura que nunca bajaban a 0).
                #
                # El conteo se calcula EXCLUSIVAMENTE en código a partir de la
                # detección instantánea del frame actual. ``predictions``
                # contiene las ``predictions`` del workflow (clave primaria;
                # ``tracked_predictions`` se usa solo como fallback de
                # retrocompatibilidad), normalizadas con el MISMO extractor
                # robusto que las cajas que se dibujan -> el conteo es SIEMPRE
                # consistente con los overlays). Usar ``predictions`` (y no una
                # extracción cruda de ``result.get('predictions', [])``) es
                # deliberado: ``run_workflow()`` devuelve una lista de outputs
                # (a veces con formato anidado ``{ "<block>": {...} }``) que
                # ``normalize_predictions`` ya maneja, evitando ``KeyError`` y
                # divergencias entre el conteo y lo dibujado.
                #
                # Atomicidad: si la lista está vacía, ``len([]) == 0`` se
                # propaga de forma inmediata. NO existe lógica del tipo "si el
                # nuevo conteo es 0, mantener el anterior" ni
                # ``max(conteo_nuevo, conteo_previo)``. El conteo refleja
                # fielmente la detección instantánea del frame actual, incluso
                # si es 0.
                total_count = len(predictions)
                counts_by_label = _count_predictions(predictions)
                self._store_detections(total_count, counts_by_label)

                # Opción: usar la imagen anotada por el servidor del workflow.
                if self._use_server_overlay:
                    server_frame = extract_workflow_output_image(result)
                    if server_frame is not None:
                        return server_frame

                return draw_predictions(frame, predictions)
            else:
                result = self._client.infer(frame, model_id=self._model_id)
                predictions = normalize_predictions(result, workflow=False)
                # Observabilidad de confianza (sin filtrado local).
                _log_confianzas(predictions, "cloud.standard")
                _alertar_confianzas_sospechosas(predictions, "cloud.standard")
                # Contar detecciones agrupadas por clase (modo modelo estándar).
                counts_by_label = _count_predictions(predictions)
                self._store_detections(len(predictions), counts_by_label)
                return draw_predictions(frame, predictions)
        except Exception as exc:  # noqa: BLE001
            self._infer_error_count += 1
            # Throttle: loguear el detalle completo en el primer error y luego
            # cada 10 ocurrencias, para no inundar el log si el fallo es
            # persistente (p.ej. sin conectividad).
            if self._infer_error_count == 1 or self._infer_error_count % 10 == 0:
                self._logger.error(
                    "Fallo en la inferencia Cloud [%s: %s] (ocurrencia #%d). "
                    "Devolviendo frame sin anotar.",
                    type(exc).__name__, exc, self._infer_error_count,
                )
            # Reset del cache de detecciones: los errores consecutivos bajan el
            # badge a 0 en lugar de conservar el último cache válido (elimina la
            # fuga de estado / detecciones estancadas en fallos persistentes).
            self._store_detections(0, {})
            return frame

    def get_detections(self) -> dict:
        """
        Retorna el conteo de detecciones del último frame procesado con éxito.

        Protección de antigüedad (staleness — P2): si el timestamp del cache
        supera :data:`STALE_TIMEOUT_SECONDS` (p.ej. el stream se detuvo sin
        lanzar excepción y la inferencia ya no se actualiza), se devuelve
        ``count=0`` y un flag ``stale=True`` en lugar del cache viejo. Esto
        evita tanto el parpadeo (no hay reset prematuro al inicio de
        :meth:`process_frame`) como el estancamiento del badge con conteos
        obsoletos. El umbral (30s) es holgado frente al polling de la UI (~10s),
        así que no dispara falsos "stale" durante la latencia normal de red.

        Returns:
            Dict con la estructura::

                {
                    'count': int,
                    'labels': {str: int},
                    'timestamp': float | None,
                    'stale': bool   # True si el cache superó el timeout
                }
        """
        last = getattr(self, '_last_detections', None)
        if not last:
            return {'count': 0, 'labels': {}, 'timestamp': None, 'stale': False}
        ts = last.get('timestamp')
        # Comprobación de antigüedad: cache stale -> devolver 0 (sin parpadeo
        # prematuro y sin estancamiento indefinido).
        stale = False
        if ts is not None and (time.time() - float(ts)) > STALE_TIMEOUT_SECONDS:
            age = time.time() - float(ts)
            logger.debug(
                "CloudVisionEngine.get_detections: cache stale (edad=%.1fs > "
                "%.1fs). Devolviendo count=0, stale=True.",
                age, STALE_TIMEOUT_SECONDS,
            )
            stale = True
        return {
            'count': 0 if stale else last.get('count', 0),
            'labels': {} if stale else dict(last.get('labels', {})),
            'timestamp': ts,
            'stale': stale,
        }


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
        # Cache de detecciones del último frame procesado con éxito.
        self._last_detections: dict = {
            'count': 0, 'labels': {}, 'timestamp': None
        }
        # Contador de errores de inferencia (para throttle de logs).
        self._infer_error_count: int = 0
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

        Tras cada inferencia exitosa se actualiza el cache de detecciones
        (``self._last_detections``), accesible vía :meth:`get_detections`.

        Degradación *graceful*: si el motor no está disponible (paquete
        ``inference`` ausente, modelo no cargado) o la inferencia falla, se
        devuelve el frame original sin anotar **sin sobreescribir** el último
        cache de detecciones válido.
        """
        if frame is None:
            return frame  # type: ignore[return-value]

        if not self.is_available:
            self._logger.debug(
                "LocalVisionEngine no disponible: devolviendo frame sin anotar."
            )
            return frame

        # NOTA (P2 — anti-parpadeo): NO se resetea el cache de detecciones al
        # inicio (mismo razonamiento que en CloudVisionEngine). El reset
        # prematuro hacía que el badge parpadease a 0 mientras la inferencia
        # estaba en curso; el polling de la UI (~cada 10s) atrapaba ese 0
        # transitorio. Ahora el cache solo se actualiza en dos puntos:
        # (1) éxito de la inferencia (conteo real) y (2) bloque ``except``
        # (señal real de fallo → 0). El estancamiento indefinido se controla
        # vía antigüedad en :meth:`get_detections` (``STALE_TIMEOUT_SECONDS``),
        # no con un reset prematuro.

        try:
            result = self._model.infer(frame)
            predictions = normalize_predictions(result)
            # Observabilidad de confianza (sin filtrado local): el motor local
            # también pasa las predicciones TAL CUAL; solo se registra (DEBUG) y
            # se alerta (WARNING) de confianzas sospechosas.
            _log_confianzas(predictions, "local")
            _alertar_confianzas_sospechosas(predictions, "local")
            # Contar detecciones agrupadas por clase y actualizar el cache.
            counts_by_label = _count_predictions(predictions)
            self._store_detections(len(predictions), counts_by_label)
            return draw_predictions(frame, predictions)
        except Exception as exc:  # noqa: BLE001
            self._infer_error_count += 1
            # Throttle: loguear el detalle completo en el primer error y luego
            # cada 10 ocurrencias, para no inundar el log si el fallo es
            # persistente.
            if self._infer_error_count == 1 or self._infer_error_count % 10 == 0:
                self._logger.error(
                    "Fallo en la inferencia local [%s: %s] (ocurrencia #%d). "
                    "Devolviendo frame sin anotar.",
                    type(exc).__name__, exc, self._infer_error_count,
                )
            # Reset del cache de detecciones: los errores consecutivos bajan el
            # badge a 0 en lugar de conservar el último cache válido (elimina la
            # fuga de estado / detecciones estancadas en fallos persistentes).
            self._store_detections(0, {})
            return frame

    def get_detections(self) -> dict:
        """
        Retorna el conteo de detecciones del último frame procesado con éxito.

        Protección de antigüedad (staleness — P2): igual que en
        :class:`CloudVisionEngine`, si el timestamp del cache supera
        :data:`STALE_TIMEOUT_SECONDS` (p.ej. el stream se detuvo sin lanzar
        excepción), se devuelve ``count=0`` y ``stale=True`` en lugar del cache
        viejo. Esto evita tanto el parpadeo (sin reset prematuro) como el
        estancamiento indefinido del badge.

        Returns:
            Dict con la estructura::

                {
                    'count': int,
                    'labels': {str: int},
                    'timestamp': float | None,
                    'stale': bool   # True si el cache superó el timeout
                }
        """
        last = getattr(self, '_last_detections', None)
        if not last:
            return {'count': 0, 'labels': {}, 'timestamp': None, 'stale': False}
        ts = last.get('timestamp')
        # Comprobación de antigüedad: cache stale -> devolver 0 (sin parpadeo
        # prematuro y sin estancamiento indefinido).
        stale = False
        if ts is not None and (time.time() - float(ts)) > STALE_TIMEOUT_SECONDS:
            age = time.time() - float(ts)
            logger.debug(
                "LocalVisionEngine.get_detections: cache stale (edad=%.1fs > "
                "%.1fs). Devolviendo count=0, stale=True.",
                age, STALE_TIMEOUT_SECONDS,
            )
            stale = True
        return {
            'count': 0 if stale else last.get('count', 0),
            'labels': {} if stale else dict(last.get('labels', {})),
            'timestamp': ts,
            'stale': stale,
        }


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
        workspace: Optional[str] = None,
        workflow_id: Optional[str] = None,
        workflow_image_input: Optional[str] = None,
        workflow_use_cache: Optional[bool] = None,
        use_server_overlay: Optional[bool] = None,
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
            workspace: Workspace de Roboflow (solo cloud; modo workflow).
            workflow_id: ID del workflow (solo cloud; modo workflow).
            workflow_image_input: Nombre del parámetro de entrada de imagen del
                workflow (solo cloud).
            workflow_use_cache: Si activar el caché del workflow (solo cloud).
                **Debe ser un ``bool`` real**, no un string (ver ``_env_bool``).
            use_server_overlay: Si usar el overlay renderizado por el servidor
                (solo cloud). **Debe ser un ``bool`` real**, no un string.
            device: Dispositivo de inferencia ``cpu``/``cuda`` (solo local).
            auto_initialize: Si ``True`` (por defecto), llama a ``initialize()``
                del motor creado. Útil para tests que solo quieren verificar el
                tipo de instancia sin inicializar.

        Note:
            Los parámetros cloud con valor ``None`` se resuelven dentro de
            :class:`CloudVisionEngine` leyendo ``os.environ`` (con sus
            *defaults*). Pasarlos explícitamente permite inyectar credenciales
            desde la base de datos sin depender del estado de ``os.environ``.

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
            # Reenviar TODOS los kwargs de CloudVisionEngine. Los valores
            # ``None`` se resuelven dentro del constructor leyendo ``os.environ``
            # (con sus defaults), por lo que es seguro pasarlos siempre.
            cloud_kwargs: dict = dict(kwargs_common)
            cloud_kwargs["api_url"] = api_url
            cloud_kwargs["workspace"] = workspace
            cloud_kwargs["workflow_id"] = workflow_id
            cloud_kwargs["workflow_image_input"] = workflow_image_input
            cloud_kwargs["workflow_use_cache"] = workflow_use_cache
            cloud_kwargs["use_server_overlay"] = use_server_overlay
            engine: VisionEngine = CloudVisionEngine(**cloud_kwargs)
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
