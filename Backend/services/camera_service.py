"""
Servicio de gestión de cámaras para Argos2.

Proporciona abstracciones para múltiples fuentes de video (USB, IP, ESP32-CAM),
gestión multi-cámara y persistencia de configuración.

Fase 1 — VideoSource ABC + Subclases + CameraManager
"""

import collections
import json
import logging
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

# Intentar importar OpenCV; si no está disponible, las clases lo manejan gracefully
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "OpenCV (cv2) no está disponible. "
        "Las funcionalidades de cámara estarán deshabilitadas."
    )

# Intentar importar requests para ESP32 capture
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.getLogger(__name__).warning(
        "requests no está disponible. "
        "La captura individual de ESP32-CAM estará deshabilitada."
    )

# numpy es dependencia del proyecto (usada por la capa de visión).
import numpy as np  # noqa: E402

# Importar la capa de visión (opcional — degradación graceful si falla).
# Paso #4: arquitectura Strategy + Factory (services/vision_engine.py).
try:
    from services.vision_engine import VisionEngine, VisionEngineFactory
    VISION_AVAILABLE = True
except ImportError:  # pragma: no cover
    VISION_AVAILABLE = False
    VisionEngine = None  # type: ignore[assignment,misc]
    VisionEngineFactory = None  # type: ignore[assignment,misc]
    logging.getLogger(__name__).warning(
        "El módulo de visión (services.vision_engine) no está disponible. "
        "Las funciones de visión de CameraManager estarán deshabilitadas."
    )

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Configuración — Validación de frames antes de la inferencia (ahorro de cuota)
# -----------------------------------------------------------------------------
# Umbral mínimo de luminosidad media (0–255): por debajo se considera que el
# frame está demasiado oscuro para contener detecciones útiles.
LUMINOSIDAD_MIN = 15.0
# Umbral mínimo de desviación estándar de los píxeles: por debajo se considera
# que el frame está congelado/tapado o es un color puro sin información útil
# (frame "plano"). Evita enviar a Roboflow frames sin varianza.
VARIANZA_MIN = 5.0
# Tamaño fijo de downsampling (ancho, alto) al que se reduce el frame ANTES de
# calcular luminosidad/varianza en :meth:`CameraManager._frame_is_valid`.
# Optimización P1: procesar el frame a resolución completa (p.ej. 640x480 =
# ~300k píxeles) por cada frame mataba los FPS. Reducir a 64x64 (~4k píxeles)
# hace el cálculo ~75x más barato manteniendo precisión estadística suficiente
# para detectar oscuridad/congelamiento (la media/std sobre un downsampling
# *nearest-neighbor* son estadísticamente equivalentes para este fin).
# 32x32 también sería válido; 64x64 es la base elegida.
FRAME_DOWNSAMPLE_SIZE = (64, 64)


# =============================================================================
# VideoSource — Abstract Base Class
# =============================================================================

class VideoSource(ABC):
    """Clase base abstracta para todas las fuentes de video."""

    @abstractmethod
    def start(self) -> bool:
        """Inicia la captura de video. Retorna True si tuvo éxito."""
        ...

    @abstractmethod
    def get_frame(self) -> Optional[bytes]:
        """Retorna el último frame como bytes JPEG, o None si no hay disponible."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Detiene la captura y libera recursos."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """True si la captura está activa."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre descriptivo de la fuente."""
        ...

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Tipo de fuente: 'usb', 'ip', 'esp32'."""
        ...


# =============================================================================
# LocalCamera — Webcams USB y laptop
# =============================================================================

class LocalCamera(VideoSource):
    """
    Fuente de video para cámaras locales (USB / integradas).

    Usa un thread dedicado para capturar frames continuamente
    y los almacena en un deque para acceso thread-safe.
    """

    def __init__(
        self,
        camera_index: int = 0,
        name: Optional[str] = None,
        fps: int = 30,
        resolution: tuple = (640, 480),
    ):
        self._name = name or f"Cámara USB {camera_index}"
        self._camera_index = camera_index
        self._fps = fps
        self._resolution = resolution
        self._running = False
        self._cap: Optional[cv2.VideoCapture] = None  # type: ignore[name-defined]
        self._frame_deque: collections.deque = collections.deque(maxlen=2)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._logger = logging.getLogger(f"{__name__}.LocalCamera.{camera_index}")

    # --- Propiedades ---

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_type(self) -> str:
        return "usb"

    # --- Métodos públicos ---

    def start(self) -> bool:
        """Inicia el thread de captura de video."""
        if not CV2_AVAILABLE:
            self._logger.error("OpenCV no está disponible. No se puede iniciar la cámara.")
            return False

        if self._running:
            self._logger.warning("La cámara ya está en ejecución.")
            return True

        try:
            self._cap = cv2.VideoCapture(self._camera_index)
            if not self._cap.isOpened():
                self._logger.error(
                    "No se pudo abrir la cámara índice %s.", self._camera_index
                )
                self._cap.release()
                self._cap = None
                return False

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._resolution[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._resolution[1])
            self._cap.set(cv2.CAP_PROP_FPS, self._fps)

            self._running = True
            self._thread = threading.Thread(
                target=self._capture_loop,
                name=f"LocalCamera-{self._camera_index}",
                daemon=True,
            )
            self._thread.start()
            self._logger.info("Cámara USB índice %s iniciada.", self._camera_index)
            return True

        except Exception as e:
            self._logger.error("Error al iniciar cámara índice %s: %s", self._camera_index, e)
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            return False

    def get_frame(self) -> Optional[bytes]:
        """Retorna el último frame como bytes JPEG."""
        with self._lock:
            if not self._frame_deque:
                return None
            frame = self._frame_deque[-1]
        try:
            success, encoded = cv2.imencode(
                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            if success:
                return encoded.tobytes()
            return None
        except Exception:
            return None

    def stop(self) -> None:
        """Detiene el thread de captura y libera la cámara."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        with self._lock:
            self._frame_deque.clear()

        self._logger.info("Cámara USB índice %s detenida.", self._camera_index)

    # --- Loop interno de captura ---

    def _capture_loop(self) -> None:
        """Loop de captura que se ejecuta en un thread dedicado."""
        frame_interval = 1.0 / self._fps if self._fps > 0 else 1.0 / 30.0

        while self._running:
            try:
                ret, frame = self._cap.read()  # type: ignore[union-attr]
                if ret and frame is not None:
                    with self._lock:
                        self._frame_deque.append(frame)
                else:
                    self._logger.debug("Frame vacío de cámara índice %s.", self._camera_index)
            except Exception as e:
                self._logger.error("Error capturando frame: %s", e)

            time.sleep(frame_interval)

        self._logger.debug("Thread de captura finalizado para índice %s.", self._camera_index)


