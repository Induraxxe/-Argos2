"""
Aplicación Flask principal para Argos2.
Configura CORS, blueprints, middlewares y sirve archivos estáticos del frontend.
"""

from flask import Flask, jsonify, send_from_directory, render_template_string, request
from flask_cors import CORS
import atexit
import os
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Habilitar logging a nivel INFO para visibilidad del pipeline de visión
# (mensajes INFO/WARNING del vision engine y camera service en consola).
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
)

# Cargar variables de entorno desde .env (antes de cualquier uso)
load_dotenv()

# Importar blueprints
from routes import auth_bp, admin_bp, vision_bp, camera_bp, settings_bp

# Importar rate limiter
from middleware.rate_limiter import limiter

# Importar módulos de base de datos
from database.db import init_database
from database.utils import UPLOAD_FOLDER, PROCESSED_FOLDER, ensure_directories
from auth.jwt_handler import start_cleanup_scheduler

# Ruta del frontend
FRONTEND_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Frontend')

# Validar que SECRET_KEY esté definida
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    raise EnvironmentError(
        "SECRET_KEY no está configurada. "
        "Ejecute install.bat (Windows) o install.sh (Linux) para configurar las variables de entorno."
    )


def create_app():
    """Factory para crear la aplicación Flask."""
    app = Flask(__name__, static_folder=FRONTEND_FOLDER, static_url_path='')
    
    # Configurar CORS
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    # Configurar carpeta de templates para servir HTML
    app.template_folder = FRONTEND_FOLDER
    
    # Configuración de la aplicación
    app.config['SECRET_KEY'] = _secret_key
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload
    
    # Inicializar rate limiter (DESPUÉS de crear app, ANTES de blueprints)
    limiter.init_app(app)
    
    # Registrar blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(vision_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(settings_bp)
    
    # Inicializar base de datos
    init_database()
    ensure_directories()

    # Sincronizar settings de visión: la DB es la fuente de verdad.
    # Los valores persistidos en la DB se cargan en os.environ para que los
    # motores de visión los tomen al instanciarse.
    try:
        from services.settings_service import sync_settings_to_env
        sync_settings_to_env()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "No se pudieron sincronizar los settings de visión: %s", e
        )
    
    # Iniciar limpieza periódica de tokens expirados
    start_cleanup_scheduler(interval_hours=1)
    
    # =====================
    # Shutdown — Detener cámaras al cerrar la app
    # =====================
    
    from services.camera_service import CameraManager as _CameraManager
    
    def _cleanup_cameras():
        _CameraManager().shutdown_all()
    
    atexit.register(_cleanup_cameras)
    
    # =====================
    # CORS headers para streams MJPEG
    # =====================
    
    @app.after_request
    def add_cors_headers(response):
        """Agrega headers CORS específicos para streams MJPEG de cámaras."""
        if '/api/cameras/' in request.path and '/stream' in request.path:
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    
    # =====================
    # Rutas del Frontend (Páginas HTML)
    # =====================
    
    @app.route('/')
    def index():
        """Página de inicio - Redirige a index.html (Login)."""
        return send_from_directory(FRONTEND_FOLDER, 'index.html')
    
    @app.route('/index.html')
    def login_page():
        """Página de Login."""
        return send_from_directory(FRONTEND_FOLDER, 'index.html')
    
    @app.route('/registro.html')
    def registro_page():
        """Página de Registro."""
        return send_from_directory(FRONTEND_FOLDER, 'registro.html')
    
    @app.route('/verificacion.html')
    def verificacion_page():
        """Página de Verificación de Correo."""
        return send_from_directory(FRONTEND_FOLDER, 'verificacion.html')
    
    @app.route('/recuperar.html')
    def recuperar_page():
        """Página de Recuperación de Contraseña."""
        return send_from_directory(FRONTEND_FOLDER, 'recuperar.html')
    
    @app.route('/reset-password.html')
    def reset_password_page():
        """Página de Reset de Contraseña."""
        return send_from_directory(FRONTEND_FOLDER, 'reset-password.html')
    
    @app.route('/dashboard.html')
    def dashboard_page():
        """Página del Dashboard (Vision Computacional)."""
        return send_from_directory(FRONTEND_FOLDER, 'dashboard.html')
    
    @app.route('/admin.html')
    def admin_page():
        """Página de Administración."""
        return send_from_directory(FRONTEND_FOLDER, 'admin.html')
    
    # =====================
    # Rutas de API (Documentación)
    # =====================
    
    @app.route('/api')
    def api_documentation():
        """Documentación de la API en formato JSON."""
        base_url = request.host_url.rstrip('/')
        
        return jsonify({
            'name': 'Argos2 API',
            'version': '1.0.0',
            'description': 'Sistema de Visión Computacional con autenticación JWT',
            'base_url': base_url,
            'frontend_pages': {
                'login': f'{base_url}/index.html',
                'registro': f'{base_url}/registro.html',
                'verificacion': f'{base_url}/verificacion.html',
                'recuperar': f'{base_url}/recuperar.html',
                'reset_password': f'{base_url}/reset-password.html',
                'dashboard': f'{base_url}/dashboard.html',
                'admin': f'{base_url}/admin.html'
            },
            'endpoints': {
                'auth': {
                    'login': 'POST /api/login',
                    'logout': 'POST /api/logout',
                    'logout_all': 'POST /api/logout-all',
                    'refresh': 'POST /api/refresh',
                    'me': 'GET /api/me',
                    'register': 'POST /api/register',
                    'verify_code': 'POST /api/verify-code',
                    'resend_code': 'POST /api/resend-code',
                    'forgot_password': 'POST /api/forgot-password',
                    'reset_password': 'POST /api/reset-password',
                    'validate_document': 'POST /api/validate-document'
                },
                'admin': {
                    'list_users': 'GET /api/admin/users',
                    'update_role': 'PUT /api/admin/users/{id}/role',
                    'update_status': 'PUT /api/admin/users/{id}/status',
                    'delete_user': 'DELETE /api/admin/users/{id}'
                },
                'vision': {
                    'process': 'POST /api/vision/process',
                    'status': 'GET /api/vision/status/<task_id>'
                },
                'cameras_vision': {
                    'start': 'POST /api/cameras/<id>/vision/start {mode}',
                    'stop': 'POST /api/cameras/<id>/vision/stop',
                    'stream': 'GET /api/cameras/<id>/vision/stream (MJPEG anotado)',
                    'status': 'GET /api/cameras/<id>/vision/status',
                    'modes': 'GET /api/cameras/vision/modes'
                },
                'settings': {
                    'get_vision': 'GET /api/settings/vision (API key enmascarada)',
                    'update_vision': 'PUT /api/settings/vision (admin)',
                    'test_vision': 'GET /api/settings/vision/test (admin)'
                },
                'system': {
                    'health': 'GET /health',
                    'docs': 'GET /api'
                }
            }
        }), 200
    
    @app.route('/health')
    def health():
        """Health check endpoint."""
        return jsonify({
            'status': 'healthy',
            'service': 'argos2-api',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }), 200
    
    # =====================
    # Manejadores de Errores
    # =====================
    
    @app.errorhandler(400)
    def bad_request(error):
        """Manejador de errores 400."""
        msg = str(error.description) if hasattr(error, 'description') else 'Solicitud inválida'
        return jsonify({'error': msg, 'type': 'Bad Request'}), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        """Manejador de errores 401."""
        msg = str(error.description) if hasattr(error, 'description') else 'Autenticación requerida'
        return jsonify({'error': msg, 'type': 'Unauthorized'}), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        """Manejador de errores 403."""
        msg = str(error.description) if hasattr(error, 'description') else 'Acceso denegado'
        return jsonify({'error': msg, 'type': 'Forbidden'}), 403
    
    @app.errorhandler(404)
    def not_found(error):
        """Manejador de errores 404."""
        return jsonify({'error': 'Recurso no encontrado', 'type': 'Not Found'}), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        """Manejador de errores 405."""
        return jsonify({'error': 'Método HTTP no permitido', 'type': 'Method Not Allowed'}), 405
    
    @app.errorhandler(429)
    def too_many_requests(error):
        """Manejador de errores 429."""
        msg = str(error.description) if hasattr(error, 'description') else 'Demasiadas solicitudes'
        return jsonify({'error': msg, 'type': 'Too Many Requests'}), 429
    
    @app.errorhandler(500)
    def internal_error(error):
        """Manejador de errores 500."""
        return jsonify({'error': 'Error interno del servidor', 'type': 'Internal Server Error'}), 500
    
    return app


# Crear instancia de la aplicación
app = create_app()


# =====================
# Punto de Entrada
# =====================

if __name__ == '__main__':
    # Configurar variables de entorno para desarrollo
    os.environ.setdefault('FLASK_ENV', 'development')
    os.environ.setdefault('FLASK_DEBUG', '1')
    
    # Ejecutar la aplicación
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
