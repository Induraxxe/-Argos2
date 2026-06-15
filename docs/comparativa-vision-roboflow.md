# Comparativa de Documentos — Vision Roboflow Argos2

> **Propósito:** Comparar dos análisis arquitectónicos para integrar Roboflow en Argos2:
> - **Doc A** = [`docs/opciones-vision-roboflow.md`](opciones-vision-roboflow.md:1) (generado en esta sesión)
> - **Doc B** = documento alternativo provisto por el usuario
>
> **Fecha:** 2026-06-15 · **Modo:** Análisis objetivo

---

## 1. Resumen Ejecutivo

Los dos documentos coinciden en el diagnóstico (WebRTC es caro para 24/7; el muestreo HTTP es el mejor punto de partida) pero **divergen en tres decisiones arquitectónicas críticas**:

| Decisión | Doc A | Doc B | Impacto |
|----------|-------|-------|---------|
| **3ª opción** | Inferencia **local/edge** (cero nube) | Arquitectura **híbrida WebSocket** (sigue en nube) | A cubre privacidad + costo cero; B prioriza UX |
| **Modelo de concurrencia** | **Threads + multiprocessing** (100% fiel al código existente) | Introduce **asyncio + aiohttp** | B rompe el paradigma síncrono del proyecto |
| **Ilusión continua (muestreo)** | **Overlay de cajas sobre frame crudo** a 15-30 fps | **Repetir último frame anotado** a ~5 fps | A produce video más fluido |

**Conclusión rápida:** El Doc A es más fiel al códigobase real y aborda la privacidad; el Doc B es más ambicioso en UX (WebSocket, smart sampling) pero introduce fricción técnica con asyncio y descarta la opción local.

---

## 2. Comparación Opción por Opción

### Opción 1 — WebRTC (equivalente en ambos)

| Aspecto | Doc A: WebRTC en Hilo Demonio | Doc B: WebRTC Dedicado con Thread Pool |
|---------|-------------------------------|----------------------------------------|
| Mecanismo asíncrono | Thread daemon por cámara + `deque(maxlen=2)` | `ThreadPoolExecutor` + `RoboflowSessionManager` |
| Ilusión continua | Fallback a frame crudo si sesión cae | Fallback a stream MJPEG original |
| Canal de datos | SSE o polling | SSE o WebSocket |
| **Diferencia clave** | A describe el callback `@session.on_frame` alimentando el buffer | B propone un `Result Aggregator` central |

**Veredicto:** Son **esencialmente la misma opción** (ambos aíslan `session.run()` en threads). El Doc A es más preciso técnicamente sobre el mecanismo de callbacks; el Doc B añade la idea de un agregador central multi-cámara. Ambos coinciden: **prohibitivo para 24/7**.

### Opción 2 — Muestreo HTTP (equivalente conceptual, divergencia en el "truco")

| Aspecto | Doc A: Overlay Continuo | Doc B: Polling con repetición de frame |
|---------|-------------------------|----------------------------------------|
| Frecuencia de inferencia | 1 frame / 1-2s | 1 frame / 1-3s |
| **Ilusión continua** | Dibuja cajas stale con `cv2.rectangle` sobre **cada frame crudo fresco** (15-30 fps) | Repite el **último frame anotado** servido a ~5 fps |
| Staleness de detecciones | 1-3s | 1-3s |
| Modelo de concurrencia | `threading.Thread` + `ThreadPoolExecutor` opcional | **asyncio + aiohttp** |
| Dibujo de cajas | Server-side con OpenCV | La API retorna imagen ya anotada |
| Tolerancia a fallos | Video fluye, cajas desaparecen | Video fluye con overlay "Procesando..." |

**Diferencia técnica crítica — la ilusión continua:**
- **Doc A**: el usuario ve video real a 15-30 fps con cajas que se "mueven" sobre objetos. El fondo cambia en tiempo real; solo las cajas tienen desfase. Esto es **genuinamente fluido**.
- **Doc B**: el usuario ve la **misma imagen estática anotada repetida 5 veces** hasta que llega la siguiente inferencia. El video se ve **entrecortado/congelado** entre actualizaciones. Su afirmación de que "el ojo percibe movimiento fluido a 5 fps repitiendo el último frame" es discutible para vigilancia.

**Veredicto:** El enfoque de **overlay de Doc A es técnicamente superior** para la continuidad percibida. El overlay server-side es además más simple de implementar que gestionar asyncio.

### Opción 3 — Divergencia máxima (opciones totalmente diferentes)

