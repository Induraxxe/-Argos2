@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================
:: INICIADOR RAPIDO ARGOS2 - WINDOWS
:: ============================================

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║           INICIADOR ARGOS2 - Windows                       ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: Verificar si el entorno virtual existe
if not exist "Backend\venv\Scripts\activate.bat" (
    echo ❌ ERROR: El entorno virtual no existe.
    echo.
    echo    Por favor ejecute install.bat primero para instalar el sistema.
    echo.
    pause
    exit /b 1
)

:: Activar entorno virtual
call Backend\venv\Scripts\activate.bat

:: Verificar si las dependencias estan instaladas
python -c "import flask" 2>nul
if errorlevel 1 (
    echo ⚠️  Las dependencias no estan instaladas. Instalando...
    pip install -r Backend\requirements.txt
)

:: Verificar que .env existe
if not exist ".env" (
    echo ❌ ERROR: El archivo .env no existe.
    echo.
    echo    Por favor ejecute install.bat primero para configurar las variables de entorno.
    echo.
    pause
    exit /b 1
)

:: Cargar variables del archivo .env
echo Cargando variables de entorno...
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    set "line=%%a"
    if not "!line:~0,1!"=="#" (
        set "%%a=%%b"
    )
)
echo ✅ Variables de entorno cargadas

:: Crear directorios si no existen
if not exist "Backend\uploads" mkdir "Backend\uploads"
if not exist "Backend\processed" mkdir "Backend\processed"

:: Iniciar aplicacion
echo.
echo 🚀 Iniciando Argos2...
echo    Servidor: http://localhost:5000
echo    Presione Ctrl+C para detener
echo.
cd Backend
python app.py
