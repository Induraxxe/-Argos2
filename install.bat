@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================
:: INSTALADOR ARGOS2 - WINDOWS
:: ============================================

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║           INSTALADOR ARGOS2 - Windows                      ║
echo ║     Sistema de Vision Computacional con Autenticacion      ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

:: --------------------------------------------
:: 1. VERIFICAR PYTHON
:: --------------------------------------------
echo [1/6] Verificando Python...

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ ERROR: Python no esta instalado o no esta en PATH.
    echo.
    echo    Por favor instale Python 3.8 o superior desde:
    echo    https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYTHON_VERSION=%%v
echo ✅ Python encontrado: !PYTHON_VERSION!

:: Validar que sea Python 3.8+
for /f "tokens=1,2 delims=." %%a in ("!PYTHON_VERSION!") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if !PY_MAJOR! lss 3 (
    echo.
    echo ❌ ERROR: Se requiere Python 3.8 o superior. Encontrado: !PYTHON_VERSION!
    echo.
    pause
    exit /b 1
)
if !PY_MAJOR! equ 3 if !PY_MINOR! lss 8 (
    echo.
    echo ❌ ERROR: Se requiere Python 3.8 o superior. Encontrado: !PYTHON_VERSION!
    echo.
    pause
    exit /b 1
)
echo ✅ Version valida: !PYTHON_VERSION! ^(3.8+ requerido^)

:: --------------------------------------------
:: 2. CREAR ENTORNO VIRTUAL
:: --------------------------------------------
echo.
echo [2/6] Configurando entorno virtual...

cd /d "%~dp0"

if exist "Backend\venv" (
    echo    Entorno virtual ya existe, verificando...
    
    :: Verificar si el venv es valido
    if exist "Backend\venv\Scripts\python.exe" (
        echo ✅ Entorno virtual valido encontrado
    ) else (
        echo    ⚠️  Entorno virtual corrupto, recreando...
        rmdir /s /q "Backend\venv"
        python -m venv Backend\venv
        echo ✅ Entorno virtual creado
    )
) else (
    echo    Creando nuevo entorno virtual...
    python -m venv Backend\venv
    echo ✅ Entorno virtual creado
)

:: --------------------------------------------
:: 3. ACTIVAR ENTORNO VIRTUAL
:: --------------------------------------------
echo.
echo [3/6] Activando entorno virtual...

call Backend\venv\Scripts\activate.bat
if errorlevel 1 (
    echo ❌ ERROR: No se pudo activar el entorno virtual
    pause
    exit /b 1
)
echo ✅ Entorno virtual activado

:: --------------------------------------------
:: 4. VERIFICAR E INSTALAR DEPENDENCIAS
:: --------------------------------------------
echo.
echo [4/6] Verificando dependencias...

:: Verificar si pip esta actualizado
python -m pip install --upgrade pip --quiet

:: Verificar si las dependencias estan instaladas
set NEED_INSTALL=0

:: Verificar Flask
python -c "import flask" 2>nul
if errorlevel 1 (
    echo    ⚠️  Flask no esta instalado
    set NEED_INSTALL=1
) else (
    echo    ✅ Flask instalado
)

:: Verificar flask-cors
python -c "import flask_cors" 2>nul
if errorlevel 1 (
    echo    ⚠️  flask-cors no esta instalado
    set NEED_INSTALL=1
) else (
    echo    ✅ flask-cors instalado
)

:: Verificar PyJWT
python -c "import jwt" 2>nul
if errorlevel 1 (
    echo    ⚠️  PyJWT no esta instalado
    set NEED_INSTALL=1
) else (
    echo    ✅ PyJWT instalado
)

:: Verificar bcrypt
python -c "import bcrypt" 2>nul
if errorlevel 1 (
    echo    ⚠️  bcrypt no esta instalado
    set NEED_INSTALL=1
) else (
    echo    ✅ bcrypt instalado
)

:: Verificar opencv-python
python -c "import cv2" 2>nul
if errorlevel 1 (
    echo    ⚠️  opencv-python no esta instalado
    set NEED_INSTALL=1
) else (
    echo    ✅ opencv-python instalado
)

