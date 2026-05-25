"""
Módulo de conexión y operaciones base de SQLite3 para Argos2.
Incluye soporte para WAL mode y gestión de nombres de archivo con UUIDs.
"""

import sqlite3
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import json
import threading

# Ruta de la base de datos
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'argos2.db')

# Thread-local storage para conexiones
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """
    Crea y retorna una conexión a la base de datos configurada con WAL mode.
    Cada hilo obtiene su propia conexión para evitar conflictos.
    
    Returns:
        sqlite3.Connection: Conexión activa a la base de datos
    """
    # Verificar si ya existe una conexión para este hilo
    if hasattr(_local, 'connection') and _local.connection is not None:
        try:
            # Verificar que la conexión sigue activa
            _local.connection.execute('SELECT 1')
            return _local.connection
        except sqlite3.Error:
            # Conexión cerrada, crear nueva
            pass
    
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # Permite acceso por nombre de columna
    
    # Habilitar WAL mode para concurrencia
    conn.execute("PRAGMA journal_mode=WAL")
    
    # Configuraciones adicionales de rendimiento
    conn.execute("PRAGMA synchronous=NORMAL")  # Balance entre seguridad y rendimiento
    conn.execute("PRAGMA cache_size=-64000")   # 64MB de caché
    conn.execute("PRAGMA busy_timeout=30000")  # 30 segundos de timeout
    
    # Habilita foreign keys
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Guardar conexión en thread-local
    _local.connection = conn
    
    return conn


