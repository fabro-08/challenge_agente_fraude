"""Tests del proceso batch durable en PostgreSQL (integración con DB).

Cubre (requiere la DB corriendo con seed, como el resto de `@pytest.mark.integration`):
- Persistencia consolidada y su idempotencia (ON CONFLICT).
- Semántica de reclamo de items (retry → ``failed`` al agotar intentos).
- Recuperación de runs huérfanos tras reinicio.
- Persistencia de filas demo (modo ``persistir=False``).

Los tests limpian los registros de prueba que crean (no dejar basura).
"""

import pytest

from src.batch import repository as repo

CASO = "COMP-0001"


def _resultado_valido(decision: str = "APROBAR") -> dict:
    """Estado mínimo que el pipeline dejaría como resultado persistible."""
    return {
        "final_decision": decision,
        "decision_regla": decision,
        "decision_llm": "APROBAR",
        "justificacion_llm": "test",
        "justificacion_regla": "test",
        "senales_llm": ["comp_ratio<1"],
        "senales_regla": ["flags >= 2 = 3"],
        "reglas_checklist": [],
        "llm_resultado": {"veredicto": "APROBAR", "resumen": "test"},
        "features_version": "v1",
    }


def _limpiar_run(run_id: str) -> None:
    import psycopg2

    conn = psycopg2.connect(**repo.DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM batch_runs WHERE run_id = %s", (run_id,))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.integration
class TestBatchDurable:
    """El lote se persiste y consulta de forma durable desde PostgreSQL."""

    def test_crear_run_persiste_items(self):
        run_id = "test-run-0001"
        pk = repo.crear_run(run_id, "todos", {}, True, ["COMP-0001", "COMP-0002"])
        try:
            estado = repo.estado_run(run_id)
            assert estado["status"] == "running"
            assert estado["total"] == 2
            assert estado["procesados"] == 0
        finally:
            _limpiar_run(run_id)

    def test_reclamar_item_atomico_y_failed_tras_intentos(self):
        run_id = "test-run-retry"
        pk = repo.crear_run(run_id, "todos", {}, True, ["COMP-0003"])
        try:
            # Primer reclamo → running
            item = repo.reclamar_item(pk, max_intentos=2)
            assert item is not None
            item_id, caso = item
            assert caso == "COMP-0003"

            # No se reclama dos veces el mismo item (at-least-once)
            assert repo.reclamar_item(pk, max_intentos=2) is None

            # Falla N veces: al superar max_intentos → failed
            e1 = repo.incrementar_item_fallido(item_id, "transient", max_intentos=2)
            assert e1 == "queued"  # queda 1 intento
            e2 = repo.incrementar_item_fallido(item_id, "stable-fail", max_intentos=2)
            assert e2 == "failed"
        finally:
            _limpiar_run(run_id)

    def test_recuperar_runs_huerfanos(self):
        run_id = "test-run-huertest"
        pk = repo.crear_run(run_id, "todos", {}, True, ["COMP-0004"])
        # Simula un item quedado en 'running' (worker murió a mitad)
        import psycopg2

        conn = psycopg2.connect(**repo.DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE batch_run_items SET estado = 'running' WHERE run_id = %s", (pk,)
                )
            conn.commit()
        finally:
            conn.close()

        try:
            recuperados = repo.recuperar_runs_huerfanos()
            assert recuperados >= 1
            estado = repo.estado_run(run_id)
            assert estado["status"] == "error"
        finally:
            _limpiar_run(run_id)

    def test_persistir_resolucion_idempotente(self):
        repo.persistir_resolucion(CASO, _resultado_valido(), batch_run_id=None)
        repo.persistir_resolucion(CASO, _resultado_valido("RECHAZAR"), batch_run_id=None)
        try:
            import psycopg2

            conn = psycopg2.connect(**repo.DB_CONFIG)
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM resolution_case WHERE caso_id = %s", (CASO,)
                    )
                    n = cur.fetchone()[0]
                    cur.execute(
                        "SELECT decision FROM resolution_case WHERE caso_id = %s", (CASO,)
                    )
                    dec = cur.fetchone()[0]
            finally:
                conn.close()
            assert n == 1
            assert dec == "RECHAZAR"
        finally:
            # Restaurar el caso a un valor válido para no romper el invariante
            # de los demás tests de simulación (contar 250 filas en resolution_case).
            repo.persistir_resolucion(CASO, _resultado_valido("APROBAR"), batch_run_id=None)

    def test_filas_demo_almacenadas_y_recuperables(self):
        run_id = "test-run-demo"
        pk = repo.crear_run(run_id, "todos", {}, False, ["COMP-0005"])
        try:
            item = repo.reclamar_item(pk, max_intentos=2)
            assert item is not None
            item_id, _ = item
            fila = {"caso_id": "COMP-0005", "recomendacion": "APROBAR"}
            repo.marcar_item(item_id, "done", fila_demo=fila)
            filas = repo.filas_run(run_id)
            assert len(filas) == 1
            assert filas[0]["recomendacion"] == "APROBAR"
        finally:
            _limpiar_run(run_id)