"""Repositorio de reglas: acceso a configuración, versiones y resultados en DB.

Centraliza todo el SQL relacionado con el motor de reglas genérico:
- ``cargar_reglas_activas()`` → definiciones para el ``GenericRuleEngine``
- ``persistir_resultados()`` → checklist por caso (``resultados_reglas``)
- ``crear_regla()`` / ``actualizar_regla()`` → versionado (cada cambio = nueva versión)

La conexión se abre y cierra por operación (el pipeline y la API son efímeros).
"""

import os

import psycopg2
from psycopg2.extras import Json

from src.rules.generic_engine import RuleDefinition

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "dbname": os.environ.get("DB_NAME", "rappi_cases"),
    "user": os.environ.get("DB_USER", "rappi"),
    "password": os.environ.get("DB_PASSWORD", "rappi_pass"),
}


def _conectar() -> psycopg2.extensions.connection:
    return psycopg2.connect(**DB_CONFIG)


def cargar_reglas_activas(incluir_inactivas: bool = False) -> list[RuleDefinition]:
    """Carga las reglas activas con su versión actual desde la DB.

    Args:
        incluir_inactivas: Si True, devuelve también las desactivadas.

    Returns:
        Lista de RuleDefinition listas para el GenericRuleEngine.
        Lista vacía si la tabla no tiene reglas (el llamador decide el fallback).
    """
    sql = """
        SELECT c.regla_id, v.version_id, c.nombre, c.tipo_regla, c.prioridad, v.config
        FROM configuracion_reglas c
        JOIN reglas_versiones v
          ON v.regla_id = c.regla_id AND v.version = c.version_actual
    """
    if not incluir_inactivas:
        sql += " WHERE c.activo = TRUE"
    sql += " ORDER BY c.tipo_regla, c.prioridad"

    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        RuleDefinition(
            regla_id=r[0],
            version_id=r[1],
            nombre=r[2],
            tipo_regla=r[3],
            prioridad=r[4],
            config=r[5],
        )
        for r in rows
    ]


def persistir_resultados(caso_id: str, rule_details: list[dict]) -> int:
    """Persiste el checklist de reglas de un caso en ``resultados_reglas``.

    Idempotente por caso: borra resultados previos del mismo caso antes de
    insertar (re-análisis reemplaza el checklist anterior).

    Args:
        caso_id: Identificador del caso.
        rule_details: Lista de dicts con ``version_id``, ``se_disparo``,
            ``valor_actual`` y ``detalle`` (un dict por regla evaluada).

    Returns:
        Número de filas insertadas.
    """
    if not rule_details:
        return 0
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM resultados_reglas WHERE caso_id = %s", (caso_id,))
            cur.executemany(
                """
                INSERT INTO resultados_reglas
                    (caso_id, version_id, se_disparo, valor_actual, detalle)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        caso_id,
                        r["version_id"],
                        r["se_disparo"],
                        r.get("valor_actual", ""),
                        r.get("detalle", ""),
                    )
                    for r in rule_details
                ],
            )
            n = cur.rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def crear_regla(
    regla_id: str,
    nombre: str,
    tipo_regla: str,
    config: dict,
    prioridad: int = 0,
    updated_by: str | None = None,
    cambio_descripcion: str | None = None,
) -> int:
    """Crea una regla nueva con su versión 1.

    Returns:
        version_id de la versión creada.
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO configuracion_reglas
                    (regla_id, nombre, tipo_regla, prioridad, version_actual)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (regla_id, nombre, tipo_regla, prioridad),
            )
            cur.execute(
                """
                INSERT INTO reglas_versiones
                    (regla_id, version, config, cambio_descripcion, updated_by)
                VALUES (%s, 1, %s, %s, %s)
                RETURNING version_id
                """,
                (regla_id, Json(config), cambio_descripcion or "Creación de la regla", updated_by),
            )
            version_id = cur.fetchone()[0]
        conn.commit()
        return version_id
    finally:
        conn.close()


def actualizar_regla(
    regla_id: str,
    config: dict,
    updated_by: str,
    cambio_descripcion: str,
    nombre: str | None = None,
    prioridad: int | None = None,
    activo: bool | None = None,
) -> int:
    """Actualiza una regla creando una NUEVA versión (nunca edita la anterior).

    Args:
        regla_id: Regla a actualizar.
        config: Nueva definición JSONB.
        updated_by: Analista de fraude que hace el cambio (obligatorio, auditoría).
        cambio_descripcion: Motivo del cambio (obligatorio, auditoría).
        nombre/prioridad/activo: Campos opcionales a actualizar en el puntero.

    Returns:
        version_id de la nueva versión.
    """
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version_actual FROM configuracion_reglas WHERE regla_id = %s FOR UPDATE",
                (regla_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Regla '{regla_id}' no existe")
            nueva_version = row[0] + 1

            cur.execute(
                """
                INSERT INTO reglas_versiones
                    (regla_id, version, config, cambio_descripcion, updated_by)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING version_id
                """,
                (regla_id, nueva_version, Json(config), cambio_descripcion, updated_by),
            )
            version_id = cur.fetchone()[0]

            sets = ["version_actual = %s", "updated_at = NOW()"]
            params: list = [nueva_version]
            if nombre is not None:
                sets.append("nombre = %s")
                params.append(nombre)
            if prioridad is not None:
                sets.append("prioridad = %s")
                params.append(prioridad)
            if activo is not None:
                sets.append("activo = %s")
                params.append(activo)
            params.append(regla_id)
            cur.execute(
                f"UPDATE configuracion_reglas SET {', '.join(sets)} WHERE regla_id = %s",
                params,
            )
        conn.commit()
        return version_id
    finally:
        conn.close()


def obtener_versiones(regla_id: str) -> list[dict]:
    """Devuelve el historial de versiones de una regla (más reciente primero)."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT version_id, version, config, cambio_descripcion, updated_by, updated_at
                FROM reglas_versiones
                WHERE regla_id = %s
                ORDER BY version DESC
                """,
                (regla_id,),
            )
            cols = ["version_id", "version", "config", "cambio_descripcion", "updated_by", "updated_at"]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()


def tablas_reglas_vacias() -> bool:
    """True si no hay ninguna regla configurada (permite fallback a YAML)."""
    conn = _conectar()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM configuracion_reglas")
            return cur.fetchone()[0] == 0
    finally:
        conn.close()


def insertar_seed(reglas: list[tuple[str, str, str, int, dict]], updated_by: str) -> int:
    """Inserta el seed inicial de reglas (v1) si la tabla está vacía.

    Args:
        reglas: Iterable de (regla_id, nombre, tipo_regla, prioridad, config).
        updated_by: Autor del seed (ej. "seed: thresholds.yaml").

    Returns:
        Número de reglas insertadas (0 si ya existían).
    """
    if not tablas_reglas_vacias():
        return 0

    n = 0
    for regla_id, nombre, tipo, prioridad, config in reglas:
        crear_regla(
            regla_id=regla_id,
            nombre=nombre,
            tipo_regla=tipo,
            config=config,
            prioridad=prioridad,
            updated_by=updated_by,
            cambio_descripcion="Seed inicial desde thresholds.yaml",
        )
        n += 1
    return n