@contextmanager
def get_db():
    """
    Context manager para manejo automático de conexiones.
    
    Usage:
        with get_db() as db:
            cursor = db.execute("SELECT * FROM usuarios")
            users = cursor.fetchall()
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e


def close_connection():
    """Cierra la conexión del hilo actual."""
    if hasattr(_local, 'connection') and _local.connection is not None:
        _local.connection.close()
        _local.connection = None


def init_database():
    """
    Inicializa la base de datos creando todas las tablas necesarias.
    Ejecutar solo una vez al instalar el sistema.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Tabla de usuarios
    conn.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nombre_completo TEXT NOT NULL,
            fecha_nacimiento DATE NOT NULL,
            telefono TEXT,
            tipo_documento TEXT NOT NULL CHECK(tipo_documento IN ('V', 'P')),
            numero_documento TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'usuario' CHECK(rol IN ('usuario', 'admin')),
            activo BOOLEAN NOT NULL DEFAULT 1,
            email_verificado BOOLEAN NOT NULL DEFAULT 0,
            fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Índices de usuarios
    conn.execute('CREATE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios(email)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios(username)')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_documento ON usuarios(tipo_documento, numero_documento)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_usuarios_rol ON usuarios(rol)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_usuarios_activo ON usuarios(activo)')
    
    # Tabla de códigos de verificación
    conn.execute('''
        CREATE TABLE IF NOT EXISTS codigos_verificacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            email TEXT NOT NULL,
            codigo TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('verificacion', 'recuperacion')),
            fecha_expiracion DATETIME NOT NULL,
            usado BOOLEAN NOT NULL DEFAULT 0,
            fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
        )
    ''')
    
    # Índices de códigos
    conn.execute('CREATE INDEX IF NOT EXISTS idx_codigos_email ON codigos_verificacion(email)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_codigos_codigo ON codigos_verificacion(codigo)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_codigos_tipo ON codigos_verificacion(tipo)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_codigos_expiracion ON codigos_verificacion(fecha_expiracion)')
    
    # Tabla de trazabilidad (cola de estados del ThreadPool)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS trazabilidad (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            task_id TEXT UNIQUE,
            estado TEXT NOT NULL DEFAULT 'PENDING' CHECK(estado IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'RETRY', 'CANCELLED')),
            timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            timestamp_inicio DATETIME,
            timestamp_fin DATETIME,
            operacion TEXT NOT NULL,
            imagen_entrada TEXT,
            imagen_salida TEXT,
            parametros TEXT,
            progreso INTEGER DEFAULT 0 CHECK(progreso >= 0 AND progreso <= 100),
            mensaje_progreso TEXT,
            resultado TEXT,
            error_log TEXT,
            error_type TEXT,
            error_traceback TEXT,
            reintentos INTEGER DEFAULT 0,
            max_reintentos INTEGER DEFAULT 3,
            worker_id TEXT,
            prioridad INTEGER DEFAULT 5,
            tiempo_procesamiento_ms INTEGER,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
        )
    ''')
    
    # Índices de trazabilidad
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_usuario ON trazabilidad(usuario_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_timestamp ON trazabilidad(timestamp)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_operacion ON trazabilidad(operacion)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_estado ON trazabilidad(estado)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_task ON trazabilidad(task_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_worker ON trazabilidad(worker_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_trazabilidad_prioridad ON trazabilidad(prioridad)')
    
    # Tabla de sesiones
    conn.execute('''
        CREATE TABLE IF NOT EXISTS sesiones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            fecha_inicio DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_expiracion DATETIME NOT NULL,
            activa BOOLEAN NOT NULL DEFAULT 1,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
    ''')
    
    # Índices de sesiones
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sesiones_usuario ON sesiones(usuario_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sesiones_token ON sesiones(token)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sesiones_activa ON sesiones(activa)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sesiones_expiracion ON sesiones(fecha_expiracion)')
    
    # Tabla de intentos de login
    conn.execute('''
        CREATE TABLE IF NOT EXISTS intentos_login (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            username_intentado TEXT NOT NULL,
            ip_address TEXT,
            exitoso BOOLEAN NOT NULL DEFAULT 0,
            motivo_fallo TEXT,
            fecha_intento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL
        )
    ''')
    
    # Índices de intentos
    conn.execute('CREATE INDEX IF NOT EXISTS idx_intentos_usuario ON intentos_login(usuario_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_intentos_ip ON intentos_login(ip_address)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_intentos_fecha ON intentos_login(fecha_intento)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_intentos_exitoso ON intentos_login(exitoso)')
    
    # Tabla de tokens revocados (blacklist)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tokens_revocados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            jti TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            fecha_revocacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            fecha_expiracion DATETIME NOT NULL,
            motivo TEXT,
            FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
    ''')
    
    # Índices de tokens revocados
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tokens_revocados_jti ON tokens_revocados(jti)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tokens_revocados_user ON tokens_revocados(user_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_tokens_revocados_expiracion ON tokens_revocados(fecha_expiracion)')
    
    # Tabla de versiones de token
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_token_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            version INTEGER NOT NULL DEFAULT 1,
            fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )
    ''')
    
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_user_token_versions_user ON user_token_versions(user_id)')
    
    # Tabla de logs del sistema
    conn.execute('''
        CREATE TABLE IF NOT EXISTS logs_sistema (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            nivel TEXT NOT NULL CHECK(nivel IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
            componente TEXT NOT NULL,
            mensaje TEXT NOT NULL,
            datos_adicionales TEXT,
            usuario_id INTEGER,
            trazabilidad_id INTEGER,
            duracion_ms INTEGER,
            ip_address TEXT,
            user_agent TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL,
            FOREIGN KEY (trazabilidad_id) REFERENCES trazabilidad(id) ON DELETE SET NULL
        )
    ''')
    
    # Índices de logs
    conn.execute('CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs_sistema(timestamp)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_logs_nivel ON logs_sistema(nivel)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_logs_componente ON logs_sistema(componente)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_logs_usuario ON logs_sistema(usuario_id)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_logs_trazabilidad ON logs_sistema(trazabilidad_id)')
    
    conn.close()
    print("Base de datos inicializada con WAL mode habilitado.")


def row_to_dict(row: sqlite3.Row) -> Optional[Dict[str, Any]]:
    """
    Convierte un Row de SQLite a diccionario.
    
    Args:
        row: Fila resultado de una consulta
        
    Returns:
        Dict: Diccionario con los datos de la fila, o None si row es None
    """
    return dict(row) if row is not None else None


def rows_to_list(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    """
    Convierte una lista de Rows a lista de diccionarios.
    
    Args:
        rows: Lista de filas resultado de una consulta
        
    Returns:
        List: Lista de diccionarios
    """
    return [dict(row) for row in rows]


# ==================== OPERACIONES CRUD ====================

# ==================== USUARIOS ====================

def crear_usuario(
    username: str,
    email: str,
    password_hash: str,
    nombre_completo: str,
    fecha_nacimiento: str,
    tipo_documento: str,
    numero_documento: str,
    telefono: Optional[str] = None,
    rol: str = 'usuario'
) -> int:
    """
    Crea un nuevo usuario en la base de datos.
    
    Returns:
        int: ID del usuario creado
    """
    with get_db() as db:
        cursor = db.execute('''
            INSERT INTO usuarios
            (username, email, password_hash, nombre_completo, fecha_nacimiento,
             telefono, tipo_documento, numero_documento, rol)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (username, email, password_hash, nombre_completo, fecha_nacimiento,
              telefono, tipo_documento, numero_documento, rol))
        return cursor.lastrowid or 0


