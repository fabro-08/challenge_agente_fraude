"""Tests de integración de la API REST (requieren DB corriendo + seed de reglas).

Marcados con ``@pytest.mark.integration`` para separar de tests unitarios.
"""

import io
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(scope="session")
def client():
    """TestClient con el lifespan ejecutado (compila el grafo una vez)."""
    from src.api.main import app

    with TestClient(app) as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["db"] == "ok"
        assert data["casos"] >= 250
        assert data["reglas_yaml"] >= 10
        assert data["grafo"] == "compilado"


# ── Casos ─────────────────────────────────────────────────────────────


class TestCases:
    def test_list_cases_default(self, client):
        resp = client.get("/cases?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 250
        assert len(data["casos"]) == 5
        assert data["casos"][0]["caso_id"]

    def test_list_cases_filter_rechazar(self, client):
        resp = client.get("/cases?recomendacion=RECHAZAR&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        for c in data["casos"]:
            assert c["recomendacion_agente"] == "RECHAZAR"

    def test_get_case_ok(self, client):
        resp = client.get("/cases/COMP-0009")
        assert resp.status_code == 200
        data = resp.json()
        assert data["caso"]["caso_id"] == "COMP-0009"
        assert isinstance(data["checklist"], list)
        if data["checklist"]:
            item = data["checklist"][0]
            assert "regla_id" in item
            assert "se_disparo" in item

    def test_get_case_not_found(self, client):
        resp = client.get("/cases/NO-EXISTE-999")
        assert resp.status_code == 404

    def test_stats(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_casos"] >= 250
        for d in ("APROBAR", "RECHAZAR", "ESCALAR"):
            assert d in data["distribucion"]


# ── Análisis ──────────────────────────────────────────────────────────


class TestAnalyze:
    def test_analyze_case_fast(self, client):
        """COMP-0009: se resuelve por reglas (sin LLM), respuesta rápida."""
        resp = client.post("/analyze", json={"case_id": "COMP-0009"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["final_decision"] == "RECHAZAR"
        assert "COMP-0009" in data["case_id"]
        assert data["fuente"] == "reglas"
        assert data["decision_regla"] == "RECHAZAR"
        assert data["decision_llm"] is None
        assert data["justificacion_regla"]  # texto de reglas (desde thresholds.yaml)
        assert data["senales_regla"]        # señales de reglas (desde thresholds.yaml)

    def test_analyze_escalar_forzado(self, client):
        """COMP-0002: palabras críticas → ESCALAR forzado; el LLM analiza pero
        la decisión queda forzada a ESCALAR con fuente 'reglas'."""
        resp = client.post("/analyze", json={"case_id": "COMP-0002"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["final_decision"] == "ESCALAR"
        assert data["fuente"] == "reglas"
        assert data["decision_regla"] == "ESCALAR"
        assert data["decision_llm"] in ("APROBAR", "RECHAZAR", "ESCALAR")
        assert data["justificacion_regla"] and "ESCALAR" in data["justificacion_regla"]

    def test_analyze_not_found(self, client):
        resp = client.post("/analyze", json={"case_id": "NO-EXISTE-999"})
        assert resp.status_code == 404


# ── Batch ─────────────────────────────────────────────────────────────


class TestBatch:
    def test_lanzar_batch_limite_1(self, client):
        resp = client.post("/analyze/batch", json={"limite": 1, "es_sintetico": False})
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["total_casos"] <= 1

        # Consultar estado
        resp = client.get(f"/jobs/{data['job_id']}")
        assert resp.status_code == 200
        job = resp.json()
        assert job["status"] in ("running", "done")
        assert job["total"] <= 1

    def test_batch_aleatorio(self, client):
        """Muestreo aleatorio: solo verifica el lanzamiento (job en background)."""
        resp = client.post(
            "/analyze/batch",
            json={"limite": 3, "aleatorio": True, "persistir": False, "es_sintetico": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_casos"] == 3

    def test_batch_memoria_no_persiste(self, client):
        """Demo en memoria (persistir=False): no escribe resolution_case.

        Usa casos resueltos por reglas (sin LLM) para que el job termine rápido.
        """
        from src.api import services

        conn = services.conectar()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT c.caso_id FROM cases c
                       JOIN resolution_case a ON a.caso_id = c.caso_id
                       WHERE a.decision_regla IN ('APROBAR', 'RECHAZAR')
                         AND a.decision_llm IS NULL
                       ORDER BY c.caso_id LIMIT 2"""
                )
                ids = [r["caso_id"] for r in cur.fetchall()]
                cur.execute("SELECT COUNT(*) AS n FROM resolution_case")
                antes = cur.fetchone()["n"]
        finally:
            conn.close()
        assert len(ids) == 2, "Se esperaban 2 casos resueltos por reglas"

        resp = client.post("/analyze/batch", json={"case_ids": ids, "persistir": False})
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        assert resp.json()["total_casos"] == 2

        for _ in range(30):
            estado = client.get(f"/jobs/{job_id}").json()
            if estado["status"] == "done":
                break
            time.sleep(1)
        assert estado["status"] == "done"
        assert estado["errores"] == 0
        assert estado["procesados"] == 2

        # resolution_case no se modificó
        conn = services.conectar()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM resolution_case")
                despues = cur.fetchone()["n"]
        finally:
            conn.close()
        assert despues == antes, "El batch demo no debe escribir en resolution_case"

        # Filas del job en memoria
        resp = client.get(f"/jobs/{job_id}/resultados")
        assert resp.status_code == 200
        datos = resp.json()
        assert datos["total"] == 2
        assert {r["caso_id"] for r in datos["resultados"]} == set(ids)

        # Excel de la demo
        resp = client.get(f"/jobs/{job_id}/excel")
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"
        df = pd.read_excel(io.BytesIO(resp.content))
        assert len(df) == 2
        assert "recomendacion" in df.columns

    def test_job_not_found(self, client):
        resp = client.get("/jobs/NO-EXISTE-999")
        assert resp.status_code == 404


# ── Export ─────────────────────────────────────────────────────────────


class TestExport:
    def test_export_excel_150(self, client):
        resp = client.get("/export/excel")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == XLSX_MIME
        assert 'filename="150casos_analizados.xlsx"' in resp.headers["content-disposition"]
        assert resp.content[:2] == b"PK"  # magic de zip/xlsx

        df = pd.read_excel(io.BytesIO(resp.content))
        assert len(df) == 150
        for col in (
            "caso_id",
            "recomendacion",
            "decision_regla",
            "decision_llm",
            "justificacion_llm",
            "justificacion_regla",
            "senales_llm",
            "senales_regla",
            "resumen_llm",
        ):
            assert col in df.columns
        assert set(df["recomendacion"].unique()) <= {"APROBAR", "RECHAZAR", "ESCALAR"}
        assert df["recomendacion"].notna().sum() == 150

    def test_export_excel_sinteticos_250(self, client):
        resp = client.get("/export/excel", params={"es_sintetico": True})
        assert resp.status_code == 200
        assert 'filename="250casos_analizados.xlsx"' in resp.headers["content-disposition"]
        df = pd.read_excel(io.BytesIO(resp.content))
        assert len(df) == 250

    def test_export_politicas(self, client):
        resp = client.get("/export/politicas")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "Políticas" in resp.text
