#!/bin/bash

# ============================================
# INSTALADOR ARGOS2 - LINUX
# (Caracteres ASCII para maxima portabilidad)
# ============================================

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Obtener directorio del script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "============================================================"
echo "           INSTALADOR ARGOS2 - Linux"
echo "     Sistema de Vision Computacional con Autenticacion"
echo "============================================================"
echo ""

# --------------------------------------------
# 1. VERIFICAR PYTHON
# --------------------------------------------
echo -e "${CYAN}[1/6] Verificando Python...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] Python3 no esta instalado.${NC}"
    echo ""
    echo "   Por favor instale Python 3.8 o superior:"
    echo ""
    echo "   Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "   Fedora:        sudo dnf install python3 python3-virtualenv"
    echo "   Arch:          sudo pacman -S python python-virtualenv"
    echo ""
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
echo -e "${GREEN}[OK] Python encontrado: $PYTHON_VERSION${NC}"

# Validar que sea Python 3.8+
PY_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]); then
    echo -e "${RED}[ERROR] Se requiere Python 3.8 o superior. Encontrado: $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}[OK] Version valida: $PYTHON_VERSION (3.8+ requerido)${NC}"

# --------------------------------------------
# 2. CREAR ENTORNO VIRTUAL
# --------------------------------------------
echo ""
echo -e "${CYAN}[2/6] Configurando entorno virtual...${NC}"

cd "$SCRIPT_DIR"

if [ -d "Backend/venv" ]; then
    echo "   Entorno virtual ya existe, verificando..."
    
    # Verificar si el venv es valido
    if [ -f "Backend/venv/bin/python" ]; then
        echo -e "${GREEN}[OK] Entorno virtual valido encontrado${NC}"
    else
        echo -e "${YELLOW}   [!] Entorno virtual corrupto, recreando...${NC}"
        rm -rf "Backend/venv"
        python3 -m venv Backend/venv
        echo -e "${GREEN}[OK] Entorno virtual creado${NC}"
    fi
else
    echo "   Creando nuevo entorno virtual..."
    python3 -m venv Backend/venv
    echo -e "${GREEN}[OK] Entorno virtual creado${NC}"
fi

# --------------------------------------------
# 3. ACTIVAR ENTORNO VIRTUAL
# --------------------------------------------
echo ""
echo -e "${CYAN}[3/6] Activando entorno virtual...${NC}"

source Backend/venv/bin/activate

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] No se pudo activar el entorno virtual${NC}"
    exit 1
fi

echo -e "${GREEN}[OK] Entorno virtual activado${NC}"

# --------------------------------------------
# 4. VERIFICAR E INSTALAR DEPENDENCIAS
# --------------------------------------------
echo ""
echo -e "${CYAN}[4/6] Verificando dependencias...${NC}"

# Actualizar pip
pip install --upgrade pip --quiet 2>/dev/null

# Funcion para verificar modulo
check_module() {
    python -c "import $1" 2>/dev/null
    return $?
}

# Verificar cada dependencia
NEED_INSTALL=0

if check_module flask; then
    echo "   [OK] Flask instalado"
else
    echo -e "   ${YELLOW}[!] Flask no esta instalado${NC}"
    NEED_INSTALL=1
fi

if check_module flask_cors; then
    echo "   [OK] flask-cors instalado"
else
    echo -e "   ${YELLOW}[!] flask-cors no esta instalado${NC}"
    NEED_INSTALL=1
fi

if check_module jwt; then
    echo "   [OK] PyJWT instalado"
else
    echo -e "   ${YELLOW}[!] PyJWT no esta instalado${NC}"
    NEED_INSTALL=1
fi

if check_module bcrypt; then
    echo "   [OK] bcrypt instalado"
else
    echo -e "   ${YELLOW}[!] bcrypt no esta instalado${NC}"
    NEED_INSTALL=1
fi

if check_module cv2; then
    echo "   [OK] opencv-python instalado"