| Aspecto | Doc A: Inferencia Local/Edge | Doc B: Híbrida WebSocket |
|---------|------------------------------|--------------------------|
| Dónde corre el modelo | **Servidor local** (paquete `inference`, CPU/GPU) | **Nube Roboflow** (REST) |
| Costo cloud | 🟢 **Cero** | 🟡 Bajo-medio (smart sampling) |
| Privacidad | 🟢 Frames **nunca salen** del servidor | 🔴 Muestras salen a Roboflow |
| Dependencia de internet | No | Sí |
| Latencia IA | 20-100 ms (GPU) | 1-3s |
| Modelo de concurrencia | `ProcessPoolExecutor` (multiprocessing) | asyncio + `flask-socketio` |
| Entrega de resultados | Buffer + MJPEG anotado | **WebSocket** con overlays HTML/CSS |
| Smart sampling | No (procesa a máxima velocidad local) | **Sí** — detección de movimiento ahorra 40-70% |
| Complejidad | Alta (multiprocessing, memoria compartida) | Alta (WebSocket, cola prioridad, broadcaster) |

**Análisis:**

- **Doc A aborda una dimensión que Doc B ignora por completo: la PRIVACIDAD.** En un sistema de vigilancia, que los frames salgan a un proveedor cloud es un riesgo legal y de seguridad. La opción local de A es la **única** que resuelve esto. Su comparativa incluso incluye la fila "Privacidad (frames salen)".

- **Doc B introduce ideas valiosas que A no tiene:**
  - **Smart sampling con detección de movimiento** (ahorra 40-70% de API calls) — excelente optimización.
  - **Separación limpia**: video directo (MJPEG) + análisis (WebSocket) — arquitectónicamente elegante.
  - **Overlays HTML/CSS** en el frontend en vez de dibujar en el frame — más flexible para UI.

- **Pero el enfoque de overlays HTML/CSS de Doc B tiene un defecto** que ellos mismos reconocen: *"Las cajas no coinciden perfectamente si el stream tiene latencia o aspect ratio diferente."* Sincronizar coordenadas de cajas (en píxeles de la inferencia) con un `<img>` escalado por CSS es notoriamente frágil.

---

## 3. El Punto Más Crítico: asyncio vs Threads

Esta es la **divergencia técnica más importante** y tiene consecuencias profundas:

### El problema de asyncio en Doc B

El código actual de Argos2 es **100% síncrono con threads**:
- [`Backend/app.py`](../Backend/app.py:39) usa `Flask` (WSGI síncrono), no Quart ni ASGI.
- Todas las subclases de [`VideoSource`](../Backend/services/camera_service.py:49) usan `threading.Thread`.
- No hay `async def` ni `await` en **ningún** archivo del backend.

El Doc B propone en sus Opciones 2 y 3 usar **`asyncio` + `aiohttp`**. Esto crea **fricción arquitectónica**:

1. **Flask WSGI no ejecuta corutinas nativamente.** Mezclar asyncio dentro de Flask síncrono requiere levantar un event loop en un thread separado (`asyncio.run()` en un `threading.Thread`), lo cual es propenso a errores y anula gran parte del beneficio de asyncio.
2. **Dos modelos mentales coexisten**: threads (captura, MJPEG) y asyncio (inferencia). Esto complica el debugging y el razonamiento sobre concurrencia.
3. **`aiohttp` no está en [`requirements.txt`](../Backend/requirements.txt:1)** y `flask-socketio` tampoco.

### La ventaja de Doc A

El Doc A mantiene el **paradigma existente**: todas sus opciones usan `threading.Thread` o `concurrent.futures.ProcessPoolExecutor`, que se integran limpiamente con el `CameraManager` y el generador MJPEG actuales. No introducen un segundo modelo de concurrencia. Esto significa:
- Menor riesgo de integración.
- El equipo no necesita aprender asyncio de golpe.
- El rate limiter [`Flask-Limiter`](../Backend/middleware/rate_limiter.py) sigue funcionando sin cambios.

**Veredicto:** Para un proyecto síncrono como Argos2, **el enfoque de Doc A (threads/multiprocessing) es más coherente y seguro**. Si se quisiera asyncio, habría que migrar primero el framework a Quart/ASGI, lo cual es un proyecto aparte.

---

## 4. Dimensiones que Cada Documento Cubre Exclusivamente

### Fortalezas exclusivas del Doc A

