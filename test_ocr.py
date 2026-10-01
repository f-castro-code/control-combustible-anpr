"""
test_ocr.py
Prueba el motor ANPR con imágenes fijas de la carpeta capturas/.

Uso:
    python test_ocr.py                       # procesa todas las imágenes de capturas/
    python test_ocr.py capturas/foto.jpg     # procesa una imagen concreta
    python test_ocr.py --debug               # además guarda recortes en capturas/debug/

Truco para medir precisión: nombra las fotos con la placa real,
por ejemplo  1234ABC.jpg  o  1234ABC_noche.jpg  y el script calculará el % de aciertos.
"""

import argparse
import re
import time
from pathlib import Path

from config import BASE_DIR, PLACA_REGEX
from ocr_engine import leer_placa_desde_archivo

CARPETA_CAPTURAS = BASE_DIR / "capturas"
EXTENSIONES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def placa_esperada(ruta: Path) -> str | None:
    """Si el nombre del archivo empieza con una placa válida, la usa como valor real."""
    candidato = re.split(r"[_\-\s.]", ruta.stem.upper())[0]
    return candidato if re.match(PLACA_REGEX, candidato) else None


def main():
    parser = argparse.ArgumentParser(description="Prueba del motor ANPR")
    parser.add_argument("imagen", nargs="?", help="Ruta de una imagen (opcional)")
    parser.add_argument("--debug", action="store_true",
                        help="Guarda recortes y binarizados en capturas/debug/")
    args = parser.parse_args()

    if args.imagen:
        imagenes = [Path(args.imagen)]
    else:
        CARPETA_CAPTURAS.mkdir(exist_ok=True)
        imagenes = sorted(p for p in CARPETA_CAPTURAS.iterdir()
                          if p.suffix.lower() in EXTENSIONES)

    if not imagenes:
        print(f"No hay imágenes. Copia fotos de placas en: {CARPETA_CAPTURAS}")
        return

    aciertos = con_esperada = 0

    for ruta in imagenes:
        debug_dir = CARPETA_CAPTURAS / "debug" / ruta.stem if args.debug else None

        inicio = time.perf_counter()
        try:
            r = leer_placa_desde_archivo(ruta, debug_dir)
        except Exception as e:
            print(f"\n[{ruta.name}] ERROR: {e}")
            continue
        segundos = time.perf_counter() - inicio

        print(f"\n[{ruta.name}]")
        print(f"  Placa detectada : {r['placa'] or '--- no se detectó placa válida ---'}")
        print(f"  Texto crudo OCR : {r['texto_crudo']!r}")
        print(f"  Confianza       : {r['confianza']}%")
        print(f"  Región          : {r['region'] or 'imagen completa'}")
        print(f"  Tiempo          : {segundos:.2f} s")

        esperada = placa_esperada(ruta)
        if esperada:
            con_esperada += 1
            ok = r["placa"] == esperada
            aciertos += ok
            print(f"  Esperada        : {esperada}  ->  {'ACIERTO' if ok else 'FALLO'}")

    if con_esperada:
        print(f"\n=== Precisión: {aciertos}/{con_esperada} = {aciertos / con_esperada:.0%} "
              f"(meta del proyecto: >= 90%) ===")


if __name__ == "__main__":
    main()