def obtener_usuario_por_id(usuario_id: int) -> Optional[Dict]:
    """Obtiene un usuario por su ID."""
    with get_db() as db:
        cursor = db.execute('SELECT * FROM usuarios WHERE id = ?', (usuario_id,))
        row = cursor.fetchone()
        return row_to_dict(row)


def obtener_usuario_por_username(username: str) -> Optional[Dict]:
    """Obtiene un usuario por su username."""
    with get_db() as db:
        cursor = db.execute('SELECT * FROM usuarios WHERE username = ?', (username,))
        row = cursor.fetchone()
        return row_to_dict(row)


def obtener_usuario_por_email(email: str) -> Optional[Dict]:
    """Obtiene un usuario por su email."""
    with get_db() as db:
        cursor = db.execute('SELECT * FROM usuarios WHERE email = ?', (email,))
        row = cursor.fetchone()
        return row_to_dict(row)


def verificar_documento_existe(tipo_documento: str, numero_documento: str) -> bool:
    """Verifica si un documento ya está registrado."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT COUNT(*) as count FROM usuarios
            WHERE tipo_documento = ? AND numero_documento = ?
        ''', (tipo_documento, numero_documento))
        result = cursor.fetchone()
        return result['count'] > 0


def listar_usuarios() -> List[Dict]:
    """Lista todos los usuarios (para admin)."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT id, username, email, nombre_completo, fecha_nacimiento,
                   telefono, tipo_documento, numero_documento, rol, activo,
                   email_verificado, fecha_creacion
            FROM usuarios
            ORDER BY fecha_creacion DESC
        ''')
        return rows_to_list(cursor.fetchall())


def actualizar_rol_usuario(usuario_id: int, nuevo_rol: str) -> bool:
    """Actualiza el rol de un usuario."""
    with get_db() as db:
        db.execute('''
            UPDATE usuarios SET rol = ?, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (nuevo_rol, usuario_id))
        return True


def toggle_estado_usuario(usuario_id: int) -> bool:
    """Alterna el estado activo/inactivo de un usuario."""
    with get_db() as db:
        db.execute('''
            UPDATE usuarios
            SET activo = NOT activo, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (usuario_id,))
        return True


def verificar_email_usuario(usuario_id: int) -> bool:
    """Marca el email de un usuario como verificado."""
    with get_db() as db:
        db.execute('''
            UPDATE usuarios
            SET email_verificado = 1, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (usuario_id,))
        return True


