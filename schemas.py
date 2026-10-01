"""
schemas.py
Modelos Pydantic que definen la estructura de las peticiones y respuestas JSON.
"""

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