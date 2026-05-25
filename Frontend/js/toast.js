/**
 * Sistema de Notificaciones Toast - Argos2
 * Muestra notificaciones emergentes temporales en la esquina superior derecha
 */

/**
 * Muestra una notificación toast
 * @param {string} message - Mensaje a mostrar
 * @param {string} type - Tipo de notificación: 'success' | 'error' | 'warning' | 'info'
 * @param {number} duration - Duración en milisegundos antes de desaparecer (default: 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    // Crear o obtener el contenedor de toasts
    let container = document.getElementById('toast-container');
    
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    // Crear el elemento toast
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    // Icono según el tipo
    let icon = '';
    switch (type) {
        case 'success':
            icon = '✓';
            break;
        case 'error':
            icon = '✕';
            break;
        case 'warning':
            icon = '⚠';
            break;
        case 'info':
        default:
            icon = 'ℹ';
            break;
    }
    
    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    
    // Agregar al contenedor
    container.appendChild(toast);
    
    // Remover después de la duración especificada
    setTimeout(() => {
        toast.remove();
    }, duration);
}

/**
 * Muestra una notificación de éxito
 * @param {string} message - Mensaje a mostrar
 * @param {number} duration - Duración en milisegundos
 */
function showSuccessToast(message, duration = 3000) {
    showToast(message, 'success', duration);
}

/**
 * Muestra una notificación de error
 * @param {string} message - Mensaje a mostrar
 * @param {number} duration - Duración en milisegundos
 */
function showErrorToast(message, duration = 3000) {
    showToast(message, 'error', duration);
}

/**
 * Muestra una notificación de advertencia
 * @param {string} message - Mensaje a mostrar
 * @param {number} duration - Duración en milisegundos
 */
function showWarningToast(message, duration = 3000) {
    showToast(message, 'warning', duration);
}

/**
 * Muestra una notificación informativa
 * @param {string} message - Mensaje a mostrar
 * @param {number} duration - Duración en milisegundos
 */
function showInfoToast(message, duration = 3000) {
    showToast(message, 'info', duration);
}

// Exportar funciones para uso en otros módulos
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        showToast,
        showSuccessToast,
        showErrorToast,
        showWarningToast,
        showInfoToast
    };
}
