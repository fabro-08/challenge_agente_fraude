#!/usr/bin/env python3
"""Entrypoint CLI del proceso batch durable en PostgreSQL.

Unifica el disparo de los antiguos ``batch_process.py``/``batch_chunk.py`` en
una sola entrada que usa el MISMO worker que la API (``/analyze/batch``):
crea un ``batch_runs`` + ``batch_run_items`` en DB, corre el grafo LangGraph
con retry por caso y persiste en ``resolution_case`` (con ``batch_run_id`` para
auditoría).

Las features se calculan y persisten por el propio pipeline (nodo
``compute_features``), por lo que no se necesita un paso 2 aparte.

Uso:
    python scripts/run_batch.py [--sintetico|--pendientes|--todos] [--limite N]
    python scripts/run_batch.py --demo             # no escribe en resolution_case
    python scripts/run_batch.py --case COMP-0009 COMP-0078
"""

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from src.batch import repository as batch_repo  # reordena tras sys.path
from src.batch.worker import procesar_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--sintetico", action="store_true", help="Solo casos sintéticos")
    modo.add_argument("--pendientes", action="store_true", help="Solo casos sin análisis")
    modo.add_argument("--todos", action="store_true", help="Todos los casos (default)")
    modo.add_argument(
        "--demo",
        action="store_true",
        help="Modo demo: no escribe en resolution_case (Excel en memoria)",
    )
    parser.add_argument("--limite", type=int, default=None, help="Máx. casos a procesar")
    parser.add_argument("--case-ids", nargs="+", help="Selección manual de casos")
    args = parser.parse_args()

    filtros: dict = {"persistir": not args.demo}
    if args.case_ids:
        filtros["case_ids"] = args.case_ids
    elif args.sintetico:
        filtros["es_sintetico"] = True
    elif args.pendientes:
        filtros["solo_pendientes"] = True
    # args.todos / default → sin filtros (todos los casos)
    if args.limite:
        filtros["limite"] = args.limite

    case_ids, tipo = _resolver_casos(filtros)
    if not case_ids:
        print("No hay casos que procesar.")
        return

    run_id = uuid.uuid4().hex[:12]
    run_pk = batch_repo.crear_run(run_id, tipo, filtros, filtros.get("persistir", True), case_ids)
    print(f"[batch] Run {run_id} ({tipo}) con {len(case_ids)} casos...")
    inicio = time.time()
    procesar_run(run_pk, persistir=filtros.get("persistir", True))
    estado = batch_repo.estado_run(run_id)
    print(f"[batch] Completado en {time.time() - inicio:.0f}s → {estado}")
    print(f"[batch] Estado detail: {estado}")


def _resolver_casos(filtros: dict) -> tuple[list[str], str]:
    """Resuelve los caso_id y el tipo de filtro (reusando el de la API)."""
    import psycopg2.extras

    conn = psycopg2.connect(
        cursor_factory=psycopg2.extras.RealDictCursor,
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "rappi_cases"),
        user=os.getenv("DB_USER", "rappi"),
        password=os.getenv("DB_PASSWORD", "rappi_pass"),
    )
    try:
        if filtros.get("case_ids"):
            return list(filtros["case_ids"]), "seleccion"
        where, params = [], []
        if filtros.get("es_sintetico") is not None:
            where.append("es_sintetico = %s")
            params.append(filtros["es_sintetico"])
        if filtros.get("solo_pendientes"):
            where.append(
                "NOT EXISTS (SELECT 1 FROM resolution_case a WHERE a.caso_id = c.caso_id)"
            )
        sql = "SELECT c.caso_id FROM cases c"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY c.caso_id"
        if filtros.get("limite"):
            sql += " LIMIT %s"
            params.append(filtros["limite"])
        with conn.cursor() as cur:
            cur.execute(sql, params)
            case_ids = [r["caso_id"] for r in cur.fetchall()]
        tipo = "aleatorio" if filtros.get("aleatorio") else (
            "sintetico" if filtros.get("es_sintetico") is not None else (
                "pendientes" if filtros.get("solo_pendientes") else "todos"))
        return case_ids, tipo
    finally:
        conn.close()


if __name__ == "__main__":
    main()