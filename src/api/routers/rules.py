"""Router de reglas: CRUD versionado, simulación de impacto y campos disponibles."""

import logging

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, HTTPException

from src.api import schemas
from src.rules import repository
from src.rules.generic_engine import OPERADORES_VALIDOS, RuleDefinition
from src.rules.simulator import simular_cambio

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/rules")


def _db():
    """Conexión con RealDictCursor para queries de reglas."""
    return psycopg2.connect(cursor_factory=psycopg2.extras.RealDictCursor, **repository.DB_CONFIG)


# Cache simple de columnas de la tabla casos
_campos_cache: list[str] | None = None
_campos_cache_ttl: float = 0.0


def _obtener_campos() -> list[str]:
    """Devuelve las columnas disponibles para reglas (``cases`` ∪ ``features``)."""
    import time
    global _campos_cache, _campos_cache_ttl
    if _campos_cache is not None and time.time() - _campos_cache_ttl < 120:
        return _campos_cache

    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name IN ('cases', 'features')
                     AND table_schema = 'public'
                     AND column_name NOT IN ('caso_id', 'created_at', 'updated_at',
                                             'version', 'es_sintetico',
                                             'recomendacion_agente')
                   ORDER BY column_name"""
            )
            campos = sorted({r["column_name"] for r in cur.fetchall()})
    finally:
        conn.close()

    _campos_cache = campos
    _campos_cache_ttl = time.time()
    return campos


def _validar_config(config: dict, campos_disponibles: list[str]) -> None:
    """Valida que una config de regla tenga campos y operadores válidos.

    Raises:
        HTTPException 422 con detalle del error.
    """
    campo_set = set(campos_disponibles)
    for cond in config.get("condiciones", []):
        campo = cond.get("campo", "")
        operador = str(cond.get("operador", ""))
        valor = cond.get("valor")

        if campo not in campo_set:
            raise HTTPException(
                422,
                f"Campo '{campo}' no existe. "
                f"Disponibles: {', '.join(sorted(campo_set))}",
            )
        if operador not in OPERADORES_VALIDOS:
            raise HTTPException(
                422,
                f"Operador '{operador}' no válido. Válidos: {', '.join(sorted(OPERADORES_VALIDOS))}",
            )
        if operador in ("contains_any", "contains_all") and not isinstance(valor, list):
            raise HTTPException(
                422,
                f"Operador '{operador}' requiere valor tipo lista, recibió {type(valor).__name__}",
            )


def _row_to_ruleout(row: dict) -> schemas.RuleOut:
    """Convierte una fila de configuracion_reglas + reglas_versiones a RuleOut."""
    cfg = row["config"]
    if isinstance(cfg, dict):
        config_out = cfg
    else:
        config_out = dict(cfg) if hasattr(cfg, "items") else {"_raw": str(cfg)}
    updated = row["updated_at"]
    return schemas.RuleOut(
        regla_id=row["regla_id"],
        nombre=row["nombre"],
        tipo_regla=row["tipo_regla"],
        prioridad=row["prioridad"],
        activo=row["activo"],
        version_actual=row["version_actual"],
        config=config_out,
        updated_at=updated.isoformat() if hasattr(updated, "isoformat") else str(updated),
    )


# ── Listar campos disponibles ─────────────────────────────────────────


@router.get("/campos", response_model=schemas.CamposResponse)
def list_campos():
    """Campos y operadores disponibles para construir condiciones de reglas."""
    return schemas.CamposResponse(
        campos=_obtener_campos(),
        operadores=sorted(OPERADORES_VALIDOS),
    )


# ── Simulación de impacto ─────────────────────────────────────────────


@router.post("/simulate", response_model=schemas.SimulateResponse)
def simulate(req: schemas.SimulateRequest):
    """Simula el impacto de un cambio en las reglas sin persistir nada."""

    def mutador(reglas: list[RuleDefinition]) -> list[RuleDefinition]:
        if req.accion == "delete":
            return [r for r in reglas if r.regla_id != req.regla_id]

        if req.accion == "create":
            if req.config is None:
                raise HTTPException(400, "config requerido para accion=create")
            if not req.nombre or not req.tipo_regla:
                raise HTTPException(400, "nombre y tipo_regla requeridos para accion=create")
            reglas.append(RuleDefinition(
                regla_id=req.regla_id,
                version_id=0,
                nombre=req.nombre,
                tipo_regla=req.tipo_regla,
                prioridad=req.prioridad,
                config=req.config.model_dump(),
            ))
            return reglas

        # update
        encontrada = False
        for r in reglas:
            if r.regla_id == req.regla_id:
                if req.config is None:
                    raise HTTPException(400, "config requerido para accion=update")
                r.config = req.config.model_dump()
                encontrada = True
                break
        if not encontrada:
            raise HTTPException(404, f"Regla '{req.regla_id}' no encontrada en reglas activas")
        return reglas

    try:
        resultado = simular_cambio(mutador, filtros=req.filtros)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error en simulación: {e}") from e

    return schemas.SimulateResponse(**resultado)


# ── CRUD ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[schemas.RuleOut])
def list_rules():
    """Lista todas las reglas con su configuración activa."""
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.regla_id, c.nombre, c.tipo_regla, c.prioridad, c.activo,
                          c.version_actual, v.config, c.updated_at
                   FROM configuracion_reglas c
                   JOIN reglas_versiones v
                     ON v.regla_id = c.regla_id AND v.version = c.version_actual
                   ORDER BY c.tipo_regla, c.prioridad"""
            )
            return [_row_to_ruleout(r) for r in cur.fetchall()]
    finally:
        conn.close()


