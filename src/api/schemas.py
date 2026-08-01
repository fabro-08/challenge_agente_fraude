"""Modelos Pydantic v2 de la API (requests y responses)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Casos ─────────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """Request para analizar un caso individual."""

    case_id: str = Field(..., examples=["COMP-0009"])


class RuleChecklistItem(BaseModel):
    """Una fila del checklist de reglas de un caso."""

    regla_id: str
    version: int
    nombre: str
    tipo_regla: str
    se_disparo: bool
    valor_actual: str | None
    detalle: str | None
    descripcion: str | None = None
    condiciones: list[dict[str, Any]] | None = None


class AnalyzeResponse(BaseModel):
    """Resultado del análisis del pipeline."""

    case_id: str
    final_decision: str
    fuente: str
    decision_regla: str | None = None
    decision_llm: str | None = None
    justificacion_regla: str = ""
    justificacion_llm: str | None = None
    senales_regla: list[str] = []
    senales_llm: list[str] = []
    llm_usado: bool
    llm_resultado: dict[str, Any] | None = None
    checklist: list[RuleChecklistItem]


class BatchRequest(BaseModel):
    """Request para procesar casos en lote (background)."""

    es_sintetico: bool | None = None
    solo_pendientes: bool = False
    limite: int | None = Field(default=None, ge=1, le=1000)


class BatchResponse(BaseModel):
    """Respuesta al lanzar un batch."""

    job_id: str
    total_casos: int
    mensaje: str


class JobStatus(BaseModel):
    """Estado de un job batch."""

    job_id: str
    status: Literal["running", "done", "error"]
    total: int
    procesados: int
    errores: int
    decisiones: dict[str, int]
    error_mensaje: str | None = None


class CaseListItem(BaseModel):
    """Fila de la lista de casos."""

    caso_id: str
    usuario_id: str
    ciudad: str | None
    vertical: str | None
    restaurante: str | None = None
    valor_orden_mxn: float | None
    compensacion_solicitada_mxn: float | None
    flags_fraude_previos: int | None
    recomendacion_agente: str | None
    fuente: str | None = None
    es_sintetico: bool
    decision_regla: str | None = None
    decision_llm: str | None = None
    justificacion_llm: str | None = None
    has_llm: bool | None = None


class CaseListResponse(BaseModel):
    """Lista paginada de casos."""

    total: int
    limit: int
    offset: int
    casos: list[CaseListItem]


class CaseDetail(BaseModel):
    """Detalle completo de un caso con su checklist de reglas."""

    caso: dict[str, Any]
    checklist: list[RuleChecklistItem]
    llm_resultado: dict[str, Any] | None = None


class StatsResponse(BaseModel):
    """KPIs agregados."""

    total_casos: int
    distribucion: dict[str, int]
    por_origen: list[dict[str, Any]]
    reglas_activas: int


class HealthResponse(BaseModel):
    """Estado de salud del servicio."""

    status: str
    db: str
    casos: int
    reglas_activas: int
    grafo: str


# ── Reglas ────────────────────────────────────────────────────────────

Operador = Literal[">", ">=", "<", "<=", "==", "!=", "in", "not_in", "contains_any", "contains_all"]
TipoRegla = Literal["RECHAZAR", "APROBAR", "ESCALAR_FORZOSO"]


class Condicion(BaseModel):
    """Una condición de una regla."""

    campo: str
    operador: Operador
    valor: Any


class RuleConfig(BaseModel):
    """Definición declarativa de una regla."""

    descripcion: str = ""
    match: Literal["all", "any"] = "all"
    condiciones: list[Condicion] = Field(..., min_length=1)


class RuleOut(BaseModel):
    """Regla con su configuración activa."""

    regla_id: str
    nombre: str
    tipo_regla: str
    prioridad: int
    activo: bool
    version_actual: int
    config: dict[str, Any]
    updated_at: datetime


class RuleCreateRequest(BaseModel):
    """Request para crear una regla nueva."""

    regla_id: str = Field(..., pattern=r"^[A-Z0-9-]{2,50}$")
    nombre: str
    tipo_regla: TipoRegla
    prioridad: int = 0
    config: RuleConfig
    updated_by: str
    cambio_descripcion: str = "Creación de la regla"


class RuleUpdateRequest(BaseModel):
    """Request para actualizar una regla (crea nueva versión)."""

    config: RuleConfig
    updated_by: str
    cambio_descripcion: str = Field(..., min_length=5)
    nombre: str | None = None
    prioridad: int | None = None
    activo: bool | None = None


class RuleDeleteRequest(BaseModel):
    """Request para desactivar una regla (auditable)."""

    updated_by: str
    cambio_descripcion: str = "Desactivación de la regla"


class RuleVersionOut(BaseModel):
    """Una versión histórica de una regla."""

    version_id: int
    version: int
    config: dict[str, Any]
    cambio_descripcion: str | None
    updated_by: str | None
    updated_at: datetime


class CamposResponse(BaseModel):
    """Campos disponibles para construir condiciones."""

    campos: list[str]
    operadores: list[str]


class SimulateRequest(BaseModel):
    """Request de simulación de impacto (efímera)."""

    accion: Literal["update", "create", "delete"]
    regla_id: str
    config: RuleConfig | None = None
    nombre: str | None = None
    tipo_regla: TipoRegla | None = None
    prioridad: int = 0
    filtros: dict[str, Any] | None = None


class SimulateResponse(BaseModel):
    """Resultado de la simulación (sin persistir)."""

    casos_evaluados: int
    cambian_decision: int
    transiciones: dict[str, int]
    casos_afectados: list[dict[str, Any]]
    nota: str


# ── Usuarios ──────────────────────────────────────────────────────────


class UserOut(BaseModel):
    """Analista de fraude."""

    usuario_id: int
    nombre: str
    email: str | None