else
    echo -e "   ${YELLOW}[!] opencv-python no esta instalado${NC}"
    NEED_INSTALL=1
fi

if check_module numpy; then
    echo "   [OK] numpy instalado"
else
    echo -e "   ${YELLOW}[!] numpy no esta instalado${NC}"
    NEED_INSTALL=1
fi

# Instalar dependencias faltantes
if [ $NEED_INSTALL -eq 1 ]; then
    echo ""
    echo "   [PAQUETE] Instalando dependencias faltantes..."
    pip install -r Backend/requirements.txt --quiet
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR] No se pudieron instalar las dependencias${NC}"
        exit 1
    fi
    echo -e "${GREEN}[OK] Dependencias instaladas correctamente${NC}"
else
    echo ""
    echo -e "${GREEN}[OK] Todas las dependencias estan instaladas${NC}"
fi

# --------------------------------------------
# 5. CONFIGURAR VARIABLES DE ENTORNO (.env)
# --------------------------------------------
echo ""
echo -e "${CYAN}[5/6] Configurando variables de entorno...${NC}"

cd "$SCRIPT_DIR"

if [ -f ".env" ]; then
    echo ""
    echo "   [!] Ya existe un archivo .env configurado."
    read -p "   Desea sobrescribirlo? (s/N): " OVERWRITE
    if [ "$OVERWRITE" = "s" ] || [ "$OVERWRITE" = "S" ]; then
        rm .env
    else
        echo -e "   ${GREEN}[OK] Manteniendo configuracion existente de .env${NC}"
        SKIP_ENV=1
    fi
fi

