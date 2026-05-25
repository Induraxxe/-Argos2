/**
 * Lógica de la Página de Verificación de Correo - Argos2
 * Maneja la verificación de código de 6 dígitos, countdown y reenvío
 */

// ============================================
// Variables Globales
// ============================================
let userEmail = '';
let countdownInterval = null;
const COUNTDOWN_SECONDS = 120; // 2 minutos

// ============================================
// Inicialización
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    // Obtener email de los query params
    const urlParams = new URLSearchParams(window.location.search);
    userEmail = urlParams.get('email') || '';
    
    if (!userEmail) {
        showToast('No se proporcionó un correo electrónico', 'error');
        setTimeout(() => {
            window.location.href = 'index.html';
        }, 2000);
        return;
    }
    
    // Mostrar email en la página
    const emailDisplay = document.getElementById('user-email');
    if (emailDisplay) {
        emailDisplay.textContent = userEmail;
    }
    
    // Inicializar inputs de código
    initializeCodeInputs();
    
    // Iniciar countdown
    startCountdownTimer();
    
    // Configurar formulario
    const form = document.getElementById('verificacion-form');
    if (form) {
        form.addEventListener('submit', handleVerification);
    }
    
    // Configurar reenvío
    const resendLink = document.getElementById('resend-link');
    if (resendLink) {
        resendLink.addEventListener('click', handleResendCode);
    }
});

// ============================================
// Manejo de Inputs de Código
// ============================================
function initializeCodeInputs() {
    const codeInputs = document.querySelectorAll('.code-digit');
    
    codeInputs.forEach((input, index) => {
        // Manejar entrada de texto
        input.addEventListener('input', function(e) {
            const value = e.target.value;
            
            // Solo permitir números
            if (!/^\d*$/.test(value)) {
                e.target.value = '';
                return;
            }
            
            // Mover al siguiente input si se escribió un dígito
            if (value.length === 1 && index < codeInputs.length - 1) {
                codeInputs[index + 1].focus();
            }
            
            // Validar que todos los inputs tengan valor
            validateCodeComplete();
        });
        
        // Manejar teclas especiales
        input.addEventListener('keydown', function(e) {
            // Borrar y mover al input anterior
            if (e.key === 'Backspace' && e.target.value === '' && index > 0) {
                codeInputs[index - 1].focus();
            }
            
            // Mover al siguiente con flecha derecha
            if (e.key === 'ArrowRight' && index < codeInputs.length - 1) {
                codeInputs[index + 1].focus();
            }
            
            // Mover al anterior con flecha izquierda
            if (e.key === 'ArrowLeft' && index > 0) {
                codeInputs[index - 1].focus();
            }
            
            // Pegar código completo
            if (e.key === 'v' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                navigator.clipboard.readText().then(pastedText => {
                    const digits = pastedText.replace(/\D/g, '').split('');
                    digits.forEach((digit, i) => {
                        if (i < codeInputs.length) {
                            codeInputs[i].value = digit;
                        }
                    });
                    // Enfocar el último input con valor o el siguiente disponible
                    const lastFilledIndex = Math.min(digits.length, codeInputs.length - 1);
                    codeInputs[lastFilledIndex].focus();
                    validateCodeComplete();
                });
            }
        });
        
        // Manejar paste
        input.addEventListener('paste', function(e) {
            e.preventDefault();
            const pastedText = e.clipboardData.getData('text');
            const digits = pastedText.replace(/\D/g, '').split('');
            
            digits.forEach((digit, i) => {
                if (i < codeInputs.length) {
                    codeInputs[i].value = digit;
                }
            });
            
            // Enfocar el último input con valor o el siguiente disponible
            const lastFilledIndex = Math.min(digits.length, codeInputs.length - 1);
            codeInputs[lastFilledIndex].focus();
            validateCodeComplete();
        });
    });
}

// ============================================
// Validación de Código Completo
// ============================================
function validateCodeComplete() {
    const codeInputs = document.querySelectorAll('.code-digit');
    const btnVerificar = document.getElementById('btn-verificar');
    
    const allFilled = Array.from(codeInputs).every(input => input.value.length === 1);
    
    if (btnVerificar) {
        btnVerificar.disabled = !allFilled;
    }
}

