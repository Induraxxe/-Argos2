/**
 * Lógica de la Página de Reset de Contraseña - Argos2
 * Maneja la verificación de código y cambio de contraseña
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
            window.location.href = 'recuperar.html';
        }, 2000);
        return;
    }
    
    // Inicializar inputs de código
    initializeCodeInputs();
    
    // Configurar formulario
    const form = document.getElementById('reset-form');
    if (form) {
        form.addEventListener('submit', handleResetPassword);
    }
    
    // Iniciar countdown
    startCountdownTimer();
    
    // Configurar reenvío
    const resendLink = document.getElementById('resend-link');
    if (resendLink) {
        resendLink.addEventListener('click', handleResendCode);
    }
    
    // Configurar validación de contraseña en tiempo real
    const newPasswordInput = document.getElementById('new-password');
    const confirmPasswordInput = document.getElementById('confirm-password');
    
    if (newPasswordInput) {
        newPasswordInput.addEventListener('blur', validateNewPassword);
        newPasswordInput.addEventListener('input', clearPasswordValidation);
    }
    
    if (confirmPasswordInput) {
        confirmPasswordInput.addEventListener('blur', validatePasswordMatch);
        confirmPasswordInput.addEventListener('input', clearPasswordMatchValidation);
    }
});

// ============================================
// Manejo de Inputs de Código (reutilizado de verificacion.js)
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
    const btnCambiar = document.getElementById('btn-cambiar');
    
    const allFilled = Array.from(codeInputs).every(input => input.value.length === 1);
    
    if (btnCambiar) {
        btnCambiar.disabled = !allFilled;
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
// Validación de Contraseña
// ============================================
function validateNewPassword() {
    const newPasswordInput = document.getElementById('new-password');
    const password = newPasswordInput.value;
    
    if (!password) {
        return;
    }
    
    const validation = validatePassword(password);
    
    if (!validation.valid) {
        showToast(validation.message, 'warning');
        newPasswordInput.classList.add('invalid');
    } else {
        newPasswordInput.classList.remove('invalid');
        newPasswordInput.classList.add('valid');
    }
}

function clearPasswordValidation() {
    const newPasswordInput = document.getElementById('new-password');
    if (newPasswordInput) {
        newPasswordInput.classList.remove('invalid', 'valid');
    }
}

function validatePasswordMatch() {
    const newPasswordInput = document.getElementById('new-password');
    const confirmPasswordInput = document.getElementById('confirm-password');
    
    const newPassword = newPasswordInput.value;
    const confirmPassword = confirmPasswordInput.value;
    
    if (!confirmPassword) {
        return;
    }
    
    if (newPassword !== confirmPassword) {
        showToast('Las contraseñas no coinciden', 'warning');
        confirmPasswordInput.classList.add('invalid');
    } else {
        confirmPasswordInput.classList.remove('invalid');
        confirmPasswordInput.classList.add('valid');
    }
}

function clearPasswordMatchValidation() {
    const confirmPasswordInput = document.getElementById('confirm-password');
    if (confirmPasswordInput) {
        confirmPasswordInput.classList.remove('invalid', 'valid');
    }
}

// ============================================
// Manejo de Reset de Contraseña
// ============================================
async function handleResetPassword(e) {
    e.preventDefault();
    
    const code = getCompleteCode();
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;
    
    // Validar código
    if (code.length !== 6) {
        showToast('Por favor, ingrese el código de 6 dígitos completo', 'warning');
        return;
    }
    
    // Validar nueva contraseña
    const passwordValidation = validatePassword(newPassword);
    if (!passwordValidation.valid) {
        showToast(passwordValidation.message, 'warning');
        document.getElementById('new-password').focus();
        return;
    }
    
    // Validar que las contraseñas coincidan
    if (newPassword !== confirmPassword) {
        showToast('Las contraseñas no coinciden', 'warning');
        document.getElementById('confirm-password').focus();
        return;
    }
    
    const btnCambiar = document.getElementById('btn-cambiar');
    if (btnCambiar) {
        btnCambiar.disabled = true;
        btnCambiar.textContent = 'CAMBIANDO...';
    }
    
    try {
        const result = await resetPassword(userEmail, code, newPassword);
        showToast(result.message, 'success');
        
        // Redirigir al login después de un breve delay
        setTimeout(() => {
            window.location.href = 'index.html?reset=true';
        }, 1500);
    } catch (error) {
        if (error.isRateLimit) {
            showToast(error.message, 'warning');
        } else {
            showToast(error.message, 'error');
        }
        
        // Marcar inputs de código como inválidos
        const codeInputs = document.querySelectorAll('.code-digit');
        codeInputs.forEach(input => {
            input.classList.add('invalid');
            setTimeout(() => input.classList.remove('invalid'), 500);
        });
        
        // Limpiar inputs de código
        codeInputs.forEach(input => input.value = '');
        codeInputs[0].focus();
        
        if (btnCambiar) {
            btnCambiar.disabled = true;
            btnCambiar.textContent = 'CAMBIAR CONTRASEÑA';
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
    updateCountdownDisplay(remaining);
    
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
        const result = await resendCode(userEmail, 'recuperacion');
        showToast(result.message, 'success');
        
        // Limpiar inputs de código
        const codeInputs = document.querySelectorAll('.code-digit');
        codeInputs.forEach(input => input.value = '');
        codeInputs[0].focus();
        
        // Reiniciar countdown
        if (countdownInterval) {
            clearInterval(countdownInterval);
        }
        
        const countdownEl = document.getElementById('countdown');
        if (countdownEl && resendLink) {
            countdownEl.style.display = 'inline';
            resendLink.style.display = 'none';
            startCountdownTimer();
        }
        
    } catch (error) {
        showToast(error.message, 'error');
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
