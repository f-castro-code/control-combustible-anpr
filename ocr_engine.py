"""
ocr_engine.py
Motor de visión artificial (ANPR) para placas bolivianas.

Flujo:
    imagen -> localizar región de la placa (contornos rectangulares)
           -> escala de grises + binarización de Otsu
           -> Tesseract OCR
           -> limpieza + corrección de confusiones (O/0, I/1, B/8...)
           -> validación con regex  ^[0-9]{3,4}[A-Z]{3}$

Uso principal:
    resultado = leer_placa(imagen_bgr)
    resultado = leer_placa_desde_archivo("capturas/foto.jpg")
"""

import logging
import re
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from config import (
    PLACA_REGEX,
    TESSERACT_CMD,
    TESSERACT_CONFIG,
    TESSERACT_LANG,
)

logger = logging.getLogger(__name__)

if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

_PLACA_RE = re.compile(PLACA_REGEX)


ANCHO_MAX_PROCESO = 1280
ALTO_PLACA_OCR = 120
RATIO_MIN, RATIO_MAX = 1.2, 7.0       # Tolera perspectiva y ángulos
AREA_MIN_REL = 0.001                  # Capta placas lejanas (0.1% de la foto)
MAX_REGIONES = 6                      # Intenta más candidato por imagen
CONFIANZA_SUFICIENTE = 75.0

# Confusiones típicas del OCR según la posición (dígito vs letra)
_A_DIGITO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1",
             "Z": "2", "S": "5", "G": "6", "T": "7", "B": "8"}
_A_LETRA = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}


# ---------------------------------------------------------------------
# Carga de imágenes
# ---------------------------------------------------------------------
def cargar_imagen(ruta: str | Path) -> np.ndarray:
    """Lee una imagen (compatible con rutas con tildes/espacios en Windows)."""
    datos = np.fromfile(str(ruta), dtype=np.uint8)
    imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if imagen is None:
        raise ValueError(f"No se pudo leer la imagen: {ruta}")
    return imagen


def _reducir(imagen: np.ndarray) -> np.ndarray:
    alto, ancho = imagen.shape[:2]
    if ancho <= ANCHO_MAX_PROCESO:
        return imagen
    escala = ANCHO_MAX_PROCESO / ancho
    return cv2.resize(imagen, (ANCHO_MAX_PROCESO, int(alto * escala)),
                      interpolation=cv2.INTER_AREA)


