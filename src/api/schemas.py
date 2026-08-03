"""Modelos Pydantic v2 de la API (requests y responses)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Casos ─────────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """Request para analizar un caso individual."""

    case_id: str = Field(..., examples=["COMP-0009"])


class RuleChecklistItem(BaseModel):
    """Una fila del checklist de reglas de un caso (vacío: reglas desde YAML)."""

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
    """Request para procesar casos en lote (background).

    Args:
        case_ids: Selección manual de casos (ej. ``["COMP-0009", "COMP-0078"]``).
            Si se provee, ignora el resto de filtros.
        aleatorio: Muestreo aleatorio de ``limite`` casos.
        persistir: ``True`` escribe en ``resolution_case``; ``False`` corre el
            pipeline en memoria (demo) sin tocar la base de datos.
    """

    es_sintetico: bool | None = None
    solo_pendientes: bool = False
    limite: int | None = Field(default=None, ge=1, le=1000)
    case_ids: list[str] | None = None
    aleatorio: bool = False
    persistir: bool = True


class BatchResponse(BaseModel):
    """Respuesta al lanzar un batch."""

    job_id: str
    total_casos: int
    mensaje: str


class JobStatus(BaseModel):
    """Estado de un job batch."""

    job_id: str
    status: Literal["queued", "running", "done", "error"]
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
    antiguedad_usuario_dias: float | None = None
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
    reglas_yaml: int


class HealthResponse(BaseModel):
    """Estado de salud del servicio."""

    status: str
    db: str
    casos: int
    reglas_yaml: int
    grafo: str
