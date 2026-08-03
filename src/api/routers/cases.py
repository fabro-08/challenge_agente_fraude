"""Router de casos: análisis, listado, detalle, estadísticas y healthcheck."""

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response

from src.api import schemas, services
from src.rules.rule_engine import _cargar_thresholds

logger = logging.getLogger(__name__)
router = APIRouter()


def _contar_reglas_yaml() -> int:
    """Cantidad de reglas definidas en ``thresholds.yaml`` (KPI del dashboard)."""
    try:
        t = _cargar_thresholds()
        return sum(len(v) for k, v in t.items() if isinstance(v, dict))
    except Exception:
        return 0


def _decimal_a_float(v: Any) -> Any:
    """Convierte Decimal y datetime a JSON-serializable."""
    if isinstance(v, Decimal):
        return float(v)
    return v


def _fila_a_dict(fila: dict) -> dict:
    """Convierte una row (RealDictRow) a dict plano con valores serializables."""
    return {k: _decimal_a_float(v) for k, v in fila.items()}


# ── Healthcheck ───────────────────────────────────────────────────────


@router.get("/health", response_model=schemas.HealthResponse)
def health():
    """Verifica que el servicio, la DB y el grafo estén operativos."""
    conn = services.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
            cur.execute("SELECT COUNT(*) AS n FROM cases")
            total_casos = cur.fetchone()["n"]
    except Exception as e:
        return schemas.HealthResponse(status="error", db=str(e), casos=0, reglas_yaml=0, grafo="error")
    finally:
        conn.close()

    return schemas.HealthResponse(
        status="ok",
        db="ok",
        casos=total_casos,
        reglas_yaml=_contar_reglas_yaml(),
        grafo="compilado" if services.get_graph() else "no_inicializado",
    )


# ── Análisis ──────────────────────────────────────────────────────────


@router.post("/analyze", response_model=schemas.AnalyzeResponse)
async def analyze(req: schemas.AnalyzeRequest):
    """Ejecuta el pipeline completo sobre un caso y persiste el resultado."""
    try:
        resultado = await services.analizar_caso(req.case_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(503, str(e)) from e

    checklist = [
        schemas.RuleChecklistItem(**item)
        for item in resultado.get("reglas_checklist") or []
    ]

    decision_regla = resultado.get("decision_regla", "AMBIGUO")
    llm_usado = resultado.get("llm_analysis") is not None
    # ESCALAR forzado por reglas: la decisión es de las reglas aunque el LLM
    # haya generado análisis enriquecido.
    fuente = "reglas" if decision_regla == "ESCALAR" else ("llm" if llm_usado else "reglas")

    return schemas.AnalyzeResponse(
        case_id=req.case_id,
        final_decision=resultado["final_decision"],
        fuente=fuente,
        decision_regla=decision_regla,
        decision_llm=resultado.get("decision_llm"),
        justificacion_regla=resultado.get("justificacion_regla") or "",
        justificacion_llm=resultado.get("justificacion_llm"),
        senales_regla=resultado.get("senales_regla") or [],
        senales_llm=resultado.get("senales_llm") or [],
        llm_usado=llm_usado,
        llm_resultado=resultado.get("llm_resultado"),
        checklist=checklist,
    )


# ── Batch ──────────────────────────────────────────────────────────────


@router.post("/analyze/batch", response_model=schemas.BatchResponse)
def analyze_batch(req: schemas.BatchRequest):
    """Lanza un procesamiento batch en background."""
    job_id, total = services.lanzar_batch(req.model_dump(exclude_none=True))
    return schemas.BatchResponse(
        job_id=job_id,
        total_casos=total,
        mensaje=f"Batch lanzado con {total} casos en background",
    )


@router.get("/jobs/{job_id}", response_model=schemas.JobStatus)
def get_job(job_id: str):
    """Consulta el estado de un job batch."""
    job = services.estado_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} no encontrado")
    return schemas.JobStatus(**job)


@router.get("/jobs/{job_id}/resultados")
def get_job_resultados(job_id: str):
    """Devuelve las filas del job demo (modo memoria, sin persistir).

    Solo tiene contenido cuando el batch se lanzó con ``persistir=False``.
    """
    if services.estado_job(job_id) is None:
        raise HTTPException(404, f"Job {job_id} no encontrado")
    filas = services.filas_job(job_id)
    return {"job_id": job_id, "resultados": filas, "total": len(filas)}


