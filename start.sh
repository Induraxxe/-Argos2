#!/bin/bash

# ============================================
# INICIADOR RAPIDO ARGOS2 - LINUX
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
echo "╔════════════════════════════════════════════════════════════╗"
echo "║           INICIADOR ARGOS2 - Linux                          ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

cd "$SCRIPT_DIR"

# Verificar si el entorno virtual existe
if [ ! -f "Backend/venv/bin/activate" ]; then
    echo -e "${RED}❌ ERROR: El entorno virtual no existe.${NC}"
    echo ""
    echo "   Por favor ejecute ./install.sh primero para instalar el sistema."
    echo ""
    exit 1
fi

# Activar entorno virtual
source Backend/venv/bin/activate

# Verificar si las dependencias estan instaladas
if ! python -c "import flask" 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Las dependencias no estan instaladas. Instalando...${NC}"
    pip install -r Backend/requirements.txt
fi

# Verificar que .env existe
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ ERROR: El archivo .env no existe.${NC}"
    echo ""
    echo "   Por favor ejecute ./install.sh primero para configurar las variables de entorno."
    echo ""
    exit 1
fi

# Cargar variables del archivo .env
echo "Cargando variables de entorno..."
set -a
source .env
set +a
echo -e "${GREEN}✅ Variables de entorno cargadas${NC}"

# Crear directorios si no existen
mkdir -p Backend/uploads
mkdir -p Backend/processed

# Iniciar aplicacion
echo ""
echo -e "${GREEN}🚀 Iniciando Argos2...${NC}"
echo "   Servidor: http://localhost:5000"
echo "   Presione Ctrl+C para detener"
echo ""
cd Backend
python app.py
