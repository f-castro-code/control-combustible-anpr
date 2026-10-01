"""
schemas.py
Modelos Pydantic que definen la estructura de las peticiones y respuestas JSON.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Lo que la pantalla del playero debe mostrar
Resultado = Literal["VERDE", "ROJO"]


class VehiculoInfo(BaseModel):
    """Datos del vehículo encontrado en la base de datos."""
    placa: str
    propietario: str
    tipo_combustible: str
    capacidad_tanque_litros: float
    cupo_diario_litros: float
    cupo_disponible_litros: float
    estado: Literal["HABILITADO", "INHABILITADO", "CUPO_AGOTADO"]


# ---------------------------------------------------------------------
# POST /validar
# ---------------------------------------------------------------------
class ValidarResponse(BaseModel):
    resultado: Resultado = Field(..., description="VERDE = puede cargar | ROJO = bloqueado")
    motivo: str | None = Field(None, description="Razón del bloqueo (solo si es ROJO)")
    placa: str | None = Field(None, description="Placa detectada y validada (None si no hubo lectura)")
    texto_crudo_ocr: str | None = Field(None, description="Texto tal cual lo leyó el OCR")
    confianza_ocr: float | None = Field(None, description="Confianza de Tesseract (0-100)")
    vehiculo: VehiculoInfo | None = None
    tiempo_ms: int = Field(..., description="Tiempo total de procesamiento en milisegundos")


# ---------------------------------------------------------------------
# POST /despachar
# ---------------------------------------------------------------------
class DespacharRequest(BaseModel):
    placa: str = Field(..., min_length=5, max_length=10, examples=["1234ABC"])
    litros: float = Field(..., gt=0, le=999.99, examples=[20.5],
                          description="Litros a despachar (máx. 2 decimales)")
    surtidor_id: int = Field(1, ge=1, description="Número de surtidor")


class DespacharResponse(BaseModel):
    resultado: Resultado
    autorizado: bool
    placa: str
    litros: float
    motivo: str | None = None
    cupo_restante: float | None = None


# ---------------------------------------------------------------------
# POST /login  y  GET /admin/stats
# ---------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, examples=["admin"])
    password: str = Field(..., min_length=1, max_length=100)


class LoginResponse(BaseModel):
    token: str = Field(..., description="Enviar como cabecera  Authorization: Bearer <token>")
    rol: Literal["ADMIN", "PLAYERO"]
    nombre: str
    expira_en_segundos: int


class StatsResponse(BaseModel):
    litros_hoy: float
    despachos_aprobados_hoy: int
    despachos_rechazados_hoy: int
    vehiculos_total: int
    vehiculos_habilitados: int
    vehiculos_cupo_agotado: int


# ---------------------------------------------------------------------
# Dashboard: despachos y vehículos
# ---------------------------------------------------------------------
Combustible = Literal["Gasolina Especial", "Gasolina Especial (+)"]


class DespachoItem(BaseModel):
    id: int
    placa: str
    propietario: str | None = None
    litros: float
    fecha_hora: datetime
    surtidor_id: int
    estado: Literal["APROBADO", "RECHAZADO"]
    motivo: str | None = None


class VehiculoAdmin(BaseModel):
    placa: str
    propietario: str
    ci_propietario: str
    tipo_combustible: Combustible
    capacidad_tanque_litros: float
    cupo_diario_litros: float
    cupo_disponible_litros: float
    estado: Literal["HABILITADO", "INHABILITADO", "CUPO_AGOTADO"]


class VehiculoUpsert(BaseModel):
    placa: str = Field(..., min_length=5, max_length=10, examples=["1234ABC"])
    propietario: str = Field(..., min_length=2, max_length=100)
    ci_propietario: str = Field(..., min_length=3, max_length=20)
    tipo_combustible: Combustible
    capacidad_tanque_litros: float = Field(..., gt=0, le=999.99)
    cupo_diario_litros: float = Field(..., ge=0, le=999.99)
    estado: Literal["HABILITADO", "INHABILITADO"] = "HABILITADO"


class VehiculoGuardado(BaseModel):
    creado: bool = Field(..., description="True = vehículo nuevo | False = actualizado")
    vehiculo: VehiculoAdmin