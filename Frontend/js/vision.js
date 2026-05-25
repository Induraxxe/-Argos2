/**
 * Módulo de Visión Computacional - Argos2
 * Maneja el procesamiento de imágenes con comunicación al backend
 */

// ============================================
// Configuración
// ============================================
const VISION = {
    API_BASE: `${window.location.origin}/api/vision`,
    
    /**
     * Procesa una imagen enviándola al backend
     * @param {File} file - Archivo de imagen a procesar
     * @param {string} operation - Tipo de operación: 'deteccion', 'clasificacion', 'mejora'
     * @returns {Promise<object|null>} Resultado del procesamiento o null en caso de error
     */
    async processImage(file, operation = 'deteccion') {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('operation', operation);
        
        try {
            const response = await authenticatedFetch(`${this.API_BASE}/process`, {
                method: 'POST',
                body: formData
            });
            
            // Manejo específico de HTTP 429 - Servidor Saturado
            if (response.status === 429) {
                const data = await response.json();
                showToast(
                    'El servidor está a máxima capacidad procesando otras imágenes. Intente de nuevo en unos segundos',
                    'warning',
                    5000  // Duración extendida para este mensaje
                );
                // Opcional: reintentar automáticamente después de retry_after
                if (data.retry_after) {
                    console.log(`Reintentar en ${data.retry_after} segundos`);
                }
                return null;
            }
            
            // Manejo de HTTP 401 - No autorizado
            if (response.status === 401) {
                showToast('Su sesión ha expirado. Por favor inicie sesión nuevamente.', 'error');
                setTimeout(() => {
                    window.location.href = 'index.html';
                }, 2000);
                return null;
            }
            
            // Manejo de HTTP 500 - Error del servidor
            if (response.status === 500) {
                showToast('Error interno del servidor. Por favor intente más tarde.', 'error');
                return null;
            }
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || `Error ${response.status}: ${response.statusText}`);
            }
            
            return await response.json();
            
        } catch (error) {
            console.error('Error en processImage:', error);
            showToast('Error al conectar con el servidor', 'error');
            return null;
        }
    },
    
    /**
     * Obtiene el estado de una tarea de procesamiento
     * @param {string} taskId - ID de la tarea
     * @returns {Promise<object|null>} Estado de la tarea o null en caso de error
     */
    async getTaskStatus(taskId) {
        try {
            const response = await authenticatedFetch(`${this.API_BASE}/status/${taskId}`);
            
            if (!response.ok) {
                throw new Error(`Error ${response.status}`);
            }
            
            return await response.json();
            
        } catch (error) {
            console.error('Error en getTaskStatus:', error);
            return null;
        }
    },
    
    /**
     * Realiza polling para actualizar el estado de una tarea
     * @param {string} taskId - ID de la tarea
     * @param {function} onProgress - Callback llamado con el estado actual
     * @param {function} onComplete - Callback llamado cuando la tarea se completa
     * @param {function} onError - Callback llamado cuando hay un error
     */
    async pollTaskStatus(taskId, onProgress, onComplete, onError) {
        let pollAttempts = 0;
        const MAX_POLL_ATTEMPTS = 60; // Máximo 2 minutos (60 * 2 segundos)
        
        const poll = async () => {
            if (pollAttempts >= MAX_POLL_ATTEMPTS) {
                onError('Tiempo de espera agotado. La tarea tardó demasiado en completarse.');
                return;
            }
            
            pollAttempts++;
            
            const status = await this.getTaskStatus(taskId);
            
            if (!status) {
                onError('Error al consultar estado de la tarea');
                return;
            }
            
            // Llamar al callback de progreso
            onProgress(status);
            
            // Verificar estado de la tarea
            if (status.estado === 'COMPLETED') {
                onComplete(status);
            } else if (status.estado === 'FAILED') {
                onError(status.mensaje_error || 'Error en el procesamiento de la imagen');
            } else {
                // Continuar polling cada 2 segundos
                setTimeout(poll, 2000);
            }
        };
        
        await poll();
    }
};

// ============================================
// Funciones de UI
// ============================================

/**
 * Actualiza la interfaz de usuario con el estado de la tarea
 * @param {object} status - Estado de la tarea
 */
function updateTaskStatus(status) {
    const statusEl = document.getElementById('task-status');
    const progressFill = document.getElementById('progress-fill');
    
    if (!statusEl) return;
    
    const estadoMap = {
        'PENDING': 'En cola...',
        'PROCESSING': 'Procesando...',
        'COMPLETED': 'Completado',
        'FAILED': 'Error'
    };
    
    const estadoTexto = estadoMap[status.estado] || status.estado;
    const progreso = status.progreso || 0;
    
    statusEl.textContent = `Estado: ${estadoTexto} - Progreso: ${progreso}%`;
    
    if (progressFill) {
        progressFill.style.width = `${progreso}%`;
    }
}

/**
 * Muestra el resultado del procesamiento
 * @param {object} status - Estado final de la tarea
 */
