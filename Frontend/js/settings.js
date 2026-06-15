/**
 * settings.js - Ajustes de Visión (Roboflow) para Argos2
 *
 * Permite a los administradores ver y modificar la configuración de
 * visión computacional (Roboflow) directamente desde el dashboard.
 *
 * Depende de:
 *   - auth2.js  -> authenticatedFetch(), isAdmin(), clearSession()
 *   - toast.js  -> showToast()
 *
 * Endpoints usados (backend ya implementado):
 *   GET  /api/settings/vision       — lectura (API key enmascarada: ****abcd)
 *   PUT  /api/settings/vision       — actualización (solo admin, recarga motores)
 *   GET  /api/settings/vision/test  — prueba de conectividad (solo admin)
 *
 * Manejo especial de la API key:
 *   El GET devuelve la key enmascarada (****abcd). Por seguridad NO se carga
 *   como valor del input; se muestra como placeholder/ayuda. Al guardar, solo
 *   se envía roboflow_api_key si el admin escribió una clave nueva real
 *   (no vacía y que no empiece con ****). Si se deja vacío, el backend la
 *   mantiene sin sobrescribir.
 */

const SETTINGS_API_URL = '/api/settings/vision';

const SETTINGS = {

    // ─── Inicialización ───

    init() {
        // Protección: solo administradores pueden usar el panel.
        if (typeof isAdmin !== 'function' || !isAdmin()) {
            return;
        }
        this.bindEvents();
    },

    bindEvents() {
        const btnSave = document.getElementById('btn-save-vision');
        if (btnSave) btnSave.addEventListener('click', () => this.save());

        const btnTest = document.getElementById('btn-test-vision');
        if (btnTest) btnTest.addEventListener('click', () => this.test());

        const btnReset = document.getElementById('btn-reset-vision');
        if (btnReset) btnReset.addEventListener('click', () => this.reset());

        const btnToggleKey = document.getElementById('btn-toggle-apikey');
        if (btnToggleKey) btnToggleKey.addEventListener('click', () => this._toggleApiKeyVisibility());
    },

    // ─── Cargar configuración (GET /api/settings/vision) ───

    async load() {
        if (typeof isAdmin !== 'function' || !isAdmin()) return;

        this._setLoading(true);
        try {
            const res = await authenticatedFetch(SETTINGS_API_URL, { method: 'GET' });
            if (this._isUnauthorized(res)) return;
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                if (typeof showToast === 'function') showToast(err.error || 'Error al cargar la configuración', 'error');
                return;
            }
            const data = await res.json();
            // El backend puede devolver {config: {...}} o los campos planos.
            const cfg = data.config || data;
            this._populate(cfg);
        } catch (e) {
            if (typeof showToast === 'function') showToast('Error de conexión al cargar los ajustes', 'error');
        } finally {
            this._setLoading(false);
        }
    },

    // ─── Guardar cambios (PUT /api/settings/vision) ───

    async save() {
        if (typeof isAdmin !== 'function' || !isAdmin()) {
            if (typeof showToast === 'function') showToast('Acción restringida a administradores', 'error');
            return;
        }

        const payload = {};

        // Modo de visión
        const modeEl = document.getElementById('setting-default-mode');
        if (modeEl) payload.vision_default_mode = modeEl.value;

        // ─── API key: manejo especial ───
        // El campo se carga vacío (la key viene enmascarada). Solo enviamos una
        // key nueva si el admin escribió algo que NO empieza con ****.
        const apiKeyInput = document.getElementById('setting-api-key');
        if (apiKeyInput) {
            const key = apiKeyInput.value.trim();
            if (key !== '' && !/^\*+/.test(key)) {
                payload.roboflow_api_key = key;
            }
        }

        // Campos de texto
        this._collectText(payload, 'setting-api-url', 'roboflow_api_url');
        this._collectText(payload, 'setting-workspace', 'roboflow_workspace');
        this._collectText(payload, 'setting-workflow-id', 'roboflow_workflow_id');
        this._collectText(payload, 'setting-image-input', 'roboflow_workflow_image_input');
        this._collectText(payload, 'setting-model-id', 'roboflow_model_id');

        // Booleanos
        payload.roboflow_workflow_use_cache = this._getCheckbox('setting-use-cache');
        payload.roboflow_use_server_overlay = this._getCheckbox('setting-use-overlay');

        const btn = document.getElementById('btn-save-vision');
        this._setBusy(btn, true);
        try {
            const res = await authenticatedFetch(SETTINGS_API_URL, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (this._isUnauthorized(res)) return;
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                if (typeof showToast === 'function') showToast(err.error || 'Error al guardar la configuración', 'error');
                return;
            }
            const data = await res.json();
            const cfg = data.config || {};
            this._populate(cfg); // refresca el formulario (muestra la key enmascarada nueva)

            // Cámaras recargadas en caliente
            const reloaded = Array.isArray(data.reloaded_cameras) ? data.reloaded_cameras : [];
            const n = reloaded.length;
            const msg = n > 0
                ? `Configuración guardada. ${n} cámara${n !== 1 ? 's' : ''} recargada${n !== 1 ? 's' : ''} en caliente.`
                : 'Configuración guardada correctamente.';
            if (typeof showToast === 'function') showToast(msg, 'success');

            // Limpiar el campo de API key (vacío = mantener la actual)
            if (apiKeyInput) apiKeyInput.value = '';
        } catch (e) {
            if (typeof showToast === 'function') showToast('Error de conexión al guardar', 'error');
        } finally {
            this._setBusy(btn, false);
        }
    },

    // ─── Probar conexión (GET /api/settings/vision/test) ───

    async test() {
        if (typeof isAdmin !== 'function' || !isAdmin()) {
            if (typeof showToast === 'function') showToast('Acción restringida a administradores', 'error');
            return;
        }

        const btn = document.getElementById('btn-test-vision');
        this._setBusy(btn, true);
        this._setConnStatus('testing', 'Probando conexión...');
        try {
            const res = await authenticatedFetch(`${SETTINGS_API_URL}/test`, { method: 'GET' });
            if (this._isUnauthorized(res)) return;
            const data = await res.json().catch(() => ({}));
            if (res.ok && data.success) {
                this._setConnStatus('ok', data.message || 'Conexión exitosa');
                if (typeof showToast === 'function') showToast(data.message || 'Conexión exitosa con Roboflow', 'success');
            } else {
                this._setConnStatus('error', data.message || 'Sin conexión');
                if (typeof showToast === 'function') showToast(data.message || 'No se pudo conectar con Roboflow', 'error', 5000);
            }
        } catch (e) {
            this._setConnStatus('error', 'Error de red');
            if (typeof showToast === 'function') showToast('Error de conexión al realizar la prueba', 'error');
        } finally {
            this._setBusy(btn, false);
        }
    },

    // ─── Restablecer formulario a la configuración del servidor ───

    async reset() {
        if (!confirm('¿Restablecer el formulario a la configuración actual del servidor? Se perderán los cambios no guardados.')) {
            return;
        }
        await this.load();
        if (typeof showToast === 'function') showToast('Formulario restablecido', 'info');
    },

    // ─── Poblado del formulario ───

    _populate(cfg) {
        const setText = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.value = (val === undefined || val === null) ? '' : val;
        };

        setText('setting-default-mode', cfg.vision_default_mode || 'off');

        // API key enmascarada — NO se pone como valor (seguridad). Se usa como placeholder/ayuda.
        const apiKeyInput = document.getElementById('setting-api-key');
        const masked = cfg.roboflow_api_key || '';
        if (apiKeyInput) {
            apiKeyInput.value = '';
            apiKeyInput.type = 'password';
            apiKeyInput.placeholder = masked
                ? `${masked}  (déjalo vacío para mantenerla)`
                : 'No configurada — escribe la nueva API key';
        }
        const hint = document.getElementById('apikey-hint');
        if (hint) {
            hint.textContent = masked
                ? `Clave actual: ${masked}. Para cambiarla escribe una nueva; déjalo vacío para conservarla.`
                : 'No hay ninguna API key configurada.';
        }

        setText('setting-api-url', cfg.roboflow_api_url);
        setText('setting-workspace', cfg.roboflow_workspace);
        setText('setting-workflow-id', cfg.roboflow_workflow_id);
        setText('setting-image-input', cfg.roboflow_workflow_image_input || 'image');
        setText('setting-model-id', cfg.roboflow_model_id);

        this._setCheckbox('setting-use-cache', cfg.roboflow_workflow_use_cache);
        this._setCheckbox('setting-use-overlay', cfg.roboflow_use_server_overlay);
    },

    // ─── Utilidades de UI ───

    _toggleApiKeyVisibility() {
        const input = document.getElementById('setting-api-key');
        const btn = document.getElementById('btn-toggle-apikey');
        if (!input) return;
        if (input.type === 'password') {
            input.type = 'text';
            if (btn) btn.textContent = '🙈';
        } else {
            input.type = 'password';
            if (btn) btn.textContent = '👁️';
        }
    },

    _collectText(payload, elId, field) {
        const el = document.getElementById(elId);
        if (el) payload[field] = el.value.trim();
    },

    _getCheckbox(id) {
        const el = document.getElementById(id);
        return !!(el && el.checked);
    },

    _setCheckbox(id, val) {
        const el = document.getElementById(id);
        if (!el) return;
        // Acepta booleanos y strings "true"/"false"
        if (typeof val === 'string') {
            el.checked = val.toLowerCase() === 'true';
        } else {
            el.checked = !!val;
        }
    },

    /** Bloquea/desbloquea todos los campos y botones del formulario (carga inicial). */
    _setLoading(loading) {
        const form = document.getElementById('vision-settings-form');
        if (form) {
            Array.from(form.querySelectorAll('input, select, button')).forEach(el => {
                el.disabled = loading;
            });
        }
    },

    /** Muestra un spinner dentro del botón y lo deshabilita durante la operación. */
    _setBusy(btn, busy) {
        if (!btn) return;
        if (busy) {
            if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent;
            btn.disabled = true;
            btn.classList.add('btn-loading');
            btn.innerHTML = '<span class="settings-spinner"></span>' + (btn.dataset.originalText || '');
        } else {
            btn.disabled = false;
            btn.classList.remove('btn-loading');
            btn.textContent = btn.dataset.originalText || btn.textContent;
        }
    },

    /** Actualiza el indicador visual de estado de conexión. */
    _setConnStatus(state, message) {
        const box = document.getElementById('vision-conn-status');
        if (!box) return;
        box.style.display = 'flex';
        box.classList.remove('ok', 'error', 'testing');
        if (state) box.classList.add(state);
        const text = box.querySelector('.conn-text');
        if (text) text.textContent = message || '—';
    },

    /**
     * Verifica respuestas de autenticación.
     * 401 → limpia sesión y redirige al login.
     * 403 → avisa que se requiere rol admin.
     * Retorna true si la respuesta representa un fallo de auth que ya fue manejado.
     */
    _isUnauthorized(res) {
        if (res.status === 401) {
            if (typeof clearSession === 'function') clearSession();
            if (typeof showToast === 'function') showToast('Sesión expirada. Redirigiendo...', 'error');
            setTimeout(() => { window.location.href = '/index.html'; }, 1500);
            return true;
        }
        if (res.status === 403) {
            if (typeof showToast === 'function') showToast('No tienes permisos de administrador', 'error');
            return true;
        }
        return false;
    }
};

// ─── Funciones globales (invocadas por dashboard.js al cambiar de tab) ───
function loadVisionSettings() { return SETTINGS.load(); }
function saveVisionSettings() { return SETTINGS.save(); }
function testVisionConnection() { return SETTINGS.test(); }

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    SETTINGS.init();
});

// Exportar para entornos con módulos (tests)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { SETTINGS, loadVisionSettings, saveVisionSettings, testVisionConnection };
}
