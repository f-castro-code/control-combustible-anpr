"""
main.py
API FastAPI del sistema de control de combustible ANPR.

Endpoints:
    POST /validar    -> lee la placa (imagen u opcionalmente texto manual) y consulta el cupo
    POST /despachar  -> descuenta litros del cupo y registra la transacción
    GET  /health     -> estado del servicio y de la base de datos

Ejecutar:
    uvicorn main:app --reload
Documentación interactiva:
    http://127.0.0.1:8000/docs
"""

import asyncio
import logging
import secrets
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import database
from config import BASE_DIR, CAMARA_URL
from ocr_engine import es_placa_valida, leer_placa
from schemas import (
    DespacharRequest,
    DespachoItem,
    DespacharResponse,
    LoginRequest,
    LoginResponse,
    StatsResponse,
    ValidarResponse,
    VehiculoAdmin,
    VehiculoGuardado,
    VehiculoInfo,
    VehiculoUpsert,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("anpr.api")

TAMANO_MAX_IMAGEN = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------
# Cámara IP: un hilo lee el video y guarda el último fotograma.
# /stream lo retransmite y /validar lo usa para el OCR (una sola conexión al celular).
# ---------------------------------------------------------------------
class CamaraIP:
    def __init__(self, url: str | None):
        self.url = url
        self._frame = None
        self._lock = threading.Lock()
        self._activa = False

    def iniciar(self):
        if self.url and not self._activa:
            self._activa = True
            threading.Thread(target=self._leer, daemon=True).start()

    def detener(self):
        self._activa = False

    def _leer(self):
        while self._activa:  # si se cae la conexión, reintenta cada 2 s
            cap = cv2.VideoCapture(self.url)
            while self._activa and cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                with self._lock:
                    self._frame = frame
            cap.release()
            with self._lock:
                self._frame = None
            time.sleep(2)

    def ultimo_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()


camara = CamaraIP(CAMARA_URL)


def _frame_sin_senal() -> np.ndarray:
    img = np.zeros((540, 960, 3), np.uint8)
    cv2.putText(img, "Sin senal de camara", (230, 280), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (200, 200, 200), 3, cv2.LINE_AA)
    return img


async def _mjpeg(request: Request):
    while not await request.is_disconnected():
        frame = camara.ultimo_frame()
        if frame is None:
            frame = _frame_sin_senal()
        elif frame.shape[1] > 960:
            frame = cv2.resize(frame, (960, int(frame.shape[0] * 960 / frame.shape[1])))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        await asyncio.sleep(0.07)


# ---------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    if database.probar_conexion():
        logger.info("Conexión a MySQL OK")
    else:
        logger.warning("No hay conexión a MySQL. Revisa el .env y que el servidor esté activo.")
    camara.iniciar()
    yield
    camara.detener()


app = FastAPI(
    title="Control de Combustible ANPR - Jacha Inti S.R.L.",
    description="Validación de placas y cupos de combustible subvencionado.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------
def _decodificar_imagen(contenido: bytes) -> np.ndarray:
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo de imagen está vacío.")
    if len(contenido) > TAMANO_MAX_IMAGEN:
        raise HTTPException(status_code=413, detail="La imagen supera los 10 MB.")
    imagen = cv2.imdecode(np.frombuffer(contenido, np.uint8), cv2.IMREAD_COLOR)
    if imagen is None:
        raise HTTPException(status_code=400, detail="El archivo no es una imagen válida (usa JPG o PNG).")
    return imagen


def _evaluar_vehiculo(vehiculo: dict | None) -> tuple[str, str | None]:
    """Decide VERDE/ROJO según los datos del vehículo."""
    if vehiculo is None:
        return "ROJO", "Placa no registrada"
    if vehiculo["puede_despachar"]:
        return "VERDE", None
    if vehiculo["estado"] == "INHABILITADO":
        return "ROJO", "Vehículo inhabilitado"
    return "ROJO", "Cupo diario agotado"


# ---------------------------------------------------------------------
# Autenticación y roles (sesiones en memoria: se pierden al reiniciar el servidor)
# ---------------------------------------------------------------------
DURACION_SESION = 8 * 3600  # 8 horas
SESIONES: dict[str, dict] = {}
esquema_bearer = HTTPBearer(auto_error=False, description="Token obtenido en POST /login")


def usuario_actual(cred: HTTPAuthorizationCredentials | None = Depends(esquema_bearer)) -> dict:
    sesion = SESIONES.get(cred.credentials) if cred else None
    if sesion is None or sesion["expira"] < time.time():
        if cred:
            SESIONES.pop(cred.credentials, None)
        raise HTTPException(status_code=401, detail="Sesión no válida o expirada. Inicia sesión.",
                            headers={"WWW-Authenticate": "Bearer"})
    return sesion


def requiere_rol(*roles: str):
    def dependencia(sesion: dict = Depends(usuario_actual)) -> dict:
        if sesion["rol"] not in roles:
            raise HTTPException(status_code=403, detail="No tienes permiso para esta sección.")
        return sesion
    return dependencia


@app.post("/login", response_model=LoginResponse, summary="Iniciar sesión")
def login(datos: LoginRequest):
    """Valida usuario y contraseña y devuelve un token y el rol (ADMIN o PLAYERO)."""
    try:
        usuario = database.validar_usuario(datos.username, datos.password)
    except Exception as e:
        logger.error("Error en login: %s", e)
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")

    if usuario is None:
        logger.warning("Login fallido para '%s'", datos.username)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    token = secrets.token_urlsafe(32)
    SESIONES[token] = {**usuario, "expira": time.time() + DURACION_SESION}
    return LoginResponse(token=token, rol=usuario["rol"], nombre=usuario["nombre"],
                         expira_en_segundos=DURACION_SESION)


@app.get("/admin/stats", response_model=StatsResponse, summary="Métricas del dashboard (solo ADMIN)")
def admin_stats(_: dict = Depends(requiere_rol("ADMIN"))):
    try:
        return StatsResponse(**database.obtener_stats_hoy())
    except Exception as e:
        logger.error("Error obteniendo métricas: %s", e)
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")


@app.get("/admin/despachos", response_model=list[DespachoItem], summary="Historial de despachos (solo ADMIN)")
def admin_despachos(
    desde: date | None = None,
    hasta: date | None = None,
    placa: str | None = None,
    surtidor_id: int | None = Query(None, ge=1),
    estado: Literal["APROBADO", "RECHAZADO"] | None = None,
    limite: int = Query(200, ge=1, le=1000),
    _: dict = Depends(requiere_rol("ADMIN")),
):
    try:
        return database.listar_despachos(desde, hasta, placa, surtidor_id, estado, limite)
    except Exception as e:
        logger.error("Error listando despachos: %s", e)
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")


@app.get("/admin/vehiculos", response_model=list[VehiculoAdmin], summary="Listar vehículos (solo ADMIN)")
def admin_listar_vehiculos(q: str | None = None, _: dict = Depends(requiere_rol("ADMIN"))):
    try:
        return database.listar_vehiculos(q)
    except Exception as e:
        logger.error("Error listando vehículos: %s", e)
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")


@app.post("/admin/vehiculos", response_model=VehiculoGuardado, summary="Registrar o actualizar un vehículo (solo ADMIN)")
def admin_guardar_vehiculo(datos: VehiculoUpsert, sesion: dict = Depends(requiere_rol("ADMIN"))):
    """Si la placa no existe se crea; si existe se actualizan sus datos y su estado (HABILITADO/INHABILITADO)."""
    placa = database.normalizar_placa(datos.placa)
    if not es_placa_valida(placa):
        raise HTTPException(status_code=422, detail="Placa inválida. Formato esperado: 1234ABC.")
    try:
        creado, fila = database.guardar_vehiculo({**datos.model_dump(), "placa": placa})
    except Exception as e:
        if getattr(e, "errno", None) == 3819:  # violación de CHECK
            raise HTTPException(status_code=422, detail="Los datos no cumplen las reglas del sistema.")
        logger.error("Error guardando vehículo %s: %s", placa, e)
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")
    logger.info("Vehículo %s %s por '%s'", placa, "creado" if creado else "actualizado", sesion["username"])
    return VehiculoGuardado(creado=creado, vehiculo=fila)


# ---------------------------------------------------------------------
# POST /validar
# ---------------------------------------------------------------------
@app.post("/validar", response_model=ValidarResponse, summary="Leer placa y validar cupo")
def validar(
    imagen: UploadFile | None = File(None, description="Foto o fotograma con la placa (JPG/PNG)"),
    placa_manual: str | None = Form(None, description="Solo para pruebas: placa escrita a mano (omite el OCR)"),
    _: dict = Depends(requiere_rol("PLAYERO", "ADMIN")),
):
    """
    Lee la placa de la imagen con el motor OCR y consulta en MySQL si el vehículo
    está HABILITADO y tiene cupo. **No descuenta litros** (eso lo hace `/despachar`).

    Envía **una** de las dos opciones: `imagen` o `placa_manual`.
    """
    inicio = time.perf_counter()

    usar_manual = bool(placa_manual and placa_manual.strip())
    frame = None
    if imagen is not None:
        frame = _decodificar_imagen(imagen.file.read())
    elif not usar_manual:
        # Sin parámetros: usa el último fotograma de la cámara IP
        frame = camara.ultimo_frame()
        if frame is None:
            raise HTTPException(status_code=503, detail="La cámara no tiene señal. Revisa CAMARA_URL en el .env.")

    placa: str | None
    texto_crudo: str | None = None
    confianza: float | None = None

    if frame is not None:
        # 1) OCR
        try:
            lectura = leer_placa(frame)
        except RuntimeError as e:  # Tesseract no instalado / mal configurado
            logger.error("Error de OCR: %s", e)
            raise HTTPException(status_code=500, detail=str(e))

        placa = lectura["placa"]
        texto_crudo = lectura["texto_crudo"]
        confianza = lectura["confianza"]

        # Guarda la lectura para medir la precisión del ANPR
        database.registrar_lectura((placa or texto_crudo or "SIN_TEXTO")[:20], confianza)
    else:
        # Modo prueba: sin OCR
        candidata = database.normalizar_placa(placa_manual)
        placa = candidata if es_placa_valida(candidata) else None
        texto_crudo = candidata

    # 2) Sin placa legible -> ROJO
    if placa is None:
        return ValidarResponse(
            resultado="ROJO",
            motivo="No se pudo leer una placa válida. Intente nuevamente.",
            texto_crudo_ocr=texto_crudo,
            confianza_ocr=confianza,
            tiempo_ms=int((time.perf_counter() - inicio) * 1000),
        )

    # 3) Consulta en la base de datos
    try:
        vehiculo = database.consultar_placa(placa)
    except Exception as e:
        logger.error("Error consultando la placa %s: %s", placa, e)
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")

    resultado, motivo = _evaluar_vehiculo(vehiculo)

    return ValidarResponse(
        resultado=resultado,
        motivo=motivo,
        placa=placa,
        texto_crudo_ocr=texto_crudo,
        confianza_ocr=confianza,
        vehiculo=VehiculoInfo.model_validate(vehiculo) if vehiculo else None,
        tiempo_ms=int((time.perf_counter() - inicio) * 1000),
    )


# ---------------------------------------------------------------------
# POST /despachar
# ---------------------------------------------------------------------
@app.post("/despachar", response_model=DespacharResponse, summary="Descontar cupo y registrar despacho")
def despachar(datos: DespacharRequest, _: dict = Depends(requiere_rol("PLAYERO", "ADMIN"))):
    """
    Ejecuta el procedimiento `sp_validar_y_despachar`: verifica de nuevo el estado y
    el cupo, descuenta los litros y registra la transacción (APROBADO o RECHAZADO).

    Un rechazo por cupo o estado **no es un error HTTP**: responde 200 con `resultado: "ROJO"`.
    """
    litros = round(datos.litros, 2)
    if litros <= 0:
        raise HTTPException(status_code=422, detail="Los litros deben ser mayores a 0.")

    r = database.validar_y_despachar(datos.placa, litros, datos.surtidor_id)

    if r["motivo"] == "Error de base de datos":
        raise HTTPException(status_code=503, detail="Base de datos no disponible.")

    return DespacharResponse(
        resultado="VERDE" if r["autorizado"] else "ROJO",
        autorizado=r["autorizado"],
        placa=r["placa"],
        litros=litros,
        motivo=r["motivo"],
        cupo_restante=r["cupo_restante"],
    )


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
@app.get("/health", summary="Estado del servicio")
def health():
    return {"api": "ok",
            "base_de_datos": "ok" if database.probar_conexion() else "sin conexión",
            "camara": "ok" if camara.ultimo_frame() is not None else "sin señal"}


@app.get("/stream", summary="Video en vivo de la cámara (MJPEG)")
async def stream(request: Request, token: str | None = None):
    """Retransmite la cámara IP. Un <img> no puede enviar cabeceras, por eso el token va en ?token=..."""
    sesion = SESIONES.get(token or "")
    if sesion is None or sesion["expira"] < time.time():
        raise HTTPException(status_code=401, detail="Sesión no válida. Inicia sesión.")
    return StreamingResponse(_mjpeg(request), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/", include_in_schema=False)
def raiz():
    # Pantalla del playero
    index = BASE_DIR / "static" / "index.html"
    return FileResponse(index) if index.exists() else RedirectResponse("/docs")


# Sirve la interfaz del playero (Fase 4) si la carpeta static/ existe
if (BASE_DIR / "static").is_dir():
    app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")