def actualizar_password(usuario_id: int, nuevo_password_hash: str) -> bool:
    """Actualiza la contraseña de un usuario."""
    with get_db() as db:
        db.execute('''
            UPDATE usuarios
            SET password_hash = ?, fecha_actualizacion = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (nuevo_password_hash, usuario_id))
        return True


def eliminar_usuario(usuario_id: int) -> bool:
    """Elimina un usuario de la base de datos."""
    with get_db() as db:
        db.execute('DELETE FROM usuarios WHERE id = ?', (usuario_id,))
        return True


# ==================== CÓDIGOS DE VERIFICACIÓN ====================

def crear_codigo_verificacion(
    email: str,
    tipo: str,
    usuario_id: Optional[int] = None,
    duracion_minutos: int = 2
) -> str:
    """
    Crea un código de verificación de 6 dígitos.
    
    Returns:
        str: Código generado
    """
    import secrets
    codigo = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
    fecha_expiracion = datetime.now() + timedelta(minutes=duracion_minutos)
    
    with get_db() as db:
        # Invalidar códigos anteriores del mismo tipo
        db.execute('''
            UPDATE codigos_verificacion
            SET usado = 1
            WHERE email = ? AND tipo = ? AND usado = 0
        ''', (email, tipo))
        
        # Crear nuevo código
        db.execute('''
            INSERT INTO codigos_verificacion
            (usuario_id, email, codigo, tipo, fecha_expiracion)
            VALUES (?, ?, ?, ?, ?)
        ''', (usuario_id, email, codigo, tipo, fecha_expiracion))
    
    return codigo


def verificar_codigo(email: str, codigo: str, tipo: str) -> Dict[str, Any]:
    """
    Verifica si un código es válido.
    
    Returns:
        Dict: {valido: bool, mensaje: str, usuario_id: int or None}
    """
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM codigos_verificacion
            WHERE email = ? AND codigo = ? AND tipo = ? AND usado = 0
            ORDER BY fecha_creacion DESC LIMIT 1
        ''', (email, codigo, tipo))
        row = cursor.fetchone()
        
        if not row:
            return {'valido': False, 'mensaje': 'Código no encontrado o ya usado'}
        
        codigo_data = row_to_dict(row)
        
        if datetime.now() > datetime.fromisoformat(codigo_data['fecha_expiracion']):
            return {'valido': False, 'mensaje': 'Código expirado'}
        
        # Marcar como usado
        db.execute('UPDATE codigos_verificacion SET usado = 1 WHERE id = ?',
                   (codigo_data['id'],))
        
        return {
            'valido': True,
            'mensaje': 'Código verificado correctamente',
            'usuario_id': codigo_data['usuario_id']
        }


def limpiar_codigos_expirados():
    """Elimina códigos expirados antiguos (más de 1 hora)."""
    with get_db() as db:
        limite = datetime.now() - timedelta(hours=1)
        db.execute('DELETE FROM codigos_verificacion WHERE fecha_expiracion < ?',
                   (limite,))


# ==================== TRAZABILIDAD (Cola de Estados ThreadPool) ====================

def crear_registro_trazabilidad(
    operacion: str,
    usuario_id: Optional[int] = None,
    task_id: Optional[str] = None,
    imagen_entrada: Optional[str] = None,
    parametros: Optional[Dict] = None,
    prioridad: int = 5,
    max_reintentos: int = 3
) -> Dict:
    """
    Crea un registro inicial de trazabilidad con estado PENDING.
    
    Args:
        operacion: Tipo de operación (deteccion, clasificacion, etc.)
        usuario_id: ID del usuario que solicita la operación
        task_id: UUID de la tarea
        imagen_entrada: Path de la imagen de entrada
        parametros: Diccionario con parámetros de la operación
        prioridad: Prioridad de la tarea (1=alta, 10=baja)
        max_reintentos: Máximo de reintentos permitidos
    
    Returns:
        Dict: Registro creado con todos los campos (diccionario vacío si hay error)
    """
    parametros_json = json.dumps(parametros) if parametros else None
    
    with get_db() as db:
        cursor = db.execute('''
            INSERT INTO trazabilidad
            (usuario_id, task_id, operacion, imagen_entrada, parametros,
             estado, progreso, prioridad, max_reintentos)
            VALUES (?, ?, ?, ?, ?, 'PENDING', 0, ?, ?)
        ''', (usuario_id, task_id, operacion, imagen_entrada,
              parametros_json, prioridad, max_reintentos))
        registro_id = cursor.lastrowid
        
        # Retornar el registro completo
        if registro_id is not None:
            result = obtener_trazabilidad_por_id(registro_id)
            return result if result is not None else {}
        return {}