# ---------------------------------------------------------------------
# 1. Localización de la placa (región de interés)
# ---------------------------------------------------------------------
def _buscar_regiones(imagen: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    Busca contornos de 4 lados con proporciones de placa.
    Retorna hasta MAX_REGIONES cajas (x, y, w, h), de mayor a menor área.
    """
    alto_img, ancho_img = imagen.shape[:2]
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    suave = cv2.bilateralFilter(gris, 11, 17, 17)
    bordes = cv2.Canny(suave, 30, 200)
    bordes = cv2.dilate(bordes, np.ones((3, 3), np.uint8), iterations=1)

    contornos, _ = cv2.findContours(bordes, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contornos = sorted(contornos, key=cv2.contourArea, reverse=True)[:40]

    candidatos = []
    for c in contornos:
        perimetro = cv2.arcLength(c, True)
        aprox = cv2.approxPolyDP(c, 0.018 * perimetro, True)
        if len(aprox) != 4:
            continue
        x, y, w, h = cv2.boundingRect(aprox)
        if h == 0:
            continue
        ratio = w / h
        area_rel = (w * h) / (ancho_img * alto_img)
        if RATIO_MIN <= ratio <= RATIO_MAX and area_rel >= AREA_MIN_REL:
            candidatos.append((w * h, (x, y, w, h)))

    candidatos.sort(key=lambda t: t[0], reverse=True)

    regiones = []
    for _, (x, y, w, h) in candidatos:
        # Evita regiones casi idénticas (contornos anidados)
        if any(abs(x - rx) < 10 and abs(y - ry) < 10 and abs(w - rw) < 20
               for rx, ry, rw, _ in regiones):
            continue
        regiones.append((x, y, w, h))
        if len(regiones) >= MAX_REGIONES:
            break
    return regiones


def _recortar(imagen: np.ndarray, caja: tuple[int, int, int, int], margen: float = 0.04) -> np.ndarray:
    """Recorta la caja con un pequeño margen para no cortar caracteres."""
    x, y, w, h = caja
    mx, my = int(w * margen), int(h * margen)
    y1, y2 = max(0, y - my), min(imagen.shape[0], y + h + my)
    x1, x2 = max(0, x - mx), min(imagen.shape[1], x + w + mx)
    return imagen[y1:y2, x1:x2]


# ---------------------------------------------------------------------
# 2. Preprocesamiento: grises + Otsu
# ---------------------------------------------------------------------
def _quitar_marco(binaria: np.ndarray) -> np.ndarray:
    """
    Borra las líneas largas del marco de la placa (horizontales y verticales)
    sin tocar los caracteres, aunque estén pegados al marco.
    Recibe texto negro sobre fondo blanco y devuelve lo mismo.
    """
    alto, ancho = binaria.shape
    texto = cv2.bitwise_not(binaria)  # texto/marco en blanco

    # Un trazo de letra nunca es tan largo como el marco
    k_horiz = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, ancho // 3), 1))
    k_vert = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(alto * 0.6))))
    lineas = cv2.bitwise_or(
        cv2.morphologyEx(texto, cv2.MORPH_OPEN, k_horiz),
        cv2.morphologyEx(texto, cv2.MORPH_OPEN, k_vert),
    )
    lineas = cv2.dilate(lineas, np.ones((3, 3), np.uint8), iterations=1)

    limpio = cv2.bitwise_and(texto, cv2.bitwise_not(lineas))
    return cv2.bitwise_not(limpio)


def _preprocesar(recorte: np.ndarray) -> list[np.ndarray]:
    gris = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)

    alto, ancho = gris.shape
    if alto == 0 or ancho == 0:
        return []
        
    escala = ALTO_PLACA_OCR / alto
    gris = cv2.resize(gris, (max(1, int(ancho * escala)), ALTO_PLACA_OCR), interpolation=cv2.INTER_CUBIC)

    # Mejorar contraste local
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gris_contrastada = clahe.apply(gris)

    suave = cv2.GaussianBlur(gris_contrastada, (3, 3), 0)
    _, bin_otsu = cv2.threshold(suave, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bin_adapt = cv2.adaptiveThreshold(suave, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 8)

    variaciones = []
    for b in [bin_otsu, bin_adapt]:
        if np.mean(b) < 127:
            b = cv2.bitwise_not(b)
        b_limpio = _quitar_marco(b)
        
        borda = cv2.copyMakeBorder(b_limpio, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=255)
        variaciones.append(borda)
        variaciones.append(cv2.bitwise_not(borda))

    return variaciones

# ---------------------------------------------------------------------
# 3. OCR
# ---------------------------------------------------------------------
def _ocr(binaria: np.ndarray) -> tuple[str, float]:
    """Ejecuta Tesseract y retorna (texto_crudo, confianza_media 0-100)."""
    try:
        datos = pytesseract.image_to_data(
            binaria, lang=TESSERACT_LANG, config=TESSERACT_CONFIG,
            output_type=Output.DICT,
        )
    except pytesseract.TesseractNotFoundError as e:
        raise RuntimeError(
            "No se encontró Tesseract. Instálalo y revisa TESSERACT_CMD en el .env"
        ) from e

    textos, confianzas = [], []
    for texto, conf in zip(datos["text"], datos["conf"]):
        if texto.strip():
            textos.append(texto.strip())
            c = float(conf)
            if c >= 0:
                confianzas.append(c)

    crudo = "".join(textos)
    confianza = sum(confianzas) / len(confianzas) if confianzas else 0.0
    return crudo, confianza


# ---------------------------------------------------------------------
# 4. Limpieza y validación de la placa
# ---------------------------------------------------------------------
def _corregir_posiciones(candidato: str) -> str:
    """Formato esperado: (3 o 4 dígitos) + 3 letras. Corrige confusiones por posición."""
    n_digitos = len(candidato) - 3
    digitos = "".join(_A_DIGITO.get(c, c) for c in candidato[:n_digitos])
    letras = "".join(_A_LETRA.get(c, c) for c in candidato[n_digitos:])
    return digitos + letras


def extraer_placa(texto_crudo: str) -> str | None:
    """
    Limpia el texto del OCR y busca una placa válida dentro de él
    (tolera ruido antes/después). Retorna la placa o None.
    """
    limpio = re.sub(r"[^A-Z0-9]", "", (texto_crudo or "").upper())

    for largo in (7, 6):  # primero 4 dígitos + 3 letras, luego 3 + 3
        for i in range(len(limpio) - largo + 1):
            candidato = _corregir_posiciones(limpio[i:i + largo])
            if _PLACA_RE.match(candidato):
                return candidato
    return None


def es_placa_valida(placa: str) -> bool:
    return bool(placa and _PLACA_RE.match(placa))


# ---------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------
def leer_placa(imagen: np.ndarray, carpeta_debug: str | Path | None = None) -> dict:
    """
    Detecta y lee la placa de una imagen BGR (OpenCV).

    Retorna:
        {
            "placa": "1234ABC" | None,     # None si no se logró una placa válida
            "valida": True/False,
            "confianza": 87.5,             # confianza media de Tesseract (0-100)
            "texto_crudo": "1234ABC",      # lo que leyó el OCR (útil para depurar)
            "region": (x, y, w, h) | None  # dónde se encontró la placa
        }

    Si 'carpeta_debug' se indica, guarda los recortes y binarizados.
    """
    imagen = _reducir(imagen)

    # Candidatos: regiones detectadas + imagen completa (por si ya es un recorte)
    alto, ancho = imagen.shape[:2]
    cajas = _buscar_regiones(imagen)
    cajas.append((0, 0, ancho, alto))

    mejor = {"placa": None, "valida": False, "confianza": 0.0,
             "texto_crudo": "", "region": None}

    if carpeta_debug:
        carpeta_debug = Path(carpeta_debug)
        carpeta_debug.mkdir(parents=True, exist_ok=True)

    for idx, caja in enumerate(cajas):
        recorte = _recortar(imagen, caja)
        if recorte.size == 0:
            continue

        for var, binaria in enumerate(_preprocesar(recorte)):
            if carpeta_debug:
                cv2.imencode(".png", recorte)[1].tofile(str(carpeta_debug / f"region{idx}.png"))
                cv2.imencode(".png", binaria)[1].tofile(str(carpeta_debug / f"region{idx}_bin{var}.png"))

            crudo, confianza = _ocr(binaria)
            placa = extraer_placa(crudo)
            valida = placa is not None

            # Prioridad: placa válida > mayor confianza
            mejora = (valida, confianza) > (mejor["valida"], mejor["confianza"])
            if mejora or (not mejor["texto_crudo"] and crudo):
                mejor = {"placa": placa, "valida": valida, "confianza": round(confianza, 1),
                         "texto_crudo": crudo,
                         "region": None if caja == (0, 0, ancho, alto) else caja}

            if valida and confianza >= CONFIANZA_SUFICIENTE:
                return mejor  # suficiente: no seguir probando (ahorra tiempo)

    return mejor


def leer_placa_desde_archivo(ruta: str | Path, carpeta_debug: str | Path | None = None) -> dict:
    """Atajo: carga una imagen desde disco y lee la placa."""
    return leer_placa(cargar_imagen(ruta), carpeta_debug)