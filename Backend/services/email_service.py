"""
Módulo de servicio de correo - Argos2
Funciones para enviar correos electrónicos de verificación y recuperación
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from datetime import datetime
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

# Configuración de correo
EMAIL_FROM = os.environ.get('EMAIL_FROM')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
EMAIL_SMTP = os.environ.get('EMAIL_SMTP', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))

# Validar que las variables críticas estén definidas
if not EMAIL_FROM:
    raise EnvironmentError(
        "EMAIL_FROM no está configurada. "
        "Ejecute install.bat (Windows) o install.sh (Linux) para configurar las variables de entorno."
    )
if not EMAIL_PASSWORD:
    raise EnvironmentError(
        "EMAIL_PASSWORD no está configurada. "
        "Ejecute install.bat (Windows) o install.sh (Linux) para configurar las variables de entorno."
    )


def enviar_correo_verificacion(email, codigo):
    """
    Enviar correo electrónico con código de verificación de registro.
    
    Args:
        email: Dirección de correo del destinatario
        codigo: Código de verificación de 6 dígitos
    
    Returns:
        tuple: (exitoso: bool, mensaje: str)
    """
    try:
        # Crear mensaje
        mensaje = MIMEMultipart()
        mensaje['From'] = EMAIL_FROM
        mensaje['To'] = email
        mensaje['Subject'] = 'ARGOS2 - Código de Verificación'
        
        cuerpo = f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #1a1a2e; padding: 20px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, rgba(106,27,154,0.1), rgba(142,36,170,0.1)); backdrop-filter: blur(10px); padding: 40px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.2); box-shadow: 0 8px 32px rgba(0,0,0,0.3);">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: #8E24AA; margin: 0; font-size: 32px; font-weight: 700;">ARGOS2</h1>
                    <p style="color: rgba(255,255,255,0.7); margin: 10px 0 0 0; font-size: 14px;">Sistema de Visión Computacional</p>
                </div>
                
                <h2 style="color: #FFFFFF; text-align: center; margin-bottom: 20px;">Verificación de Correo</h2>
                
                <p style="color: rgba(255,255,255,0.8); font-size: 16px; line-height: 1.6;">
                    Estimado usuario,
                </p>
                
                <p style="color: rgba(255,255,255,0.8); font-size: 16px; line-height: 1.6;">
                    Gracias por registrarte en <strong>ARGOS2</strong>. Para completar tu registro, por favor ingresa el siguiente código de verificación:
                </p>
                
                <div style="background: linear-gradient(135deg, #6A1B9A, #8E24AA); color: white; font-size: 36px; font-weight: bold; text-align: center; padding: 25px; border-radius: 15px; margin: 30px 0; letter-spacing: 8px; box-shadow: 0 4px 20px rgba(106,27,154,0.5);">
                    {codigo}
                </div>
                
                <p style="color: rgba(255,255,255,0.8); font-size: 16px; line-height: 1.6; text-align: center;">
                    Este código expirará en <strong>2 minutos</strong>.
                </p>
                
                <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #8E24AA;">
                    <p style="color: rgba(255,255,255,0.7); font-size: 14px; margin: 0;">
                        <strong>Nota:</strong> Si no solicitaste este código, por favor ignora este mensaje. Tu cuenta permanecerá segura.
                    </p>
                </div>
                
                <hr style="border: none; border-top: 1px solid rgba(255,255,255,0.2); margin: 30px 0;">
                
                <p style="color: rgba(255,255,255,0.5); font-size: 12px; text-align: center; margin: 0;">
                    © {datetime.now().year} ARGOS2 - Sistema de Visión Computacional
                </p>
            </div>
        </body>
        </html>
        """
        
        mensaje.attach(MIMEText(cuerpo, 'html'))
        
        # Conectar al servidor SMTP y enviar
        servidor = smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT)
        servidor.starttls()
        servidor.login(EMAIL_FROM, EMAIL_PASSWORD)
        servidor.send_message(mensaje)
        servidor.quit()
        
        return True, "Correo de verificación enviado exitosamente"
    except Exception as e:
        print(f"Error al enviar correo de verificación: {e}")
        return False, f"Error al enviar correo: {str(e)}"


def enviar_correo_recuperacion(email, codigo):
    """
    Enviar correo electrónico con código de recuperación de contraseña.
    
    Args:
        email: Dirección de correo del destinatario
        codigo: Código de recuperación de 6 dígitos
    
    Returns:
        tuple: (exitoso: bool, mensaje: str)
    """
    try:
        # Crear mensaje
        mensaje = MIMEMultipart()
        mensaje['From'] = EMAIL_FROM
        mensaje['To'] = email
        mensaje['Subject'] = 'ARGOS2 - Recuperación de Contraseña'
        
        cuerpo = f"""
        <html>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #1a1a2e; padding: 20px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background: linear-gradient(135deg, rgba(106,27,154,0.1), rgba(142,36,170,0.1)); backdrop-filter: blur(10px); padding: 40px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.2); box-shadow: 0 8px 32px rgba(0,0,0,0.3);">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: #8E24AA; margin: 0; font-size: 32px; font-weight: 700;">ARGOS2</h1>
                    <p style="color: rgba(255,255,255,0.7); margin: 10px 0 0 0; font-size: 14px;">Sistema de Visión Computacional</p>
                </div>
                
                <h2 style="color: #FFFFFF; text-align: center; margin-bottom: 20px;">Recuperación de Contraseña</h2>
                
                <p style="color: rgba(255,255,255,0.8); font-size: 16px; line-height: 1.6;">
                    Hemos recibido una solicitud para restablecer tu contraseña en <strong>ARGOS2</strong>.
                </p>
                
                <p style="color: rgba(255,255,255,0.8); font-size: 16px; line-height: 1.6;">
                    Para continuar con el proceso, por favor ingresa el siguiente código de recuperación:
                </p>
                
                <div style="background: linear-gradient(135deg, #6A1B9A, #8E24AA); color: white; font-size: 36px; font-weight: bold; text-align: center; padding: 25px; border-radius: 15px; margin: 30px 0; letter-spacing: 8px; box-shadow: 0 4px 20px rgba(106,27,154,0.5);">
                    {codigo}
                </div>
                
                <p style="color: rgba(255,255,255,0.8); font-size: 16px; line-height: 1.6; text-align: center;">
                    Este código expirará en <strong>2 minutos</strong>.
                </p>
                
                <div style="background: rgba(255,255,255,0.1); padding: 15px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #F57C00;">
                    <p style="color: rgba(255,255,255,0.7); font-size: 14px; margin: 0;">
                        <strong>⚠️ Seguridad:</strong> Si no solicitaste este cambio, por favor ignora este mensaje y tu contraseña permanecerá sin cambios.
                    </p>
                </div>
                
                <hr style="border: none; border-top: 1px solid rgba(255,255,255,0.2); margin: 30px 0;">
                
                <p style="color: rgba(255,255,255,0.5); font-size: 12px; text-align: center; margin: 0;">
                    © {datetime.now().year} ARGOS2 - Sistema de Visión Computacional
                </p>
            </div>
        </body>
        </html>
        """
        
        mensaje.attach(MIMEText(cuerpo, 'html'))
        
        # Conectar al servidor SMTP y enviar
        servidor = smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT)
        servidor.starttls()
        servidor.login(EMAIL_FROM, EMAIL_PASSWORD)
        servidor.send_message(mensaje)
        servidor.quit()
        
        return True, "Correo de recuperación enviado exitosamente"
    except Exception as e:
        print(f"Error al enviar correo de recuperación: {e}")
        return False, f"Error al enviar correo: {str(e)}"