@router.post("", response_model=schemas.RuleOut, status_code=201)
def create_rule(req: schemas.RuleCreateRequest):
    """Crea una regla nueva con su versión 1."""
    campos = _obtener_campos()
    _validar_config(req.config.model_dump(), campos)

    try:
        repository.crear_regla(
            regla_id=req.regla_id,
            nombre=req.nombre,
            tipo_regla=req.tipo_regla,
            config=req.config.model_dump(),
            prioridad=req.prioridad,
            updated_by=req.updated_by,
            cambio_descripcion=req.cambio_descripcion,
        )
    except psycopg2.errors.UniqueViolation:  # type: ignore[attr-defined]
        raise HTTPException(409, f"Regla '{req.regla_id}' ya existe")

    return get_rule(req.regla_id)


@router.get("/{regla_id}", response_model=schemas.RuleOut)
def get_rule(regla_id: str):
    """Detalle de una regla con su configuración activa."""
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.regla_id, c.nombre, c.tipo_regla, c.prioridad, c.activo,
                          c.version_actual, v.config, c.updated_at
                   FROM configuracion_reglas c
                   JOIN reglas_versiones v
                     ON v.regla_id = c.regla_id AND v.version = c.version_actual
                   WHERE c.regla_id = %s""",
                (regla_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(404, f"Regla '{regla_id}' no encontrada")

    return _row_to_ruleout(row)


@router.put("/{regla_id}", response_model=schemas.RuleOut)
def update_rule(regla_id: str, req: schemas.RuleUpdateRequest):
    """Actualiza una regla creando una nueva versión (auditable)."""
    campos = _obtener_campos()
    _validar_config(req.config.model_dump(), campos)

    try:
        repository.actualizar_regla(
            regla_id=regla_id,
            config=req.config.model_dump(),
            updated_by=req.updated_by,
            cambio_descripcion=req.cambio_descripcion,
            nombre=req.nombre,
            prioridad=req.prioridad,
            activo=req.activo,
        )
    except ValueError as e:
        raise HTTPException(404, str(e)) from e

    return get_rule(regla_id)


@router.delete("/{regla_id}")
def delete_rule(regla_id: str, req: schemas.RuleDeleteRequest):
    """Desactiva una regla (auditable: crea nueva versión documentando quién y por qué)."""
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT config FROM reglas_versiones rv
                   JOIN configuracion_reglas cr ON cr.regla_id = rv.regla_id
                     AND cr.version_actual = rv.version
                   WHERE rv.regla_id = %s""",
                (regla_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, f"Regla '{regla_id}' no encontrada")
            config_actual = row["config"]
    finally:
        conn.close()

    if isinstance(config_actual, dict):
        cfg = config_actual
    else:
        cfg = dict(config_actual) if hasattr(config_actual, "items") else {"_raw": str(config_actual)}

    repository.actualizar_regla(
        regla_id=regla_id,
        config=cfg,
        updated_by=req.updated_by,
        cambio_descripcion=req.cambio_descripcion,
        activo=False,
    )

    return {"mensaje": f"Regla '{regla_id}' desactivada", "regla_id": regla_id}


@router.get("/{regla_id}/versions", response_model=list[schemas.RuleVersionOut])
def get_rule_versions(regla_id: str):
    """Historial de versiones de una regla."""
    versiones = repository.obtener_versiones(regla_id)
    if not versiones:
        raise HTTPException(404, f"Regla '{regla_id}' no encontrada o sin versiones")

    return [
        schemas.RuleVersionOut(
            version_id=v["version_id"],
            version=v["version"],
            config=v["config"],
            cambio_descripcion=v["cambio_descripcion"],
            updated_by=v["updated_by"],
            updated_at=v["updated_at"].isoformat() if hasattr(v["updated_at"], "isoformat") else str(v["updated_at"]),
        )
        for v in versiones
    ]