// ============================================
// Obtener Código Completo
// ============================================
function getCompleteCode() {
    const codeInputs = document.querySelectorAll('.code-digit');
    return Array.from(codeInputs).map(input => input.value).join('');
}

// ============================================
// Manejo de Verificación
// ============================================
async function handleVerification(e) {
    e.preventDefault();
    
    const code = getCompleteCode();
    
    if (code.length !== 6) {
        showToast('Por favor, ingrese el código de 6 dígitos completo', 'warning');
        return;
    }
    
    const btnVerificar = document.getElementById('btn-verificar');
    if (btnVerificar) {
        btnVerificar.disabled = true;
        btnVerificar.textContent = 'VERIFICANDO...';
    }
    
    try {
        const result = await verifyCode(userEmail, code);
        showToast(result.message, 'success');
        
        // Redirigir al login después de un breve delay
        setTimeout(() => {
            window.location.href = 'index.html?verified=true';
        }, 1500);
    } catch (error) {
        showToast(error.message, 'error');
        
        // Marcar inputs como inválidos
        const codeInputs = document.querySelectorAll('.code-digit');
        codeInputs.forEach(input => {
            input.classList.add('invalid');
            setTimeout(() => input.classList.remove('invalid'), 500);
        });
        
        // Limpiar inputs
        codeInputs.forEach(input => input.value = '');
        codeInputs[0].focus();
        
        if (btnVerificar) {
            btnVerificar.disabled = true;
            btnVerificar.textContent = 'VERIFICAR';
        }
    }
}

// ============================================
// Countdown Timer
// ============================================
function startCountdownTimer() {
    const countdownEl = document.getElementById('countdown');
    const resendLink = document.getElementById('resend-link');
    
    if (!countdownEl || !resendLink) return;
    
    let remaining = COUNTDOWN_SECONDS;
    
    // Mostrar countdown inicial
    updateCountdownDisplay(remaining);
    
    // Iniciar intervalo
    countdownInterval = setInterval(() => {
        remaining--;
        updateCountdownDisplay(remaining);
        
        if (remaining <= 0) {
            clearInterval(countdownInterval);
            countdownEl.style.display = 'none';
            resendLink.style.display = 'inline';
        }
    }, 1000);
}

function updateCountdownDisplay(seconds) {
    const countdownEl = document.getElementById('countdown');
    if (countdownEl) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        countdownEl.textContent = `Reenviar código en ${minutes}:${secs.toString().padStart(2, '0')}`;
    }
}

// ============================================
// Manejo de Reenvío de Código
// ============================================
async function handleResendCode(e) {
    e.preventDefault();
    
    const resendLink = document.getElementById('resend-link');
    if (resendLink) {
        resendLink.disabled = true;
        resendLink.textContent = 'ENVIANDO...';
    }
    
    try {
        const result = await resendCode(userEmail, 'verificacion');
        showToast(result.message, 'success');
        
        // Reiniciar countdown
        if (countdownInterval) {
            clearInterval(countdownInterval);
        }
        
        // Ocultar link y mostrar countdown
        const countdownEl = document.getElementById('countdown');
        if (countdownEl && resendLink) {
            countdownEl.style.display = 'inline';
            resendLink.style.display = 'none';
            startCountdownTimer();
        }
        
        // Limpiar inputs
        const codeInputs = document.querySelectorAll('.code-digit');
        codeInputs.forEach(input => input.value = '');
        codeInputs[0].focus();
        
    } catch (error) {
        if (error.isRateLimit) {
            showToast(error.message, 'warning');
        } else {
            showToast(error.message, 'error');
        }
    } finally {
        if (resendLink) {
            resendLink.disabled = false;
            resendLink.textContent = 'Reenviar código';
        }
    }
}

// ============================================
// Limpieza al salir de la página
// ============================================
window.addEventListener('beforeunload', function() {
    if (countdownInterval) {
        clearInterval(countdownInterval);
    }
});
