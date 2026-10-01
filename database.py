"""
database.py
Conexión a MySQL (con pool) y funciones que invocan los procedimientos
almacenados del sistema:
    - sp_consultar_placa       -> consulta SIN descontar
    - sp_validar_y_despachar   -> valida y descuenta el cupo (transaccional)
"""

import hashlib
import hmac
import logging
import secrets
from contextlib import contextmanager
from functools import lru_cache
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
# Usuarios y contraseñas (PBKDF2-SHA256, sin dependencias extra)
# ---------------------------------------------------------------------
_ITERACIONES = 600_000


def hash_password(password: str) -> str:
    """Genera 'pbkdf2_sha256$iteraciones$sal$hash'. Nunca se guarda la clave en texto plano."""
    sal = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), sal, _ITERACIONES)
    return f"pbkdf2_sha256${_ITERACIONES}${sal.hex()}${h.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    try:
        _, iteraciones, sal, esperado = almacenado.split("$")
        calculado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                        bytes.fromhex(sal), int(iteraciones))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado.hex(), esperado)


@lru_cache(maxsize=1)
def _hash_falso() -> str:
    return hash_password("clave-inexistente")


def validar_usuario(username: str, password: str) -> dict | None:
    """
    Retorna {"id", "nombre", "username", "rol"} si las credenciales son correctas
    y el usuario está activo; si no, None. Lanza mysql.connector.Error si falla la BD.
    """
    username = (username or "").strip()

    with get_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT id, nombre, username, password_hash, rol "
                "FROM usuarios WHERE username = %s AND activo = 1",
                (username,),
            )
            fila = cur.fetchone()
            cur.fetchall()

            if fila is None:
                verificar_password(password, _hash_falso())  # mismo tiempo de respuesta
                return None
            if not verificar_password(password, fila["password_hash"]):
                return None

            cur.execute("UPDATE usuarios SET ultimo_acceso = NOW() WHERE id = %s", (fila["id"],))
            conn.commit()
        finally:
            cur.close()

    return {"id": fila["id"], "nombre": fila["nombre"],
            "username": fila["username"], "rol": fila["rol"]}


# ---------------------------------------------------------------------
# Métricas del dashboard
# ---------------------------------------------------------------------
def obtener_stats_hoy() -> dict:
    """KPIs del día: litros despachados, aprobados/rechazados y estado del parque."""
    with get_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "SELECT COALESCE(SUM(IF(estado_transaccion = 'APROBADO', litros_despachados, 0)), 0) AS litros, "
                "       COALESCE(SUM(estado_transaccion = 'APROBADO'), 0)  AS aprobados, "
                "       COALESCE(SUM(estado_transaccion = 'RECHAZADO'), 0) AS rechazados "
                "FROM despachos WHERE fecha_hora >= CURDATE()"
            )
            d = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "       COALESCE(SUM(estado = 'HABILITADO'), 0)   AS habilitados, "
                "       COALESCE(SUM(estado = 'CUPO_AGOTADO'), 0) AS agotados "
                "FROM vehiculos"
            )
            v = cur.fetchone()
        finally:
            cur.close()

    return {
        "litros_hoy": float(d["litros"]),
        "despachos_aprobados_hoy": int(d["aprobados"]),
        "despachos_rechazados_hoy": int(d["rechazados"]),
        "vehiculos_total": int(v["total"]),
        "vehiculos_habilitados": int(v["habilitados"]),
        "vehiculos_cupo_agotado": int(v["agotados"]),
    }


# ---------------------------------------------------------------------
# Dashboard: historial y gestión de vehículos
# ---------------------------------------------------------------------
_COLS_VEHICULO = ("placa, propietario, ci_propietario, tipo_combustible, capacidad_tanque_litros, "
                  "cupo_diario_litros, cupo_disponible_litros, estado")


def _limpiar(fila: dict) -> dict:
    return {k: _a_float(v) for k, v in fila.items()}


def listar_despachos(desde=None, hasta=None, placa=None, surtidor_id=None,
                     estado=None, limite: int = 200) -> list[dict]:
    """Historial filtrado (más recientes primero). 'hasta' incluye todo ese día."""
    where, params = [], []
    if desde:
        where.append("d.fecha_hora >= %s"); params.append(desde)
    if hasta:
        where.append("d.fecha_hora < %s + INTERVAL 1 DAY"); params.append(hasta)
    if placa:
        where.append("d.placa LIKE %s"); params.append(f"%{normalizar_placa(placa)}%")
    if surtidor_id:
        where.append("d.surtidor_id = %s"); params.append(surtidor_id)
    if estado:
        where.append("d.estado_transaccion = %s"); params.append(estado)

    sql = ("SELECT d.id, d.placa, v.propietario, d.litros_despachados AS litros, d.fecha_hora, "
           "d.surtidor_id, d.estado_transaccion AS estado, d.motivo_rechazo AS motivo "
           "FROM despachos d LEFT JOIN vehiculos v ON v.placa = d.placa"
           + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY d.fecha_hora DESC, d.id DESC LIMIT %s")
    params.append(limite)

    with get_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            return [_limpiar(f) for f in cur.fetchall()]
        finally:
            cur.close()


def listar_vehiculos(q: str | None = None, limite: int = 500) -> list[dict]:
    """Lista vehículos; 'q' busca en placa, propietario o CI."""
    sql, params = f"SELECT {_COLS_VEHICULO} FROM vehiculos", []
    if q and q.strip():
        sql += " WHERE placa LIKE %s OR propietario LIKE %s OR ci_propietario LIKE %s"
        params += [f"%{q.strip()}%"] * 3
    sql += " ORDER BY placa LIMIT %s"
    params.append(limite)

    with get_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, params)
            return [_limpiar(f) for f in cur.fetchall()]
        finally:
            cur.close()


def guardar_vehiculo(d: dict) -> tuple[bool, dict]:
    """
    Alta o actualización (upsert por placa). En un alta, el cupo disponible
    arranca igual al cupo diario; en una actualización se conserva (sin superar el nuevo cupo diario).
    Retorna (creado, vehiculo). Lanza mysql.connector.Error si la BD rechaza los datos.
    """
    sql = ("INSERT INTO vehiculos (placa, propietario, ci_propietario, tipo_combustible, "
           "capacidad_tanque_litros, cupo_diario_litros, cupo_disponible_litros, estado) "
           "VALUES (%(placa)s, %(propietario)s, %(ci_propietario)s, %(tipo_combustible)s, "
           "%(capacidad_tanque_litros)s, %(cupo_diario_litros)s, %(cupo_diario_litros)s, %(estado)s) "
           "ON DUPLICATE KEY UPDATE "
           "propietario = VALUES(propietario), "
           "ci_propietario = VALUES(ci_propietario), "
           "tipo_combustible = VALUES(tipo_combustible), "
           "capacidad_tanque_litros = VALUES(capacidad_tanque_litros), "
           "cupo_diario_litros = VALUES(cupo_diario_litros), "
           "cupo_disponible_litros = LEAST(vehiculos.cupo_disponible_litros, VALUES(cupo_diario_litros)), "
           "estado = VALUES(estado)")

    with get_connection() as conn:
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(sql, d)
            creado = cur.rowcount == 1  # 1 = insertado, 2 = actualizado
            cur.execute(f"SELECT {_COLS_VEHICULO} FROM vehiculos WHERE placa = %s", (d["placa"],))
            fila = _limpiar(cur.fetchone())
            conn.commit()
            return creado, fila
        finally:
            cur.close()
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