def actualizar_estado_trazabilidad(
    registro_id: int,
    estado: str,
    progreso: Optional[int] = None,
    mensaje_progreso: Optional[str] = None,
    imagen_salida: Optional[str] = None,
    resultado: Optional[Dict] = None,
    error_log: Optional[str] = None,
    error_type: Optional[str] = None,
    error_traceback: Optional[str] = None,
    worker_id: Optional[str] = None,
    tiempo_procesamiento_ms: Optional[int] = None
) -> bool:
    """
    Actualiza el estado de un registro de trazabilidad.
    
    Args:
        registro_id: ID del registro a actualizar
        estado: Nuevo estado (PENDING, PROCESSING, COMPLETED, FAILED, RETRY, CANCELLED)
        progreso: Porcentaje de progreso (0-100)
        mensaje_progreso: Mensaje descriptivo del progreso
        imagen_salida: Path de la imagen procesada
        resultado: Diccionario con resultado final de la operación
        error_log: Mensaje de error legible para el usuario
        error_type: Tipo de excepción (ValueError, RuntimeError, etc.)
        error_traceback: Traceback completo para depuración
        worker_id: ID del thread que procesa la tarea
        tiempo_procesamiento_ms: Tiempo total de procesamiento en ms
    """
    with get_db() as db:
        # Construir query dinámicamente según los campos proporcionados
        updates = ['estado = ?']
        params = [estado]
        
        if progreso is not None:
            updates.append('progreso = ?')
            params.append(progreso)
        
        if mensaje_progreso is not None:
            updates.append('mensaje_progreso = ?')
            params.append(mensaje_progreso)
        
        if imagen_salida is not None:
            updates.append('imagen_salida = ?')
            params.append(imagen_salida)
        
        if resultado is not None:
            updates.append('resultado = ?')
            params.append(json.dumps(resultado) if isinstance(resultado, dict) else resultado)
        
        if error_log is not None:
            updates.append('error_log = ?')
            params.append(error_log)
        
        if error_type is not None:
            updates.append('error_type = ?')
            params.append(error_type)
        
        if error_traceback is not None:
            updates.append('error_traceback = ?')
            params.append(error_traceback)
        
        if worker_id is not None:
            updates.append('worker_id = ?')
            params.append(worker_id)
        
        if tiempo_procesamiento_ms is not None:
            updates.append('tiempo_procesamiento_ms = ?')
            params.append(tiempo_procesamiento_ms)
        
        # Agregar timestamp de inicio si cambia a PROCESSING
        if estado == 'PROCESSING':
            updates.append('timestamp_inicio = CURRENT_TIMESTAMP')
        
        # Agregar timestamp de fin si cambia a estado terminal
        if estado in ('COMPLETED', 'FAILED', 'CANCELLED'):
            updates.append('timestamp_fin = CURRENT_TIMESTAMP')
        
        # Incrementar contador de reintentos si estado es RETRY
        if estado == 'RETRY':
            updates.append('reintentos = reintentos + 1')
        
        params.append(registro_id)
        query = f"UPDATE trazabilidad SET {', '.join(updates)} WHERE id = ?"
        db.execute(query, params)
        return True


def incrementar_reintento(registro_id: int) -> bool:
    """Incrementa el contador de reintentos de una tarea."""
    with get_db() as db:
        db.execute('''
            UPDATE trazabilidad
            SET reintentos = reintentos + 1, estado = 'RETRY'
            WHERE id = ?
        ''', (registro_id,))
        return True


