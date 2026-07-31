"""Router de casos: análisis, listado, detalle, estadísticas y healthcheck."""

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.api import schemas, services

logger = logging.getLogger(__name__)
router = APIRouter()


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
            cur.execute("SELECT COUNT(*) AS n FROM casos")
            total_casos = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM configuracion_reglas WHERE activo = TRUE")
            reglas = cur.fetchone()["n"]
    except Exception as e:
        return schemas.HealthResponse(status="error", db=str(e), casos=0, reglas_activas=0, grafo="error")
    finally:
        conn.close()

    return schemas.HealthResponse(
        status="ok",
        db="ok",
        casos=total_casos,
        reglas_activas=reglas,
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

    rule_details = resultado.get("rule_details") or []
    conn = services.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT rv.version, cr.nombre, cr.tipo_regla
                   FROM reglas_versiones rv
                   JOIN configuracion_reglas cr ON cr.regla_id = rv.regla_id
                   WHERE rv.version_id = %s""",
                (None,),
            )
            versiones: dict[int, dict[str, Any]] = {}
            # Cargar todas las version_ids de una
            vids = [r["version_id"] for r in rule_details]
            for vid in vids:
                cur.execute(
                    """SELECT rv.version, cr.nombre, cr.tipo_regla
                       FROM reglas_versiones rv
                       JOIN configuracion_reglas cr ON cr.regla_id = rv.regla_id
                       WHERE rv.version_id = %s""",
                    (vid,),
                )
                row = cur.fetchone()
                if row:
                    versiones[vid] = row
    finally:
        conn.close()

    checklist = []
    for r in rule_details:
        vinfo = versiones.get(r["version_id"], {})
        checklist.append(schemas.RuleChecklistItem(
            regla_id=r["regla_id"],
            version=vinfo.get("version", 0),
            nombre=vinfo.get("nombre", r.get("nombre", "")),
            tipo_regla=vinfo.get("tipo_regla", r.get("tipo_regla", "")),
            se_disparo=r["se_disparo"],
            valor_actual=r.get("valor_actual"),
            detalle=r.get("detalle"),
        ))

    return schemas.AnalyzeResponse(
        case_id=req.case_id,
        final_decision=resultado["final_decision"],
        justification=resultado["justification"],
        signals=resultado["signals"],
        llm_usado=resultado.get("llm_analysis") is not None,
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
            cur.execute(f"SELECT COUNT(*) AS n FROM casos c LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id{wsql}", params)
            total = cur.fetchone()["n"]

            cur.execute(
                f"""SELECT c.caso_id, c.usuario_id, c.ciudad, c.vertical,
                           c.valor_orden_mxn, c.compensacion_solicitada_mxn,
                           c.flags_fraude_previos, c.es_sintetico,
                           a.decision AS recomendacion_agente,
                           a.justificacion,
                           (a.llm_resultado IS NOT NULL) AS has_llm
                      FROM casos c LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id{wsql}
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
                """SELECT c.*, a.decision AS recomendacion_agente,
                           a.justificacion, a.senales_usadas,
                           a.llm_resultado, a.fuente
                    FROM casos c LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id
                    WHERE c.caso_id = %s""",
                (case_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, f"Caso {case_id} no encontrado")

            caso = _fila_a_dict(row)
            llm_resultado = caso.pop("llm_resultado", None)

            cur.execute(
                """SELECT cr.regla_id, rv.version, cr.nombre, cr.tipo_regla,
                           rr.se_disparo, rr.valor_actual, rr.detalle
                    FROM resultados_reglas rr
                    JOIN reglas_versiones rv ON rv.version_id = rr.version_id
                    JOIN configuracion_reglas cr ON cr.regla_id = rv.regla_id
                    WHERE rr.caso_id = %s
                    ORDER BY cr.regla_id""",
                (case_id,),
            )
            checklist = [
                schemas.RuleChecklistItem(
                    regla_id=r["regla_id"],
                    version=r["version"],
                    nombre=r["nombre"],
                    tipo_regla=r["tipo_regla"],
                    se_disparo=r["se_disparo"],
                    valor_actual=r["valor_actual"],
                    detalle=r["detalle"],
                )
                for r in cur.fetchall()
            ]
    finally:
        conn.close()

    return schemas.CaseDetail(
        caso=caso,
        checklist=checklist,
        llm_resultado=llm_resultado,
    )


# ── Estadísticas ──────────────────────────────────────────────────────


@router.get("/stats", response_model=schemas.StatsResponse)
def stats():
    """KPIs agregados de todos los casos."""
    conn = services.conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM casos")
            total = cur.fetchone()["n"]

            cur.execute(
                """SELECT COALESCE(a.decision, 'PENDIENTE') AS decision, COUNT(*) AS n
                   FROM casos c LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id
                   GROUP BY a.decision ORDER BY n DESC"""
            )
            distribucion = {r["decision"]: r["n"] for r in cur.fetchall()}

            cur.execute(
                """SELECT c.es_sintetico, a.decision, COUNT(*) AS n
                   FROM casos c LEFT JOIN analisis_casos a ON a.caso_id = c.caso_id
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

            cur.execute("SELECT COUNT(*) AS n FROM configuracion_reglas WHERE activo = TRUE")
            reglas = cur.fetchone()["n"]
    finally:
        conn.close()

    return schemas.StatsResponse(
        total_casos=total,
        distribucion=distribucion,
        por_origen=por_origen,
        reglas_activas=reglas,
    )
