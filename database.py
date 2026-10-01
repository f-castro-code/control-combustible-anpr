"""
database.py
Conexión a MySQL (con pool) y funciones que invocan los procedimientos
almacenados del sistema:
    - sp_consultar_placa       -> consulta SIN descontar
    - sp_validar_y_despachar   -> valida y descuenta el cupo (transaccional)
"""

import logging
from contextlib import contextmanager
from decimal import Decimal

import mysql.connector
from mysql.connector import pooling, Error

from config import DB_CONFIG, DB_POOL_SIZE, SURTIDOR_ID_DEFECTO

logger = logging.getLogger(__name__)

_pool: pooling.MySQLConnectionPool | None = None


# ---------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------
def _get_pool() -> pooling.MySQLConnectionPool:
    """Crea el pool la primera vez que se necesita (lazy)."""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="anpr_pool",
            pool_size=DB_POOL_SIZE,
            pool_reset_session=True,
            **DB_CONFIG,
        )
    return _pool


@contextmanager
def get_connection():
    """Entrega una conexión del pool y la devuelve al terminar."""
    conn = _get_pool().get_connection()
    try:
        yield conn
    finally:
        conn.close()  # en un pool, close() devuelve la conexión, no la cierra


def probar_conexion() -> bool:
    """Verifica que la BD responde. Útil al iniciar la aplicación."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
        return True
    except Error as e:
        logger.error("No se pudo conectar a MySQL: %s", e)
        return False


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def normalizar_placa(placa: str) -> str:
    """Mayúsculas, sin espacios ni guiones (ej: '1234-abc ' -> '1234ABC')."""
    return "".join(ch for ch in (placa or "").upper() if ch.isalnum())


def _a_float(valor):
    """Convierte Decimal a float para que sea serializable en JSON."""
    return float(valor) if isinstance(valor, Decimal) else valor


# ---------------------------------------------------------------------
# Consulta (NO descuenta cupo)  ->  endpoint /validar
# ---------------------------------------------------------------------
def consultar_placa(placa: str) -> dict | None:
    """
    Consulta los datos y el cupo de un vehículo sin modificar nada.
    Retorna un diccionario, o None si la placa no está registrada.
    """
    placa = normalizar_placa(placa)

    with get_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute("CALL sp_consultar_placa(%s)", (placa,))
            filas = cur.fetchall()
            # Consumir resultados restantes del CALL para poder cerrar el cursor
            while cur.nextset():
                pass
        finally:
            cur.close()

    if not filas:
        return None

    fila = {k: _a_float(v) for k, v in filas[0].items()}
    fila["puede_despachar"] = bool(fila["puede_despachar"])
    return fila


# ---------------------------------------------------------------------
# Validar y despachar (descuenta cupo)  ->  endpoint /despachar
# ---------------------------------------------------------------------
def validar_y_despachar(
    placa: str,
    litros: float,
    surtidor_id: int = SURTIDOR_ID_DEFECTO,
) -> dict:
    """
    Ejecuta sp_validar_y_despachar. Siempre registra la transacción
    (APROBADO o RECHAZADO) en la tabla 'despachos'.

    Retorna:
        {
            "placa": "1234ABC",
            "autorizado": True/False,
            "motivo": None | "Cupo diario agotado" | ...,
            "cupo_restante": 20.0 | None
        }
    """
    placa = normalizar_placa(placa)
    litros_dec = Decimal(str(litros))

    try:
        with get_connection() as conn:
            cur = conn.cursor()
            try:
                # Los 3 últimos valores son los parámetros OUT (se inicializan en 0/'')
                resultado = cur.callproc(
                    "sp_validar_y_despachar",
                    [placa, litros_dec, surtidor_id, 0, "", 0],
                )
            finally:
                cur.close()

        autorizado, motivo, cupo_restante = resultado[3], resultado[4], resultado[5]

        return {
            "placa": placa,
            "autorizado": bool(autorizado),
            "motivo": motivo if motivo else None,
            "cupo_restante": _a_float(cupo_restante),
        }

    except Error as e:
        logger.error("Error en sp_validar_y_despachar (%s): %s", placa, e)
        return {
            "placa": placa,
            "autorizado": False,
            "motivo": "Error de base de datos",
            "cupo_restante": None,
        }


# ---------------------------------------------------------------------
# Registro de lecturas del OCR (para medir la precisión del ANPR)
# ---------------------------------------------------------------------
def registrar_lectura(
    placa_leida: str,
    confianza: float | None = None,
    imagen_ruta: str | None = None,
) -> int | None:
    """Guarda una lectura del OCR en 'lecturas_anpr'. Retorna el id insertado."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO lecturas_anpr (placa_leida, confianza, imagen_ruta) "
                    "VALUES (%s, %s, %s)",
                    (placa_leida, confianza, imagen_ruta),
                )
                conn.commit()
                return cur.lastrowid
            finally:
                cur.close()
    except Error as e:
        logger.error("No se pudo registrar la lectura ANPR: %s", e)
        return None


# ---------------------------------------------------------------------
# Prueba rápida:  python database.py
# ---------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("Conexión MySQL:", "OK" if probar_conexion() else "FALLÓ")

    print("\n-- Consulta 1234ABC --")
    print(consultar_placa("1234ABC"))

    print("\n-- Consulta placa inexistente --")
    print(consultar_placa("0000XXX"))

    print("\n-- Despacho 10 L a 1234ABC --")
    print(validar_y_despachar("1234ABC", 10))

    print("\n-- Despacho a vehículo con cupo agotado (9012GHI) --")
    print(validar_y_despachar("9012GHI", 10))

    print("\n-- Despacho a placa no registrada --")
    print(validar_y_despachar("0000XXX", 10))