function showResult(status) {
    const resultSection = document.getElementById('result-section');
    const resultImage = document.getElementById('result-image');
    const resultInfo = document.getElementById('result-info');
    
    if (!resultSection) return;
    
    resultSection.style.display = 'block';
    
    if (status.imagen_salida && resultImage) {
        resultImage.src = status.imagen_salida;
    }
    
    if (resultInfo && status.resultados) {
        let infoHTML = '<h4>Detalles del Resultado:</h4>';
        for (const [key, value] of Object.entries(status.resultados)) {
            infoHTML += `<p><strong>${key}:</strong> ${value}</p>`;
        }
        resultInfo.innerHTML = infoHTML;
    }
}

/**
 * Oculta la sección de resultados
 */
function hideResult() {
    const resultSection = document.getElementById('result-section');
    if (resultSection) {
        resultSection.style.display = 'none';
    }
}

/**
 * Reinicia la interfaz de progreso
 */
function resetProgress() {
    const statusEl = document.getElementById('task-status');
    const progressFill = document.getElementById('progress-fill');
    
    if (statusEl) {
        statusEl.textContent = 'Estado: Esperando imagen...';
    }
    
    if (progressFill) {
        progressFill.style.width = '0%';
    }
    
    hideResult();
}

/**
 * Deshabilita el formulario de procesamiento
 * @param {boolean} disabled - true para deshabilitar, false para habilitar
 */
function toggleFormDisabled(disabled) {
    const btnProcess = document.getElementById('btn-process');
    const imageInput = document.getElementById('image-input');
    const operationSelect = document.getElementById('operation-select');
    
    if (btnProcess) {
        btnProcess.disabled = disabled;
        btnProcess.textContent = disabled ? 'Procesando...' : 'Procesar Imagen';
    }
    
    if (imageInput) {
        imageInput.disabled = disabled;
    }
    
    if (operationSelect) {
        operationSelect.disabled = disabled;
    }
}

// ============================================
// Inicialización
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    // Verificar autenticación
    if (!await checkAuth()) {
        return;
    }
    
    // Mostrar nombre de usuario
    const session = getSession();
    const usernameDisplay = document.getElementById('username-display');
    if (usernameDisplay && session) {
        // Los datos pueden estar en session (mock) o session.user (backend)
        const userData = session.user || session;
        usernameDisplay.textContent = userData.nombre_completo || userData.username;
    }
    
    // Manejo del input de archivo
    const imageInput = document.getElementById('image-input');
    const fileName = document.getElementById('file-name');
    
    if (imageInput && fileName) {
        imageInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                fileName.textContent = e.target.files[0].name;
                resetProgress();
            } else {
                fileName.textContent = '';
            }
        });
    }
    
    // Manejo del botón de procesar
    const visionForm = document.getElementById('vision-form');
    if (visionForm) {
        visionForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const fileInput = document.getElementById('image-input');
            const operation = document.getElementById('operation-select').value;
            
            if (!fileInput || !fileInput.files[0]) {
                showToast('Por favor seleccione una imagen', 'warning');
                return;
            }
            
            const file = fileInput.files[0];
            
            // Validar que sea una imagen
            if (!file.type.startsWith('image/')) {
                showToast('Por favor seleccione un archivo de imagen válido', 'error');
                return;
            }
            
            // Validar tamaño (máximo 10MB)
            const maxSize = 10 * 1024 * 1024; // 10MB
            if (file.size > maxSize) {
                showToast('La imagen no puede exceder 10MB', 'error');
                return;
            }
            
            // Deshabilitar formulario
            toggleFormDisabled(true);
            resetProgress();
            
            showToast('Enviando imagen al servidor...', 'info');
            
            const result = await VISION.processImage(file, operation);
            
            if (result && result.task_id) {
                showToast('Imagen enviada a procesamiento', 'success');
                
                // Iniciar polling de estado
                VISION.pollTaskStatus(
                    result.task_id,
                    (status) => {
                        updateTaskStatus(status);
                    },
                    (status) => {
                        showToast('Procesamiento completado', 'success');
                        showResult(status);
                        toggleFormDisabled(false);
                    },
                    (error) => {
                        showToast(error, 'error');
                        toggleFormDisabled(false);
                    }
                );
            } else {
                toggleFormDisabled(false);
            }
        });
    }
    
    // Manejo del botón de cerrar sesión
    const btnLogout = document.getElementById('btn-logout');
    if (btnLogout) {
        btnLogout.addEventListener('click', async () => {
            try {
                await logout();
                showToast('Sesión cerrada correctamente', 'success');
                window.location.href = 'index.html';
            } catch (error) {
                console.error('Error al cerrar sesión:', error);
                showToast('Error al cerrar sesión', 'error');
                // Cerrar sesión localmente de todos modos
                clearSession();
                window.location.href = 'index.html';
            }
        });
    }
});

// ============================================
// Exportar módulo
// ============================================
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        VISION,
        updateTaskStatus,
        showResult,
        hideResult,
        resetProgress,
        toggleFormDisabled
    };
}
