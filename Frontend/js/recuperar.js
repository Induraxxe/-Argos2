/**
 * Lógica de la Página de Recuperar Contraseña - Argos2
 * Maneja el envío de código de recuperación al correo del usuario
 */

// ============================================
// Inicialización
// ============================================
document.addEventListener('DOMContentLoaded', function() {
    // Configurar formulario
    const form = document.getElementById('recuperar-form');
    if (form) {
        form.addEventListener('submit', handleForgotPassword);
    }
    
    // Configurar validación de email en tiempo real
    const emailInput = document.getElementById('email');
    if (emailInput) {
        emailInput.addEventListener('blur', validateEmailInput);
        emailInput.addEventListener('input', clearEmailValidation);
    }
});

// ============================================
// Validación de Email
// ============================================
function validateEmailInput() {
    const emailInput = document.getElementById('email');
    const email = emailInput.value.trim();
    
    if (!email) {
        return;
    }
    
    if (!validateEmail(email)) {
        showToast('Por favor, ingrese un correo electrónico válido', 'warning');
        emailInput.classList.add('invalid');
    } else {
        emailInput.classList.remove('invalid');
        emailInput.classList.add('valid');
    }
}

function clearEmailValidation() {
    const emailInput = document.getElementById('email');
    if (emailInput) {
        emailInput.classList.remove('invalid', 'valid');
    }
}

// ============================================
// Manejo de Recuperación de Contraseña
// ============================================
async function handleForgotPassword(e) {
    e.preventDefault();
    
    const emailInput = document.getElementById('email');
    const email = emailInput.value.trim();
    
    // Validar email
    if (!email) {
        showToast('Por favor, ingrese su correo electrónico', 'warning');
        emailInput.focus();
        return;
    }
    
    if (!validateEmail(email)) {
        showToast('Por favor, ingrese un correo electrónico válido', 'warning');
        emailInput.focus();
        return;
    }
    
    const btnEnviar = document.getElementById('btn-enviar');
    if (btnEnviar) {
        btnEnviar.disabled = true;
        btnEnviar.textContent = 'ENVIANDO...';
    }
    
    try {
        const result = await forgotPassword(email);
        showToast(result.message, 'success');
        
        // Redirigir a la página de reset de contraseña con el email
        setTimeout(() => {
            window.location.href = `reset-password.html?email=${encodeURIComponent(email)}`;
        }, 1500);
    } catch (error) {
        if (error.isRateLimit) {
            showToast(error.message, 'warning');
        } else {
            showToast(error.message, 'error');
        }
        
        if (btnEnviar) {
            btnEnviar.disabled = false;
            btnEnviar.textContent = 'ENVIAR CÓDIGO';
        }
    }
}
