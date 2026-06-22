#!/usr/bin/env python3
"""Script de diagnóstico: prueba el workflow de Roboflow directamente."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Cargar settings de la BD
from services.settings_service import sync_settings_to_env, get_vision_settings
sync_settings_to_env()
settings = get_vision_settings()

api_key = settings.get('roboflow_api_key') or os.environ.get('ROBOFLOW_API_KEY')
workspace = settings.get('roboflow_workspace') or os.environ.get('ROBOFLOW_WORKSPACE')
workflow_id = settings.get('roboflow_workflow_id') or os.environ.get('ROBOFLOW_WORKFLOW_ID')

print(f"API Key: {'✓ configurada' if api_key else '✗ FALTA'}")
print(f"Workspace: {workspace}")
print(f"Workflow ID: {workflow_id}")

if not all([api_key, workspace, workflow_id]):
    print("ERROR: Faltan credenciales. Configúralas en Ajustes.")
    sys.exit(1)

from inference_sdk import InferenceHTTPClient

client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=api_key
)

# Crear imagen de prueba (cuadrado rojo 640x480)
import numpy as np
import cv2

frame = np.zeros((480, 640, 3), dtype=np.uint8)
cv2.rectangle(frame, (100, 100), (300, 300), (0, 0, 255), -1)  # rectángulo rojo
cv2.putText(frame, "TEST", (200, 200), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)

# Método 1: Archivo temporal
import tempfile
tmp_fd, tmp_path = tempfile.mkstemp(suffix='.jpg')
os.close(tmp_fd)
cv2.imwrite(tmp_path, frame)

print(f"\n--- Método 1: Archivo temporal ({tmp_path}) ---")
try:
    result1 = client.run_workflow(
        workspace_name=workspace,
        workflow_id=workflow_id,
        images={"image": tmp_path},
        use_cache=False
    )
    print(f"Resultado: {result1}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
finally:
    os.unlink(tmp_path)

# Método 2: numpy array
print(f"\n--- Método 2: numpy array directo ---")
try:
    result2 = client.run_workflow(
        workspace_name=workspace,
        workflow_id=workflow_id,
        images={"image": frame},
        use_cache=False
    )
    print(f"Resultado: {result2}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

# Método 3: base64
import base64
_, buf = cv2.imencode('.jpg', frame)
b64 = base64.b64encode(buf.tobytes()).decode('ascii')
print(f"\n--- Método 3: base64 string ---")
try:
    result3 = client.run_workflow(
        workspace_name=workspace,
        workflow_id=workflow_id,
        images={"image": b64},
        use_cache=False
    )
    print(f"Resultado: {result3}")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")

print("\n--- Fin del diagnóstico ---")
print("Si TODOS los métodos devuelven [{}], el problema está en la configuración")
print("del workflow en Roboflow (output blocks no configurados o workflow mal publicado).")
