"""
config.py
Lee las variables de entorno (.env) y las expone como constantes
para el resto del sistema.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Carpeta raíz del proyecto (donde está este archivo)
BASE_DIR = Path(__file__).resolve().parent

# Carga el .env de la raíz del proyecto, sin importar desde dónde se ejecute
load_dotenv(BASE_DIR / ".env")


def _get_env(nombre: str, default: str | None = None, obligatoria: bool = False) -> str | None:
    """Obtiene una variable de entorno; falla con un mensaje claro si es obligatoria."""
    valor = os.getenv(nombre, default)
    if obligatoria and (valor is None or valor == ""):
        raise RuntimeError(
            f"Falta la variable de entorno '{nombre}'. Revisa tu archivo .env"
        )
    return valor


# ---------------------------------------------------------------------
# MySQL
# ---------------------------------------------------------------------
DB_CONFIG = {
    "host": _get_env("DB_HOST", "localhost"),
    "port": int(_get_env("DB_PORT", "3306")),
    "user": _get_env("DB_USER", obligatoria=True),
    "password": _get_env("DB_PASSWORD", ""),
    "database": _get_env("DB_NAME", "estacion_jacha_inti"),
    "charset": "utf8mb4",
}

DB_POOL_SIZE = int(_get_env("DB_POOL_SIZE", "5"))

# ---------------------------------------------------------------------
# Cámara IP (IP Webcam). Si está vacío, /stream muestra 'Sin señal'
# ---------------------------------------------------------------------
CAMARA_URL = _get_env("CAMARA_URL") or None

# ---------------------------------------------------------------------
# Tesseract OCR
# ---------------------------------------------------------------------
# Si está vacío, pytesseract usará el 'tesseract' disponible en el PATH
TESSERACT_CMD = _get_env("TESSERACT_CMD") or None
TESSERACT_LANG = _get_env("TESSERACT_LANG", "eng")

# --psm 7 : una sola línea de texto | whitelist: solo letras mayúsculas y dígitos
TESSERACT_CONFIG = (
    "--oem 3 --psm 7 "
    "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)

# ---------------------------------------------------------------------
# Reglas del sistema
# ---------------------------------------------------------------------
# Formato de placa boliviana (coincide con el CHECK de la BD): 1234ABC
PLACA_REGEX = r"^[0-9]{3,4}[A-Z]{3}$"
SURTIDOR_ID_DEFECTO = 1