# =============================================================================
# IPStreamCamera — Cámaras IP (iPhone, etc.)
# =============================================================================

class IPStreamCamera(VideoSource):
    """
    Fuente de video para cámaras IP (stream MJPEG/RTSP).

    Incluye auto-reconexión con backoff exponencial en caso de
    desconexión o fallo de lectura.
    """

    # Tiempos de backoff en segundos: 5, 10, 20, 30 (máximo)
    _BACKOFF_STEPS = [5, 10, 20, 30]

    def __init__(
        self,
        url: str,
        name: Optional[str] = None,
        fps: int = 15,
        reconnect_delay: int = 5,
    ):
        self._name = name or f"Cámara IP ({url.split('//')[-1].split('/')[0]})"
        self._url = url
        self._fps = fps
        self._reconnect_delay = reconnect_delay
        self._running = False
        self._connected = False
        self._cap: Optional[cv2.VideoCapture] = None  # type: ignore[name-defined]
        self._frame_deque: collections.deque = collections.deque(maxlen=2)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._backoff_index = 0
        self._logger = logging.getLogger(f"{__name__}.IPStreamCamera")

    # --- Propiedades ---

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_type(self) -> str:
        return "ip"

    @property
    def url(self) -> str:
        return self._url

    # --- Métodos públicos ---

    def start(self) -> bool:
        """Inicia la conexión al stream IP y el thread de captura."""
        if not CV2_AVAILABLE:
            self._logger.error("OpenCV no está disponible. No se puede iniciar el stream IP.")
            return False

        if self._running:
            self._logger.warning("El stream IP ya está en ejecución.")
            return True

        if not self._connect():
            self._logger.error("No se pudo conectar a %s", self._url)
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"IPStream-{self._name}",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("Stream IP iniciado: %s", self._url)
        return True

    def get_frame(self) -> Optional[bytes]:
        """Retorna el último frame como bytes JPEG. No bloquea."""
        with self._lock:
            if not self._frame_deque:
                return None
            frame = self._frame_deque[-1]
        try:
            success, encoded = cv2.imencode(
                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            if success:
                return encoded.tobytes()
            return None
        except Exception:
            return None

    def stop(self) -> None:
        """Detiene el thread y libera la conexión."""
        self._running = False
        self._connected = False

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None

        self._release_cap()

        with self._lock:
            self._frame_deque.clear()

        self._logger.info("Stream IP detenido: %s", self._url)

    # --- Métodos internos ---

    def _connect(self) -> bool:
        """Intenta abrir la conexión al stream IP."""
        try:
            self._release_cap()
            self._cap = cv2.VideoCapture(self._url)
            if self._cap.isOpened():
                self._connected = True
                self._backoff_index = 0
                self._logger.info("Conectado a %s", self._url)
                return True
            else:
                self._connected = False
                self._cap.release()
                self._cap = None
                return False
        except Exception as e:
            self._logger.error("Error conectando a %s: %s", self._url, e)
            self._connected = False
            return False

    def _release_cap(self) -> None:
        """Libera el VideoCapture si existe."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _get_backoff_delay(self) -> float:
        """Retorna el delay de backoff actual y avanza al siguiente paso."""
        if self._backoff_index < len(self._BACKOFF_STEPS):
            delay = self._BACKOFF_STEPS[self._backoff_index]
        else:
            delay = self._BACKOFF_STEPS[-1]
        self._backoff_index = min(self._backoff_index + 1, len(self._BACKOFF_STEPS) - 1)
        return delay

    def _capture_loop(self) -> None:
        """Loop de captura con auto-reconexión."""
        frame_interval = 1.0 / self._fps if self._fps > 0 else 1.0 / 15.0

        while self._running:
            if not self._connected or self._cap is None:
                self._logger.info(
                    "Intentando reconectar a %s...", self._url
                )
                if self._connect():
                    self._logger.info("Reconexión exitosa a %s", self._url)
                else:
                    delay = self._get_backoff_delay()
                    self._logger.warning(
                        "Reconexión fallida. Reintentando en %ss...", delay
                    )
                    # Esperar interrumpiblemente
                    self._interruptible_sleep(delay)
                    continue

            try:
                ret, frame = self._cap.read()  # type: ignore[union-attr]
                if ret and frame is not None:
                    with self._lock:
                        self._frame_deque.append(frame)
                    # Resetear backoff si tuvimos éxito
                    self._backoff_index = 0
                else:
                    self._logger.warning(
                        "Frame fallido de %s. Marcando como desconectado.", self._url
                    )
                    self._connected = False
                    self._release_cap()
                    delay = self._get_backoff_delay()
                    self._logger.info("Reintentando en %ss...", delay)
                    self._interruptible_sleep(delay)
                    continue
            except Exception as e:
                self._logger.error("Error capturando frame de %s: %s", self._url, e)
                self._connected = False
                self._release_cap()
                delay = self._get_backoff_delay()
                self._interruptible_sleep(delay)
                continue

            time.sleep(frame_interval)

        self._logger.debug("Thread de captura IP finalizado.")

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep que puede ser interrumpido si _running cambia a False."""
        end_time = time.time() + seconds
        while self._running and time.time() < end_time:
            time.sleep(min(0.5, end_time - time.time()))


# =============================================================================
# ESP32Camera — ESP32-CAM
# =============================================================================

class ESP32Camera(VideoSource):
    """
    Fuente de video para ESP32-CAM.

    Soporta stream MJPEG continuo y captura individual vía HTTP.
    Incluye auto-reconexión con backoff exponencial.
    """

    # Tiempos de backoff en segundos: 5, 10, 20, 30 (máximo)
    _BACKOFF_STEPS = [5, 10, 20, 30]

    def __init__(
        self,
        ip: str,
        port: int = 80,
        name: Optional[str] = None,
        stream_path: str = '/stream',
        capture_path: str = '/capture',
    ):
        self._name = name or f"ESP32-CAM ({ip})"
        self._ip = ip
        self._port = port
        self._stream_path = stream_path
        self._capture_path = capture_path
        self._stream_url = f"http://{ip}:{port}{stream_path}"
        self._capture_url = f"http://{ip}:{port}{capture_path}"
        self._running = False
        self._connected = False
        self._cap: Optional[cv2.VideoCapture] = None  # type: ignore[name-defined]
        self._frame_deque: collections.deque = collections.deque(maxlen=2)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._backoff_index = 0
        self._logger = logging.getLogger(f"{__name__}.ESP32Camera")

    # --- Propiedades ---

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def name(self) -> str:
        return self._name

    @property
    def source_type(self) -> str:
        return "esp32"

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def port(self) -> int:
        return self._port

    @property
    def stream_url(self) -> str:
        return self._stream_url

    @property
    def capture_url(self) -> str:
        return self._capture_url

    # --- Métodos públicos ---

    def start(self) -> bool:
        """Inicia la conexión al stream MJPEG del ESP32-CAM."""
        if not CV2_AVAILABLE:
            self._logger.error("OpenCV no está disponible. No se puede iniciar ESP32-CAM.")
            return False

        if self._running:
            self._logger.warning("ESP32-CAM ya está en ejecución.")
            return True

        if not self._connect():
            self._logger.error("No se pudo conectar a ESP32-CAM en %s", self._stream_url)
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"ESP32-{self._name}",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("ESP32-CAM iniciado: %s", self._stream_url)
        return True

    def get_frame(self) -> Optional[bytes]:
        """Retorna el último frame como bytes JPEG. No bloquea."""
        with self._lock:
            if not self._frame_deque:
                return None
            frame = self._frame_deque[-1]
        try:
            success, encoded = cv2.imencode(
                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            if success:
                return encoded.tobytes()
            return None
        except Exception:
            return None

    def stop(self) -> None:
        """Detiene el thread y libera la conexión."""
        self._running = False
        self._connected = False

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None

        self._release_cap()

        with self._lock:
            self._frame_deque.clear()

        self._logger.info("ESP32-CAM detenido: %s", self._stream_url)

    def capture_single(self) -> Optional[bytes]:
        """
        Hace un request HTTP GET a la URL de captura del ESP32-CAM
        y retorna los bytes JPEG de la imagen.
        """
        if not REQUESTS_AVAILABLE:
            self._logger.error("requests no está disponible. No se puede capturar.")
            return None

        try:
            response = requests.get(self._capture_url, timeout=10)
            if response.status_code == 200:
                content_type = response.headers.get('Content-Type', '')
                if 'image' in content_type or 'jpeg' in content_type:
                    return response.content
                # Si no indica Content-Type de imagen, igual intentar retornar
                return response.content
            else:
                self._logger.warning(
                    "Captura ESP32 fallida. Status: %s", response.status_code
                )
                return None
        except requests.exceptions.Timeout:
            self._logger.error("Timeout al capturar de ESP32-CAM: %s", self._capture_url)
            return None
        except requests.exceptions.ConnectionError:
            self._logger.error(
                "Error de conexión al capturar de ESP32-CAM: %s", self._capture_url
            )
            return None
        except Exception as e:
            self._logger.error("Error inesperado en capture_single: %s", e)
            return None

    # --- Métodos internos ---

    def _connect(self) -> bool:
        """Intenta abrir la conexión al stream MJPEG del ESP32-CAM."""
        try:
            self._release_cap()
            self._cap = cv2.VideoCapture(self._stream_url)
            if self._cap.isOpened():
                self._connected = True
                self._backoff_index = 0
                self._logger.info("Conectado a ESP32-CAM: %s", self._stream_url)
                return True
            else:
                self._connected = False
                self._cap.release()
                self._cap = None
                return False
        except Exception as e:
            self._logger.error("Error conectando a ESP32-CAM %s: %s", self._stream_url, e)
            self._connected = False
            return False

    def _release_cap(self) -> None:
        """Libera el VideoCapture si existe."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _get_backoff_delay(self) -> float:
        """Retorna el delay de backoff actual y avanza al siguiente paso."""
        if self._backoff_index < len(self._BACKOFF_STEPS):
            delay = self._BACKOFF_STEPS[self._backoff_index]
        else:
            delay = self._BACKOFF_STEPS[-1]
        self._backoff_index = min(self._backoff_index + 1, len(self._BACKOFF_STEPS) - 1)
        return delay

    def _capture_loop(self) -> None:
        """Loop de captura con auto-reconexión."""
        while self._running:
            if not self._connected or self._cap is None:
                self._logger.info(
                    "Intentando reconectar a ESP32-CAM %s...", self._stream_url
                )
                if self._connect():
                    self._logger.info("Reconexión exitosa a ESP32-CAM.")
                else:
                    delay = self._get_backoff_delay()
                    self._logger.warning(
                        "Reconexión ESP32 fallida. Reintentando en %ss...", delay
                    )
                    self._interruptible_sleep(delay)
                    continue

            try:
                ret, frame = self._cap.read()  # type: ignore[union-attr]
                if ret and frame is not None:
                    with self._lock:
                        self._frame_deque.append(frame)
                    self._backoff_index = 0
                else:
                    self._logger.warning(
                        "Frame fallido de ESP32-CAM %s. Desconectado.", self._stream_url
                    )
                    self._connected = False
                    self._release_cap()
                    delay = self._get_backoff_delay()
                    self._logger.info("Reintentando en %ss...", delay)
                    self._interruptible_sleep(delay)
                    continue
            except Exception as e:
                self._logger.error("Error capturando frame de ESP32: %s", e)
                self._connected = False
                self._release_cap()
                delay = self._get_backoff_delay()
                self._interruptible_sleep(delay)
                continue

            time.sleep(1.0 / 15)  # ~15 fps para ESP32-CAM

        self._logger.debug("Thread de captura ESP32 finalizado.")

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep que puede ser interrumpido si _running cambia a False."""
        end_time = time.time() + seconds
        while self._running and time.time() < end_time:
            time.sleep(min(0.5, end_time - time.time()))


# =============================================================================
# CameraManager — Gestiona múltiples cámaras (Singleton)
# =============================================================================

class CameraManager:
    """
    Gestiona múltiples fuentes de video.

    Implementa el patrón Singleton para garantizar una única instancia global.
    Thread-safe mediante locks en todas las operaciones sobre el diccionario
    de cámaras.
    """

    _instance: Optional['CameraManager'] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> 'CameraManager':
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._cameras: Dict[str, VideoSource] = {}
        # NUEVO (Paso #4): motores de visión activos por cámara.
        # Restricción: una cámara = un motor activo.
        self._vision_engines: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._logger = logging.getLogger(f"{__name__}.CameraManager")
        self._initialized = True

    @classmethod
    def reset_instance(cls) -> None:
        """
        Resetea el singleton (útil para testing).
        En producción no debe llamarse.
        """
        with cls._init_lock:
            if cls._instance is not None:
                cls._instance.shutdown_all()
            cls._instance = None

    # --- Descubrimiento ---

    def discover_local_cameras(self, max_index: int = 5) -> List[dict]:
        """
        Descubre cámaras locales probando índices del 0 al max_index - 1.

        Retorna una lista de diccionarios con información de cada cámara
        encontrada: id, index, name, type, status.
        """
        discovered: List[dict] = []

        if not CV2_AVAILABLE:
            self._logger.warning("OpenCV no disponible. No se pueden descubrir cámaras.")
            return discovered

        for i in range(max_index):
            try:
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    camera_id = str(uuid.uuid4())
                    discovered.append({
                        "id": camera_id,
                        "index": i,
                        "name": f"Cámara USB {i}",
                        "type": "usb",
                        "status": "available",
                    })
                    cap.release()
                    self._logger.debug("Cámara encontrada en índice %s", i)
                else:
                    cap.release()
            except Exception as e:
                self._logger.debug("Error probando índice %s: %s", i, e)

        self._logger.info("Descubrimiento completado: %s cámara(s) encontrada(s).", len(discovered))
        return discovered

    # --- Gestión de cámaras ---

    def add_camera(self, source: VideoSource) -> str:
        """
        Agrega una fuente de video al manager, la inicia automáticamente,
        y retorna el ID asignado.
        """
        camera_id = str(uuid.uuid4())

        with self._lock:
            self._cameras[camera_id] = source

        # Iniciar la cámara (fuera del lock para evitar deadlock)
        try:
            source.start()
            self._logger.info(
                "Cámara agregada y iniciada: %s (ID: %s)", source.name, camera_id
            )
        except Exception as e:
            self._logger.error(
                "Error al iniciar cámara %s (ID: %s): %s", source.name, camera_id, e
            )

        return camera_id

    def remove_camera(self, camera_id: str) -> bool:
        """Detiene y elimina una cámara del manager."""
        with self._lock:
            source = self._cameras.pop(camera_id, None)

        if source is None:
            self._logger.warning("Cámara ID %s no encontrada para eliminar.", camera_id)
            return False

        try:
            source.stop()
        except Exception as e:
            self._logger.error("Error al detener cámara %s: %s", camera_id, e)

        self._logger.info("Cámara eliminada: %s (ID: %s)", source.name, camera_id)
        return True

    def get_camera(self, camera_id: str) -> Optional[VideoSource]:
        """Retorna la fuente de video correspondiente al ID, o None."""
        with self._lock:
            return self._cameras.get(camera_id)

    def list_cameras(self) -> List[dict]:
        """
        Retorna información de todas las cámaras registradas.

        Cada entrada contiene: id, name, type, is_running, source_info.
        """
        result: List[dict] = []

        with self._lock:
            for cam_id, source in self._cameras.items():
                info: dict = {
                    "id": cam_id,
                    "name": source.name,
                    "type": source.source_type,
                    "is_running": source.is_running,
                    "source_info": self._get_source_info(source),
                }
                result.append(info)

        return result

    def get_frame(self, camera_id: str) -> Optional[bytes]:
        """Delega la obtención de frame al VideoSource correspondiente."""
        source = self.get_camera(camera_id)
        if source is None:
            self._logger.warning("Cámara ID %s no encontrada para get_frame.", camera_id)
            return None
        return source.get_frame()

    def start_camera(self, camera_id: str) -> bool:
        """Inicia una cámara ya registrada."""
        source = self.get_camera(camera_id)
        if source is None:
            self._logger.warning("Cámara ID %s no encontrada para iniciar.", camera_id)
            return False
        try:
            result = source.start()
            if result:
                self._logger.info("Cámara %s iniciada.", camera_id)
            return result
        except Exception as e:
            self._logger.error("Error al iniciar cámara %s: %s", camera_id, e)
            return False

    def stop_camera(self, camera_id: str) -> bool:
        """Detiene una cámara sin eliminarla del manager."""
        source = self.get_camera(camera_id)
        if source is None:
            self._logger.warning("Cámara ID %s no encontrada para detener.", camera_id)
            return False
        try:
            source.stop()
            self._logger.info("Cámara %s detenida.", camera_id)
            return True
        except Exception as e:
            self._logger.error("Error al detener cámara %s: %s", camera_id, e)
            return False

    def restart_camera(self, camera_id: str) -> bool:
        """Detiene y vuelve a iniciar una cámara."""
        source = self.get_camera(camera_id)
        if source is None:
            self._logger.warning("Cámara ID %s no encontrada para reiniciar.", camera_id)
            return False
        try:
            source.stop()
            time.sleep(0.5)  # Pequeña pausa antes de reiniciar
            result = source.start()
            if result:
                self._logger.info("Cámara %s reiniciada.", camera_id)
            return result
        except Exception as e:
            self._logger.error("Error al reiniciar cámara %s: %s", camera_id, e)
            return False

    def shutdown_all(self) -> None:
        """Detiene todas las cámaras registradas. Llamar al cerrar la app."""
        self._logger.info("Deteniendo todas las cámaras...")

        with self._lock:
            camera_ids = list(self._cameras.keys())
            vision_ids = list(self._vision_engines.keys())

        # NUEVO (Paso #4): detener los motores de visión antes de las cámaras.
        for cam_id in vision_ids:
            self.disable_vision(cam_id)

        for cam_id in camera_ids:
            self.remove_camera(cam_id)

        self._logger.info("Todas las cámaras detenidas.")

    # -----------------------------------------------------------------------
    # Visión Computacional (Paso #4 — Zona C del plan)
    # -----------------------------------------------------------------------

    def _resolve_cloud_credentials(self) -> dict:
        """
        Lee las credenciales de Roboflow desde la BD (fuente de verdad) y las
        devuelve como kwargs listos para ``VisionEngineFactory.create()``.

        Se pasan **todos** los campos cloud de forma explícita —incluidos los
        booleanos, convertidos a ``bool`` real— para que el motor cloud no
        dependa del estado (posiblemente vacío o desactualizado) de
        ``os.environ``. Esto es lo que corrige el bug del modo cloud activado
        desde el dashboard: antes el motor solo leía ``os.environ`` y degradaba
        silenciosamente.

        Nota sobre ``os.environ``: **no** se llama a ``sync_settings_to_env()``
        aquí. Esa sincronización ya ocurre al actualizar los settings (ver
        ``update_vision_settings()``) y llamarla de nuevo aquí provocaría un
        *side-effect* global que contaminaría ``os.environ`` (rompiendo el
        aislamiento de los tests y pudiendo afectar a otros motores). Como
        pasamos las credenciales explícitamente, no se necesita.

        Si la BD no está disponible (p. ej. entorno de tests sin inicializar,
        tabla ``settings`` ausente), se devuelve un dict vacío y el motor se
        creará leyendo ``os.environ`` (comportamiento previo, degradación
        graceful).

        Returns:
            Dict con TODAS las claves cloud (``api_key``, ``api_url``,
            ``model_id``, ``workspace``, ``workflow_id``,
            ``workflow_image_input``, ``workflow_use_cache``,
            ``use_server_overlay``). Los valores vacíos se normalizan a
            ``None``; los booleanos se convierten a ``bool`` real (o ``None``
            si están vacíos) para que el constructor no aplique el parsing
            erróneo ``bool('false') == True`` de ``_env_bool`` con strings.
        """

        def _to_bool(val) -> Optional[bool]:
            """Convierte un valor string de la BD a ``bool`` (``None`` vacío)."""
            if val is None or str(val).strip() == '':
                return None
            return str(val).strip().lower() in (
                '1', 'true', 'yes', 'on', 'si', 'sí'
            )

        try:
            # Import local para evitar dependencias circulares en tiempo de
            # carga del módulo (settings_service no depende de camera_service,
            # pero mantenemos el patrón defensivo usado en routes/settings.py).
            from services.settings_service import get_vision_settings
            vsettings = get_vision_settings()
        except Exception as exc:  # noqa: BLE001
            self._logger.warning(
                "No se pudieron leer las credenciales de visión desde la BD "
                "(%s). El motor cloud se creará usando os.environ como "
                "fallback.", exc,
            )
            return {}

        return {
            'api_key': vsettings.get('roboflow_api_key') or None,
            'api_url': vsettings.get('roboflow_api_url') or None,
            'model_id': vsettings.get('roboflow_model_id') or None,
            'workspace': vsettings.get('roboflow_workspace') or None,
            'workflow_id': vsettings.get('roboflow_workflow_id') or None,
            'workflow_image_input': (
                vsettings.get('roboflow_workflow_image_input') or None
            ),
            'workflow_use_cache': _to_bool(
                vsettings.get('roboflow_workflow_use_cache')
            ),
            'use_server_overlay': _to_bool(
                vsettings.get('roboflow_use_server_overlay')
            ),
        }

    def enable_vision(self, camera_id: str, mode: str = 'cloud') -> bool:
        """
        Activa el motor de visión para una cámara en el modo especificado.

        Si ya existe un motor activo para la cámara, se detiene y reemplaza
        (restricción: una cámara = un motor activo).

        Args:
            camera_id: ID de la cámara registrada.
            mode: Modo de visión: ``'cloud'``, ``'local'`` o ``'off'``/``'none'``.

        Returns:
            ``True`` si la operación se completó (incluso si el modo es
            ``'off'``). ``False`` si la cámara no existe o la capa de visión
            no está disponible.
        """
        if not VISION_AVAILABLE:
            self._logger.error(
                "La capa de visión no está disponible. No se puede activar "
                "la visión para la cámara %s.", camera_id
            )
            return False

        source = self.get_camera(camera_id)
        if source is None:
            self._logger.warning(
                "Cámara ID %s no encontrada para enable_vision.", camera_id
            )
            return False

        # Detener el motor previo si existe.
        self.disable_vision(camera_id)

        # Inyectar las credenciales de Roboflow desde la BD (fuente de verdad).
        # Antes el motor cloud solo leía os.environ, que podía estar vacío o
        # desactualizado, causando degradación silenciosa (available=False) y
        # frames sin detecciones. Ver bug del modo cloud activado desde el
        # dashboard. Para el modo 'local' los kwargs cloud simplemente se
        # ignoran (la factory no los reenvía a LocalVisionEngine).
        cloud_kwargs = self._resolve_cloud_credentials()
        self._logger.info(
            "enable_vision(%s): cloud kwargs - workspace=%s, workflow_id=%s, model_id=%s, api_key_set=%s",
            camera_id,
            cloud_kwargs.get('workspace'),
            cloud_kwargs.get('workflow_id'),
            cloud_kwargs.get('model_id'),
            bool(cloud_kwargs.get('api_key')),
        )

        # create() inicializa el motor y degrada gracefully ante fallos.
        engine = VisionEngineFactory.create(
            mode, **cloud_kwargs
        )  # type: ignore[union-attr]
        if engine is None:
            # mode 'off' / 'none' — visión desactivada explícitamente.
            self._logger.info(
                "Visión desactivada para cámara %s (modo off).", camera_id
            )
            return True

        with self._lock:
            self._vision_engines[camera_id] = engine

        self._logger.info(
            "Visión activada para cámara %s en modo '%s' (disponible=%s).",
            camera_id, engine.mode, engine.is_available,
        )
        return True

    def disable_vision(self, camera_id: str) -> bool:
        """
        Desactiva y libera el motor de visión de una cámara.

        Es idempotente: no hace nada si no hay motor activo.

        Returns:
            ``True`` siempre.
        """
        with self._lock:
            engine = self._vision_engines.pop(camera_id, None)

        if engine is not None:
            try:
                engine.shutdown()
            except Exception as exc:  # noqa: BLE001
                self._logger.error(
                    "Error al detener motor de visión de cámara %s: %s",
                    camera_id, exc,
                )
            self._logger.info(
                "Visión desactivada para cámara %s.", camera_id
            )
        return True

    def get_annotated_frame(self, camera_id: str) -> Optional[bytes]:
        """
        Retorna el último frame de la cámara anotado por el motor de visión,
        como bytes JPEG.

        Si no hay motor de visión activo/disponible para la cámara, retorna el
        frame crudo (sin anotar) como fallback.

        Returns:
            Bytes JPEG del frame (anotado o crudo), o ``None`` si no hay frame.
        """
        with self._lock:
            engine = self._vision_engines.get(camera_id)

        source = self.get_camera(camera_id)
        if source is None:
            return None

        # Si hay motor activo y disponible, anotar el frame crudo (np.ndarray).
        if engine is not None and engine.is_available:
            raw_frame = self._get_raw_ndframe(source)
            if raw_frame is not None:
                # ----------------------------------------------------------
                # PRE-PROCESAMIENTO DE LUMINOSIDAD/VARIANZA (ahorro de cuota):
                # antes de enviar el frame al motor de visión (y por tanto a
                # Roboflow), se valida que contenga información útil. Si el
                # frame está oscuro, congelado/tapado o es color puro, NO se
                # envía a inferencia y se devuelve el frame crudo re-codificado
                # a JPEG sin anotaciones (el badge mostrará 0 gracias al reset
                # de process_frame() o porque nunca se llama).
                # ----------------------------------------------------------
                valido, razon = self._frame_is_valid(raw_frame)
                if not valido:
                    self._logger.debug(
                        "Frame de cámara %s descartado antes de la inferencia "
                        "(razón=%s): no se envía a Roboflow (ahorro de cuota).",
                        camera_id, razon,
                    )
                    encoded_raw = self._encode_jpeg(raw_frame)
                    if encoded_raw is not None:
                        return encoded_raw
                    # No se pudo re-codificar el frame crudo: fallback general.
                    return source.get_frame()

                try:
                    annotated = engine.process_frame(raw_frame)
                    encoded = self._encode_jpeg(annotated)
                    if encoded is not None:
                        return encoded
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning(
                        "Error anotando frame de cámara %s: %s. "
                        "Fallback a frame crudo.", camera_id, exc,
                    )

        # Fallback: frame crudo (bytes JPEG) sin anotar.
        return source.get_frame()

    def get_vision_status(self, camera_id: str) -> dict:
        """
        Retorna el estado del motor de visión de una cámara.

        Returns:
            Dict con claves ``active`` (bool), ``mode`` (str),
            ``available`` (bool) y ``detections`` (dict). ``detections``
            contiene el conteo de objetos del último frame procesado::

                {
                    'active': bool,
                    'mode': str,
                    'available': bool,
                    'detections': {
                        'count': int,
                        'labels': {str: int},
                        'timestamp': float | None
                    }
                }

            Si no hay motor activo, retorna ``{'active': False, 'mode':
            'none', 'available': False, 'detections': {...zeros...}}``.
        """
        with self._lock:
            engine = self._vision_engines.get(camera_id)

        if engine is None:
            return {
                'active': False,
                'mode': 'none',
                'available': False,
                'detections': {'count': 0, 'labels': {}, 'timestamp': None},
            }

        # Obtener las detecciones del motor de forma defensiva.
        try:
            detections = engine.get_detections()  # type: ignore[union-attr]
        except Exception:
            detections = {'count': 0, 'labels': {}, 'timestamp': None}

        # LOG TEMPORAL de diagnóstico: confirma que el backend envía las
        # detecciones a la UI. Permite aislar si el problema está en el backend
        # (cache de detecciones vacío) o en el frontend (badge/cache navegador).
        self._logger.info(
            "get_vision_status(%s): detections=%s", camera_id, detections
        )

        return {
            'active': True,
            'mode': engine.mode,
            'available': engine.is_available,
            'detections': detections,
        }

    def reload_vision_engines(self) -> List[str]:
        """
        Recrea todos los motores de visión activos para que tomen la
        configuración actualizada de ``os.environ``.

        Para cada cámara con visión activa, captura su modo actual,
        desactiva el motor (libera recursos) y lo vuelve a activar en el
        mismo modo. El nuevo motor se instancia leyendo de ``os.environ``,
        por lo que si los settings se actualizaron antes de llamar este
        método, el motor usará los valores nuevos.

        Pensado para llamarse tras un ``PUT /api/settings/vision``.

        Returns:
            List[str]: IDs de las cámaras cuyos motores fueron recargados.
        """
        with self._lock:
            active_cam_ids = list(self._vision_engines.keys())

        reloaded: List[str] = []
        for cam_id in active_cam_ids:
            with self._lock:
                engine = self._vision_engines.get(cam_id)
            mode = engine.mode if engine is not None else 'cloud'
            self.disable_vision(cam_id)
            self.enable_vision(cam_id, mode)
            reloaded.append(cam_id)
            self._logger.info(
                "Motor de visión recargado para cámara %s (modo=%s).",
                cam_id, mode,
            )

        if reloaded:
            self._logger.info(
                "Recarga de motores completada: %d cámara(s).", len(reloaded)
            )
        return reloaded

    @staticmethod
    def _get_raw_ndframe(source: VideoSource) -> Optional[np.ndarray]:
        """
        Obtiene el último frame crudo como ``np.ndarray`` desde el deque
        interno del ``VideoSource`` (sin codificar a JPEG).

        Funciona para todas las subclases de ``VideoSource`` (todas exponen
        ``_frame_deque`` protegido por ``_lock``).
        """
        frame_deque = getattr(source, '_frame_deque', None)
        if frame_deque is None or len(frame_deque) == 0:
            return None
        lock = getattr(source, '_lock', None)
        try:
            if lock is not None:
                with lock:
                    return frame_deque[-1]
            return frame_deque[-1]
        except Exception:
            return None

    @staticmethod
    def _encode_jpeg(frame: Optional[np.ndarray], quality: int = 80) -> Optional[bytes]:
        """Codifica un ``np.ndarray`` (BGR) a bytes JPEG."""
        if not CV2_AVAILABLE or frame is None:
            return None
        try:
            success, encoded = cv2.imencode(
                '.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            return encoded.tobytes() if success else None
        except Exception:
            return None

    @staticmethod
    def _frame_is_valid(frame: Optional[np.ndarray]) -> Tuple[bool, str]:
        """
        Valida un frame antes de enviarlo al motor de visión.

        Comprueba que el frame no esté vacío y tenga suficiente luminosidad y
        varianza para contener información útil. El objetivo es **no
        desperdiciar cuota de Roboflow** enviando frames negros, congelados,
        tapados o de color puro.

        Optimización de rendimiento (P1): el cálculo de luminosidad/varianza se
        realiza sobre una versión **muy reducida** del frame
        (:data:`FRAME_DOWNSAMPLE_SIZE`, p.ej. 64x64), no sobre la resolución
        completa. Esto preserva los FPS: la media/desviación estándar sobre un
        downsampling *nearest-neighbor* son estadísticamente equivalentes para
        detectar oscuridad/congelamiento, pero procesar ~4k píxeles en lugar de
        ~300k es órdenes de magnitud más barato. Los umbrales
        (:data:`LUMINOSIDAD_MIN`, :data:`VARIANZA_MIN`) no cambian.

        Técnicas de downsampling:

        - Si ``cv2`` está disponible: ``cv2.resize`` con
          ``cv2.INTER_NEAREST`` (la interpolación más barata: copia píxeles sin
          remuestreo). Después se convierte a gris y se calcula media/std.
        - Si ``cv2`` NO está disponible (degradación graceful): se usa
          *slicing/striding* con NumPy sobre el frame original
          (``frame[::N, ::N]``) como aproximación barata, con ``N`` calculado
          dinámicamente para acercarse a ~64x64. No se usan funciones costosas.

        Criterios:

        - Frame ``None`` o vacío → ``(False, "frame_vacio")``.
        - Luminosidad media < :data:`LUMINOSIDAD_MIN` →
          ``(False, "luminosidad_baja")``.
        - Desviación estándar (varianza) < :data:`VARIANZA_MIN` →
          ``(False, "varianza_baja")``.
        - En caso contrario → ``(True, "ok")`` (o ``(True, "sin_cv2")`` si el
          análisis no fue posible, para no bloquear el stream MJPEG).

        Args:
            frame: Frame crudo como ``np.ndarray`` (H, W, 3) en formato BGR.

        Returns:
            Tupla ``(valido, razon)``.
        """
        # Frame nulo o sin contenido.
        if frame is None:
            return (False, "frame_vacio")
        try:
            if frame.size == 0:
                return (False, "frame_vacio")
        except AttributeError:
            return (False, "frame_vacio")

        # Tamaño original para auditoría de rendimiento (log DEBUG).
        try:
            orig_shape = tuple(frame.shape[:2])  # (H, W)
        except AttributeError:
            orig_shape = None

        if CV2_AVAILABLE:
            try:
                # ----------------------------------------------------------
                # DOWNSAMPLING P1 (preservación de FPS): se reduce el frame a
                # ``FRAME_DOWNSAMPLE_SIZE`` (64x64) usando ``cv2.INTER_NEAREST``,
                # la interpolación más barata (sin remuestreo: solo copia de
                # píxeles). Reducir ~300k píxeles (640x480) a ~4k (64x64) hace
                # el cálculo ~75x más barato. La media/std sobre el
                # downsampling nearest son estadísticamente equivalentes para
                # detectar oscuridad/congelamiento (umbrales sin cambio).
                # ----------------------------------------------------------
                small = cv2.resize(
                    frame,
                    FRAME_DOWNSAMPLE_SIZE,
                    interpolation=cv2.INTER_NEAREST,
                )
                # ``cv2.cvtColor`` devuelve un MatLike; se convierte a ndarray
                # de float64 explícitamente para tipar correctamente y para
                # estabilidad numérica al calcular media/desviación. Se hace
                # sobre la versión reducida, NO sobre el frame original.
                gray = np.asarray(
                    cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), dtype=np.float64
                )
                luminosidad = float(gray.mean())
                varianza = float(gray.std())
                logger.debug(
                    "_frame_is_valid: downsampling cv2 %s -> %s "
                    "(píxeles: %d -> %d).",
                    orig_shape,
                    FRAME_DOWNSAMPLE_SIZE,
                    (orig_shape[0] * orig_shape[1]) if orig_shape else -1,
                    FRAME_DOWNSAMPLE_SIZE[0] * FRAME_DOWNSAMPLE_SIZE[1],
                )
            except Exception:
                # cv2 falló inesperadamente: no bloquear el flujo.
                return (True, "ok")
        else:
            # ----------------------------------------------------------
            # Degradación graceful sin cv2: aproximación barata con NumPy
            # usando slicing/striding (``frame[::N, ::N]``), que es O(1) en la
            # práctica (vista del array, no copia hasta el cálculo final). El
            # paso ``N`` se calcula dinámicamente para acercarse a ~64 píxeles
            # en el lado mayor, evitando procesar el frame completo.
            # ----------------------------------------------------------
            try:
                h, w = frame.shape[:2]
                n = max(1, max(h, w) // 64)
                small = frame[::n, ::n]
                small_f = np.asarray(small, dtype=np.float64)
                luminosidad = float(small_f.mean())
                varianza = float(small_f.std())
                logger.debug(
                    "_frame_is_valid: downsampling numpy striding %s -> %s "
                    "(paso N=%d) [cv2 no disponible].",
                    orig_shape,
                    tuple(small.shape[:2]),
                    n,
                )
            except Exception:
                # No se pudo analizar el frame: no bloquear el flujo de visión.
                return (True, "sin_cv2")

        if luminosidad < LUMINOSIDAD_MIN:
            return (False, "luminosidad_baja")
        if varianza < VARIANZA_MIN:
            return (False, "varianza_baja")
        return (True, "ok")

    # --- Métodos internos ---

    @staticmethod
    def _get_source_info(source: VideoSource) -> dict:
        """Extrae información adicional específica del tipo de fuente."""
        info: dict = {}

        if isinstance(source, LocalCamera):
            info["camera_index"] = source._camera_index
            info["fps"] = source._fps
            info["resolution"] = source._resolution
        elif isinstance(source, IPStreamCamera):
            info["url"] = source.url
            info["fps"] = source._fps
        elif isinstance(source, ESP32Camera):
            info["ip"] = source.ip
            info["port"] = source.port
            info["stream_url"] = source.stream_url
            info["capture_url"] = source.capture_url

        return info


# =============================================================================
# CamerasConfig — Persistencia de configuración en JSON
# =============================================================================

class CamerasConfig:
    """
    Lee y escribe la configuración de cámaras en un archivo JSON.

    Archivo por defecto: Backend/cameras_config.json
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # Ubicación por defecto relativa a este archivo
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(base_dir, "cameras_config.json")
        self._config_path = config_path
        self._lock = threading.Lock()
        self._logger = logging.getLogger(f"{__name__}.CamerasConfig")

    def load(self) -> List[dict]:
        """
        Carga la configuración de cámaras desde el archivo JSON.

        Retorna una lista de diccionarios con la configuración de cada cámara.
        Si el archivo no existe, retorna una lista vacía.
        """
        with self._lock:
            if not os.path.exists(self._config_path):
                self._logger.info(
                    "Archivo de configuración no encontrado: %s", self._config_path
                )
                return []

            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                cameras = data.get("cameras", [])
                self._logger.info(
                    "Configuración cargada: %s cámara(s) desde %s",
                    len(cameras),
                    self._config_path,
                )
                return cameras
            except json.JSONDecodeError as e:
                self._logger.error(
                    "Error parseando JSON de configuración: %s", e
                )
                return []
            except Exception as e:
                self._logger.error(
                    "Error cargando configuración: %s", e
                )
                return []

    def save(self, cameras: List[dict]) -> None:
        """
        Guarda la lista completa de configuraciones de cámaras en el archivo JSON.
        """
        with self._lock:
            try:
                data = {"cameras": cameras}
                os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
                with open(self._config_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                self._logger.info(
                    "Configuración guardada: %s cámara(s) en %s",
                    len(cameras),
                    self._config_path,
                )
            except Exception as e:
                self._logger.error("Error guardando configuración: %s", e)

    def add_camera(self, config: dict) -> None:
        """
        Agrega una cámara a la configuración existente y guarda.
        """
        cameras = self.load()
        cameras.append(config)
        self.save(cameras)
        self._logger.info("Cámara agregada a configuración: %s", config.get("name", "sin nombre"))

    def remove_camera(self, camera_id: str) -> None:
        """
        Elimina una cámara de la configuración por su ID y guarda.
        """
        cameras = self.load()
        original_len = len(cameras)
        cameras = [c for c in cameras if c.get("id") != camera_id]
        if len(cameras) < original_len:
            self.save(cameras)
            self._logger.info("Cámara %s eliminada de configuración.", camera_id)
        else:
            self._logger.warning(
                "Cámara %s no encontrada en configuración para eliminar.", camera_id
            )


# =============================================================================
# Función de fábrica
# =============================================================================

def create_camera_from_config(config: dict) -> VideoSource:
    """
    Crea la subclase de VideoSource correcta a partir de un diccionario
    de configuración.

    Parámetros esperados en config:
        - type: "usb" | "ip" | "esp32"
        - Para USB: camera_index (int), name (str), fps (int), resolution (tuple)
        - Para IP: url (str), name (str), fps (int)
        - Para ESP32: ip (str), port (int), name (str), stream_path (str), capture_path (str)
    """
    camera_type = config.get("type", "").lower()
    log = logging.getLogger(f"{__name__}.factory")

    if camera_type == "usb":
        return LocalCamera(
            camera_index=config.get("camera_index", 0),
            name=config.get("name"),
            fps=config.get("fps", 30),
            resolution=tuple(config.get("resolution", [640, 480])),
        )
    elif camera_type == "ip":
        url = config.get("url")
        if not url:
            raise ValueError("La configuración de cámara IP debe incluir 'url'.")
        return IPStreamCamera(
            url=url,
            name=config.get("name"),
            fps=config.get("fps", 15),
            reconnect_delay=config.get("reconnect_delay", 5),
        )
    elif camera_type == "esp32":
        ip = config.get("ip")
        if not ip:
            raise ValueError("La configuración de ESP32-CAM debe incluir 'ip'.")
        return ESP32Camera(
            ip=ip,
            port=config.get("port", 80),
            name=config.get("name"),
            stream_path=config.get("stream_path", "/stream"),
            capture_path=config.get("capture_path", "/capture"),
        )
    else:
        raise ValueError(
            f"Tipo de cámara no reconocido: '{camera_type}'. "
            f"Tipos válidos: 'usb', 'ip', 'esp32'."
        )
