/**
 * Módulo de Autenticación - Argos2
 * Maneja login, registro, verificación y gestión de sesiones
 */

// Detectar automáticamente la URL del servidor (localhost o IP)
const API_URL = `${window.location.origin}/api`;
const CODE_EXPIRY_MINUTES = 2; // 2 minutos de expiración

// ============================================
// Validaciones
// ============================================

/**
 * Valida que la contraseña cumpla con los requisitos
 * @param {string} password - Contraseña a validar
 * @returns {object} { valid: boolean, message: string }
 */
function validatePassword(password) {
    if (password.length < 8) {
        return { valid: false, message: 'La contraseña debe tener al menos 8 caracteres' };
    }
    if (!/[A-Z]/.test(password)) {
        return { valid: false, message: 'La contraseña debe contener al menos una mayúscula' };
    }
    if (!/[a-z]/.test(password)) {
        return { valid: false, message: 'La contraseña debe contener al menos una minúscula' };
    }
    if (!/\d/.test(password)) {
        return { valid: false, message: 'La contraseña debe contener al menos un número' };
    }
    if (!/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?\/]/.test(password)) {
        return { valid: false, message: 'La contraseña debe contener al menos un carácter especial (!@#$%^&* etc.)' };
    }
    return { valid: true, message: '' };
}

/**
 * Valida el formato de teléfono venezolano
 * @param {string} phone - Teléfono a validar
 * @returns {boolean}
 */
function validatePhone(phone) {
    if (!phone) return true; // Es opcional
    const phoneRegex = /^04[1-4]\d{8}$/;
    return phoneRegex.test(phone);
}

/**
 * Valida el formato de documento de identidad
 * @param {string} tipo - Tipo de documento (V o P)
 * @param {string} numero - Número de documento
 * @returns {object} { valid: boolean, message: string }
 */
function validateDocument(tipo, numero) {
    if (tipo === 'V') {
        const cedulaRegex = /^V\d{7,8}$/;
        if (!cedulaRegex.test(`V${numero}`)) {
            return { valid: false, message: 'La cédula debe tener el formato V + 7-8 dígitos' };
        }
    } else if (tipo === 'P') {
        const pasaporteRegex = /^P[A-Za-z0-9]{6,12}$/;
        if (!pasaporteRegex.test(`P${numero}`)) {
            return { valid: false, message: 'El pasaporte debe tener el formato P + 6-12 caracteres alfanuméricos' };
        }
    }
    return { valid: true, message: '' };
}

/**
 * Valida el formato de email
 * @param {string} email - Email a validar
 * @returns {boolean}
 */
function validateEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

/**
 * Valida el formato del nombre de usuario
 * @param {string} username - Username a validar
 * @returns {object} { valid: boolean, message: string }
 */
function validateUsername(username) {
    if (username.length < 3) {
        return { valid: false, message: 'El usuario debe tener al menos 3 caracteres' };
    }
    if (username.length > 20) {
        return { valid: false, message: 'El usuario no debe superar los 20 caracteres' };
    }
    if (!/^[a-zA-Z0-9_]+$/.test(username)) {
        return { valid: false, message: 'El usuario solo puede contener letras, números y guion bajo' };
    }
    return { valid: true, message: '' };
}

// ============================================
// Funciones Principales de API
// ============================================

/**
 * Inicia sesión de usuario
 * @param {string} username - Nombre de usuario
 * @param {string} password - Contraseña
 * @returns {Promise<object>} Datos de usuario o error
 */
async function login(username, password) {
    const response = await fetch(`${API_URL}/login`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ username, password })
    });

    if (response.status === 429) {
        const data = await response.json();
        const err = new Error(data.error || 'Demasiados intentos. Por favor espera un momento antes de intentar de nuevo.');
        err.isRateLimit = true;
        throw err;
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al iniciar sesión');
    }

    const data = await response.json();
    saveSession(data);
    return data;
}

/**
 * Registra un nuevo usuario
 * @param {object} userData - Datos del usuario
 * @returns {Promise<object>} Resultado del registro
 */
async function register(userData) {
    const response = await fetch(`${API_URL}/register`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(userData)
    });

    if (response.status === 429) {
        const data = await response.json();
        const err = new Error(data.error || 'Demasiados intentos. Por favor espera un momento antes de intentar de nuevo.');
        err.isRateLimit = true;
        throw err;
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al registrar usuario');
    }

    return await response.json();
}

