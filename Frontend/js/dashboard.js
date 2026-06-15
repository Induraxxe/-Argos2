/**
 * Dashboard.js - Navegación y gestión del dashboard Argos2
 * Maneja tabs, detección de rol admin, fullscreen y formularios de admin.
 * Compatible con toast.js, auth2.js y vision.js existentes.
 */
const DASHBOARD = {
    currentTab: 'monitoreo',
    isAdmin: false,

    // ─── Inicialización ───

    init() {
        this.checkAdminRole();
        this.setupTabs();
        this.setupFullscreen();
        this.setupAdminForms();
    },

    // ─── Detección de rol admin ───

    checkAdminRole() {
        // Usar las funciones de auth2.js en lugar de leer 'token' directamente
        if (typeof isAdmin === 'function' && isAdmin()) {
            this.isAdmin = true;
            // Mostrar todos los tabs restringidos a administrador (Admin + Ajustes)
            document.querySelectorAll('.tab-admin, .tab-ajustes').forEach(tab => {
                tab.style.display = 'flex';
            });
            this.loadAdminStats();
        }
    },

    // ─── Tabs ───

    setupTabs() {
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const tab = btn.dataset.tab;
                if (tab) {
                    this.switchTab(tab);
                }
            });
        });
    },

    switchTab(tabName) {
        // Desactivar todos los tabs
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => {
            p.classList.remove('active');
            p.style.display = 'none';
        });

        // Activar tab seleccionado
        const tabBtn = document.querySelector(`[data-tab="${tabName}"]`);
        const tabPanel = document.getElementById(`tab-${tabName}`);

        if (tabBtn) tabBtn.classList.add('active');
        if (tabPanel) {
            tabPanel.style.display = 'flex';
            // Forzar reflow antes de agregar la clase active para la animación
            tabPanel.offsetHeight;
            tabPanel.classList.add('active');
        }

        this.currentTab = tabName;

        // Disparar evento personalizado para que otros módulos reaccionen
        document.dispatchEvent(new CustomEvent('tabChanged', { detail: { tab: tabName } }));

        // Si cambiamos al tab admin, recargar stats
        if (tabName === 'admin' && this.isAdmin) {
            this.loadAdminStats();
        }

        // Si cambiamos al tab ajustes, cargar la configuración de visión
        if (tabName === 'ajustes' && this.isAdmin) {
            if (typeof loadVisionSettings === 'function') {
                loadVisionSettings();
            }
        }
    },

    // ─── Fullscreen Modal ───

    setupFullscreen() {
        const btnClose = document.getElementById('btn-close-fullscreen');
        if (btnClose) {
            btnClose.addEventListener('click', () => {
                this.closeFullscreen();
            });
        }

        // ESC para cerrar fullscreen
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeFullscreen();
            }
        });
    },

    openFullscreen(cameraId, cameraName) {
        const modal = document.getElementById('fullscreen-modal');
        if (!modal) return;

        const nameEl = document.getElementById('fullscreen-camera-name');
        const imgEl = document.getElementById('fullscreen-stream');

        if (nameEl) nameEl.textContent = cameraName || 'Cámara';
        if (imgEl) {
            const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
            // Coherencia visual: si la visión está activa para esta cámara,
            // mostrar el stream anotado (con bounding boxes) en pantalla
            // completa, igual que en la tarjeta de monitoreo.
            const visionState = (typeof CAMERA !== 'undefined' && CAMERA.visionState)
                ? CAMERA.visionState[cameraId]
                : null;
            const visionActive = !!(visionState && visionState.mode && visionState.mode !== 'off');
            const base = visionActive ? 'vision/stream' : 'stream';
            imgEl.src = `/api/cameras/${cameraId}/${base}?token=${token}&t=${Date.now()}`;
        }

        modal.style.display = 'flex';
    },

    closeFullscreen() {
        const modal = document.getElementById('fullscreen-modal');
        if (!modal) return;

        const imgEl = document.getElementById('fullscreen-stream');
        if (imgEl) imgEl.src = '';

        modal.style.display = 'none';
    },

    // ─── Admin Forms ───

    setupAdminForms() {
        if (!this.isAdmin) return;

        // Toggle formulario agregar cámara
        const btnAdd = document.getElementById('btn-add-camera');
        const form = document.getElementById('add-camera-form');
        const btnCancel = document.getElementById('btn-cancel-camera');

        if (btnAdd && form) {
            btnAdd.addEventListener('click', () => {
                form.style.display = form.style.display === 'none' ? 'block' : 'none';
            });
        }
        if (btnCancel) {
            btnCancel.addEventListener('click', () => {
                const f = document.getElementById('add-camera-form');
                if (f) f.style.display = 'none';
            });
        }

        // Toggle campos según tipo de cámara
        const typeSelect = document.getElementById('new-camera-type');
        if (typeSelect) {
            typeSelect.addEventListener('change', () => {
                const type = typeSelect.value;
                const fgUrl = document.getElementById('fg-url');
                const fgIp = document.getElementById('fg-ip');
                const fgPort = document.getElementById('fg-port');

                if (fgUrl) fgUrl.style.display = type === 'ip' ? 'block' : 'none';
                if (fgIp) fgIp.style.display = type === 'esp32' ? 'block' : 'none';
                if (fgPort) fgPort.style.display = type === 'esp32' ? 'block' : 'none';
            });
        }

        // Submit formulario
        const cameraForm = document.getElementById('camera-form');
        if (cameraForm) {
            cameraForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.submitNewCamera();
            });
        }

        // Scan ESP32
        const btnScan = document.getElementById('btn-scan-esp32');
        if (btnScan) {
            btnScan.addEventListener('click', () => this.scanESP32());
        }

        // Delegación de eventos en la lista de cámaras admin
        const camerasList = document.getElementById('admin-cameras-list');
        if (camerasList) {
            camerasList.addEventListener('click', (e) => {
                const btn = e.target.closest('button');
                const item = e.target.closest('.admin-camera-item');
                if (!btn || !item) return;

                const cameraId = item.dataset.cameraId;

                if (btn.classList.contains('btn-restart')) {
                    this.restartCamera(cameraId);
                } else if (btn.classList.contains('btn-delete-cam')) {
                    this.deleteCamera(cameraId);
                }
            });
        }
    },

    // ─── Admin Stats ───

    async loadAdminStats() {
        if (!this.isAdmin) return;

        try {
            const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
            const headers = { 'Authorization': `Bearer ${token}` };

            // Stats de cámaras — delegar a CAMERA.loadCameras() para evitar llamada duplicada
            let cameras = [];
            if (typeof CAMERA !== 'undefined' && typeof CAMERA.loadCameras === 'function') {
                await CAMERA.loadCameras();
                cameras = CAMERA.cameras || [];
            } else {
                const camRes = await fetch('/api/cameras', { headers });
                if (this._checkAuthResponse(camRes)) return;
                if (camRes.ok) {
                    const camData = await camRes.json();
                    cameras = camData.cameras || [];
                }
            }

            const statCameras = document.getElementById('stat-cameras');
            const statOnline = document.getElementById('stat-online');

            if (statCameras) statCameras.textContent = cameras.length;
            if (statOnline) statOnline.textContent = cameras.filter(c => c.is_running).length;

            // Renderizar lista de cámaras en el panel admin
            this.renderAdminCamerasList(cameras);

            // Stats de usuarios (GET /api/admin/users)
            try {
                const userRes = await fetch('/api/admin/users', { headers });
                if (this._checkAuthResponse(userRes)) return;
                if (userRes.ok) {
                    const userData = await userRes.json();
                    // El endpoint puede retornar un array directo o {users: [...]}
                    const users = Array.isArray(userData) ? userData : (userData.users || []);
                    const statUsers = document.getElementById('stat-users');
                    if (statUsers) statUsers.textContent = users.length;
                }
            } catch (e) {
                // Endpoint de admin puede no estar disponible
                console.warn('[DASHBOARD] No se pudieron cargar stats de usuarios:', e);
            }

            // Cargar health del sistema
            this.loadSystemHealth();

        } catch (e) {
            console.error('[DASHBOARD] Error cargando stats:', e);
        }
    },

    // ─── Renderizar Lista de Cámaras Admin ───

    renderAdminCamerasList(cameras) {
        const container = document.getElementById('admin-cameras-list');
        if (!container) return;

        // Usar cámaras proporcionadas o intentar obtenerlas de CAMERA
        if (!cameras && typeof CAMERA !== 'undefined' && CAMERA.cameras) {
            cameras = CAMERA.cameras;
        }
        if (!cameras) cameras = [];

        if (cameras.length === 0) {
            container.innerHTML = `
                <div class="admin-empty-cameras">
                    <p>No hay cámaras registradas</p>
                </div>
            `;
            return;
        }

        container.innerHTML = '';

        cameras.forEach(camera => {
            const item = document.createElement('div');
            item.className = 'admin-camera-item';
            item.dataset.cameraId = camera.id;

            const typeName = this._getTypeLabel(camera.type);
            const isOnline = camera.is_running;
            const statusClass = isOnline ? 'online' : 'offline';
            const statusText = isOnline ? '● En línea' : '● Desconectada';

            item.innerHTML = `
                <div class="admin-camera-info">
                    <span class="camera-name">${this._escapeHtml(camera.name || 'Cámara')}</span>
                    <span class="camera-type-badge ${camera.type || 'usb'}">${typeName}</span>
                    <span class="camera-status ${statusClass}">${statusText}</span>
                </div>
                <div class="admin-camera-actions">
                    <button class="btn-icon-only btn-restart" title="Reiniciar">🔄</button>
                    <button class="btn-icon-only btn-delete-cam" title="Eliminar">🗑️</button>
                </div>
            `;

            container.appendChild(item);
        });
    },

    // ─── Reiniciar Cámara ───

    async restartCamera(cameraId) {
        if (!this.isAdmin) return;

        try {
            const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
            const res = await fetch(`/api/cameras/${cameraId}/restart`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (this._checkAuthResponse(res)) return;
            if (res.ok) {
                if (typeof showToast === 'function') showToast('Cámara reiniciada correctamente', 'success');
                this.loadAdminStats();
            } else {
                const err = await res.json().catch(() => ({}));
                if (typeof showToast === 'function') showToast(err.error || 'Error al reiniciar cámara', 'error');
            }
        } catch (e) {
            console.error('[DASHBOARD] Error reiniciando cámara:', e);
            if (typeof showToast === 'function') showToast('Error de conexión al reiniciar', 'error');
        }
    },

    // ─── Eliminar Cámara ───

    async deleteCamera(cameraId) {
        if (!this.isAdmin) return;
        if (!confirm('¿Eliminar esta cámara? Esta acción no se puede deshacer.')) return;

        try {
            const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
            const res = await fetch(`/api/cameras/${cameraId}`, {
                method: 'DELETE',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (this._checkAuthResponse(res)) return;
            if (res.ok) {
                if (typeof showToast === 'function') showToast('Cámara eliminada correctamente', 'success');
                // Refresh admin stats y lista
                this.loadAdminStats();
                // También notificar al módulo CAMERA para actualizar
                if (typeof CAMERA !== 'undefined') CAMERA.loadCameras();
            } else {
                const err = await res.json().catch(() => ({}));
                if (typeof showToast === 'function') showToast(err.error || 'Error al eliminar cámara', 'error');
            }
        } catch (e) {
            console.error('[DASHBOARD] Error eliminando cámara:', e);
            if (typeof showToast === 'function') showToast('Error de conexión al eliminar', 'error');
        }
    },

    // ─── Submit Nueva Cámara ───

    async submitNewCamera() {
        if (!this.isAdmin) return;

        const type = document.getElementById('new-camera-type').value;
        const name = document.getElementById('new-camera-name').value;
        const token = typeof getAccessToken === 'function' ? getAccessToken() : '';

        let config = { type, name };

        if (type === 'ip') {
            config.url = document.getElementById('new-camera-url').value;
            config.source = config.url;
        } else if (type === 'esp32') {
            const ip = document.getElementById('new-camera-ip').value;
            const port = parseInt(document.getElementById('new-camera-port').value) || 80;
            config.ip = ip;
            config.port = port;
            config.source = `http://${ip}:${port}/stream`;
        }

        try {
            const res = await fetch('/api/cameras', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(config)
            });

            if (this._checkAuthResponse(res)) return;
            if (res.ok) {
                if (typeof showToast === 'function') showToast('Cámara registrada exitosamente', 'success');
                const form = document.getElementById('add-camera-form');
                if (form) form.style.display = 'none';
                const cameraForm = document.getElementById('camera-form');
                if (cameraForm) cameraForm.reset();
                // Recargar stats y lista admin
                this.loadAdminStats();
                // Notificar al módulo CAMERA para actualizar
                if (typeof CAMERA !== 'undefined') CAMERA.loadCameras();
            } else {
                const err = await res.json();
                if (typeof showToast === 'function') showToast(err.error || 'Error al registrar cámara', 'error');
            }
        } catch (e) {
            console.error('[DASHBOARD] Error registrando cámara:', e);
            if (typeof showToast === 'function') showToast('Error de conexión', 'error');
        }
    },

    // ─── Escanear ESP32 ───

    async scanESP32() {
        if (!this.isAdmin) return;

        if (typeof showToast === 'function') showToast('Escaneando red local...', 'info');
        const btn = document.getElementById('btn-scan-esp32');
        const originalText = btn ? btn.textContent : '';
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Escaneando...';
        }

        try {
            const token = typeof getAccessToken === 'function' ? getAccessToken() : '';
            const res = await fetch('/api/cameras/esp32/scan', {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (this._checkAuthResponse(res)) {
                if (btn) { btn.disabled = false; btn.textContent = originalText || 'Escanear ESP32'; }
                return;
            }
            if (res.ok) {
                const data = await res.json();
                const devices = data.devices || data.esp32_devices || [];

                if (devices.length === 0) {
                    if (typeof showToast === 'function') showToast('No se encontraron dispositivos ESP32', 'warning');
                } else {
                    if (typeof showToast === 'function') showToast(`Se encontraron ${devices.length} dispositivos ESP32`, 'success');
                    // Mostrar dispositivos encontrados y ofrecer registrarlos
                    this.showESP32Results(devices);
                }
            } else {
                const err = await res.json().catch(() => ({}));
                if (typeof showToast === 'function') showToast(err.error || 'Error en el escaneo', 'error');
            }
        } catch (e) {
            console.error('[DASHBOARD] Error escaneando ESP32:', e);
            if (typeof showToast === 'function') showToast('Error de conexión durante el escaneo', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText || 'Escanear ESP32';
            }
        }
    },

    // ─── Mostrar Resultados ESP32 ───

    showESP32Results(devices) {
        // Buscar o crear contenedor de resultados
        let resultsContainer = document.getElementById('esp32-results');
        if (!resultsContainer) {
            resultsContainer = document.createElement('div');
            resultsContainer.id = 'esp32-results';
            resultsContainer.className = 'esp32-results';
            // Insertar después del botón de escaneo
            const scanBtn = document.getElementById('btn-scan-esp32');
            if (scanBtn && scanBtn.parentElement) {
                scanBtn.parentElement.insertAdjacentElement('afterend', resultsContainer);
            } else {
                const camerasList = document.getElementById('admin-cameras-list');
                if (camerasList) {
                    camerasList.insertAdjacentElement('beforebegin', resultsContainer);
                }
            }
        }

        resultsContainer.innerHTML = '';

        // Título
        const title = document.createElement('h4');
        title.textContent = `Dispositivos ESP32 encontrados (${devices.length}):`;
        title.style.marginBottom = '8px';
        title.style.color = 'var(--text-primary, #fff)';
        resultsContainer.appendChild(title);

        devices.forEach(device => {
            const deviceEl = document.createElement('div');
            deviceEl.className = 'esp32-device';

            const ip = device.ip || '—';
            const port = device.port || 80;
            const deviceName = device.name || `ESP32-CAM (${ip})`;

            deviceEl.innerHTML = `
                <div class="esp32-device-info">
                    <span class="esp32-device-name">${this._escapeHtml(deviceName)}</span>
                    <span class="esp32-device-ip">${this._escapeHtml(ip)}:${port}</span>
                </div>
                <button class="btn-register" data-ip="${this._escapeHtml(ip)}" data-port="${port}" data-name="${this._escapeHtml(deviceName)}">
                    Registrar
                </button>
            `;

            // Event: registrar dispositivo ESP32
            const regBtn = deviceEl.querySelector('.btn-register');
            if (regBtn) {
                regBtn.addEventListener('click', () => {
                    this._preFillESP32Form(ip, port, deviceName);
                });
            }

            resultsContainer.appendChild(deviceEl);
        });
    },

    /**
     * Pre-llenar el formulario de agregar cámara con datos del ESP32
     * y mostrar el formulario.
     */
    _preFillESP32Form(ip, port, name) {
        // Mostrar formulario
        const form = document.getElementById('add-camera-form');
        if (form) form.style.display = 'block';

        // Seleccionar tipo ESP32
        const typeSelect = document.getElementById('new-camera-type');
        if (typeSelect) {
            typeSelect.value = 'esp32';
            typeSelect.dispatchEvent(new Event('change'));
        }

        // Llenar campos
        const nameInput = document.getElementById('new-camera-name');
        if (nameInput) nameInput.value = name || `ESP32-CAM (${ip})`;

        const ipInput = document.getElementById('new-camera-ip');
        if (ipInput) ipInput.value = ip;

        const portInput = document.getElementById('new-camera-port');
        if (portInput) portInput.value = port || 80;

        // Scroll al formulario
        if (form) form.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },

    // ─── Health Check del Sistema ───

    async loadSystemHealth() {
        try {
            const res = await fetch('/health');
            if (res.ok) {
                const data = await res.json();
                // Actualizar o crear sección de health si existe el contenedor
                const healthContainer = document.getElementById('system-health');
                if (healthContainer) {
                    const version = data.version || '—';
                    const status = data.status || '—';
                    const uptime = data.uptime || '—';

                    healthContainer.innerHTML = `
                        <div class="health-item">
                            <span class="health-label">Estado:</span>
                            <span class="health-value ${status === 'ok' ? 'text-success' : 'text-warning'}">${status}</span>
                        </div>
                        <div class="health-item">
                            <span class="health-label">Versión:</span>
                            <span class="health-value">${version}</span>
                        </div>
                        <div class="health-item">
                            <span class="health-label">Uptime:</span>
                            <span class="health-value">${uptime}</span>
                        </div>
                    `;
                }
            }
        } catch (e) {
            // Health endpoint puede no existir, silencioso
            console.warn('[DASHBOARD] Health endpoint no disponible:', e.message);
        }
    },

    // ─── Utilidades internas ───

    _getTypeLabel(type) {
        const labels = { 'usb': 'USB', 'ip': 'IP', 'esp32': 'ESP32', 'webRTC': 'WebRTC' };
        return labels[type] || (type ? type.toUpperCase() : 'N/A');
    },

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /**
     * Verifica si una respuesta HTTP es 401 (sesión expirada).
     * Si lo es, redirige al login. Retorna true si fue 401.
     */
    _checkAuthResponse(response) {
        if (response.status === 401) {
            if (typeof clearSession === 'function') clearSession();
            if (typeof showToast === 'function') showToast('Sesión expirada. Redirigiendo...', 'error');
            setTimeout(() => {
                window.location.href = '/index.html';
            }, 1500);
            return true;
        }
        return false;
    }
};

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    DASHBOARD.init();
});