def marcar_error_trazabilidad(
    registro_id: int,
    error_log: str,
    error_type: Optional[str] = None,
    error_traceback: Optional[str] = None
) -> bool:
    """
    Marca un registro como FAILED con información de error completa.
    
    Args:
        registro_id: ID del registro
        error_log: Mensaje de error legible
        error_type: Tipo de excepción
        error_traceback: Traceback completo
    """
    return actualizar_estado_trazabilidad(
        registro_id=registro_id,
        estado='FAILED',
        error_log=error_log,
        error_type=error_type,
        error_traceback=error_traceback
    )


def obtener_trazabilidad_por_task_id(task_id: str) -> Optional[Dict]:
    """Obtiene un registro de trazabilidad por el ID de tarea."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM trazabilidad WHERE task_id = ?
        ''', (task_id,))
        row = cursor.fetchone()
        return row_to_dict(row)


def obtener_trazabilidad_por_id(registro_id: int) -> Optional[Dict]:
    """Obtiene un registro de trazabilidad por su ID."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM trazabilidad WHERE id = ?
        ''', (registro_id,))
        row = cursor.fetchone()
        return row_to_dict(row)


def obtener_historial_usuario(usuario_id: int, limite: int = 50) -> List[Dict]:
    """Obtiene el historial de operaciones de un usuario."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM trazabilidad
            WHERE usuario_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (usuario_id, limite))
        return rows_to_list(cursor.fetchall())


def obtener_tareas_pendientes() -> List[Dict]:
    """Obtiene todas las tareas en estado PENDING o PROCESSING."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM trazabilidad
            WHERE estado IN ('PENDING', 'PROCESSING', 'RETRY')
            ORDER BY prioridad ASC, timestamp ASC
        ''')
        return rows_to_list(cursor.fetchall())


def obtener_tareas_por_estado(estado: str) -> List[Dict]:
    """Obtiene todas las tareas con un estado específico."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM trazabilidad
            WHERE estado = ?
            ORDER BY timestamp DESC
        ''', (estado,))
        return rows_to_list(cursor.fetchall())


def obtener_tareas_por_worker(worker_id: str) -> List[Dict]:
    """Obtiene todas las tareas procesadas por un worker específico."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT * FROM trazabilidad
            WHERE worker_id = ?
            ORDER BY timestamp DESC
        ''', (worker_id,))
        return rows_to_list(cursor.fetchall())


def obtener_estadisticas_tareas() -> Dict:
    """Obtiene estadísticas generales de las tareas."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT
                estado,
                COUNT(*) as cantidad,
                AVG(tiempo_procesamiento_ms) as tiempo_promedio_ms
            FROM trazabilidad
            GROUP BY estado
        ''')
        stats = {}
        for row in cursor.fetchall():
            stats[row['estado']] = {
                'cantidad': row['cantidad'],
                'tiempo_promedio_ms': row['tiempo_promedio_ms']
            }
        return stats


def limpiar_tareas_antiguas(dias: int = 30) -> int:
    """
    Elimina registros de tareas completadas/fallidas mayores a X días.
    
    Args:
        dias: Días de antigüedad para eliminar
    
    Returns:
        int: Número de registros eliminados
    """
    with get_db() as db:
        limite = datetime.now() - timedelta(days=dias)
        cursor = db.execute('''
            DELETE FROM trazabilidad
            WHERE estado IN ('COMPLETED', 'FAILED', 'CANCELLED')
            AND timestamp < ?
        ''', (limite,))
        return cursor.rowcount


def eliminar_registro_trazabilidad(registro_id: int) -> bool:
    """
    Elimina un registro de trazabilidad de la base de datos.
    Se usa cuando una tarea es rechazada por el ThreadPool saturado.
    
    Args:
        registro_id: ID del registro a eliminar
    
    Returns:
        bool: True si se eliminó correctamente
    """
    with get_db() as db:
        db.execute('DELETE FROM trazabilidad WHERE id = ?', (registro_id,))
        return True