/**
 * Verifica el código de verificación de correo
 * @param {string} email - Email del usuario
 * @param {string} code - Código de verificación
 * @returns {Promise<object>} Resultado de la verificación
 */
async function verifyCode(email, code) {
    const response = await fetch(`${API_URL}/verify-code`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email, code })
    });

    if (response.status === 429) {
        const data = await response.json();
        const err = new Error(data.error || 'Demasiados intentos. Por favor espera un momento antes de intentar de nuevo.');
        err.isRateLimit = true;
        throw err;
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al verificar código');
    }

    return await response.json();
}

/**
 * Reenvía el código de verificación
 * @param {string} email - Email del usuario
 * @param {string} type - Tipo de código ('register' o 'reset')
 * @returns {Promise<object>} Resultado del reenvío
 */
async function resendCode(email, type = 'register') {
    const response = await fetch(`${API_URL}/resend-code`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email, type })
    });

    if (response.status === 429) {
        const data = await response.json();
        const err = new Error(data.error || 'Demasiados intentos. Por favor espera un momento antes de intentar de nuevo.');
        err.isRateLimit = true;
        throw err;
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al reenviar código');
    }

    return await response.json();
}

/**
 * Inicia el proceso de recuperación de contraseña
 * @param {string} email - Email del usuario
 * @returns {Promise<object>} Resultado de la solicitud
 */
async function forgotPassword(email) {
    const response = await fetch(`${API_URL}/forgot-password`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email })
    });

    if (response.status === 429) {
        const data = await response.json();
        const err = new Error(data.error || 'Demasiados intentos. Por favor espera un momento antes de intentar de nuevo.');
        err.isRateLimit = true;
        throw err;
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al procesar solicitud');
    }

    return await response.json();
}

/**
 * Restablece la contraseña con código
 * @param {string} email - Email del usuario
 * @param {string} code - Código de recuperación
 * @param {string} newPassword - Nueva contraseña
 * @returns {Promise<object>} Resultado del reset
 */
async function resetPassword(email, code, newPassword) {
    const response = await fetch(`${API_URL}/reset-password`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email, code, new_password: newPassword })
    });

    if (response.status === 429) {
        const data = await response.json();
        const err = new Error(data.error || 'Demasiados intentos. Por favor espera un momento antes de intentar de nuevo.');
        err.isRateLimit = true;
        throw err;
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al restablecer contraseña');
    }

    return await response.json();
}

/**
 * Valida si un documento de identidad ya está registrado
 * @param {string} tipo - Tipo de documento
 * @param {string} numero - Número de documento
 * @returns {Promise<object>} Resultado de la validación
 */
async function validateDocumentUnique(tipo, numero) {
    const response = await fetch(`${API_URL}/validate-document`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ tipo_documento: tipo, numero_documento: numero })
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.error || 'Error al validar documento');
    }

    return await response.json();
}

/**
 * Cierra la sesión del usuario
 * @returns {Promise<object>} Resultado del logout
 */
