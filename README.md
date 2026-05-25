# 🛡️ Argos2 - Sistema de Visión Computacional con Autenticación

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.1.3-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-4.13-5C3EE8?logo=opencv&logoColor=white)
![PWA](https://img.shields.io/badge/PWA-Installable-5A0FC8?logo=pwa&logoColor=white)
![License](https://img.shields.io/badge/License-Private-red)

**Argos2** es un sistema integral de visión computacional con autenticación segura, panel de administración y procesamiento de imágenes en tiempo real. Construido con Flask (backend) y HTML5/CSS3/JavaScript ES6+ (frontend), ofrece una experiencia completa como Progressive Web App (PWA) instalable en cualquier dispositivo.

---

## 📋 Tabla de Contenidos

- [✨ Características Principales](#-características-principales)
- [🏗️ Arquitectura del Proyecto](#️-arquitectura-del-proyecto)
- [🛠️ Stack Tecnológico](#️-stack-tecnológico)
- [📋 Requisitos Previos](#-requisitos-previos)
- [🚀 Instalación Rápida](#-instalación-rápida)
- [▶️ Inicio del Servidor](#️-inicio-del-servidor)
- [📡 API Endpoints](#-api-endpoints)
- [🔐 Seguridad](#-seguridad)
- [🗄️ Base de Datos](#️-base-de-datos)
- [📱 PWA (Progressive Web App)](#-pwa-progressive-web-app)
- [🎨 Capturas de Pantalla](#-capturas-de-pantalla)
- [🔧 Variables de Entorno](#-variables-de-entorno)
- [👤 Creación del Primer Administrador](#-creación-del-primer-administrador)
- [🤝 Contribuir](#-contribuir)
- [📄 Licencia](#-licencia)

---

## ✨ Características Principales

- 🔐 **Sistema de autenticación completo** — JWT con JTI único, bcrypt, gestión de sesiones y roles (admin/usuario)
- 👤 **Registro con verificación de email** — Código de 6 dígitos enviado por correo con expiración de 2 minutos
- 🔄 **Recuperación de contraseña** — Flujo seguro con código de un solo uso enviado por correo
- 🖥️ **Dashboard de visión computacional** — Detección, clasificación y mejora de imágenes con OpenCV
- 👨‍💼 **Panel de administración** — Gestión completa de usuarios, roles y estados desde interfaz web
- 📱 **Progressive Web App (PWA)** — Instalable en móviles y escritorio, funcionamiento offline parcial
- 🔒 **Rate Limiting** — Protección contra ataques de fuerza bruta por IP en endpoints sensibles
- 🎨 **Diseño Glassmorphism responsive** — Interfaz moderna con efectos de cristal y adaptación a cualquier pantalla
- 📧 **Servicio de correo SMTP** — Integración con Gmail para notificaciones y verificaciones
- 🔔 **Sistema de notificaciones Toast** — Feedback visual elegante para todas las acciones del usuario

---

## 🏗️ Arquitectura del Proyecto

```
Argos2/
├── Backend/                    # 🖥️ Servidor Flask (Python)
│   ├── app.py                 # Aplicación principal Flask
│   ├── requirements.txt       # Dependencias Python
│   ├── argos2.db              # Base de datos SQLite (auto-generada)
│   ├── auth/                  # 🔐 Autenticación JWT
│   │   ├── __init__.py
│   │   └── jwt_handler.py     # Manejo de tokens JWT
│   ├── database/              # 🗄️ Base de datos SQLite
│   │   ├── __init__.py
│   │   ├── db.py              # Conexión y esquema (WAL mode)
│   │   └── utils.py           # Utilidades de BD
│   ├── middleware/             # 🛡️ Middlewares
│   │   ├── __init__.py
│   │   └── rate_limiter.py    # Rate limiting por IP
│   ├── routes/                # 🛤️ Endpoints API REST
│   │   ├── __init__.py
│   │   ├── auth.py            # Rutas de autenticación
│   │   ├── admin.py           # Rutas de administración
│   │   └── vision.py          # Rutas de visión computacional
│   ├── services/              # ⚙️ Servicios
│   │   ├── __init__.py
│   │   └── email_service.py   # Servicio de correo SMTP
│   ├── uploads/               # 📤 Imágenes subidas por usuarios
│   └── processed/             # 📥 Imágenes procesadas
├── Frontend/                   # 🌐 Cliente web (HTML/CSS/JS)
│   ├── index.html             # Página de login
│   ├── dashboard.html         # Dashboard de visión computacional
│   ├── admin.html             # Panel de administración
│   ├── registro.html          # Registro de nuevos usuarios
│   ├── verificacion.html      # Verificación de código email
│   ├── recuperar.html         # Solicitar recuperación de contraseña
│   ├── reset-password.html    # Restablecer contraseña
│   ├── generate-icons.html    # Generador de iconos PWA
│   ├── css/
│   │   └── styles.css         # Estilos Glassmorphism
│   ├── js/
│   │   ├── auth2.js           # Lógica de autenticación
│   │   ├── admin.js           # Lógica del panel admin
│   │   ├── vision.js          # Lógica de visión computacional
│   │   ├── verificacion.js    # Lógica de verificación
│   │   ├── recuperar.js       # Lógica de recuperación
│   │   ├── reset-password.js  # Lógica de reseteo
│   │   └── toast.js           # Sistema de notificaciones
│   ├── assets/
│   │   ├── icons/             # Iconos SVG
│   │   └── img/               # Imágenes y logos
│   ├── manifest.json          # PWA manifest
│   └── sw.js                  # Service Worker
├── install.bat                # 📦 Instalador para Windows
├── install.sh                 # 📦 Instalador para Linux/macOS
├── start.bat                  # ▶️ Inicio rápido Windows
├── start.sh                   # ▶️ Inicio rápido Linux/macOS
├── .env.example               # 📋 Variables de entorno ejemplo
├── .gitignore                 # 🚫 Archivos ignorados por Git
└── README.md                  # 📖 Este archivo
```

---

## 🛠️ Stack Tecnológico

| Capa | Tecnología | Versión |
|------|-----------|---------|
| **Backend** | Python + Flask | 3.8+ / 3.1.3 |
| **Frontend** | HTML5 + CSS3 + JavaScript ES6+ | — |
| **Base de Datos** | SQLite3 (WAL mode) | — |
| **Autenticación** | JWT (PyJWT) + bcrypt | 2.12.1 / 5.0.0 |
| **Visión Computacional** | OpenCV + NumPy | 4.13 / 2.2.6 |
| **PWA** | Service Worker + Manifest | — |
| **Correo** | SMTP Gmail (TLS) | — |
| **Seguridad** | Flask-Limiter + python-dotenv | 3.12+ / 1.1.0 |
| **CORS** | Flask-CORS | 6.0.2 |

---

## 📋 Requisitos Previos

Antes de instalar Argos2, asegúrate de tener lo siguiente:

- ✅ **Python 3.8 o superior** instalado y agregado al PATH del sistema
  - Descargar desde: [python.org](https://www.python.org/downloads/)
  - Verificar: `python --version`
- ✅ **pip** (incluido por defecto con Python 3.4+)
  - Verificar: `pip --version`
- ✅ **Cuenta de Gmail** con contraseña de aplicación configurada
  - 🔑 **Cómo obtener la contraseña de aplicación:**
    1. Ir a [Google Account](https://myaccount.google.com/) → **Seguridad**
    2. Activar **Verificación en dos pasos** (si no está activa)
    3. Ir a **Contraseñas de aplicación** (o buscar en la barra de búsqueda)
    4. Seleccionar **Correo** → **Otro dispositivo** → Escribir "Argos2"
    5. Copiar la contraseña de 16 caracteres generada (formato: `abcd efgh ijkl mnop`)
- ✅ **Navegador moderno** (Chrome, Firefox, Edge, Safari)
- ✅ **Git** (opcional, para clonar el repositorio)

---

## 🚀 Instalación Rápida

### Opción 1: Instalación Automática (Recomendada) ⚡

El instalador automatiza todo el proceso de configuración.

**Windows:**
```bash
# 1. Clonar el repositorio
git clone https://github.com/USUARIO/Argos2.git
cd Argos2

# 2. Ejecutar instalador
install.bat
```

**Linux / macOS:**
```bash
# 1. Clonar el repositorio
git clone https://github.com/USUARIO/Argos2.git
cd Argos2

# 2. Dar permisos y ejecutar instalador
chmod +x install.sh
./install.sh
```

**¿Qué hace el instalador automáticamente?**

1. ✅ Verifica que Python 3.8+ esté instalado
2. ✅ Crea un entorno virtual en `Backend/venv/`
3. ✅ Instala todas las dependencias desde `requirements.txt`
4. ✅ Solicita la configuración de correo electrónico interactivamente
5. ✅ Genera secretos seguros automáticamente (`SECRET_KEY` y `JWT_SECRET_KEY`)
6. ✅ Crea los directorios necesarios (`uploads/`, `processed/`)
7. ✅ Genera el archivo `.env` con toda la configuración

---

### Opción 2: Instalación Manual 🔧

Para quienes prefieren tener control total sobre cada paso:

```bash
# 1. Clonar el repositorio
git clone https://github.com/USUARIO/Argos2.git
cd Argos2

# 2. Crear entorno virtual
python -m venv Backend/venv

# 3. Activar entorno virtual
# Windows:
Backend\venv\Scripts\activate
# Linux/macOS:
source Backend/venv/bin/activate

# 4. Instalar dependencias
pip install -r Backend/requirements.txt

# 5. Configurar variables de entorno
# Windows:
copy .env.example .env
# Linux/macOS:
cp .env.example .env

# 6. Editar el archivo .env con tus valores:
# EMAIL_FROM=tu_correo@gmail.com
# EMAIL_PASSWORD=tu_contraseña_de_aplicacion
# SECRET_KEY=(generar con el comando de abajo)
# JWT_SECRET_KEY=(generar con el comando de abajo)

# Generar secretos seguros:
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_hex(32))"

# 7. Crear directorios necesarios
# Windows:
mkdir Backend\uploads Backend\processed
# Linux/macOS:
mkdir -p Backend/uploads Backend/processed
```

---

## ▶️ Inicio del Servidor

### Inicio Rápido

**Windows:**
```bash
start.bat
```

**Linux / macOS:**
```bash
chmod +x start.sh
./start.sh
```

### Inicio Manual

```bash
cd Backend

# Activar entorno virtual
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Iniciar servidor
python app.py
```

🌐 El servidor inicia en: **`http://localhost:5000`**

La base de datos SQLite se crea automáticamente en el primer inicio con todas las tablas necesarias.

---

## 📡 API Endpoints

### 🔑 Autenticación

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `POST` | `/api/login` | Iniciar sesión con credenciales |
| `POST` | `/api/register` | Registrar nuevo usuario |
| `POST` | `/api/logout` | Cerrar sesión actual |
| `POST` | `/api/logout-all` | Cerrar todas las sesiones activas |
| `POST` | `/api/refresh` | Renovar token de acceso |
| `GET` | `/api/me` | Obtener datos del usuario actual |
| `POST` | `/api/verify-code` | Verificar código de email |
| `POST` | `/api/resend-code` | Reenviar código de verificación |
| `POST` | `/api/validate-document` | Validar documento único |

### 🔄 Recuperación de Contraseña

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `POST` | `/api/forgot-password` | Solicitar código de recuperación por correo |
| `POST` | `/api/reset-password` | Restablecer contraseña con código |

### 👨‍💼 Administración (requiere rol `admin`)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api/admin/users` | Listar todos los usuarios |
| `PUT` | `/api/admin/users/<id>/role` | Cambiar rol de usuario |
| `PUT` | `/api/admin/users/<id>/status` | Activar/desactivar usuario |
| `DELETE` | `/api/admin/users/<id>` | Eliminar usuario |

### 🖥️ Visión Computacional

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `POST` | `/api/vision/process` | Procesar imagen (procesamiento asíncrono) |
| `GET` | `/api/vision/status/<task_id>` | Consultar estado de tarea de procesamiento |

### 🏥 Sistema

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| `GET` | `/api` | Documentación general de la API |
| `GET` | `/health` | Health check del servidor |

---

## 🔐 Seguridad

Argos2 implementa múltiples capas de seguridad:

- 🔹 **bcrypt** — Hash seguro de contraseñas con salt automático (cost factor configurable)
- 🔹 **JWT con JTI único** — Cada token tiene un identificador único para permitir revocación individual
- 🔹 **Versionado de tokens** — Revocación masiva al incrementar la versión del usuario en BD
- 🔹 **Blacklist de tokens** — Tokens revocados almacenados en base de datos para verificación rápida
- 🔹 **Rate Limiting** — Protección contra fuerza bruta por IP en endpoints sensibles (login, registro, etc.)
- 🔹 **Verificación de email obligatoria** — Requerida antes de permitir el acceso al sistema
- 🔹 **Códigos de un solo uso** — Códigos de verificación con expiración de 2 minutos
- 🔹 **Validación de entrada** — Regex estricto para email, username, contraseña y documento
- 🔹 **Auto-renovación de tokens** — Los tokens se renuevan automáticamente antes de expirar
- 🔹 **Protección de admin** — Un administrador no puede auto-modificarse su rol, estado ni eliminarse
- 🔹 **No revela existencia de emails** — Respuesta genérica en recuperación de contraseña para evitar enumeración

---

## 🗄️ Base de Datos

Argos2 utiliza **SQLite3 en modo WAL** (Write-Ahead Logging) para máximo rendimiento concurrente.

### Tablas principales:

| Tabla | Descripción |
|-------|-------------|
| `usuarios` | Datos de usuario, roles (`admin`/`usuario`), estados (`activo`/`inactivo`) |
| `codigos_verificacion` | Códigos de verificación de email y recuperación de contraseña |
| `tokens_revocados` | Blacklist de JWT revocados (JTI + fecha de expiración) |
| `user_token_versions` | Versionado de tokens por usuario para revocación masiva |
| `trazabilidad` | Registro de tareas de procesamiento de imágenes |
| `sesiones` | Sesiones de usuario activas |
| `intentos_login` | Log de intentos de acceso (exitosos y fallidos) |
| `logs_sistema` | Logs generales del sistema |

> La base de datos se crea automáticamente en `Backend/argos2.db` al primer inicio del servidor.

---

## 📱 PWA (Progressive Web App)

Argos2 es instalable como aplicación nativa en dispositivos móviles y de escritorio:

- 📲 **Service Worker** con estrategia *Network First* + cache fallback
- 💾 **38 assets cacheados** para funcionamiento offline parcial
- 🖼️ **Iconos para home screen** — 192×192 y 512×512 píxeles
- 🪟 **Display standalone** — Se ejecuta sin barra de navegador
- 🎨 **Theme color** — Integración visual con el sistema operativo

**Para instalar:** Abrir la app en Chrome → Menú (⋮) → "Instalar Argos2" o clic en el icono de instalación en la barra de direcciones.

---

## 🎨 Capturas de Pantalla

> *📸 Agregar capturas de pantalla aquí cuando estén disponibles*
>
> - Login
> - Dashboard de visión computacional
> - Panel de administración
> - Registro y verificación
> - PWA instalada en móvil

---

## 🔧 Variables de Entorno

Las variables se configuran en el archivo `.env` (en la raíz del proyecto):

| Variable | Requerida | Descripción | Ejemplo |
|----------|:---------:|-------------|---------|
| `EMAIL_FROM` | ✅ | Correo Gmail para envío de notificaciones | `tu_correo@gmail.com` |
| `EMAIL_PASSWORD` | ✅ | Contraseña de aplicación Gmail (16 caracteres) | `abcd efgh ijkl mnop` |
| `SECRET_KEY` | ✅ | Secreto para firmar sesiones de Flask | Auto-generado por instalador |
| `JWT_SECRET_KEY` | ✅ | Secreto para firmar tokens JWT | Auto-generado por instalador |
| `EMAIL_SMTP` | ❌ | Servidor SMTP | `smtp.gmail.com` (por defecto) |
| `EMAIL_PORT` | ❌ | Puerto SMTP | `587` (por defecto) |

> ⚠️ **Nunca compartas tu archivo `.env` ni lo subas al repositorio.** Ya está incluido en `.gitignore`.

---

## 👤 Creación del Primer Administrador

Después de la instalación, el primer usuario registrado obtiene el rol `usuario` por defecto. Para promoverlo a administrador:

```bash
cd Backend

# Activar entorno virtual primero:
# Windows: venv\Scripts\activate
# Linux/macOS: source venv/bin/activate

# Promover usuario a admin:
python -c "
import sqlite3
conn = sqlite3.connect('argos2.db')
cursor = conn.cursor()
cursor.execute(\"UPDATE usuarios SET rol='admin' WHERE username='TU_USERNAME'\")
conn.commit()
print(f'Filas afectadas: {cursor.rowcount}')
conn.close()
"
```

> 📌 Reemplaza `TU_USERNAME` con el nombre de usuario real. Si `Filas afectadas: 1`, la operación fue exitosa.

---

## 🤝 Contribuir

Las contribuciones son bienvenidas. Sigue estos pasos:

1. 🍴 **Fork** del repositorio
2. 🌿 **Crear rama feature:**
   ```bash
   git checkout -b feature/nueva-funcionalidad
   ```
3. 💾 **Commit de cambios:**
   ```bash
   git commit -m 'Agregar nueva funcionalidad'
   ```
4. 📤 **Push a la rama:**
   ```bash
   git push origin feature/nueva-funcionalidad
   ```
5. 🔀 **Abrir Pull Request** con descripción detallada de los cambios

---

## 📄 Licencia

Este proyecto es de **uso privado**. Todos los derechos reservados.

© 2025 Argos2. Uso restringido. No se permite la distribución, modificación ni uso comercial sin autorización expresa del autor.
