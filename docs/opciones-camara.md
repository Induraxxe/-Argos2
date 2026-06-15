# Opciones de Implementación de Cámara para Video en Tiempo Real — Argos2

> **Documento técnico** — Análisis de las 4 opciones de fuentes de video para las funcionalidades de visión computacional del proyecto Argos2.  
> **Fecha:** 2026-06-01  
> **Estado:** Borrador para revisión

---

## Tabla de Contenidos

1. [Contexto del Proyecto](#contexto-del-proyecto)
2. [Opción 1 — Cámaras de iPhone](#opción-1--cámaras-de-iphone)
3. [Opción 2 — Cámaras Web de Laptop](#opción-2--cámaras-web-de-laptop)
4. [Opción 3 — Cámaras Web de Escritorio - USB](#opción-3--cámaras-web-de-escritorio---usb)
5. [Opción 4 — Módulos ESP32-CAM](#opción-4--módulos-esp32-cam)
6. [Tabla Comparativa](#tabla-comparativa)
7. [Recomendación General](#recomendación-general)

---

## Contexto del Proyecto

Argos2 es un sistema de visión computacional con la siguiente arquitectura:

- **Backend:** Flask (Python) con endpoints de visión en [`Backend/routes/vision.py`](Backend/routes/vision.py), servicios en `Backend/services/`
- **Frontend:** HTML/JS/CSS con módulo de visión en [`Frontend/js/vision.js`](Frontend/js/vision.js)
- **Procesamiento:** OpenCV para procesamiento de imágenes
- **Infraestructura existente:** Carpetas `Backend/processed/` y `Backend/uploads/`, sistema de tareas asíncronas con polling

Actualmente el sistema opera con **imágenes estáticas** (upload → procesamiento → resultado). Este documento analiza cómo extender la arquitectura para soportar **video en tiempo real** desde distintas fuentes de cámara.

### Estado actual de la arquitectura

```
Frontend (vision.js)                Backend (vision.py)
┌─────────────────────┐             ┌──────────────────────────┐
│  Upload de imagen   │──POST──────>│  /api/vision/process     │
│  (FormData)         │             │  → Guarda archivo        │
│                     │             │  → Crea tarea asíncrona  │
│  Polling de estado  │──GET───────>│  /api/vision/status/:id  │
│  (cada 2s)          │             │  → Retorna progreso      │
│                     │<──JSON──────│  → Resultado final       │
└─────────────────────┘             └──────────────────────────┘
```

El paso a video en tiempo real requiere un cambio de paradigma: de **request/response** a **streaming continuo** de frames.

> **Decisión de diseño**: El transporte principal de video es MJPEG sobre HTTP. WebSocket se reserva exclusivamente para eventos de detección en tiempo real (futuro). Esto simplifica la implementación y es universalmente compatible con todos los navegadores. Ver [`docs/plan-dashboard.md`](plan-dashboard.md) sección 11 "Decisiones de Compatibilidad" para más detalles.

---

## Opción 1 — Cámaras de iPhone

### Descripción General

Utilizar un iPhone como fuente de video de alta calidad para el sistema Argos2. El iPhone puede actuar como cámara IP transmitiendo video en red local hacia el backend Flask.

### Protocolos de Streaming

| Protocolo | Descripción | Latencia Típica | Complejidad |
|-----------|-------------|-----------------|-------------|
| **RTSP** | Protocolo estándar de streaming en tiempo real. Requiere servidor RTSP en el iPhone. | 100-300 ms | Media |
| **HTTP MJPEG** | Secuencia de imágenes JPEG por HTTP. Simple de implementar. | 200-500 ms | Baja |
| **HLS** | HTTP Live Streaming, nativo de Apple. Segmenta el video en chunks .ts. | 2-5 segundos | Baja |
| **RTMP** | Protocolo de Adobe, usado para streaming. Requiere servidor intermedio. | 200-500 ms | Alta |

### Apps Recomendadas

| App | Protocolo | Costo | Notas |
|-----|-----------|-------|-------|
| **iVCam** | Propietario via USB/WiFi | Gratis / Pro $10 | Alta calidad, baja latencia via USB |
| **EpocCam** | Propietario via USB/WiFi | Gratis / Pro $8 | Compatible con Windows |
| **IP Webcam Lite** | HTTP MJPEG / RTSP | Gratis | Simple, servidor web integrado |
| **CameraFi** | RTSP / HTTP | Gratis | Buena calidad de imagen |
| **StreamEez** | RTSP | Gratis | Configurable |
| **Larix Broadcaster** | RTMP / RTSP / SRT | Gratis | Profesional, muy configurable |

### APIs Nativas (desarrollo propio)

Si se desea desarrollar una app iOS personalizada:

- **AVFoundation**: Framework principal para captura de audio y video
- **AVCaptureSession**: Gestiona la sesión de captura con configuración de resolución y FPS
- **AVCaptureVideoDataOutput**: Permite acceder a los frames individuales en tiempo real
- **Network framework / sockets**: Para transmisión personalizada al backend

```swift
// Concepto: Configuración de AVCaptureSession
let session = AVCaptureSession()
session.sessionPreset = .hd1920x1080  // Full HD
let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
let input = try AVCaptureDeviceInput(device: device!)
session.addInput(input)

let output = AVCaptureVideoDataOutput()
output.setSampleBufferDelegate(self, queue: DispatchQueue(label: "videoQueue"))
session.addOutput(output)
session.startRunning()
```

### Latencia, Resolución y FPS Esperados

| Métrica | WiFi (MJPEG) | WiFi (RTSP) | USB (iVCam) |
|---------|-------------|-------------|-------------|
| **Resolución máxima** | 1920x1080 | 1920x1080 | 1920x1080 |
| **FPS** | 15-30 | 25-30 | 30 |
| **Latencia** | 200-500 ms | 100-300 ms | 50-150 ms |
| **Calidad** | Buena | Muy buena | Excelente |

### Arquitectura de Integración

```
iPhone (App de cámara IP)
│
│  HTTP MJPEG / RTSP stream
│  (ej: http://192.168.1.100:8080/video)
│
▼
Backend Flask — Endpoint de streaming
┌──────────────────────────────────────────────┐
│  POST /api/cameras/<id>/start                │
│  → OpenCV VideoCapture con URL del stream    │
│  → cv2.VideoCapture - http://iPhone:8080/v   │
│  → Procesa frames en tiempo real             │
│  → Emite frames procesados via MJPEG stream  │
│                                              │
│  POST /api/cameras/<id>/stop                 │
│  → Detiene la captura                        │
└──────────────────────────────────────────────┘
│
│  WebSocket / SSE
│
▼
Frontend (vision.js)
┌──────────────────────────────────────────────┐
│  <img> o <canvas> que muestra frames         │
│  Recibe frames procesados via WebSocket      │
│  Actualización en tiempo real                │
└──────────────────────────────────────────────┘
```

### Fragmento de Código Conceptual — Backend

```python
# Backend/routes/camera.py — Concepto para iPhone (cámara IP)
import cv2
import threading
from flask import Blueprint, jsonify, Response

camera_bp = Blueprint('camera', __name__, url_prefix='/api/cameras')

class CameraStream:
    def __init__(self):
        self.cap = None
        self.is_running = False
        self.thread = None

    def start(self, source_url):
        """
        Inicia la captura desde un iPhone.
        source_url ejemplo: 'http://192.168.1.100:8080/video'
        Para RTSP: 'rtsp://192.168.1.100:8554/live'
        """
        self.cap = cv2.VideoCapture(source_url)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo conectar a {source_url}")

        self.is_running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        while self.is_running:
            ret, frame = self.cap.read()
            if not ret:
                continue

            # Procesar frame con OpenCV (detección, clasificación, etc.)
            processed_frame = self._process_frame(frame)

            # Almacenar frame para MJPEG stream
            _, buffer = cv2.imencode('.jpg', processed_frame,
                                      [cv2.IMWRITE_JPEG_QUALITY, 80])
            self._latest_frame = buffer.tobytes()

    def stop(self):
        self.is_running = False
        if self.cap:
            self.cap.release()

camera = CameraStream()

@camera_bp.route('/<camera_id>/start', methods=['POST'])
def start_stream(camera_id):
    data = request.get_json()
    source_url = data.get('source_url')
    camera.start(source_url)
    return jsonify({'status': 'streaming', 'source': source_url}), 200

@camera_bp.route('/<camera_id>/stop', methods=['POST'])
def stop_stream(camera_id):
    camera.stop()
    return jsonify({'status': 'stopped'}), 200
```

### Estimación de Latencia y Rendimiento

- **Latencia total estimada (end-to-end):** 300-800 ms (WiFi MJPEG), 150-400 ms (WiFi RTSP), 100-250 ms (USB)
- **Ancho de banda:** 5-20 Mbps dependiendo de resolución y calidad
- **CPU backend:** Moderada (decodificación + procesamiento OpenCV)
- **Limitante principal:** Red WiFi — puede ser inestable en entornos con interferencia

### Complejidad de Implementación

**Media-Alta**

- Requiere configurar una app en el iPhone
- La conexión WiFi introduce variables de red
- Para desarrollo nativo iOS se requiere Xcode y cuenta de desarrollador Apple ($99/año)
- Para apps existentes, la integración es relativamente directa con OpenCV

### Costo Estimado

| Concepto | Costo |
|----------|-------|
| App de cámara IP (iVCam, EpocCam) | Gratis - $10 USD |
| Desarrollo app iOS nativa (opcional) | $99/año (Apple Developer) + tiempo de desarrollo |
| iPhone como cámara | $0 (si ya se posee) |
| **Total mínimo** | **$0 - $10 USD** |

### Pros y Contras

| Pros | Contras |
|------|---------|
| Excelente calidad de imagen (12-48 MP) | Dependencia de red WiFi (si no es USB) |
| Resoluciones altas (4K en modelos recientes) | Latencia variable según conexión |
| Portátil e inalámbrico | Drena la batería del iPhone rápidamente |
| Múltiples protocolos disponibles | Requiere instalar app adicional |
| Estabilización óptica de imagen | No diseñado como cámara de seguridad permanente |
| Iluminación con flash/True Tone | Costoso si se necesita dedicar un iPhone |

### Recomendación de Uso

Ideal para **prototipado rápido** y **demostraciones** donde se necesite alta calidad de imagen sin inversión en hardware adicional. También útil para capturas en campo o ubicaciones temporales donde no hay cámaras fijas instaladas.

---

## Opción 2 — Cámaras Web de Laptop

### Descripción General

Utilizar la cámara web integrada de una laptop como fuente de video. Esta opción aprovecha el acceso directo desde el navegador (WebRTC) o desde el backend (OpenCV VideoCapture).

### Acceso Directo vía WebRTC / navigator.mediaDevices

El navegador puede acceder a la cámara web directamente usando la API `navigator.mediaDevices.getUserMedia()`. Esto permite capturar video en el frontend sin necesidad de software adicional.

```javascript
// Frontend — Acceso directo a cámara web del navegador
async function startWebcam() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 30 }
            },
            audio: false
        });
        const videoElement = document.getElementById('webcam-video');
        videoElement.srcObject = stream;
        return stream;
    } catch (err) {
        console.error('Error accediendo a la cámara:', err);
    }
}
```

### Streaming al Backend

Existen dos estrategias principales para enviar los frames al backend:

#### Estrategia A: WebSocket (Frames individuales)

```
Frontend                          Backend
┌────────────────────┐            ┌─────────────────────────┐
│  getUserMedia()    │            │  WebSocket endpoint     │
│  → Canvas capture  │──WS───────>│  → Recibe frame JPEG    │
│  → toBlob/toDataURL│            │  → Procesa con OpenCV   │
│  → Envía cada frame│            │  → Retorna resultado    │
│                    │<──WS───────│  → Emite frame proc.    │
└────────────────────┘            └─────────────────────────┘
```

#### Estrategia B: HTTP MJPEG desde el backend

```
Frontend                          Backend
┌────────────────────┐            ┌─────────────────────────┐
│  <img src=...>     │            │  OpenCV VideoCapture(0) │
│  Muestra MJPEG     │<──MJPEG────│  → Genera stream MJPEG  │
│  stream del backend│            │  → Procesa frames       │
│                    │            │  → Serve en /stream      │
└────────────────────┘            └─────────────────────────┘
```

### OpenCV VideoCapture con Índice de Dispositivo

```python
# Acceso a cámara web local desde el backend
cap = cv2.VideoCapture(0)  # Índice 0 = cámara predeterminada

# Configurar resolución y FPS
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
cap.set(cv2.CAP_PROP_FPS, 30)
```

### Latencia, Resolución y FPS Esperados

| Métrica | WebRTC (Frontend) | OpenCV directo (Backend) |
|---------|-------------------|--------------------------|
| **Resolución típica** | 640x480 - 1280x720 | 640x480 - 1280x720 |
| **FPS** | 30 | 30 |
| **Latencia captura** | < 50 ms | < 50 ms |
| **Latencia total (con procesamiento)** | 100-300 ms (via WS) | 50-150 ms (local) |

### Arquitectura de Integración

```
Laptop Camera (integrada)
│
├── Opción A: Acceso desde Backend (local)
│   │
│   ▼
│   Backend Flask (en la misma laptop)
│   ┌──────────────────────────────────────────┐
│   │  OpenCV VideoCapture(0)                  │
│   │  → Captura frames directamente           │
│   │  → Procesa con visión computacional      │
│   │  → Genera stream MJPEG de salida         │
│   │  → WebSocket para resultados             │
│   └──────────────────────────────────────────┘
│   │
│   │  MJPEG stream / WebSocket
│   ▼
│   Frontend (vision.js)
│   ┌──────────────────────────────────────────┐
│   │  <img src=/api/cameras/<id>/stream>      │
│   │  Muestra video procesado en tiempo real  │
│   │  WebSocket para datos de detección       │
│   └──────────────────────────────────────────┘
│
├── Opción B: Acceso desde Frontend (WebRTC)
│   │
│   ▼
│   Frontend (vision.js)
│   ┌──────────────────────────────────────────┐
│   │  navigator.mediaDevices.getUserMedia()   │
│   │  → Captura video local                   │
│   │  → Canvas.toBlob() cada frame            │
│   │  → Envía frames via WebSocket al backend │
│   └──────────────────────────────────────────┘
│   │
│   │  WebSocket (frames JPEG)
│   ▼
│   Backend Flask
│   ┌──────────────────────────────────────────┐
│   │  Recibe frames via WebSocket             │
│   │  → Convierte a numpy array               │
│   │  → Procesa con OpenCV                    │
│   │  → Retorna resultados via WebSocket      │
│   └──────────────────────────────────────────┘
```

### Fragmento de Código Conceptual — Backend (MJPEG Streaming)

```python
# Backend/routes/camera.py — Concepto para cámara web local
import cv2
from flask import Blueprint, Response

camera_bp = Blueprint('camera', __name__, url_prefix='/api/cameras')

# Stream MJPEG desde cámara local
def generate_mjpeg_stream(camera_index=0):
    """
    Genera un stream MJPEG desde la cámara web local.
    Los frames se procesan con OpenCV antes de enviarse.
    """
    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # --- Procesamiento de visión computacional aquí ---
            # Ejemplo: detección de bordes
            processed = cv2.Canny(frame, 100, 200)
            processed_bgr = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)

            # Codificar como JPEG
            _, buffer = cv2.imencode('.jpg', processed_bgr,
                                      [cv2.IMWRITE_JPEG_QUALITY, 80])
            frame_bytes = buffer.tobytes()

            # Yield en formato MJPEG
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    finally:
        cap.release()

@camera_bp.route('/<camera_id>/stream')
def mjpeg_stream(camera_id):
    """Endpoint de streaming MJPEG para mostrar en <img> del frontend."""
    return Response(
        generate_mjpeg_stream(camera_index=int(camera_id)),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )
```

> **Importante**: Los streams MJPEG deben incluir headers CORS (`Access-Control-Allow-Origin`) para permitir captura desde canvas en el frontend. Sin embargo, la captura primaria se realiza vía endpoint backend `POST /api/cameras/<id>/capture`, que no tiene restricciones CORS. Ver [`docs/plan-dashboard.md`](plan-dashboard.md) sección 11 para más detalles.

### Fragmento de Código Conceptual — Frontend (WebRTC + WebSocket)

```javascript
// Frontend/js/vision.js — Extensión para cámara web en tiempo real
const VISION_STREAM = {
    ws: null,
    localStream: null,

    async startLocalCamera() {
        this.localStream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, frameRate: { ideal: 15 } }
        });
        const video = document.getElementById('webcam-preview');
        video.srcObject = this.localStream;

        // Conectar WebSocket al backend
        this.ws = new WebSocket(`ws://${window.location.host}/ws/vision`);

        // Enviar frames periódicamente
        this._sendFramesLoop();
    },

    _sendFramesLoop() {
        const video = document.getElementById('webcam-preview');
        const canvas = document.createElement('canvas');
        canvas.width = 640;
        canvas.height = 480;
        const ctx = canvas.getContext('2d');

        const sendFrame = () => {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

            ctx.drawImage(video, 0, 0, 640, 480);
            canvas.toBlob((blob) => {
                if (blob) this.ws.send(blob);
            }, 'image/jpeg', 0.8);

            requestAnimationFrame(sendFrame);
        };
        sendFrame();
    },

    stop() {
        if (this.localStream) {
            this.localStream.getTracks().forEach(t => t.stop());
        }
        if (this.ws) this.ws.close();
    }
};
```

### Estimación de Latencia y Rendimiento

- **Latencia total (Opción A — Backend local):** 50-150 ms (muy baja, procesamiento en la misma máquina)
- **Latencia total (Opción B — WebRTC + WebSocket):** 100-300 ms (ida y vuelta por red local)
- **CPU:** Moderada en el backend por procesamiento OpenCV
- **Ancho de banda:** N/A para Opción A (local); ~5-10 Mbps para Opción B (WebSocket)

### Complejidad de Implementación

**Baja**

- No requiere hardware adicional
- `navigator.mediaDevices` es estándar y bien soportado
- OpenCV `VideoCapture(0)` funciona inmediatamente
- La Opción A (backend directo) es la más simple de implementar

### Costo Estimado

| Concepto | Costo |
|----------|-------|
| Cámara web integrada | $0 (incluida en la laptop) |
| Desarrollo | Solo tiempo de desarrollo |
| Dependencias adicionales | Flask-SocketIO (WebSocket) — gratis |
| **Total** | **$0 USD** |

### Pros y Contras

| Pros | Contras |
|------|---------|
| Sin costo adicional | Calidad de imagen limitada (1-2 MP típico) |
| Latencia muy baja (misma máquina) | Posición fija (lid de laptop) |
| Fácil de implementar | Ángulo de visión limitado |
| Sin configuración de red | Calidad variable entre laptops |
| Ideal para desarrollo y pruebas | No escalable para producción |
| Accesible desde navegador (WebRTC) | No apto para vigilancia permanente |

### Recomendación de Uso

Ideal para **desarrollo y pruebas** del pipeline de visión computacional. Es la opción más rápida de implementar y perfecta para validar los algoritmos de procesamiento antes de integrar fuentes de video más complejas. También útil para **demostraciones en laptop**.

---

## Opción 3 — Cámaras Web de Escritorio (USB)

### Descripción General

Cámaras web USB externas conectadas al servidor o computadora de escritorio. Ofrecen mejor calidad que las cámaras integradas de laptop y mayor flexibilidad de posicionamiento.

### Drivers y Compatibilidad (UVC Standard)

La mayoría de las cámaras web USB modernas cumplen con el estándar **UVC (USB Video Class)**, lo que significa:

- **Plug & Play** en Windows, Linux y macOS
- No requieren drivers adicionales
- OpenCV las detecta automáticamente vía `VideoCapture`
- Compatible con V4L2 (Video4Linux2) en Linux y DirectShow en Windows

### OpenCV VideoCapture — Múltiples Cámaras

```python
# Acceder a múltiples cámaras USB
cameras = {}

def discover_cameras(max_index=5):
    """Detecta todas las cámaras USB conectadas."""
    available = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            available.append(index)
            cap.release()
    return available

# Usar cámara específica
cap0 = cv2.VideoCapture(0)  # Primera cámara USB
cap1 = cv2.VideoCapture(1)  # Segunda cámara USB
cap2 = cv2.VideoCapture(2)  # Tercera cámara USB

# Configurar resolución alta (cámaras de escritorio suelen soportar más)
cap0.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap0.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap0.set(cv2.CAP_PROP_FPS, 30)
cap0.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimizar latencia
```

### Latencia, Resolución y FPS Esperados

| Cámara | Resolución | FPS | Latencia Captura | Precio Aprox. |
|--------|-----------|-----|-----------------|---------------|
| Logitech C270 | 1280x720 | 30 | < 50 ms | $25 USD |
| Logitech C920 | 1920x1080 | 30 | < 50 ms | $60 USD |
| Logitech C922 Pro | 1920x1080 | 30 (60 a 720p) | < 30 ms | $80 USD |
| Logitech Brio 4K | 3840x2160 | 30 (60 a 1080p) | < 30 ms | $160 USD |
| Microsoft LifeCam HD-3000 | 1280x720 | 30 | < 50 ms | $30 USD |
| Razer Kiyo Pro | 1920x1080 | 60 | < 30 ms | $150 USD |

### Arquitectura de Integración

```
Cámara USB 1 ──┐
Cámara USB 2 ──┤  USB (UVC)
Cámara USB 3 ──┘
       │
       ▼
Backend Flask (servidor de escritorio)
┌──────────────────────────────────────────────────┐
│  Gestor de múltiples cámaras                     │
│  ┌────────────────────────────────────────────┐  │
│  │ CameraManager                              │  │
│  │  → cv2.VideoCapture(0) — Camara frontal    │  │
│  │  → cv2.VideoCapture(1) — Camara lateral    │  │
│  │  → cv2.VideoCapture(2) — Camara trasera    │  │
│  │  → Thread por cámara                       │  │
│  │  → Cola de frames por cámara               │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  Procesamiento por cámara:                       │
│  → Detección / Clasificación / Mejora            │
│  → Stream MJPEG individual por cámara            │
│  → WebSocket para eventos de detección           │
│                                                  │
│  Endpoints:                                      │
│  GET /api/cameras/<id>/stream — Stream MJPEG     │
│  GET /api/cameras — Lista cámaras                │
│  POST /api/cameras/<id>/start — Iniciar captura  │
│  POST /api/cameras/<id>/stop — Detener captura   │
└──────────────────────────────────────────────────┘
       │
       │  MJPEG / WebSocket
       ▼
Frontend (vision.js)
┌──────────────────────────────────────────────────┐
│  Selector de cámara (dropdown)                   │
│  Grid de vistas para múltiples cámaras           │
│  <img src=/api/cameras/<id>/stream> por cámara   │
│  Panel de resultados de detección en tiempo real  │
└──────────────────────────────────────────────────┘
```

### Fragmento de Código Conceptual — Backend (Multi-cámara)

```python
# Backend/services/camera_manager.py — Concepto multi-cámara USB
import cv2
import threading
from collections import deque

class CameraManager:
    """Gestiona múltiples cámaras USB simultáneas."""

    def __init__(self):
        self.cameras = {}  # {index: CameraStream}
        self.lock = threading.Lock()

    def discover(self):
        """Detecta cámaras USB conectadas."""
        available = []
        for i in range(5):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)  # DirectShow en Windows
            if cap.isOpened():
                available.append({
                    'index': i,
                    'name': f'Camera {i}',
                    'resolution': (
                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    )
                })
                cap.release()
        return available

    def start_camera(self, index, resolution=(1280, 720), fps=30):
        """Inicia captura de una cámara específica."""
        if index in self.cameras:
            self.stop_camera(index)

        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
        cap.set(cv2.CAP_PROP_FPS, fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Buffer mínimo = menor latencia

        stream = {
            'cap': cap,
            'running': True,
            'frame_queue': deque(maxlen=2),  # Solo último frame
            'thread': None
        }

        stream['thread'] = threading.Thread(
            target=self._capture_loop,
            args=(index, stream),
            daemon=True
        )
        stream['thread'].start()

        with self.lock:
            self.cameras[index] = stream

        return True

    def _capture_loop(self, index, stream):
        """Loop de captura en hilo separado."""
        while stream['running']:
            ret, frame = stream['cap'].read()
            if ret:
                stream['frame_queue'].append(frame)

    def get_frame(self, index):
        """Obtiene el último frame de una cámara."""
        with self.lock:
            if index in self.cameras and self.cameras[index]['frame_queue']:
                return self.cameras[index]['frame_queue'][-1]
        return None

    def stop_camera(self, index):
        """Detiene una cámara."""
        with self.lock:
            if index in self.cameras:
                self.cameras[index]['running'] = False
                self.cameras[index]['cap'].release()
                del self.cameras[index]

# Singleton
camera_manager = CameraManager()
```

### Estimación de Latencia y Rendimiento

- **Latencia de captura:** 30-50 ms (USB 2.0), < 30 ms (USB 3.0)
- **Latencia total con procesamiento:** 80-200 ms
- **Múltiples cámaras:** Cada cámara requiere un thread independiente
- **CPU:** Moderada — escala linealmente con número de cámaras
- **USB bandwidth:** Limitante con 3+ cámaras de alta resolución en el mismo hub USB

### Complejidad de Implementación

**Baja-Media**

- Conexión USB plug & play, sin configuración de red
- OpenCV detecta automáticamente las cámaras
- La gestión multi-cámara agrega complejidad moderada
- En Windows, usar `cv2.CAP_DSHOW` para menor latencia

### Costo Estimado

| Concepto | Costo |
|----------|-------|
| Cámara web USB básica (720p) | $20-30 USD |
| Cámara web USB media (1080p) | $50-80 USD |
| Cámara web USB premium (4K/60fps) | $130-200 USD |
| Hub USB (si se necesitan múltiples) | $15-30 USD |
| **Total (1 cámara 1080p)** | **~$60 USD** |
| **Total (3 cámaras 1080p + hub)** | **~$210 USD** |

### Pros y Contras

| Pros | Contras |
|------|---------|
| Buena relación calidad/precio | Cable USB limita distancia (5m max) |
| Plug & Play (UVC) | Requiere computadora cercana |
| Múltiples cámaras simultáneas | Ancho de banda USB compartido |
| Resoluciones hasta 4K | Requiere hubs USB para múltiples cámaras |
| Baja latencia (conexión directa) | No inalámbrico |
| Amplia compatibilidad con OpenCV | Calidad inferior a cámaras IP dedicadas |
| Fácil de reemplazar | Posicionamiento limitado por cable |

### Recomendación de Uso

Ideal para **despliegues permanentes en interiores** donde se necesiten 1-4 cámaras fijas. Perfecto para **vigilancia de áreas específicas** (entrada, pasillo, habitación) con el servidor Argos2 en la misma ubicación. Excelente opción para **monitoreo multi-cámara** a bajo costo.

---

## Opción 4 — Módulos ESP32-CAM

### Descripción General

El ESP32-CAM es un módulo microcontrolador con cámara integrada y conectividad WiFi, fabricado por Espressif. Es una solución ultra-económica para streaming de video por red, ideal para despliegues distribuidos.

### Especificaciones Técnicas

| Componente | Especificación |
|------------|---------------|
| **Microcontrolador** | ESP32 dual-core 240MHz |
| **RAM** | 4 MB PSRAM externa + 520 KB SRAM |
| **WiFi** | 802.11 b/g/n (2.4 GHz) |
| **Cámara** | OV2640 (2 MP) incluida |
| **GPIO** | 9 pines disponibles (limitado) |
| **Alimentación** | 5V via USB o 3.3V |
| **Dimensiones** | 27 x 40.5 mm |

### Configuración del Firmware

#### Opción A: CameraWebServer (Arduino IDE)

El ejemplo oficial de Espressif incluye un servidor web completo con streaming MJPEG:

```cpp
// Fragmento de configuración — Arduino IDE
// Basado en el ejemplo CameraWebServer de ESP32

#include "esp_camera.h"
#include <WiFi.h>

// Configuración de pines para ESP32-CAM AI-Thinker
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

camera_config_t config;
config.ledc_channel = LEDC_CHANNEL_0;
config.ledc_timer = LEDC_TIMER_0;
config.pin_d0 = Y2_GPIO_NUM;
config.pin_d1 = Y3_GPIO_NUM;
// ... (resto de pines)
config.pixel_format = PIXFORMAT_JPEG;
config.frame_size = FRAMESIZE_SVGA;  // 800x600
config.jpeg_quality = 12;            // 0-63, menor = mejor calidad
config.fb_count = 2;                 // 2 buffers para mejor rendimiento

WiFi.begin("SSID", "PASSWORD");
```

#### Opción B: esp32-camera (PlatformIO / IDF)

Para mayor control, se puede usar el ESP-IDF directamente con la librería `esp32-camera`.

### Resoluciones Soportadas

| Constante | Resolución | Nombre | FPS Típico | Uso Recomendado |
|-----------|-----------|--------|------------|-----------------|
| `FRAMESIZE_QQVGA` | 160x120 | QQVGA | 30-60 | Thumbnails |
| `FRAMESIZE_QCIF` | 176x144 | QCIF | 30 | Mini preview |
| `FRAMESIZE_QVGA` | 320x240 | QVGA | 25-30 | Detección básica |
| `FRAMESIZE_CIF` | 400x296 | CIF | 25 | Monitoreo |
| `FRAMESIZE_VGA` | 640x480 | VGA | 20-25 | Uso general |
| `FRAMESIZE_SVGA` | 800x600 | SVGA | 15-20 | Buena calidad |
| `FRAMESIZE_XGA` | 1024x768 | XGA | 10-15 | Alta calidad |
| `FRAMESIZE_SXGA` | 1280x960 | SXGA | 5-10 | Máximo práctico |
| `FRAMESIZE_UXGA` | 1600x1200 | UXGA | 3-5 | Foto estática |

### Protocolo HTTP MJPEG para Consumo desde OpenCV

El ESP32-CAM expone un endpoint MJPEG estándar que OpenCV puede consumir directamente:

```python
# Consumir stream MJPEG del ESP32-CAM desde el backend
ESP32_CAM_URL = "http://192.168.1.150"

# Stream MJPEG del ESP32-CAM (endpoint estándar del CameraWebServer)
stream_url = f"{ESP32_CAM_URL}:81/stream"

cap = cv2.VideoCapture(stream_url)

while True:
    ret, frame = cap.read()
    if not ret:
        print("Error leyendo frame del ESP32-CAM")
        break

    # Procesar frame con visión computacional
    # ...
```

### Arquitectura de Integración

```
ESP32-CAM #1 (192.168.1.150)
│  HTTP MJPEG en puerto 81
│  (stream de la cámara OV2640)
│
ESP32-CAM #2 (192.168.1.151)     Red WiFi Local
│  HTTP MJPEG en puerto 81
│
ESP32-CAM #3 (192.168.1.152)
│  HTTP MJPEG en puerto 81
│
└──────────┬───────────────────────────────┐
           │                               │
           ▼                               │
Backend Flask (servidor Argos2)            │
┌──────────────────────────────────────┐   │
│  ESP32CameraManager                  │   │
│  ┌────────────────────────────────┐  │   │
│  │ cv2.VideoCapture(              │  │   │
│  │   'http://192.168.1.150:81/   │  │   │
│  │    stream')                    │  │   │
│  │ → Thread por ESP32-CAM        │  │   │
│  │ → Cola de frames               │  │   │
│  │ → Procesamiento OpenCV         │  │   │
│  └────────────────────────────────┘  │   │
│                                      │   │
│  Endpoints:                              │   │
│  GET /api/cameras/esp32/<id>/stream     │   │
│  GET /api/cameras?type=esp32 — Listar   │   │
│  POST /api/cameras — Registrar ESP32    │   │
│  → Body: {ip, name, type:"esp32", res}  │   │
│                                         │   │
│  Endpoints adicionales:                 │   │
│  POST /api/cameras/<id>/capture         │   │
│  → Captura frame actual como JPEG       │   │
│  GET /api/cameras/<id>/status           │   │
│  → Estado detallado de cámara           │   │
│  GET /api/cameras/discover              │   │
│  → Descubrir cámaras USB locales        │   │
│  POST /api/cameras                      │   │
│  → Registrar nueva cámara IP/ESP32      │   │
│  DELETE /api/cameras/<id>               │   │
│  → Eliminar cámara registrada           │   │
│  POST /api/cameras/<id>/restart         │   │
│  → Reiniciar conexión de cámara         │   │
└──────────────────────────────────────┘   │
           │                               │
           │  MJPEG / WebSocket            │
           ▼                               │
Frontend (vision.js)                       │
┌──────────────────────────────────────┐   │
│  Grid de cámaras ESP32              │   │
│  Selector de resolución             │   │
│  Panel de estado de cada módulo     │   │
│  Alertas de detección en tiempo real│   │
└──────────────────────────────────────┘   │
                                           │
Configuración ESP32-CAM ───────────────────┘
┌──────────────────────────────────────┐
│  Arduino IDE / PlatformIO            │
│  → Firmware CameraWebServer          │
│  → WiFi credentials                  │
│  → Resolución y calidad JPEG         │
│  → IP estática recomendada           │
└──────────────────────────────────────┘
```

### Fragmento de Código Conceptual — Backend

```python
# Backend/services/esp32_camera.py — Concepto para ESP32-CAM
import cv2
import threading
import requests
from dataclasses import dataclass, field

@dataclass
class ESP32Camera:
    id: str
    name: str
    ip: str
    port: int = 81
    resolution: str = 'SVGA'  # QVGA, VGA, SVGA, XGA
    is_active: bool = False
    cap: object = field(default=None, repr=False)
    _thread: object = field(default=None, repr=False)
    _running: bool = False
    _latest_frame: object = field(default=None, repr=False)

    @property
    def stream_url(self):
        return f"http://{self.ip}:{self.port}/stream"

    @property
    def control_url(self):
        return f"http://{self.ip}"

    def start(self):
        """Inicia captura del stream MJPEG del ESP32-CAM."""
        self.cap = cv2.VideoCapture(self.stream_url)
        if not self.cap.isOpened():
            raise RuntimeError(
                f"No se pudo conectar al ESP32-CAM en {self.stream_url}"
            )

        # Configurar resolución via HTTP
        res_map = {
            'QVGA': 5, 'VGA': 8, 'SVGA': 9,
            'XGA': 10, 'SXGA': 11, 'UXGA': 12
        }
        try:
            requests.get(
                f"{self.control_url}/control?var=framesize&val="
                f"{res_map.get(self.resolution, 9)}",
                timeout=3
            )
        except requests.RequestException:
            pass  # No crítico si falla

        self._running = True
        self._thread = threading.Thread(target=self._capture, daemon=True)
        self._thread.start()
        self.is_active = True

    def _capture(self):
        """Loop de captura en hilo separado."""
        while self._running:
            ret, frame = self.cap.read()
            if ret:
                self._latest_frame = frame
            else:
                # Reintentar conexión
                import time
                time.sleep(1)
                self.cap.release()
                self.cap = cv2.VideoCapture(self.stream_url)

    def get_frame(self):
        """Retorna el último frame capturado."""
        return self._latest_frame

    def stop(self):
        """Detiene la captura."""
        self._running = False
        self.is_active = False
        if self.cap:
            self.cap.release()


class ESP32CameraManager:
    """Gestiona múltiples módulos ESP32-CAM."""

    def __init__(self):
        self.cameras: dict[str, ESP32Camera] = {}

    def add_camera(self, cam_id, name, ip, resolution='SVGA'):
        camera = ESP32Camera(
            id=cam_id, name=name, ip=ip, resolution=resolution
        )
        self.cameras[cam_id] = camera
        return camera

    def start_camera(self, cam_id):
        if cam_id in self.cameras:
            self.cameras[cam_id].start()
            return True
        return False

    def stop_camera(self, cam_id):
        if cam_id in self.cameras:
            self.cameras[cam_id].stop()
            return True
        return False

    def get_all_frames(self):
        """Retorna {cam_id: frame} de todas las cámaras activas."""
        return {
            cid: cam.get_frame()
            for cid, cam in self.cameras.items()
            if cam.is_active and cam.get_frame() is not None
        }

# Singleton
esp32_manager = ESP32CameraManager()
```

### Limitaciones de FPS y Calidad

| Limitación | Detalle |
|------------|---------|
| **FPS máximo** | ~25 fps a QVGA, ~15-20 fps a VGA, ~10-15 fps a SVGA |
| **Calidad JPEG** | Rango 0-63 (menor = mejor). Práctico: 10-15 |
| **RAM limitada** | 4MB PSRAM — limita resolución y buffers |
| **Sin enfoque automático** | La OV2640 tiene enfoque fijo |
| **Sin estabilización** | No tiene estabilización óptica |
| **Conectividad** | Solo WiFi 2.4 GHz, sin Ethernet |
| **Alimentación** | Requiere 5V estable; batería posible con módulo adicional |

### Estimación de Latencia y Rendimiento

- **Latencia de captura + red:** 100-300 ms (WiFi local)
- **Latencia total con procesamiento:** 200-500 ms
- **Ancho de banda por cámara:** 1-4 Mbps (dependiendo de resolución)
- **Máximo práctico de cámaras:** 4-6 simultáneas (limitado por CPU del backend)
- **Confiabilidad:** Media — puede requerir reconexión periódica

### Complejidad de Implementación

**Media**

- Requiere flashear firmware en cada módulo ESP32-CAM
- Configuración de WiFi y direcciones IP
- OpenCV consume el stream MJPEG estándar (simple)
- Manejo de reconexiones ante desconexiones WiFi
- No requiere drivers ni software adicional en el servidor

### Costo Estimado

| Concepto | Costo |
|----------|-------|
| ESP32-CAM con cámara OV2640 | $3-8 USD por unidad |
| Programador FTDI (para flashear) | $3-5 USD (una sola vez) |
| Fuente de alimentación 5V | $2-5 USD por unidad |
| Cable USB-OTG o adaptador | $1-2 USD por unidad |
| Cables y conectores | $1-2 USD por unidad |
| **Total (1 cámara ESP32-CAM)** | **~$10-20 USD** |
| **Total (4 cámaras ESP32-CAM)** | **~$35-60 USD** |

### Pros y Contras

| Pros | Contras |
|------|---------|
| Costo extremadamente bajo ($3-8/unidad) | Calidad de imagen limitada (2 MP) |
| Tamaño reducido (27x40mm) | FPS limitados a resoluciones altas |
| WiFi integrado (inalámbrico) | RAM limitada (4MB) |
| Bajo consumo eléctrico | Enfoque fijo, sin autofocus |
| Fácil de desplegar en múltiples puntos | Requiere flashear firmware |
| Escalable — agregar cámaras es barato | Conexión WiFi puede ser inestable |
| Streaming MJPEG estándar (compatible con OpenCV) | No apto para condiciones de baja luz |
| Comunidad activa y mucha documentación | Sin audio |

### Recomendación de Uso

Ideal para **redes de vigilancia distribuidas** donde se necesiten múltiples cámaras a bajo costo. Perfecto para **monitoreo de múltiples puntos** (habitaciones, pasillos, entradas) con un presupuesto mínimo. También excelente para **instalaciones temporales** o proyectos educativos.

---

## Tabla Comparativa

| Criterio | iPhone | Laptop Webcam | USB Desktop | ESP32-CAM |
|----------|--------|---------------|-------------|-----------|
| **Costo por cámara** | $0-10 USD | $0 USD | $30-80 USD | $3-8 USD |
| **Resolución máxima** | 3840x2160 (4K) | 1280x720 | 1920x1080 (4K premium) | 1600x1200 (UXGA) |
| **FPS realista** | 25-30 | 30 | 30 (60 premium) | 15-20 (VGA) |
| **Latencia total** | 150-800 ms | 50-300 ms | 80-200 ms | 200-500 ms |
| **Calidad de imagen** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| **Complejidad implementación** | Media-Alta | Baja | Baja-Media | Media |
| **Multi-cámara** | Difícil | No (1 sola) | Sí (hasta 4-5) | Sí (ilimitado en teoría) |
| **Inalámbrico** | Sí (WiFi/USB) | No | No | Sí (WiFi) |
| **Requiere hardware extra** | No | No | Sí (cámara USB) | Sí (módulo + programador) |
| **Requiere configuración** | App + red | Ninguna | Plug & Play | Firmware + WiFi |
| **Escalabilidad** | Baja | Baja | Media | Alta |
| **Consumo eléctrico** | Alto (batería) | Medio | Medio | Bajo (~200mA) |
| **Uso permanente 24/7** | No recomendado | No recomendado | Sí | Sí |
| **Distancia al servidor** | Red local | Misma máquina | 5m (USB) | Red local (WiFi) |
| **Audio** | Sí (algunas apps) | Sí | Sí (algunas) | No |
| **Integración OpenCV** | `VideoCapture(URL)` | `VideoCapture(0)` | `VideoCapture(index)` | `VideoCapture(URL)` |

---

## Recomendación General

### Orden Sugerido de Implementación

Considerando la arquitectura actual de Argos2 (Flask + OpenCV + HTML/JS), el estado del proyecto (fase de infraestructura con mocks), y los objetivos de visión computacional, se recomienda el siguiente orden de implementación:

#### 1. 🥇 Cámara Web de Laptop (Primera implementación)

**¿Por qué primero?**

- **Costo cero** — No requiere inversión en hardware
- **Complejidad mínima** — `cv2.VideoCapture(0)` funciona inmediatamente
- **Latencia más baja** — Procesamiento en la misma máquina
- **Validación rápida** — Permite probar todo el pipeline de visión (captura → procesamiento → visualización) en minutos
- **Compatible con el desarrollo actual** — El equipo ya trabaja en laptops

**Qué validar:**
- Pipeline completo de streaming en tiempo real
- Algoritmos de detección/clasificación con OpenCV
- Interfaz de usuario para video en vivo
- Rendimiento del backend con procesamiento continuo

#### 2. 🥈 Cámara Web USB de Escritorio (Segunda implementación)

**¿Por qué segundo?**

- **Extiende la Opción 2** — Misma API de OpenCV, solo cambia el índice
- **Mejor calidad** — Cámaras dedicadas con mejor óptica
- **Multi-cámara** — Valida la gestión de múltiples fuentes
- **Despliegue permanente** — Primer paso hacia producción

#### 3. 🥉 ESP32-CAM (Tercera implementación)

**¿Por qué tercero?**

- **Cambio de arquitectura** — De captura local a stream de red
- **Valida streaming por HTTP** — Base para otras cámaras IP
- **Bajo costo para múltiples puntos** — Ideal para escalar
- **Requiere trabajo de firmware** — Pero el consumo desde OpenCV es idéntico

#### 4. iPhone (Cuarta implementación)

**¿Por qué último?**

- **Mayor complejidad** — Depende de apps de terceros o desarrollo nativo
- **Latencia variable** — Red WiFi introduce inconsistencias
- **Menos práctico para producción** — No diseñado para 24/7
- **Excelente para demos** — Pero las otras opciones ya cubren los casos de uso principales

### Arquitectura Recomendada para el Streaming

Independientemente de la fuente de cámara, se recomienda implementar una capa de abstracción:

```python
# Concepto: Interfaz unificada para cualquier fuente de video
class VideoSource(ABC):
    @abstractmethod
    def start(self): ...

    @abstractmethod
    def get_frame(self) -> np.ndarray: ...

    @abstractmethod
    def stop(self): ...

class LocalCamera(VideoSource): ...      # Opciones 2 y 3
class ESP32Camera(VideoSource): ...      # Opción 4
class IPStreamCamera(VideoSource): ...   # Opción 1 (iPhone)
```

Esto permite que el pipeline de procesamiento de Argos2 sea **independiente de la fuente de video**, facilitando la incorporación de nuevas cámaras sin modificar la lógica de visión computacional.

### Persistencia de Configuración de Cámaras

Las cámaras IP y ESP32 registradas a través de `POST /api/cameras` deben persistir en el archivo [`Backend/cameras_config.json`](../Backend/cameras_config.json) para sobrevivir reinicios del servidor. El `CameraManager` carga automáticamente las cámaras persistidas al iniciar y reconecta las que estaban activas.

**Formato de `cameras_config.json`:**

```json
{
    "cameras": [
        {
            "id": "cam_002",
            "name": "Cámara Pasillo",
            "type": "ip",
            "source": "http://192.168.1.100:8080/video",
            "resolution": "1280x720",
            "active": true
        },
        {
            "id": "cam_004",
            "name": "Estacionamiento",
            "type": "esp32",
            "source": "http://192.168.1.150:81/stream",
            "resolution": "SVGA",
            "active": true
        }
    ]
}
```

> **Nota:** Las cámaras USB locales (detectadas con `GET /api/cameras/discover`) no se persisten porque su disponibilidad depende del hardware conectado. Solo se persisten las cámaras de red (IP y ESP32) que requieren configuración manual.

---

> **Documento generado para el proyecto Argos2** — Análisis de opciones de cámara para video en tiempo real.
> Para implementación, referirse a los fragmentos de código conceptual incluidos en cada sección como base de desarrollo.