async function logout() {
    const session = getSession();
    const token = session?.access_token || session?.token;
    
    if (!token) {
        // Si no hay token, solo limpiar la sesión local
        clearSession();
        return { message: 'Sesión cerrada localmente' };
    }

    const response = await fetch(`${API_URL}/logout`, {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${token}`
        }
    });

    // Limpiar la sesión local independientemente de la respuesta
    clearSession();

    if (!response.ok) {
        // No lanzar error, ya que la sesión local se limpió
        return { message: 'Sesión cerrada localmente (error en servidor)' };
    }

    return await response.json();
}

// ============================================
// Gestión de Sesión
// ============================================

/**
 * Guarda la sesión del usuario en localStorage
 * @param {object} userData - Datos del usuario
 */
function saveSession(userData) {
    localStorage.setItem('session', JSON.stringify(userData));
}

/**
 * Obtiene la sesión actual del usuario
 * @returns {object|null} Datos de la sesión o null
 */
function getSession() {
    const session = localStorage.getItem('session');
    return session ? JSON.parse(session) : null;
}

/**
 * Limpia la sesión actual
 */
function clearSession() {
    localStorage.removeItem('session');
}

/**
 * Obtiene el token de acceso de la sesión actual
 * @returns {string} Token de acceso o cadena vacía
 */
function getAccessToken() {
    const session = getSession();
    if (!session) return '';
    // El token puede estar en session.token (mock) o session.access_token (backend)
    return session.access_token || session.token || '';
}

/**
 * Obtiene el refresh token de la sesión actual
 * @returns {string} Refresh token o cadena vacía
 */
function getRefreshToken() {
    const session = getSession();
    if (!session) return '';
    return session.refresh_token || '';
}

/**
 * Verifica si un token JWT está expirado o próximo a expirar.
 * Decodifica el payload sin librerías externas usando atob().
 *
 * @param {string} token - Token JWT a verificar
 * @param {number} bufferSeconds - Segundos de margen antes de la expiración real (default: 0)
 * @returns {boolean} true si el token está expirado o no es válido
 */
function isTokenExpired(token, bufferSeconds = 0) {
    if (!token) return true;
    
    try {
        // JWT formato: header.payload.signature
        const parts = token.split('.');
        if (parts.length !== 3) return true;
        
        // Decodificar payload (segunda parte)
        // Base64Url → Base64: reemplazar - por + y _ por /
        let base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
        
        // Agregar padding si es necesario
        while (base64.length % 4 !== 0) {
            base64 += '=';
        }
        
        const payload = JSON.parse(atob(base64));
        
        // Verificar campo exp (timestamp en segundos)
        if (!payload.exp) return true;
        
        // Comparar con timestamp actual + buffer
        const now = Math.floor(Date.now() / 1000);
        return payload.exp <= (now + bufferSeconds);
        
    } catch (error) {
        return true; // Si no se puede decodificar, considerar expirado
    }
}

/**
 * Verifica si hay una sesión activa con token válido
 * @returns {boolean}
 */
function isLoggedIn() {
    const session = getSession();
    if (!session) return false;
    
    const token = session.access_token || session.token;
    if (!token) return false;
    
    return !isTokenExpired(token);
}

/**
 * Verifica si el usuario actual es administrador
 * @returns {boolean}
 */
function isAdmin() {
    const session = getSession();
    if (!session) return false;
    // El rol está en session.user.rol (formato del backend)
    const rol = session.user ? session.user.rol : session.rol;
    return rol === 'admin';
}

/**
 * Intenta renovar el access token usando el refresh token
 * @returns {Promise<string|null>} Nuevo access token o null si falla
 */
async function refreshAccessToken() {
    const refreshToken = getRefreshToken();
    
    if (!refreshToken) {
        return null;
    }
    
    try {
        const response = await fetch(`${API_URL}/refresh`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ refresh_token: refreshToken })
        });
        
        if (!response.ok) {
            // Si el refresh token también expiró, limpiar sesión
            if (response.status === 401) {
                clearSession();
                window.location.href = 'index.html';
            }
            return null;
        }
        
        const data = await response.json();
        
        // Actualizar la sesión con los nuevos tokens, preservando datos del usuario
        const session = getSession();
        const updatedSession = {
            ...session,
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            token_type: data.token_type,
            expires_in: data.expires_in
        };
        saveSession(updatedSession);
        return data.access_token;
        
    } catch (error) {
        return null;
    }
}

// Lock para evitar refreshes paralelos
let _refreshPromise = null;

/**
 * Refresh seguro que evita múltiples llamadas simultáneas
 * @returns {Promise<string|null>}
 */
async function safeRefresh() {
    if (_refreshPromise) return _refreshPromise;
    _refreshPromise = refreshAccessToken();
    const result = await _refreshPromise;
    _refreshPromise = null;
    return result;
}

/**
 * Wrapper de fetch que incluye el token de autorización y maneja renovación automática.
 * Si el access token está expirado o próximo a expirar (menos de 5 minutos),
 * intenta renovarlo antes de hacer la petición.
 *
 * @param {string} url - URL de la petición
 * @param {object} options - Opciones de fetch (se agrega Authorization automáticamente)
 * @returns {Promise<Response>} Respuesta de fetch
 */
async function authenticatedFetch(url, options = {}) {
    let token = getAccessToken();
    
    // Verificar si el token está por expirar (menos de 5 minutos)
    if (token && isTokenExpired(token, 300)) {
        const newToken = await safeRefresh();
        if (newToken) {
            token = newToken;
        }
    }
    
    // Agregar header de Authorization
    const headers = {
        ...options.headers,
        'Authorization': `Bearer ${token}`
    };
    
    const response = await fetch(url, { ...options, headers });
    
    // Si recibimos 401, intentar refresh una vez más
    if (response.status === 401 && token) {
        const newToken = await safeRefresh();
        if (newToken) {
            // Reintentar con el nuevo token
            const retryHeaders = {
                ...options.headers,
                'Authorization': `Bearer ${newToken}`
            };
            return fetch(url, { ...options, headers: retryHeaders });
        }
    }
    
    return response;
}

/**
 * Verifica la autenticación y redirige si es necesario.
 * Si el access token está expirado, intenta renovarlo antes de redirigir.
 * @param {boolean} requireAdmin - Si es true, requiere rol de admin
 * @returns {Promise<boolean>} true si está autenticado
 */
async function checkAuth(requireAdmin = false) {
    const session = getSession();
    
    if (!session) {
        window.location.href = 'index.html';
        return false;
    }
    
    const token = session.access_token || session.token;
    
    // Si el token está expirado, intentar refresh
    if (isTokenExpired(token)) {
        const newToken = await safeRefresh();
        if (!newToken) {
            // No se pudo renovar — redirigir al login
            window.location.href = 'index.html';
            return false;
        }
    }
    
    if (requireAdmin) {
        // El rol está en session.user.rol (formato del backend)
        const rol = session.user ? session.user.rol : session.rol;
        if (rol !== 'admin') {
            window.location.href = 'dashboard.html';
            return false;
        }
    }
    
    // Autenticación exitosa — mostrar contenido con transición suave
    document.body.classList.add('auth-ready');
    
    return true;
}

// ============================================
// Utilidades
// ============================================

/**
 * Muestra un mensaje en el elemento con ID 'message'
 * @param {string} text - Texto del mensaje
 * @param {string} type - Tipo: 'error', 'success', 'warning', 'info'
 */
function showMessage(text, type) {
    const messageEl = document.getElementById('message');
    if (messageEl) {
        messageEl.textContent = text;
        messageEl.className = `message ${type} show`;
        
        setTimeout(() => {
            messageEl.classList.remove('show');
        }, 5000);
    }
}

/**
 * Valida que todos los campos requeridos tengan valor
 * @param {object} fields - Objeto con campos a validar
 * @returns {object} { valid: boolean, message: string }
 */
function validateFields(fields) {
    for (const [key, value] of Object.entries(fields)) {
        if (!value || value.trim() === '') {
            return { valid: false, message: `El campo ${key} es requerido` };
        }
    }
    return { valid: true, message: '' };
}

/**
 * Formatea el documento de identidad para mostrar
 * @param {string} tipo - Tipo de documento
 * @param {string} numero - Número de documento
 * @returns {string} Documento formateado
 */
function formatDocument(tipo, numero) {
    return `${tipo}-${numero}`;
}

/**
 * Inicia una cuenta regresiva
 * @param {number} seconds - Segundos para contar
 * @param {function} callback - Función a llamar en cada segundo
 * @param {function} onComplete - Función a llamar al terminar
 */
function startCountdown(seconds, callback, onComplete) {
    let remaining = seconds;
    
    callback(remaining);
    
    const interval = setInterval(() => {
        remaining--;
        callback(remaining);
        
        if (remaining <= 0) {
            clearInterval(interval);
            if (onComplete) onComplete();
        }
    }, 1000);
}

// ============================================
// Exportar módulo
// ============================================
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        // Funciones principales
        login,
        logout,
        register,
        verifyCode,
        resendCode,
        forgotPassword,
        resetPassword,
        validateDocumentUnique,
        authenticatedFetch,
        // Validaciones
        validatePassword,
        validatePhone,
        validateDocument,
        validateEmail,
        validateUsername,
        // Gestión de sesión
        saveSession,
        getSession,
        clearSession,
        getAccessToken,
        getRefreshToken,
        isTokenExpired,
        refreshAccessToken,
        isLoggedIn,
        isAdmin,
        checkAuth,
        // Utilidades
        showMessage,
        validateFields,
        formatDocument,
        startCountdown
    };
}
