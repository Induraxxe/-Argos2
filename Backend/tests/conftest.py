"""
Configuración de pytest para los tests de Argos2.

Añade el directorio ``Backend/`` al ``sys.path`` para que los tests puedan
importar los paquetes del proyecto (``services``, ``routes``, etc.) sin
importar desde dónde se ejecute pytest.
"""

import os
import sys

# Directorio Backend/ (padre del directorio tests/)
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