# ==================== TOKENS REVOCADOS (BLACKLIST) ====================

def agregar_token_revocado(
    jti: str,
    user_id: int,
    fecha_expiracion: datetime,
    motivo: str = 'logout'
) -> bool:
    """
    Agrega un token a la lista de revocados.
    
    Args:
        jti: JWT ID único del token
        user_id: ID del usuario
        fecha_expiracion: Fecha de expiración del token
        motivo: Razón de la revocación
    """
    with get_db() as db:
        db.execute('''
            INSERT OR IGNORE INTO tokens_revocados (jti, user_id, fecha_expiracion, motivo)
            VALUES (?, ?, ?, ?)
        ''', (jti, user_id, fecha_expiracion, motivo))
        return True


def verificar_token_revocado(jti: str) -> bool:
    """Verifica si un token está revocado."""
    with get_db() as db:
        cursor = db.execute(
            'SELECT 1 FROM tokens_revocados WHERE jti = ?',
            (jti,)
        )
        return cursor.fetchone() is not None


def revocar_todos_tokens_usuario(user_id: int, motivo: str = 'security') -> int:
    """
    Incrementa la versión de tokens de un usuario, invalidando todos los tokens anteriores.
    
    Returns:
        int: Nueva versión del token
    """
    with get_db() as db:
        cursor = db.execute('''
            INSERT INTO user_token_versions (user_id, version)
            VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                version = version + 1,
                fecha_actualizacion = CURRENT_TIMESTAMP
        ''', (user_id,))
        
        cursor = db.execute(
            'SELECT version FROM user_token_versions WHERE user_id = ?',
            (user_id,)
        )
        result = cursor.fetchone()
        return result['version'] if result else 1


def obtener_version_token_usuario(user_id: int) -> int:
    """Obtiene la versión actual de tokens de un usuario."""
    with get_db() as db:
        cursor = db.execute(
            'SELECT version FROM user_token_versions WHERE user_id = ?',
            (user_id,)
        )
        result = cursor.fetchone()
        return result['version'] if result else 1


def limpiar_tokens_expirados() -> int:
    """Elimina tokens revocados que ya han expirado."""
    with get_db() as db:
        cursor = db.execute(
            'DELETE FROM tokens_revocados WHERE fecha_expiracion < CURRENT_TIMESTAMP'
        )
        return cursor.rowcount


# ==================== SESIONES ====================

def crear_sesion(
    usuario_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    duracion_horas: int = 24
) -> str:
    """
    Crea una nueva sesión para un usuario.
    
    Returns:
        str: Token de sesión
    """
    import secrets
    token = secrets.token_urlsafe(32)
    fecha_expiracion = datetime.now() + timedelta(hours=duracion_horas)
    
    with get_db() as db:
        db.execute('''
            INSERT INTO sesiones (usuario_id, token, ip_address, user_agent, fecha_expiracion)
            VALUES (?, ?, ?, ?, ?)
        ''', (usuario_id, token, ip_address, user_agent, fecha_expiracion))
    
    return token


def validar_sesion(token: str) -> Optional[Dict]:
    """Valida si una sesión es válida y retorna los datos del usuario."""
    with get_db() as db:
        cursor = db.execute('''
            SELECT s.*, u.username, u.email, u.nombre_completo, u.rol
            FROM sesiones s
            JOIN usuarios u ON s.usuario_id = u.id
            WHERE s.token = ? AND s.activa = 1 AND s.fecha_expiracion > CURRENT_TIMESTAMP
        ''', (token,))
        row = cursor.fetchone()
        return row_to_dict(row)


def cerrar_sesion(token: str) -> bool:
    """Cierra una sesión activa."""
    with get_db() as db:
        db.execute('UPDATE sesiones SET activa = 0 WHERE token = ?', (token,))
        return True


