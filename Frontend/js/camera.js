/**
 * Camera.js - Módulo de monitoreo de cámaras en vivo para Argos2
 * Gestiona descubrimiento, streaming MJPEG, grid responsive y fullscreen.
 *
 * Dependencias: toast.js (showToast), dashboard.js (DASHBOARD)
 * Se auto-inicializa en DOMContentLoaded.
 */
const CAMERA = {
    API_BASE: '/api/cameras',
    cameras: [],            // Lista de cámaras descubiertas/activas
    activeStreams: {},      // Mapa cameraId -> { imgEl, reconnectTimer, failCount, lowRateTimer }
    refreshInterval: null,  // Intervalo de refresh de estado (cada 10 s)
    discoverRunning: false, // Flag para evitar descubrimientos simultáneos
    _loadingPromise: null,  // Cache de promesa para deduplicar loadCameras()
    tabActive: false,       // Si el tab Monitoreo está activo

    // Backoff de reconexión en ms
    RECONNECT_DELAYS: [3000, 6000, 12000, 30000],
    MAX_FAIL_COUNT: 5,

    // Vision (IA anotada)
    visionModes: ['off'],           // Modos disponibles (cargados del backend vía /vision/modes)
    visionState: {},                // Mapa cameraId -> { mode: 'off'|'cloud'|'local', loading: bool }
    _singleCameraId: null,          // ID de la cámara mostrada en la vista panorámica (single)

    // === Captura de imágenes ===
    captureStream: null,        // Stream actual del tab captura
    selectedCameraId: null,     // Cámara seleccionada para captura
    captureGallery: [],         // Array de capturas recientes {id, url, timestamp, cameraName}
    MAX_GALLERY_ITEMS: 12,      // Máximo de items en galería
    lastCaptureData: null,      // Datos de la última captura {type, url, filename, blob?, path?, cameraName, timestamp}
    currentTab: 'monitoreo',    // Tab actualmente activo

    // ===================================================================
    // === INICIALIZACIÓN ===
    // ===================================================================

    init() {
        // Escuchar evento de cambio de tab emitido por DASHBOARD
        document.addEventListener('tabChanged', (e) => {
            if (e.detail.tab === 'monitoreo') {
                this.onTabActivated();
            } else {
                this.onTabDeactivated();
            }

            // Captura tab handling
            if (e.detail.tab === 'captura') {
                this.onCaptureTabActivated();
            } else if (this.currentTab === 'captura') {
                this.onCaptureTabDeactivated();
            }

            this.currentTab = e.detail.tab;
        });

        // Botón descubrir cámaras
        const btnDiscover = document.getElementById('btn-discover');
        if (btnDiscover) {
            btnDiscover.addEventListener('click', () => this.discoverCameras());
        }

        // Si el tab Monitoreo ya está activo al cargar (default)
        const monPanel = document.getElementById('tab-monitoreo');
        if (monPanel && monPanel.classList.contains('active')) {
            this.tabActive = true;
            this.loadCameras();
            this.refreshInterval = setInterval(() => this.refreshStatus(), 10000);
        }

        // Inicializar tab de captura
        this.initCaptureTab();
    },

    // ===================================================================
    // === DESCUBRIMIENTO ===
    // ===================================================================

    async discoverCameras() {
        if (this.discoverRunning) return;
        this.discoverRunning = true;

        const btnDiscover = document.getElementById('btn-discover');
        const originalText = btnDiscover ? btnDiscover.innerHTML : '';

        // Estado de carga en el botón
        if (btnDiscover) {
            btnDiscover.disabled = true;
            btnDiscover.innerHTML = '<img src="assets/icons/senal.svg" class="btn-icon" alt=""> Buscando...';
        }

        if (typeof showToast === 'function') showToast('Buscando cámaras conectadas...', 'info');

        try {
            const res = await fetch(`${this.API_BASE}/discover`, {
                headers: this.getAuthHeaders()
            });

            if (res.status === 401) {
                this.handleAuthError();
                return;
            }

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `Error ${res.status}`);
            }

            const data = await res.json();
            const discovered = data.cameras || [];

            if (discovered.length === 0) {
                if (typeof showToast === 'function') showToast('No se encontraron cámaras USB', 'warning');
            } else {
                // Auto-agregar cada cámara USB descubierta
                let added = 0;
                for (const cam of discovered) {
                    try {
                        const addRes = await fetch(this.API_BASE, {
                            method: 'POST',
                            headers: {
                                ...this.getAuthHeaders(),
                                'Content-Type': 'application/json'
                            },
                            body: JSON.stringify({
                                type: 'usb',
                                name: cam.name || `Cámara USB ${cam.camera_index !== undefined ? cam.camera_index : added}`,
                                camera_index: cam.camera_index !== undefined ? cam.camera_index : added,
                                source: cam.source || cam.device_path || `/dev/video${cam.camera_index || 0}`
                            })
                        });

                        if (addRes.ok) {
                            added++;
                        } else {
                            const errBody = await addRes.json().catch(() => ({}));
                            console.warn(`[CAMERA] No se pudo agregar cámara: ${errBody.error}`);
                        }
                    } catch (addErr) {
                        console.warn('[CAMERA] Error agregando cámara descubierta:', addErr);
                    }
                }

                if (added > 0 && typeof showToast === 'function') {
                    showToast(`${added} cámara(s) USB agregada(s)`, 'success');
                }
            }

            // Recargar lista de cámaras
            await this.loadCameras();

        } catch (err) {
            console.error('[CAMERA] Error en discoverCameras:', err);
            if (typeof showToast === 'function') showToast('Error al buscar cámaras', 'error');
        } finally {
            this.discoverRunning = false;
            if (btnDiscover) {
                btnDiscover.disabled = false;
                btnDiscover.innerHTML = originalText;
            }
        }
    },

    async loadCameras() {
        // Dedup: si ya hay una carga en progreso, reutilizar la misma promesa
        if (this._loadingPromise) return this._loadingPromise;

        this._loadingPromise = this._executeLoadCameras();
        try {
            return await this._loadingPromise;
        } finally {
            this._loadingPromise = null;
        }
    },

    async _executeLoadCameras() {
        try {
            const res = await fetch(this.API_BASE, {
                headers: this.getAuthHeaders()
            });

            if (res.status === 401) {
                this.handleAuthError();
                return;
            }

            if (!res.ok) {
                throw new Error(`Error ${res.status}`);
            }

            const data = await res.json();
            this.cameras = data.cameras || [];
            this.renderCameraView();
            this.updateStatusBar();

            // Actualizar selector de cámara en tab captura
            this.loadCameraSelector();

            // Cargar modos de visión disponibles y sincronizar estado con el backend
            this.loadVisionModes().then(() => {
                this.refreshVisionAvailability();
                this.syncAllVisionStatus();
            });

        } catch (err) {
            console.error('[CAMERA] Error cargando cámaras:', err);
            this.cameras = [];
            this.renderCameraView();
            this.loadCameraSelector();
        }
    },

    // ===================================================================
    // === RENDERIZADO ===
    // ===================================================================

    renderCameraView() {
        const noCameras = document.getElementById('no-cameras');
        const singleView = document.getElementById('single-camera');
        const gridView = document.getElementById('camera-grid');

        // Ocultar todas las vistas
        if (noCameras) noCameras.style.display = 'none';
        if (singleView) singleView.style.display = 'none';
        if (gridView) gridView.style.display = 'none';

        // Detener streams anteriores antes de renderizar
        this.stopAllStreams();
        this._singleCameraId = null;

        if (this.cameras.length === 0) {
            if (noCameras) noCameras.style.display = 'flex';

        } else if (this.cameras.length === 1) {
            if (singleView) {
                singleView.style.display = 'flex';
                this.renderSingleView(this.cameras[0]);
            }

        } else {
            if (gridView) {
                gridView.style.display = 'grid';
                this.renderGrid(this.cameras);
            }
        }
    },

    renderSingleView(camera) {
        const singleView = document.getElementById('single-camera');
        if (!singleView) return;

        const card = singleView.querySelector('.camera-card');
        if (!card) return;

        // Nombre
        const nameEl = card.querySelector('.camera-name');
        if (nameEl) nameEl.textContent = camera.name || 'Cámara';

        // Tipo badge
        const typeBadge = card.querySelector('.camera-type-badge');
        if (typeBadge) {
            typeBadge.textContent = this.getTypeLabel(camera.type);
            typeBadge.className = `camera-type-badge ${camera.type || 'usb'}`;
        }

        // Latency badge
        const latBadge = card.querySelector('.latency-badge');
        if (latBadge) latBadge.textContent = '--ms';

        // Fullscreen button
        const fsBtn = card.querySelector('.btn-fullscreen');
        if (fsBtn) {
            fsBtn.onclick = () => {
                if (typeof DASHBOARD !== 'undefined') {
                    DASHBOARD.openFullscreen(camera.id, camera.name);
                }
            };
        }

        // Inyectar selector de visión (segmented control) si no existe aún
        const controls = card.querySelector('.camera-controls');
        if (controls && !controls.querySelector('.vision-control')) {
            controls.insertAdjacentHTML('afterbegin', this._visionControlHTML(camera.id));
        }

        // Registrar cámara actual y configurar selector de visión
        this._singleCameraId = camera.id;
        this._initVisionSelector(card, camera.id);

        // Iniciar stream a bajo rate (1 fps)
        if (this.tabActive) {
            this.startSingleLowRate(camera.id, card.querySelector('.stream-img'));
        }
    },

    renderGrid(cameras) {
        const grid = document.getElementById('camera-grid');
        if (!grid) return;

        // Limpiar contenido previo
        grid.innerHTML = '';

        // Determinar clase de grid responsive
        grid.className = 'camera-grid';
        const count = cameras.length;
        if (count >= 7) {
            grid.classList.add('grid-4');
        } else if (count >= 5) {
            grid.classList.add('grid-3');
        } else {
            grid.classList.add('grid-2');
        }

        // Crear tarjetas
        cameras.forEach(camera => {
            const card = this.createCameraCard(camera);
            grid.appendChild(card);
        });

        // Iniciar streams de todas las cámaras
        if (this.tabActive) {
            cameras.forEach(camera => this.startStream(camera.id));
        }
    },

    createCameraCard(camera) {
        const card = document.createElement('div');
        card.className = 'camera-card';
        card.dataset.cameraId = camera.id;

        card.innerHTML = `
            <div class="camera-header">
                <span class="camera-name">${this.escapeHtml(camera.name || 'Cámara')}</span>
                <span class="camera-type-badge ${camera.type || 'usb'}">${this.getTypeLabel(camera.type)}</span>
                <span class="latency-badge good">--ms</span>
            </div>
            <div class="camera-feed">
                <img class="stream-img" alt="Feed de ${this.escapeHtml(camera.name || 'Cámara')}">
                <div class="camera-feed-overlay disconnected" style="display:none;">
                    <img src="assets/icons/senal-off.svg" alt="">
                    <span>Sin señal</span>
                </div>
            </div>
            <div class="camera-controls">
                ${this._visionControlHTML(camera.id)}
                <button class="btn-icon-only btn-fullscreen" title="Pantalla completa">
                    <img src="assets/icons/expandir.svg" alt="">
                </button>
            </div>
        `;

        // Inicializar selector de visión (eventos + disponibilidad + estado guardado)
        this._initVisionSelector(card, camera.id);

        // Fullscreen button
        const fsBtn = card.querySelector('.btn-fullscreen');
        if (fsBtn) {
            fsBtn.addEventListener('click', () => {
                if (typeof DASHBOARD !== 'undefined') {
                    DASHBOARD.openFullscreen(camera.id, camera.name);
                }
            });
        }

        return card;
    },

    // ===================================================================
    // === STREAMING ===
    // ===================================================================

    startStream(cameraId) {
        // Si ya existe un stream activo, no duplicar
        if (this.activeStreams[cameraId]) return;

        const card = document.querySelector(`.camera-card[data-camera-id="${cameraId}"]`);
        if (!card) return;

        const imgEl = card.querySelector('.stream-img');
        const overlay = card.querySelector('.camera-feed-overlay');
        if (!imgEl) return;

        // Ocultar overlay de "Sin señal"
        if (overlay) overlay.style.display = 'none';

        // Registrar stream activo
        const streamInfo = {
            imgEl: imgEl,
            overlay: overlay,
            card: card,
            reconnectTimer: null,
            failCount: 0,
            lowRateTimer: null
        };
        this.activeStreams[cameraId] = streamInfo;

        // Configurar src del stream MJPEG
        imgEl.src = this.getStreamUrl(cameraId);

        // Error handler para reconexión automática
        imgEl.onerror = () => {
            this.handleStreamError(cameraId);
        };

        // Load handler — resetear fail count al conectar exitosamente
        imgEl.onload = () => {
            if (this.activeStreams[cameraId]) {
                this.activeStreams[cameraId].failCount = 0;
            }
            if (overlay) overlay.style.display = 'none';
        };

        console.log(`[CAMERA] Stream iniciado: ${cameraId}`);
    },

    stopStream(cameraId) {
        const stream = this.activeStreams[cameraId];
        if (!stream) return;

        // Limpiar imagen
        if (stream.imgEl) {
            stream.imgEl.onerror = null;
            stream.imgEl.onload = null;
            stream.imgEl.src = '';
        }

        // Cancelar timers
        if (stream.reconnectTimer) {
            clearTimeout(stream.reconnectTimer);
            stream.reconnectTimer = null;
        }
        if (stream.lowRateTimer) {
            clearTimeout(stream.lowRateTimer);
            stream.lowRateTimer = null;
        }

        // Mostrar overlay
        if (stream.overlay) {
            stream.overlay.style.display = 'flex';
        }

        delete this.activeStreams[cameraId];
        console.log(`[CAMERA] Stream detenido: ${cameraId}`);
    },

    stopAllStreams() {
        const ids = Object.keys(this.activeStreams);
        ids.forEach(id => this.stopStream(id));
    },

    /**
     * Vista de cámara única: actualiza la imagen cada 1000 ms (1 fps)
     * en lugar de usar stream MJPEG continuo para ahorrar bandwidth.
     */
    startSingleLowRate(cameraId, imgEl) {
        if (!imgEl) return;

        // Si ya existe un stream para esta cámara, detenerlo
        this.stopStream(cameraId);

        const streamInfo = {
            imgEl: imgEl,
            overlay: null,
            card: null,
            reconnectTimer: null,
            failCount: 0,
            lowRateTimer: null
        };
        this.activeStreams[cameraId] = streamInfo;

        const updateFrame = () => {
            // Verificar que el stream sigue activo
            if (!this.activeStreams[cameraId]) return;
            if (!this.tabActive) return;

            const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
            imgEl.src = `${this.API_BASE}/${cameraId}/frame?token=${token}&t=${Date.now()}`;
            streamInfo.lowRateTimer = setTimeout(updateFrame, 1000);
        };

        // Primer frame
        updateFrame();

        // Error handler
        imgEl.onerror = () => {
            streamInfo.failCount = (streamInfo.failCount || 0) + 1;
            if (streamInfo.failCount < this.MAX_FAIL_COUNT) {
                // Reintentar en el próximo ciclo
                console.warn(`[CAMERA] Frame error (intento ${streamInfo.failCount}): ${cameraId}`);
            } else {
                console.error(`[CAMERA] Demasiados errores de frame, deteniendo: ${cameraId}`);
                // Buscar overlay en single view
                const singleView = document.getElementById('single-camera');
                const overlay = singleView ? singleView.querySelector('.camera-feed-overlay') : null;
                if (overlay) overlay.style.display = 'flex';
            }
        };

        imgEl.onload = () => {
            streamInfo.failCount = 0;
            const singleView = document.getElementById('single-camera');
            const overlay = singleView ? singleView.querySelector('.camera-feed-overlay') : null;
            if (overlay) overlay.style.display = 'none';
        };

        console.log(`[CAMERA] Stream low-rate iniciado: ${cameraId}`);
    },

    // ===================================================================
    // === RECONEXIÓN AUTOMÁTICA ===
    // ===================================================================

    handleStreamError(cameraId) {
        const stream = this.activeStreams[cameraId];
        if (!stream) return;

        stream.failCount = (stream.failCount || 0) + 1;

        // Mostrar overlay "Sin señal"
        if (stream.overlay) {
            stream.overlay.style.display = 'flex';
        }

        // Actualizar badge de latencia a error
        this.updateLatencyBadge(cameraId, -1);

        if (stream.failCount >= this.MAX_FAIL_COUNT) {
            console.error(`[CAMERA] Stream ${cameraId} superó ${this.MAX_FAIL_COUNT} fallos, marcando como desconectada`);
            // Actualizar badge de estado en la tarjeta
            const latBadge = stream.card ? stream.card.querySelector('.latency-badge') : null;
            if (latBadge) {
                latBadge.textContent = 'Desconectada';
                latBadge.className = 'latency-badge bad';
            }
            return;
        }

        // Calcular delay con backoff
        const delayIndex = Math.min(stream.failCount - 1, this.RECONNECT_DELAYS.length - 1);
        const delay = this.RECONNECT_DELAYS[delayIndex];

        console.warn(`[CAMERA] Stream error en ${cameraId} (intento ${stream.failCount}), reconectando en ${delay}ms`);

        // Cancelar timer anterior si existe
        if (stream.reconnectTimer) {
            clearTimeout(stream.reconnectTimer);
        }

        stream.reconnectTimer = setTimeout(() => {
            this.reconnectStream(cameraId);
        }, delay);
    },

    reconnectStream(cameraId) {
        const stream = this.activeStreams[cameraId];
        if (!stream || !this.tabActive) return;

        console.log(`[CAMERA] Reintentando conexión: ${cameraId}`);

        // Actualizar src con timestamp para evitar cache
        stream.imgEl.src = this.getStreamUrl(cameraId);
    },

    // ===================================================================
    // === ESTADO ===
    // ===================================================================

    async refreshStatus() {
        if (!this.tabActive || this.cameras.length === 0) return;

        for (const camera of this.cameras) {
            try {
                const startTime = Date.now();
                const res = await fetch(`${this.API_BASE}/${camera.id}/status`, {
                    headers: this.getAuthHeaders()
                });

                if (res.status === 401) {
                    this.handleAuthError();
                    return;
                }

                if (!res.ok) continue;

                const data = await res.json();
                const latency = Date.now() - startTime;

                // Actualizar datos de la cámara en la lista local
                camera.is_running = data.is_running;
                camera.name = data.name || camera.name;

                // Actualizar badge de latencia
                this.updateLatencyBadge(camera.id, latency);

                // Si la cámara se detuvo en el backend pero el stream sigue activo
                if (!data.is_running && this.activeStreams[camera.id]) {
                    this.stopStream(camera.id);
                }

            } catch (err) {
                // Silencioso — no saturar con errores de status
                console.warn(`[CAMERA] Error obteniendo status de ${camera.id}:`, err.message);
            }
        }

        this.updateStatusBar();
    },

    updateStatusBar() {
        const countEl = document.getElementById('cameras-count');
        const updateEl = document.getElementById('last-update');

        const activeCount = this.cameras.filter(c => c.is_running !== false).length;
        const total = this.cameras.length;

        if (countEl) {
            countEl.textContent = `${activeCount}/${total} cámara(s) conectada(s)`;
        }

        if (updateEl) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString('es-VE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            updateEl.textContent = `Última actualización: ${timeStr}`;
        }
    },

    updateLatencyBadge(cameraId, latencyMs) {
        // Buscar tarjeta en grid o en single view
        let card = document.querySelector(`.camera-card[data-camera-id="${cameraId}"]`);
        if (!card) {
            // Podría ser la tarjeta single
            const singleView = document.getElementById('single-camera');
            card = singleView ? singleView.querySelector('.camera-card') : null;
        }
        if (!card) return;

        const badge = card.querySelector('.latency-badge');
        if (!badge) return;

        if (latencyMs < 0) {
            badge.textContent = 'Sin señal';
            badge.className = 'latency-badge bad';
            return;
        }

        badge.textContent = `${latencyMs}ms`;

        if (latencyMs < 100) {
            badge.className = 'latency-badge good';
        } else if (latencyMs <= 300) {
            badge.className = 'latency-badge medium';
        } else {
            badge.className = 'latency-badge bad';
        }
    },

    // ===================================================================
    // === TAB ACTIVATION ===
    // ===================================================================

    onTabActivated() {
        this.tabActive = true;
        this.loadCameras();
        this.refreshInterval = setInterval(() => this.refreshStatus(), 10000);
    },

    onTabDeactivated() {
        this.tabActive = false;
        this.stopAllStreams();
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    },

    // ===================================================================
    // === VISIÓN (IA ANOTADA) ===
    // Lógica del segmented control Off/Cloud/Local para cada cámara.
    // ===================================================================

    /**
     * Genera el HTML del segmented control de visión para una tarjeta.
     * @private
     */
    _visionControlHTML(cameraId) {
        return `
            <div class="vision-control" data-vision-mode="off">
                <span class="vision-label">Visión</span>
                <div class="vision-segments" role="radiogroup" aria-label="Modo de visión">
                    <button class="vision-segment off active" data-mode="off" type="button" role="radio" aria-checked="true" title="Visión desactivada">Off</button>
                    <button class="vision-segment cloud" data-mode="cloud" type="button" role="radio" aria-checked="false" title="Visión en la nube (Roboflow)">Cloud</button>
                    <button class="vision-segment local" data-mode="local" type="button" role="radio" aria-checked="false" title="Visión local (Edge AI)">Local</button>
                </div>
            </div>
        `;
    },

    /**
     * Configura event listeners y estado inicial del selector de visión.
     * @private
     */
    _initVisionSelector(card, cameraId) {
        // Evitar registrar listeners duplicados cuando la misma tarjeta se
        // re-renderiza (p.ej. la tarjeta estática de la vista single, que
        // persiste entre llamadas a loadCameras()). Se marca con el cameraId
        // para que un cambio de cámara sí reinicialice los listeners.
        if (card.dataset.visionInitCam === cameraId) return;
        card.dataset.visionInitCam = cameraId;

        const segments = card.querySelectorAll('.vision-segment');
        segments.forEach(seg => {
            seg.addEventListener('click', () => {
                if (seg.disabled) return;
                this.setVisionMode(cameraId, seg.dataset.mode);
            });
        });
        // Aplicar disponibilidad según los modos cargados del backend
        this._applyVisionAvailability(card);
        // Estado guardado en localStorage (feedback inmediato antes de la sync)
        const saved = this._getStoredVisionMode(cameraId);
        if (saved && saved !== 'off') {
            this._updateVisionCardUI(card, saved, false);
        }
    },

    /**
     * Consulta al backend los modos de visión disponibles (GET /vision/modes).
     */
    async loadVisionModes() {
        try {
            const res = await fetch(`${this.API_BASE}/vision/modes`, {
                headers: this.getAuthHeaders()
            });
            if (res.status === 401) {
                this.handleAuthError();
                return;
            }
            if (!res.ok) return;
            const data = await res.json();
            this.visionModes = data.modes || ['off'];
        } catch (err) {
            console.warn('[CAMERA] Error cargando modos de visión:', err.message);
        }
    },

    /**
     * Sincroniza el estado de visión de todas las cámaras con el backend.
     */
    async syncAllVisionStatus() {
        for (const camera of this.cameras) {
            await this.syncVisionStatus(camera.id);
        }
    },

    /**
     * Consulta y aplica el estado de visión de una cámara desde el backend
     * (GET /vision/status). El backend es la fuente de verdad.
     */
    async syncVisionStatus(cameraId) {
        try {
            const res = await fetch(`${this.API_BASE}/${cameraId}/vision/status`, {
                headers: this.getAuthHeaders()
            });
            if (res.status === 401) {
                this.handleAuthError();
                return;
            }
            if (!res.ok) return;
            const data = await res.json();
            const mode = data.active ? (data.mode || 'cloud') : 'off';
            this.visionState[cameraId] = { mode, loading: false };
            this.updateVisionSelectorUI(cameraId, mode);
            this._setStoredVisionMode(cameraId, mode);
            // Sincronizar el stream para reflejar el estado real del backend
            this.switchVisionStream(cameraId, mode !== 'off');
        } catch (err) {
            console.warn(`[CAMERA] Error sincronizando visión de ${cameraId}:`, err.message);
        }
    },

    /**
     * Cambia el modo de visión de una cámara.
     * @param {string} cameraId - ID de la cámara.
     * @param {string} mode - 'off' | 'cloud' | 'local'.
     */
    async setVisionMode(cameraId, mode) {
        const current = this.visionState[cameraId] || { mode: 'off', loading: false };
        // Evitar acciones duplicadas o re-selección del mismo modo
        if (current.loading) return;
        if (current.mode === mode) return;

        // Validar que la cámara esté activa antes de activar visión
        if (mode !== 'off') {
            const cam = this.cameras.find(c => c.id === cameraId);
            if (cam && cam.is_running === false) {
                showToast('La cámara no está activa. Inicia la cámara primero.', 'warning');
                // Restaurar el selector al modo real previo (no forzar 'off')
                this.updateVisionSelectorUI(cameraId, current.mode || 'off');
                return;
            }
        }

        // Confirmación al activar modo Local por primera vez (UX 6.7 del plan):
        // advertir sobre los requisitos de hardware del procesamiento en servidor.
        if (mode === 'local' && !this._hasSeenLocalWarning()) {
            const ok = window.confirm(
                'El modo Local (Edge AI) procesa el video en este servidor y ' +
                'requiere mayor capacidad de CPU/GPU.\n\n¿Deseas continuar?'
            );
            this._markLocalWarningSeen();
            if (!ok) {
                // Revertir el selector sin llamar al backend
                this.updateVisionSelectorUI(cameraId, current.mode || 'off');
                return;
            }
        }

        const prevState = current.mode;
        // Estado de carga: la UI refleja el cambio de inmediato
        this.visionState[cameraId] = { mode, loading: true };
        this.updateVisionSelectorUI(cameraId, mode, true);
        this._setStoredVisionMode(cameraId, mode);

        try {
            if (mode === 'off') {
                await this._deactivateVision(cameraId);
                showToast('Visión desactivada', 'info');
            } else {
                await this._activateVision(cameraId, mode);
                showToast(`Visión activada: modo ${mode}`, 'success');
            }
            this.visionState[cameraId] = { mode, loading: false };
            // BUGFIX: refrescar la UI para salir del estado "cargando", detener
            // la animación de pulso y re-habilitar los segmentos según su
            // disponibilidad. Sin esta llamada, el selector quedaba bloqueado
            // hasta la próxima recarga de página.
            this.updateVisionSelectorUI(cameraId, mode, false);
        } catch (err) {
            console.error(`[CAMERA] Error cambiando visión de ${cameraId} a ${mode}:`, err.message);
            showToast(`Error al activar visión (${mode}). Revertiendo…`, 'error');
            // Revertir al estado anterior (selector, persistencia y stream)
            this.visionState[cameraId] = { mode: prevState, loading: false };
            this.updateVisionSelectorUI(cameraId, prevState, false);
            this._setStoredVisionMode(cameraId, prevState);
            this.switchVisionStream(cameraId, prevState !== 'off');
        }
    },

    /**
     * Activa la visión en el backend (POST /vision/start) y conmuta el stream.
     * @private
     */
    async _activateVision(cameraId, mode) {
        const res = await fetch(`${this.API_BASE}/${cameraId}/vision/start`, {
            method: 'POST',
            headers: {
                ...this.getAuthHeaders(),
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ mode })
        });
        if (res.status === 401) {
            this.handleAuthError();
            throw new Error('Sesión expirada');
        }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.error || `Error ${res.status}`);
        }
        // Cambiar al stream MJPEG anotado
        this.switchVisionStream(cameraId, true);
    },

    /**
     * Desactiva la visión en el backend (POST /vision/stop) y restaura el stream.
     * @private
     */
    async _deactivateVision(cameraId) {
        const res = await fetch(`${this.API_BASE}/${cameraId}/vision/stop`, {
            method: 'POST',
            headers: this.getAuthHeaders()
        });
        if (res.status === 401) {
            this.handleAuthError();
            throw new Error('Sesión expirada');
        }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.error || `Error ${res.status}`);
        }
        // Restaurar el stream crudo
        this.switchVisionStream(cameraId, false);
    },

    /**
     * Conmuta el src del <img> entre stream crudo y stream anotado.
     * Gestiona tanto la vista grid (MJPEG continuo) como la single (low-rate).
     */
    switchVisionStream(cameraId, annotated) {
        const stream = this.activeStreams[cameraId];
        const token = typeof getAccessToken === 'function' ? getAccessToken() : '';

        // Resolver el elemento img (grid, single o sin stream activo)
        let imgEl = null;
        let isSingleView = false;
        if (stream && stream.imgEl) {
            imgEl = stream.imgEl;
            isSingleView = stream.card === null;
        } else {
            const singleView = document.getElementById('single-camera');
            imgEl = singleView ? singleView.querySelector('.stream-img') : null;
            isSingleView = !!imgEl;
        }
        if (!imgEl) return;

        if (annotated) {
            // Visión activa: detener el timer low-rate y usar MJPEG anotado
            if (stream && stream.lowRateTimer) {
                clearTimeout(stream.lowRateTimer);
                stream.lowRateTimer = null;
            }
            imgEl.src = `${this.API_BASE}/${cameraId}/vision/stream?token=${token}&t=${Date.now()}`;
        } else {
            // Visión desactivada
            if (isSingleView) {
                // Single view: reiniciar actualización low-rate (1 fps)
                this.startSingleLowRate(cameraId, imgEl);
            } else if (stream) {
                // Grid view: stream MJPEG crudo
                imgEl.src = `${this.API_BASE}/${cameraId}/stream?token=${token}&t=${Date.now()}`;
            }
        }
    },

    /**
     * Actualiza la UI del selector de visión en todas las tarjetas de una cámara.
     */
    updateVisionSelectorUI(cameraId, mode, loading = false) {
        // Tarjetas del grid
        const gridCards = document.querySelectorAll(`.camera-card[data-camera-id="${cameraId}"]`);
        gridCards.forEach(card => this._updateVisionCardUI(card, mode, loading));

        // Tarjeta single (si corresponde a esta cámara)
        if (this._singleCameraId === cameraId) {
            const singleView = document.getElementById('single-camera');
            const singleCard = singleView ? singleView.querySelector('.camera-card') : null;
            if (singleCard) this._updateVisionCardUI(singleCard, mode, loading);
        }
    },

    /**
     * Actualiza las clases de un selector de visión concreto.
     * @private
     */
    _updateVisionCardUI(card, mode, loading) {
        const control = card.querySelector('.vision-control');
        if (!control) return;
        control.dataset.visionMode = mode;

        const segments = control.querySelectorAll('.vision-segment');
        segments.forEach(seg => {
            const isActive = seg.dataset.mode === mode;
            seg.classList.toggle('active', isActive);
            seg.classList.toggle('loading', loading && isActive);
            seg.setAttribute('aria-checked', isActive ? 'true' : 'false');

            if (loading) {
                // Durante la carga: solo el seleccionado queda habilitado
                seg.disabled = !isActive;
            } else {
                // Restaurar disponibilidad según los modos del backend
                const m = seg.dataset.mode;
                seg.disabled = !(m === 'off' || this.visionModes.includes(m));
            }
        });
    },

    /**
     * Aplica la disponibilidad de modos a una tarjeta concreta.
     * @private
     */
    _applyVisionAvailability(card) {
        const segments = card.querySelectorAll('.vision-segment');
        segments.forEach(seg => {
            const m = seg.dataset.mode;
            const available = m === 'off' || this.visionModes.includes(m);
            seg.disabled = !available;
            seg.classList.toggle('unavailable', !available);
        });
    },

    /**
     * Re-aplica la disponibilidad a todas las tarjetas (tras cargar los modos).
     */
    refreshVisionAvailability() {
        const cards = document.querySelectorAll('.camera-card');
        cards.forEach(card => this._applyVisionAvailability(card));
    },

    /**
     * Lee el modo de visión guardado en localStorage.
     * @private
     */
    _getStoredVisionMode(cameraId) {
        try {
            return localStorage.getItem(`vision_mode_${cameraId}`);
        } catch (e) {
            return null;
        }
    },

    /**
     * Guarda el modo de visión en localStorage.
     * @private
     */
    _setStoredVisionMode(cameraId, mode) {
        try {
            localStorage.setItem(`vision_mode_${cameraId}`, mode);
        } catch (e) {
            // localStorage no disponible (ej. modo incógnito) — no es crítico
        }
    },

    /**
     * Indica si el usuario ya vio la advertencia de requisitos de hardware
     * del modo Local (UX 6.7 del plan). Se recuerda una única vez.
     * @private
     */
    _hasSeenLocalWarning() {
        try {
            return localStorage.getItem('vision_local_warned') === '1';
        } catch (e) {
            return true; // si localStorage falla, no molestar con el aviso
        }
    },

    /**
     * Marca la advertencia del modo Local como vista.
     * @private
     */
    _markLocalWarningSeen() {
        try {
            localStorage.setItem('vision_local_warned', '1');
        } catch (e) {
            // no crítico
        }
    },

    // ===================================================================
    // === UTILIDADES ===
    // ===================================================================

    getAuthHeaders() {
        const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
        return { 'Authorization': `Bearer ${token}` };
    },

    getStreamUrl(cameraId) {
        const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
        return `${this.API_BASE}/${cameraId}/stream?token=${token}&t=${Date.now()}`;
    },

    getTypeLabel(type) {
        const labels = { 'usb': 'USB', 'ip': 'IP', 'esp32': 'ESP32', 'webRTC': 'WebRTC' };
        return labels[type] || (type ? type.toUpperCase() : 'N/A');
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    handleAuthError() {
        console.warn('[CAMERA] Token expirado o inválido, redirigiendo a login');
        if (typeof showToast === 'function') showToast('Sesión expirada. Redirigiendo...', 'error');
        if (typeof clearSession === 'function') clearSession();
        setTimeout(() => {
            window.location.href = '/index.html';
        }, 1500);
    },

    // ===================================================================
    // === CAPTURA DE IMÁGENES ===
    // ===================================================================

    initCaptureTab() {
        // 1. Selector de cámara
        const cameraSelect = document.getElementById('capture-camera-select');
        if (cameraSelect) {
            cameraSelect.addEventListener('change', (e) => {
                const cameraId = e.target.value;
                if (cameraId) {
                    this.selectedCameraId = cameraId;
                    this.startCaptureStream(cameraId);
                } else {
                    this.selectedCameraId = null;
                    this.stopCaptureStream();
                }
            });
        }

        // 2. Botón capturar
        const btnCapture = document.getElementById('btn-capture');
        if (btnCapture) {
            btnCapture.addEventListener('click', () => this.capturePhoto());
        }

        // 3. Botón procesar
        const btnProcess = document.getElementById('btn-process-capture');
        if (btnProcess) {
            btnProcess.addEventListener('click', () => this.processCapture());
        }

        // 4. Botón guardar (descargar)
        const btnSave = document.getElementById('btn-save-capture');
        if (btnSave) {
            btnSave.addEventListener('click', () => {
                if (this.lastCaptureData) {
                    const filename = this.lastCaptureData.filename || `captura_${Date.now()}.jpg`;
                    this.downloadCapture(this.lastCaptureData.url, filename);
                }
            });
        }

        // 5. Botón descartar
        const btnDiscard = document.getElementById('btn-discard-capture');
        if (btnDiscard) {
            btnDiscard.addEventListener('click', () => this.hideCapturePreview());
        }

        // Restaurar galería de sessionStorage
        this.restoreGallery();
    },

    loadCameraSelector() {
        const cameraSelect = document.getElementById('capture-camera-select');
        if (!cameraSelect) return;

        // Limpiar opciones existentes (mantener placeholder)
        cameraSelect.innerHTML = '<option value="">-- Seleccionar --</option>';

        // Agregar cámaras disponibles
        this.cameras.forEach(camera => {
            const option = document.createElement('option');
            option.value = camera.id;
            option.textContent = `${camera.name || 'Cámara'} [${this.getTypeLabel(camera.type)}]`;
            cameraSelect.appendChild(option);
        });

        // Restaurar selección previa si aún existe
        if (this.selectedCameraId) {
            const exists = this.cameras.some(c => c.id === this.selectedCameraId);
            if (exists) {
                cameraSelect.value = this.selectedCameraId;
            } else {
                this.selectedCameraId = null;
            }
        }
    },

    onCaptureTabActivated() {
        this.loadCameraSelector();
        if (this.selectedCameraId) {
            this.startCaptureStream(this.selectedCameraId);
        } else {
            // Mostrar estado "Selecciona una cámara"
            const streamEl = document.getElementById('capture-stream');
            if (streamEl) streamEl.src = '';
        }
    },

    onCaptureTabDeactivated() {
        this.stopCaptureStream();
    },

    startCaptureStream(cameraId) {
        const streamEl = document.getElementById('capture-stream');
        if (!streamEl) return;

        // Detener stream anterior si existe
        this.stopCaptureStream();

        // Iniciar nuevo stream
        const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
        streamEl.src = `${this.API_BASE}/${cameraId}/stream?token=${token}&t=${Date.now()}`;

        // Mostrar overlay "EN VIVO"
        const overlay = document.querySelector('.live-view-overlay');
        if (overlay) overlay.style.display = 'flex';

        // Habilitar botón captura
        const btnCapture = document.getElementById('btn-capture');
        if (btnCapture) btnCapture.disabled = false;

        this.captureStream = { cameraId, imgEl: streamEl };

        console.log(`[CAMERA] Capture stream iniciado: ${cameraId}`);
    },

    stopCaptureStream() {
        if (!this.captureStream) return;

        const streamEl = this.captureStream.imgEl;
        if (streamEl) {
            streamEl.onerror = null;
            streamEl.onload = null;
            streamEl.src = '';
        }

        // Deshabilitar botón captura
        const btnCapture = document.getElementById('btn-capture');
        if (btnCapture) btnCapture.disabled = true;

        this.captureStream = null;
        console.log('[CAMERA] Capture stream detenido');
    },

    async capturePhoto() {
        if (!this.selectedCameraId) {
            if (typeof showToast === 'function') showToast('Selecciona una cámara primero', 'warning');
            return;
        }

        const btnCapture = document.getElementById('btn-capture');
        const originalHTML = btnCapture ? btnCapture.innerHTML : '';
        if (btnCapture) {
            btnCapture.disabled = true;
            btnCapture.innerHTML = '<img src="assets/icons/captura.svg" class="btn-icon" alt=""> Capturando...';
        }

        try {
            // Método primario: captura via backend endpoint
            const res = await fetch(`${this.API_BASE}/${this.selectedCameraId}/capture`, {
                method: 'POST',
                headers: this.getAuthHeaders()
            });

            if (res.status === 401) {
                this.handleAuthError();
                return;
            }

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `Error ${res.status}`);
            }

            const data = await res.json();
            const imageUrl = data.path; // '/uploads/xxx.jpg'

            // Obtener nombre de la cámara
            const camera = this.cameras.find(c => c.id === this.selectedCameraId);
            const cameraName = camera ? camera.name : 'Cámara';

            // Guardar datos de la última captura
            this.lastCaptureData = {
                type: 'backend',
                url: imageUrl,
                filename: data.filename,
                path: data.path,
                cameraName: cameraName,
                timestamp: new Date()
            };

            // Mostrar preview
            this.showCapturePreview(imageUrl);

            // Efecto flash
            this.triggerFlash();

            // Agregar a galería
            this.addToGallery({
                id: this.generateId(),
                url: imageUrl,
                timestamp: new Date(),
                cameraName: cameraName
            });

            if (typeof showToast === 'function') showToast('Foto capturada exitosamente', 'success');

        } catch (err) {
            console.warn('[CAMERA] Error en captura backend, intentando canvas:', err);
            // Método secundario: captura via canvas del frontend
            try {
                await this.captureViaCanvas();
            } catch (canvasErr) {
                console.error('[CAMERA] Error en captura canvas:', canvasErr);
                if (typeof showToast === 'function') showToast('Error al capturar foto', 'error');
            }
        } finally {
            if (btnCapture) {
                btnCapture.disabled = false;
                btnCapture.innerHTML = originalHTML;
            }
        }
    },

    async captureViaCanvas() {
        const streamEl = document.getElementById('capture-stream');
        if (!streamEl || !streamEl.complete || streamEl.naturalWidth === 0) {
            throw new Error('No hay stream activo para capturar');
        }

        // Crear canvas temporal
        const canvas = document.createElement('canvas');
        canvas.width = streamEl.naturalWidth || 640;
        canvas.height = streamEl.naturalHeight || 480;
        const ctx = canvas.getContext('2d');

        // Dibujar frame actual del stream
        ctx.drawImage(streamEl, 0, 0, canvas.width, canvas.height);

        // Obtener blob JPEG
        const blob = await new Promise((resolve, reject) => {
            canvas.toBlob(
                (b) => b ? resolve(b) : reject(new Error('toBlob retornó null')),
                'image/jpeg',
                0.92
            );
        });

        // Crear URL temporal
        const blobUrl = URL.createObjectURL(blob);

        // Obtener nombre de la cámara
        const camera = this.cameras.find(c => c.id === this.selectedCameraId);
        const cameraName = camera ? camera.name : 'Cámara';

        // Guardar datos de la captura
        this.lastCaptureData = {
            type: 'canvas',
            url: blobUrl,
            blob: blob,
            filename: `captura_${Date.now()}.jpg`,
            cameraName: cameraName,
            timestamp: new Date()
        };

        // Mostrar preview
        this.showCapturePreview(blobUrl);

        // Efecto flash
        this.triggerFlash();

        // Agregar a galería
        this.addToGallery({
            id: this.generateId(),
            url: blobUrl,
            timestamp: new Date(),
            cameraName: cameraName
        });

        if (typeof showToast === 'function') showToast('Foto capturada (modo canvas)', 'success');
    },

    showCapturePreview(imageUrl) {
        const previewSection = document.getElementById('capture-preview');
        const previewImg = document.getElementById('preview-img');
        const btnProcess = document.getElementById('btn-process-capture');
        const btnSave = document.getElementById('btn-save-capture');
        const processOptions = document.getElementById('process-options');
        const overlay = document.querySelector('.live-view-overlay');

        if (previewSection) previewSection.style.display = 'block';
        if (previewImg) previewImg.src = imageUrl;
        if (btnProcess) btnProcess.style.display = 'inline-flex';
        if (btnSave) btnSave.style.display = 'inline-flex';
        if (processOptions) processOptions.style.display = 'flex';

        // Ocultar overlay "EN VIVO" temporalmente
        if (overlay) overlay.style.display = 'none';

        // Ocultar resultado previo si existe
        const captureProcessing = document.getElementById('capture-processing');
        const captureResult = document.getElementById('capture-result');
        if (captureProcessing) captureProcessing.style.display = 'none';
        if (captureResult) captureResult.style.display = 'none';
    },

    hideCapturePreview() {
        const previewSection = document.getElementById('capture-preview');
        const btnProcess = document.getElementById('btn-process-capture');
        const btnSave = document.getElementById('btn-save-capture');
        const processOptions = document.getElementById('process-options');
        const overlay = document.querySelector('.live-view-overlay');

        if (previewSection) previewSection.style.display = 'none';
        if (btnProcess) btnProcess.style.display = 'none';
        if (btnSave) btnSave.style.display = 'none';
        if (processOptions) processOptions.style.display = 'none';

        // Mostrar overlay "EN VIVO" nuevamente
        if (overlay) overlay.style.display = 'flex';

        // Limpiar última captura (revocar blob URL si aplica)
        if (this.lastCaptureData && this.lastCaptureData.type === 'canvas' && this.lastCaptureData.url) {
            URL.revokeObjectURL(this.lastCaptureData.url);
        }
        this.lastCaptureData = null;

        // Ocultar resultado y procesamiento
        const captureProcessing = document.getElementById('capture-processing');
        const captureResult = document.getElementById('capture-result');
        if (captureProcessing) captureProcessing.style.display = 'none';
        if (captureResult) captureResult.style.display = 'none';
    },

    async processCapture() {
        if (!this.lastCaptureData) {
            if (typeof showToast === 'function') showToast('No hay captura para procesar', 'warning');
            return;
        }

        const operationSelect = document.getElementById('capture-operation');
        const operation = operationSelect ? operationSelect.value : 'deteccion';

        // Mostrar sección de procesamiento
        const captureProcessing = document.getElementById('capture-processing');
        const captureTaskStatus = document.getElementById('capture-task-status');
        const captureProgressFill = document.getElementById('capture-progress-fill');

        if (captureProcessing) captureProcessing.style.display = 'block';
        if (captureTaskStatus) captureTaskStatus.textContent = 'Preparando imagen...';
        if (captureProgressFill) captureProgressFill.style.width = '0%';

        // Deshabilitar botón procesar
        const btnProcess = document.getElementById('btn-process-capture');
        const originalHTML = btnProcess ? btnProcess.innerHTML : '';
        if (btnProcess) {
            btnProcess.disabled = true;
            btnProcess.innerHTML = '<img src="assets/icons/procesar.svg" class="btn-icon" alt=""> Procesando...';
        }

        try {
            let file;

            if (this.lastCaptureData.type === 'backend') {
                // Fetch imagen del servidor y convertir a File
                const imgRes = await fetch(this.lastCaptureData.url);
                if (!imgRes.ok) throw new Error('No se pudo obtener la imagen capturada');
                const blob = await imgRes.blob();
                file = new File([blob], this.lastCaptureData.filename, { type: 'image/jpeg' });
            } else if (this.lastCaptureData.type === 'canvas') {
                // Usar blob directamente
                file = new File(
                    [this.lastCaptureData.blob],
                    this.lastCaptureData.filename,
                    { type: 'image/jpeg' }
                );
            }

            if (!file) throw new Error('No se pudo obtener el archivo de imagen');

            if (captureTaskStatus) captureTaskStatus.textContent = 'Enviando al servidor...';

            // Enviar a procesamiento via VISION
            const result = await VISION.processImage(file, operation);

            if (result && result.task_id) {
                if (typeof showToast === 'function') showToast('Imagen enviada a procesamiento', 'success');

                // Polling de estado
                VISION.pollTaskStatus(
                    result.task_id,
                    (status) => {
                        // Progreso
                        if (captureTaskStatus) {
                            const estadoMap = {
                                'PENDING': 'En cola...',
                                'PROCESSING': 'Procesando...',
                                'COMPLETED': 'Completado',
                                'FAILED': 'Error'
                            };
                            const progreso = status.progreso || 0;
                            captureTaskStatus.textContent = `${estadoMap[status.estado] || status.estado} - ${progreso}%`;
                        }
                        if (captureProgressFill) {
                            captureProgressFill.style.width = `${status.progreso || 0}%`;
                        }
                    },
                    (status) => {
                        // Completado
                        if (typeof showToast === 'function') showToast('Procesamiento completado', 'success');
                        this.showCaptureResult(status);
                        if (btnProcess) {
                            btnProcess.disabled = false;
                            btnProcess.innerHTML = originalHTML;
                        }
                    },
                    (error) => {
                        // Error
                        if (typeof showToast === 'function') showToast(error, 'error');
                        if (captureTaskStatus) captureTaskStatus.textContent = `Error: ${error}`;
                        if (btnProcess) {
                            btnProcess.disabled = false;
                            btnProcess.innerHTML = originalHTML;
                        }
                    }
                );
            } else {
                throw new Error('No se recibió task_id del servidor');
            }

        } catch (err) {
            console.error('[CAMERA] Error procesando captura:', err);
            if (typeof showToast === 'function') showToast('Error al procesar la captura', 'error');
            if (captureTaskStatus) captureTaskStatus.textContent = `Error: ${err.message}`;
            if (btnProcess) {
                btnProcess.disabled = false;
                btnProcess.innerHTML = originalHTML;
            }
        }
    },

    showCaptureResult(status) {
        const captureResult = document.getElementById('capture-result');
        const captureResultImage = document.getElementById('capture-result-image');
        const captureResultDetails = document.getElementById('capture-result-details');

        if (!captureResult) return;

        captureResult.style.display = 'block';

        if (status.imagen_salida && captureResultImage) {
            captureResultImage.src = status.imagen_salida;
        }

        if (captureResultDetails && status.resultados) {
            let html = '<h4>Detalles del Resultado:</h4>';
            for (const [key, value] of Object.entries(status.resultados)) {
                html += `<p><strong>${key}:</strong> ${value}</p>`;
            }
            captureResultDetails.innerHTML = html;
        }
    },

    addToGallery(captureData) {
        // Agregar al inicio del array
        this.captureGallery.unshift(captureData);

        // Limitar tamaño (FIFO)
        if (this.captureGallery.length > this.MAX_GALLERY_ITEMS) {
            const removed = this.captureGallery.pop();
            if (removed.url && removed.url.startsWith('blob:')) {
                URL.revokeObjectURL(removed.url);
            }
        }

        // Persistir en sessionStorage
        this.saveGallery();

        // Renderizar
        this.renderGallery();
    },

    renderGallery() {
        const grid = document.getElementById('gallery-grid');
        if (!grid) return;

        if (this.captureGallery.length === 0) {
            grid.innerHTML = `
                <div class="empty-gallery">
                    <img src="assets/icons/galeria.svg" class="empty-icon-sm" alt="">
                    <p>Sin capturas recientes</p>
                </div>
            `;
            return;
        }

        grid.innerHTML = '';

        this.captureGallery.forEach(item => {
            const galleryItem = document.createElement('div');
            galleryItem.className = 'gallery-item';
            galleryItem.dataset.captureId = item.id;

            const timeStr = item.timestamp instanceof Date
                ? item.timestamp.toLocaleTimeString('es-VE', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
                : new Date(item.timestamp).toLocaleTimeString('es-VE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

            galleryItem.innerHTML = `
                <img src="${this.escapeHtml(item.url)}" alt="Captura">
                <div class="gallery-item-info">
                    <span class="gallery-item-camera">${this.escapeHtml(item.cameraName)}</span>
                    <span class="gallery-item-time">${timeStr}</span>
                </div>
                <div class="gallery-item-actions">
                    <button class="btn-icon-only btn-gallery-process" title="Procesar">
                        <img src="assets/icons/procesar.svg" alt="">
                    </button>
                    <button class="btn-icon-only btn-gallery-delete" title="Eliminar">✕</button>
                </div>
            `;

            // Event: procesar desde galería
            const btnProcess = galleryItem.querySelector('.btn-gallery-process');
            if (btnProcess) {
                btnProcess.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.processGalleryItem(item);
                });
            }

            // Event: eliminar de galería
            const btnDelete = galleryItem.querySelector('.btn-gallery-delete');
            if (btnDelete) {
                btnDelete.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.removeFromGallery(item.id);
                });
            }

            grid.appendChild(galleryItem);
        });
    },

    async processGalleryItem(item) {
        try {
            let file;
            if (item.url.startsWith('/uploads/')) {
                const res = await fetch(item.url);
                if (!res.ok) throw new Error('No se pudo obtener la imagen');
                const blob = await res.blob();
                file = new File([blob], `captura_${item.id}.jpg`, { type: 'image/jpeg' });
            } else if (item.url.startsWith('blob:')) {
                const res = await fetch(item.url);
                const blob = await res.blob();
                file = new File([blob], `captura_${item.id}.jpg`, { type: 'image/jpeg' });
            }

            if (!file) throw new Error('No se pudo obtener el archivo');

            const operationSelect = document.getElementById('capture-operation');
            const operation = operationSelect ? operationSelect.value : 'deteccion';

            if (typeof showToast === 'function') showToast('Enviando imagen al procesamiento...', 'info');

            const result = await VISION.processImage(file, operation);

            if (result && result.task_id) {
                if (typeof showToast === 'function') showToast('Imagen enviada a procesamiento', 'success');

                const captureProcessing = document.getElementById('capture-processing');
                const captureTaskStatus = document.getElementById('capture-task-status');
                const captureProgressFill = document.getElementById('capture-progress-fill');

                if (captureProcessing) captureProcessing.style.display = 'block';

                VISION.pollTaskStatus(
                    result.task_id,
                    (status) => {
                        if (captureTaskStatus) {
                            const estadoMap = {
                                'PENDING': 'En cola...',
                                'PROCESSING': 'Procesando...',
                                'COMPLETED': 'Completado',
                                'FAILED': 'Error'
                            };
                            captureTaskStatus.textContent = `${estadoMap[status.estado] || status.estado} - ${status.progreso || 0}%`;
                        }
                        if (captureProgressFill) {
                            captureProgressFill.style.width = `${status.progreso || 0}%`;
                        }
                    },
                    (status) => {
                        if (typeof showToast === 'function') showToast('Procesamiento completado', 'success');
                        this.showCaptureResult(status);
                    },
                    (error) => {
                        if (typeof showToast === 'function') showToast(error, 'error');
                    }
                );
            }
        } catch (err) {
            console.error('[CAMERA] Error procesando item de galería:', err);
            if (typeof showToast === 'function') showToast('Error al procesar la imagen', 'error');
        }
    },

    removeFromGallery(captureId) {
        const index = this.captureGallery.findIndex(item => item.id === captureId);
        if (index !== -1) {
            const removed = this.captureGallery.splice(index, 1)[0];
            if (removed.url && removed.url.startsWith('blob:')) {
                URL.revokeObjectURL(removed.url);
            }
            this.saveGallery();
            this.renderGallery();
        }
    },

    downloadCapture(imageUrl, filename) {
        const a = document.createElement('a');
        a.href = imageUrl;
        a.download = filename || `captura_${Date.now()}.jpg`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    },

    // === Persistencia de galería en sessionStorage ===

    saveGallery() {
        try {
            // Solo guardar items con URLs persistentes (no blob:)
            const serializable = this.captureGallery
                .map(item => ({
                    id: item.id,
                    url: item.url,
                    timestamp: item.timestamp instanceof Date ? item.timestamp.toISOString() : item.timestamp,
                    cameraName: item.cameraName
                }))
                .filter(item => !item.url.startsWith('blob:'));

            sessionStorage.setItem('argos_capture_gallery', JSON.stringify(serializable));
        } catch (e) {
            console.warn('[CAMERA] Error guardando galería en sessionStorage:', e);
        }
    },

    restoreGallery() {
        try {
            const saved = sessionStorage.getItem('argos_capture_gallery');
            if (saved) {
                this.captureGallery = JSON.parse(saved).map(item => ({
                    ...item,
                    timestamp: new Date(item.timestamp)
                }));
                this.renderGallery();
            }
        } catch (e) {
            console.warn('[CAMERA] Error restaurando galería de sessionStorage:', e);
            this.captureGallery = [];
        }
    },

    generateId() {
        return Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
    },

    /**
     * Efecto visual flash al capturar una foto.
     * Busca el overlay .flash-overlay dentro del live-view y le aplica
     * la clase .flash temporalmente.
     */
    triggerFlash() {
        const liveView = document.querySelector('.live-view');
        if (!liveView) return;

        let overlay = liveView.querySelector('.flash-overlay');
        if (!overlay) {
            overlay = document.createElement('div');
            overlay.className = 'flash-overlay';
            liveView.appendChild(overlay);
        }

        // Forzar reflow y aplicar animación
        overlay.classList.remove('flash');
        overlay.offsetHeight;
        overlay.classList.add('flash');

        // Limpiar clase después de la animación
        setTimeout(() => {
            overlay.classList.remove('flash');
        }, 500);
    }
};

// Auto-inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    CAMERA.init();
});