if [ "$SKIP_ENV" != "1" ]; then
    echo ""
    echo "   ------------------------------------------------"
    echo "   Configuracion de correo SMTP"
    echo "   ------------------------------------------------"
    echo "   El correo de la empresa se configura automaticamente."
    echo "   (No requiere accion del usuario)"
    echo ""

    echo ""
    echo "   ------------------------------------------------"
    echo "   Configuracion de Vision Computacional (Roboflow)"
    echo "   ------------------------------------------------"
    echo "   Puede dejar los campos vacios y configurarlos despues."
    echo "   (Valores entre parentesis = valor por defecto al pulsar Enter)"
    echo ""

    while true; do
        read -p "   Modo de vision por defecto [off/cloud/local] (off): " VISION_MODE
        VISION_MODE=${VISION_MODE:-off}
        case "$VISION_MODE" in
            off|cloud|local) break ;;
            *) echo "   [!] Opcion no valida. Use: off, cloud o local." ;;
        esac
    done

    read -p "   API Key de Roboflow (vacio = configurar despues): " RF_API_KEY
    read -p "   URL servidor serverless de Roboflow (https://serverless.roboflow.com): " RF_API_URL
    RF_API_URL=${RF_API_URL:-https://serverless.roboflow.com}
    read -p "   Workspace de Roboflow (ej: oswaldos-workspace-0ikuh): " RF_WORKSPACE
    read -p "   Workflow ID (ej: custom-workflow-4): " RF_WORKFLOW_ID
    read -p "   Input de imagen del workflow (image): " RF_IMG_INPUT
    RF_IMG_INPUT=${RF_IMG_INPUT:-image}
    read -p "   Usar cache del workflow [true/false] (true): " RF_USE_CACHE
    RF_USE_CACHE=${RF_USE_CACHE:-true}
    read -p "   Usar overlay del servidor [true/false] (false): " RF_SERVER_OVERLAY
    RF_SERVER_OVERLAY=${RF_SERVER_OVERLAY:-false}

    RF_MODEL_ID=""
    read -p "   Configurar MODEL_ID estandar? (solo si NO usa workflows) (s/N): " ASK_MODEL
    if [ "$ASK_MODEL" = "s" ] || [ "$ASK_MODEL" = "S" ]; then
        read -p "      MODEL_ID (ej: proyecto/1): " RF_MODEL_ID
    fi

    echo ""
    echo "   Generando secretos automaticos..."

    # Generar SECRET_KEY (usar 'python' del venv activado, no python3 del sistema)
    SECRET_KEY_GEN=$(python -c "import secrets; print(secrets.token_hex(32))")

    # Generar JWT_SECRET_KEY
    JWT_SECRET_GEN=$(python -c "import secrets; print(secrets.token_hex(32))")

    # Escribir archivo .env
    cat > .env << EOF
# Configuracion de correo SMTP
EMAIL_FROM=sqprpject@gmail.com
EMAIL_PASSWORD=vzon onlg cxyu irji
EMAIL_SMTP=smtp.gmail.com
EMAIL_PORT=587

# Secretos de la aplicacion
SECRET_KEY=${SECRET_KEY_GEN}
JWT_SECRET_KEY=${JWT_SECRET_GEN}

# ============================
# Vision Computacional (Roboflow)
# ============================
VISION_DEFAULT_MODE=${VISION_MODE}
ROBOFLOW_API_KEY=${RF_API_KEY}
ROBOFLOW_API_URL=${RF_API_URL}
ROBOFLOW_WORKSPACE=${RF_WORKSPACE}
ROBOFLOW_WORKFLOW_ID=${RF_WORKFLOW_ID}
ROBOFLOW_WORKFLOW_IMAGE_INPUT=${RF_IMG_INPUT}
ROBOFLOW_WORKFLOW_USE_CACHE=${RF_USE_CACHE}
ROBOFLOW_USE_SERVER_OVERLAY=${RF_SERVER_OVERLAY}
ROBOFLOW_MODEL_ID=${RF_MODEL_ID}

# --- Modo Local (Inferencia Edge) ---
ROBOFLOW_LOCAL_MODEL_ID=
INFERENCE_DEVICE=cpu
LOCAL_INFERENCE_WORKERS=2
SAMPLE_INTERVAL=1.5
EOF

    echo -e "   ${GREEN}[OK] Archivo .env creado con secretos generados automaticamente${NC}"
fi

# --------------------------------------------
# 6. CREAR DIRECTORIOS NECESARIOS
# --------------------------------------------
echo ""
echo -e "${CYAN}[6/6] Configurando directorios...${NC}"

mkdir -p Backend/uploads
mkdir -p Backend/processed
echo -e "${GREEN}[OK] Directorios creados${NC}"

# --------------------------------------------
# RESUMEN Y MENU
# --------------------------------------------
echo ""
echo "============================================================"
echo "               INSTALACION COMPLETADA"
echo "============================================================"
echo ""
echo "   El sistema esta listo para ejecutarse."
echo ""
echo "   Opciones disponibles:"
echo ""
echo "   [1] Iniciar Argos2 ahora"
echo "   [2] Iniciar Argos2 y abrir navegador"
echo "   [3] Solo instalar (no iniciar)"
echo "   [S] Salir"
echo ""
read -p "   Seleccione una opcion [1/2/3/S]: " CHOICE

case $CHOICE in
    1)
        echo ""
        echo ">>> Iniciando Argos2..."
        echo "   Servidor: http://localhost:5000"
        echo "   Presione Ctrl+C para detener"
        echo ""
        cd Backend
        python app.py
        ;;
    2)
        echo ""
        echo ">>> Iniciando Argos2..."
        echo "   Servidor: http://localhost:5000"
        echo "   Presione Ctrl+C para detener"
        echo ""
        
        # Abrir navegador segun el entorno de escritorio
        if command -v xdg-open &> /dev/null; then
            xdg-open http://localhost:5000 &
        elif command -v gnome-open &> /dev/null; then
            gnome-open http://localhost:5000 &
        elif command -v firefox &> /dev/null; then
            firefox http://localhost:5000 &
        fi
        
        cd Backend
        python app.py
        ;;
    3|S|s)
        echo ""
        echo "Gracias por usar Argos2!"
        ;;
    *)
        echo ""
        echo "Opcion no valida. Saliendo..."
        ;;
esac

exit 0