| Dimensión | Por qué importa |
|-----------|-----------------|
| **Opción de inferencia local/edge** | Único enfoque que garantiza privacidad, costo cero y operación offline — crítico para vigilancia |
| **Fidelidad al código real** | Referencia `deque(maxlen=2)`, `_frame_deque`, locks, línea `get_frame()` con números de línea exactos |
| **Overlay sobre frame crudo** | Ilusión continua técnicamente superior a repetir frames |
| **Análisis de privacidad** | Fila "Privacidad (frames salen)" en la comparativa |
| **Ruta de evolución explícita** | Fase 1 → Fase 2 → Fase 3 con diagrama Mermaid |
| **Triple buffer** | En la Opción 3 detalla un triple buffer para evitar bloqueo del generador |

### Fortalezas exclusivas del Doc B

| Dimensión | Por qué importa |
|-----------|-----------------|
| **Smart sampling con detección de movimiento** | Optimización de costo real (40-70% menos API calls) — idea muy valiosa |
| **WebSocket para entrega de resultados** | Mejor UX que polling para datos de detección en tiempo real |
| **Separación visualización/análisis** | Arquitectónicamente elegante (MJPEG directo + WebSocket datos) |
| **Estimaciones de LOC** | Más concretas (300-800 líneas) para planificar esfuerzo |
| **FrameSelector con prioridad** | Cola de prioridad con urgencia es un patrón robusto |
| **Métricas observables** | `vision_stats` (fps, cola, latencia) vía WebSocket |

---

## 5. Tabla Comparativa de Cobertura

| Criterio de evaluación | Doc A | Doc B |
|------------------------|-------|-------|
| Fidelidad al códigobase existente | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| Coherencia del modelo de concurrencia | ⭐⭐⭐⭐⭐ (threads) | ⭐⭐⭐ (mezcla asyncio+threads) |
| Profundidad técnica por opción | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Calidad de la "ilusión continua" | ⭐⭐⭐⭐⭐ (overlay) | ⭐⭐⭐ (repetir frame) |
| Cobertura de privacidad | ⭐⭐⭐⭐⭐ | ⭐ |
| Optimización de costo cloud | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ (smart sampling) |
| Innovación en UX | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ (WebSocket) |
| Accionabilidad (qué archivos cambian) | ⭐⭐⭐⭐⭐ (tabla por archivo) | ⭐⭐⭐ (LOC globales) |
| Diagramas Mermaid | ⭐⭐⭐⭐ | ⭐⭐⭐ (ASCII) |
| Estimación de esfuerzo | ⭐⭐⭐ (cualitativa) | ⭐⭐⭐⭐⭐ (LOC) |

---

## 6. Veredicto y Síntesis

### ¿Qué documento es mejor?

**Depende del objetivo, pero para Argos2 específicamente, el Doc A es más adecuado** por tres razones:

1. **Respeta el paradigma del proyecto.** Argos2 es Flask síncrono con threads. Introducir asyncio (Doc B) es una deuda técnica que paga con complejidad. El Doc A extiende lo existente sin cambiar el modelo mental.

2. **Aborda la privacidad.** Un sistema de vigilancia donde las imágenes salen a un proveedor cloud tiene un problema grave de cumplimiento y seguridad. Solo el Doc A ofrece la opción local/edge que resuelve esto definitivamente.

3. **Su ilusión continua es objetivamente mejor.** Dibujar cajas stale sobre frames frescos a 15-30 fps produce video genuinamente fluido; repetir un frame anotado a 5 fps produce video entrecortado.

### Lo que el Doc A debería ABSORBER del Doc B

El Doc B tiene **dos ideas que enriquecerían enormemente al Doc A** y deberían incorporarse:

1. **Smart sampling con detección de movimiento** en la Proposición 2 (muestreo HTTP). En vez de muestrear a intervalo fijo, usar `cv2.absdiff` entre frames para detectar movimiento y solo enviar a Roboflow cuando hay cambios significativos. Esto reduce API calls 40-70% sin perder la opción cloud. Esta idea encaja perfectamente en el pipeline de overlay de Doc A.

2. **WebSocket/SSE para datos de detección** (no para video). Aunque Doc A ya menciona SSE, el Doc B detalla mejor el broadcaster de resultados (`vision_result_{camera_id}`, métricas, estado). Esto complementa (no reemplaza) el MJPEG de Doc A.

### Opción sintetizada recomendada

La combinación óptima sería:

> **Pipeline de Doc A (Proposición 2: overlay sobre frame crudo + threads) + Smart sampling con detección de movimiento de Doc B + Inferencia local de Doc A (Proposición 3) como evolución a producción.**

Esto da: video fluido (overlay), costo controlado (smart sampling), privacidad total (inferencia local en producción), y cero fricción con asyncio (todo threads/multiprocessing).

---

> **Documento comparativo generado para Argos2** — Análisis objetivo entre dos enfoques arquitectónicos para integración de Roboflow.