@router.get("/jobs/{job_id}/excel")
def get_job_excel(job_id: str):
    """Descarga el Excel del job demo (modo memoria, sin escribir en DB)."""
    if services.estado_job(job_id) is None:
        raise HTTPException(404, f"Job {job_id} no encontrado")
    filas = services.filas_job(job_id)
    if not filas:
        raise HTTPException(409, "El job no tiene filas (solo aplica a batch demo en memoria)")
    try:
        excel = services.excel_filas_bytes(filas)
    except Exception as e:
        raise HTTPException(500, f"Error al generar el Excel: {e}") from e
    return Response(
        content=excel,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="demo_batch_{job_id}.xlsx"'},
    )


# ── Listado y detalle ─────────────────────────────────────────────────


@router.get("/cases", response_model=schemas.CaseListResponse)
def list_cases(
    recomendacion: str | None = None,
    ciudad: str | None = None,
    vertical: str | None = None,
    es_sintetico: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Lista casos con filtros opcionales y paginación."""
    where = []
    params: list[Any] = []
    if recomendacion:
        where.append("a.decision = %s")
        params.append(recomendacion)
    if ciudad:
        where.append("c.ciudad ILIKE %s")
        params.append(f"%{ciudad}%")
    if vertical:
        where.append("c.vertical = %s")
        params.append(vertical)
    if es_sintetico is not None:
        where.append("c.es_sintetico = %s")
        params.append(es_sintetico)

    wsql = " WHERE " + " AND ".join(where) if where else ""

    conn = services.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM cases c LEFT JOIN resolution_case a ON a.caso_id = c.caso_id{wsql}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""SELECT c.caso_id, c.usuario_id, c.ciudad, c.vertical,
                           c.restaurante,
                           c.valor_orden_mxn, c.compensacion_solicitada_mxn,
                           c.antiguedad_usuario_dias,
                           c.flags_fraude_previos, c.es_sintetico,
                           a.decision AS recomendacion_agente,
                           a.fuente,
                           a.decision_regla, a.decision_llm,
                           a.justificacion_llm,
                           (a.llm_resultado IS NOT NULL) AS has_llm
                      FROM cases c LEFT JOIN resolution_case a ON a.caso_id = c.caso_id{wsql}
                      ORDER BY c.caso_id LIMIT %s OFFSET %s""",
                params + [limit, offset],
            )
            casos = [_fila_a_dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    return schemas.CaseListResponse(total=total, limit=limit, offset=offset, casos=casos)


@router.get("/cases/{case_id}", response_model=schemas.CaseDetail)
def get_case(case_id: str):
    """Devuelve detalle completo de un caso con el checklist de reglas."""
    conn = services.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.*, f.*,
                           a.decision AS recomendacion_agente,
                           a.justificacion_llm, a.justificacion_regla,
                           a.senales_llm, a.senales_regla,
                           a.reglas_checklist, a.llm_resultado, a.fuente,
                           a.decision_regla, a.decision_llm,
                           a.features_version, a.fallback
                    FROM cases c
                    LEFT JOIN features f ON f.caso_id = c.caso_id
                    LEFT JOIN resolution_case a ON a.caso_id = c.caso_id
                    WHERE c.caso_id = %s""",
                (case_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, f"Caso {case_id} no encontrado")

            caso = _fila_a_dict(row)
            llm_resultado = caso.pop("llm_resultado", None)
            checklist = caso.pop("reglas_checklist", None) or []
    finally:
        conn.close()

    return schemas.CaseDetail(
        caso=caso,
        checklist=[schemas.RuleChecklistItem(**item) for item in checklist],
        llm_resultado=llm_resultado,
    )


# ── Estadísticas ──────────────────────────────────────────────────────


@router.get("/stats", response_model=schemas.StatsResponse)
def stats():
    """KPIs agregados de todos los casos."""
    conn = services.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM cases")
            total = cur.fetchone()["n"]

            cur.execute(
                """SELECT COALESCE(a.decision, 'PENDIENTE') AS decision, COUNT(*) AS n
                   FROM cases c LEFT JOIN resolution_case a ON a.caso_id = c.caso_id
                   GROUP BY a.decision ORDER BY n DESC"""
            )
            distribucion = {r["decision"]: r["n"] for r in cur.fetchall()}

            cur.execute(
                """SELECT c.es_sintetico, a.decision, COUNT(*) AS n
                   FROM cases c LEFT JOIN resolution_case a ON a.caso_id = c.caso_id
                   GROUP BY c.es_sintetico, a.decision
                   ORDER BY 1, 3 DESC"""
            )
            por_origen = [
                {
                    "es_sintetico": r["es_sintetico"],
                    "recomendacion": r["decision"],
                    "n": r["n"],
                }
                for r in cur.fetchall()
            ]
    finally:
        conn.close()

    return schemas.StatsResponse(
        total_casos=total,
        distribucion=distribucion,
        por_origen=por_origen,
        reglas_yaml=_contar_reglas_yaml(),
    )