:: Verificar numpy
python -c "import numpy" 2>nul
if errorlevel 1 (
    echo    ⚠️  numpy no esta instalado
    set NEED_INSTALL=1
) else (
    echo    ✅ numpy instalado
)

:: Instalar dependencias faltantes
if !NEED_INSTALL! equ 1 (
    echo.
    echo    📦 Instalando dependencias faltantes...
    pip install -r Backend\requirements.txt --quiet
    if errorlevel 1 (
        echo ❌ ERROR: No se pudieron instalar las dependencias
        pause
        exit /b 1
    )
    echo ✅ Dependencias instaladas correctamente
) else (
    echo.
    echo ✅ Todas las dependencias estan instaladas
)

:: --------------------------------------------
:: 5. CONFIGURAR VARIABLES DE ENTORNO (.env)
:: --------------------------------------------
echo.
echo [5/6] Configurando variables de entorno...

cd /d "%~dp0"

if exist ".env" (
    echo.
    echo    ⚠️  Ya existe un archivo .env configurado.
    set /p OVERWRITE="   ¿Desea sobrescribirlo? (S/N): "
    if /i "!OVERWRITE!"=="S" (
        del .env
        goto CONFIGURE_ENV
    ) else (
        echo    ✅ Manteniendo configuración existente de .env
        goto SKIP_ENV
    )
)

:CONFIGURE_ENV
echo.
echo    ─────────────────────────────────────────────
echo    Configuración de correo SMTP
echo    ─────────────────────────────────────────────
echo.
set /p ENV_EMAIL="   Correo SMTP (ej: tu_correo@gmail.com): "
set /p ENV_EMAIL_PASS="   Contraseña de aplicación SMTP: "

echo.
echo    Generando secretos automáticos...

:: Generar SECRET_KEY
for /f "delims=" %%k in ('python -c "import secrets; print(secrets.token_hex(32))"') do set SECRET_KEY_GEN=%%k

:: Generar JWT_SECRET_KEY
for /f "delims=" %%j in ('python -c "import secrets; print(secrets.token_hex(32))"') do set JWT_SECRET_GEN=%%j

:: Escribir archivo .env
(
echo # Configuración de correo SMTP
echo EMAIL_FROM=!ENV_EMAIL!
echo EMAIL_PASSWORD=!ENV_EMAIL_PASS!
echo.
echo # Secretos de la aplicación
echo SECRET_KEY=!SECRET_KEY_GEN!
echo JWT_SECRET_KEY=!JWT_SECRET_GEN!
) > .env

echo    ✅ Archivo .env creado con secretos generados automáticamente

:SKIP_ENV

:: --------------------------------------------
:: 6. CREAR DIRECTORIOS NECESARIOS
:: --------------------------------------------
echo.
echo [6/6] Configurando directorios...

if not exist "Backend\uploads" mkdir "Backend\uploads"
if not exist "Backend\processed" mkdir "Backend\processed"
echo ✅ Directorios creados

:: --------------------------------------------
:: RESUMEN Y MENU
:: --------------------------------------------
echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║              INSTALACION COMPLETADA                        ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo    El sistema esta listo para ejecutarse.
echo.
echo    Opciones disponibles:
echo.
echo    [1] Iniciar Argos2 ahora
echo    [2] Iniciar Argos2 y abrir navegador
echo    [3] Solo instalar (no iniciar)
echo    [S] Salir
echo.
set /p CHOICE="   Seleccione una opcion [1/2/3/S]: "

if /i "!CHOICE!"=="1" goto START_APP
if /i "!CHOICE!"=="2" goto START_APP_BROWSER
if /i "!CHOICE!"=="3" goto END
if /i "!CHOICE!"=="S" goto END
goto END

:START_APP
echo.
echo 🚀 Iniciando Argos2...
echo    Servidor: http://localhost:5000
echo    Presione Ctrl+C para detener
echo.
cd Backend
python app.py
goto END

:START_APP_BROWSER
echo.
echo 🚀 Iniciando Argos2...
echo    Servidor: http://localhost:5000
echo    Presione Ctrl+C para detener
echo.
start http://localhost:5000
cd Backend
python app.py
goto END

:END
echo.
echo Gracias por usar Argos2!
pause