def limpiar_sesiones_expiradas():
    """Elimina sesiones expiradas."""
    with get_db() as db:
        db.execute('DELETE FROM sesiones WHERE fecha_expiracion < CURRENT_TIMESTAMP')


# ==================== INTENTOS DE LOGIN ====================

def registrar_intento_login(
    username_intentado: str,
    exitoso: bool,
    usuario_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    motivo_fallo: Optional[str] = None
):
    """Registra un intento de login."""
    with get_db() as db:
        db.execute('''
            INSERT INTO intentos_login
            (usuario_id, username_intentado, ip_address, exitoso, motivo_fallo)
            VALUES (?, ?, ?, ?, ?)
        ''', (usuario_id, username_intentado, ip_address, exitoso, motivo_fallo))


def obtener_intentos_fallidos(ip_address: str, minutos: int = 15) -> int:
    """Cuenta intentos fallidos desde una IP en los últimos X minutos."""
    with get_db() as db:
        limite = datetime.now() - timedelta(minutes=minutos)
        cursor = db.execute('''
            SELECT COUNT(*) as count FROM intentos_login
            WHERE ip_address = ? AND exitoso = 0 AND fecha_intento > ?
        ''', (ip_address, limite))
        result = cursor.fetchone()
        return result['count']


# ==================== LOGS DEL SISTEMA ====================

def crear_log(
    nivel: str,
    componente: str,
    mensaje: str,
    datos_adicionales: Optional[Dict] = None,
    usuario_id: Optional[int] = None,
    trazabilidad_id: Optional[int] = None,
    duracion_ms: Optional[int] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> int:
    """
    Crea un registro de log en el sistema.
    
    Args:
        nivel: Nivel del log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        componente: Componente que genera el log
        mensaje: Mensaje del log
        datos_adicionales: Datos adicionales en formato JSON
        usuario_id: ID del usuario relacionado
        trazabilidad_id: ID del registro de trazabilidad relacionado
        duracion_ms: Duración de la operación en milisegundos
        ip_address: Dirección IP del cliente
        user_agent: User agent del cliente
    
    Returns:
        int: ID del log creado
    """
    datos_json = json.dumps(datos_adicionales) if datos_adicionales else None
    
    with get_db() as db:
        cursor = db.execute('''
            INSERT INTO logs_sistema
            (nivel, componente, mensaje, datos_adicionales, usuario_id,
             trazabilidad_id, duracion_ms, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nivel, componente, mensaje, datos_json, usuario_id,
              trazabilidad_id, duracion_ms, ip_address, user_agent))
        return cursor.lastrowid or 0


def obtener_logs(
    nivel: Optional[str] = None,
    componente: Optional[str] = None,
    usuario_id: Optional[int] = None,
    limite: int = 100
) -> List[Dict]:
    """
    Obtiene logs del sistema con filtros opcionales.
    
    Args:
        nivel: Filtrar por nivel de log
        componente: Filtrar por componente
        usuario_id: Filtrar por usuario
        limite: Número máximo de registros a retornar
    
    Returns:
        List: Lista de logs
    """
    with get_db() as db:
        query = 'SELECT * FROM logs_sistema WHERE 1=1'
        params = []
        
        if nivel:
            query += ' AND nivel = ?'
            params.append(nivel)
        
        if componente:
            query += ' AND componente = ?'
            params.append(componente)
        
        if usuario_id:
            query += ' AND usuario_id = ?'
            params.append(usuario_id)
        
        query += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limite)
        
        cursor = db.execute(query, params)
        return rows_to_list(cursor.fetchall())


def limpiar_logs_antiguos(dias: int = 7) -> int:
    """
    Elimina logs antiguos mayores a X días.
    
    Args:
        dias: Días de antigüedad para eliminar
    
    Returns:
        int: Número de registros eliminados
    """
    with get_db() as db:
        limite = datetime.now() - timedelta(days=dias)
        cursor = db.execute(
            'DELETE FROM logs_sistema WHERE timestamp < ?',
            (limite,)
        )
        return cursor.rowcount