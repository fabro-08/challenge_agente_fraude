"""Tests de integración de la API REST (requieren DB corriendo + seed de reglas).

Marcados con ``@pytest.mark.integration`` para separar de tests unitarios.
"""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


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
        assert data["reglas_activas"] >= 10
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
        assert data["justificacion_regla"]  # R1 — descripción de la regla
        assert data["senales_regla"]        # campo operador umbral = valor real
        assert len(data["checklist"]) > 0
        for item in data["checklist"]:
            assert "version" in item
            assert "se_disparo" in item

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
        assert data["justificacion_regla"].startswith("ESCALAR-1 —")

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

    def test_job_not_found(self, client):
        resp = client.get("/jobs/NO-EXISTE-999")
        assert resp.status_code == 404


# ── Reglas ────────────────────────────────────────────────────────────


class TestRules:
    def test_list_rules(self, client):
        resp = client.get("/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 11
        for r in data:
            assert "regla_id" in r
            assert "version_actual" in r
            assert "config" in r
            assert "condiciones" in r["config"]

    def test_get_rule_ok(self, client):
        resp = client.get("/rules/R1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["regla_id"] == "R1"
        assert data["version_actual"] >= 1

    def test_get_rule_not_found(self, client):
        resp = client.get("/rules/NO-EXISTE")
        assert resp.status_code == 404

    def test_update_rule_and_revert(self, client):
        """Actualiza R1 (valor=99 → debe fallar ningún caso), verifica version, revierte."""
        resp = client.put(
            "/rules/R1",
            json={
                "config": {
                    "descripcion": "Test: flags >= 99",
                    "match": "all",
                    "condiciones": [{"campo": "flags_fraude_previos", "operador": ">=", "valor": 99}],
                },
                "updated_by": "pytest",
                "cambio_descripcion": "Test temporal de versionado",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["version_actual"] > 1

        # Revertir a la configuración canónica de R1 (no dejar basura)
        resp = client.put(
            "/rules/R1",
            json={
                "config": {
                    "descripcion": "Usuario con 2 o más flags de fraude previos",
                    "explicacion": "El usuario tiene 2 o más flags de fraude previos: ya está señalado por el sistema.",
                    "match": "all",
                    "condiciones": [{"campo": "flags_fraude_previos", "operador": ">=", "valor": 2}],
                },
                "updated_by": "pytest",
                "cambio_descripcion": "Revertir test de versionado",
            },
        )
        assert resp.status_code == 200

    def test_update_invalid_field(self, client):
        resp = client.put(
            "/rules/R1",
            json={
                "config": {
                    "descripcion": "Campo inválido",
                    "match": "all",
                    "condiciones": [{"campo": "CAMPO_INEXISTENTE_999", "operador": ">=", "valor": 5}],
                },
                "updated_by": "pytest",
                "cambio_descripcion": "Test campo inválido",
            },
        )
        assert resp.status_code == 422
        assert "CAMPO_INEXISTENTE_999" in resp.json()["detail"]

    def test_versions(self, client):
        resp = client.get("/rules/R1/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3  # v1 seed + v2 test anterior + v3 revert
        assert data[0]["version"] > data[-1]["version"]

    def test_campos(self, client):
        resp = client.get("/rules/campos")
        assert resp.status_code == 200
        data = resp.json()
        assert "comp_ratio" in data["campos"]
        assert ">=" in data["operadores"]

    def test_simulate_update_does_not_persist(self, client):
        """Simular cambio a R1=3: detecta transiciones, pero config activa sigue siendo 2."""
        resp = client.post(
            "/rules/simulate",
            json={
                "accion": "update",
                "regla_id": "R1",
                "config": {
                    "descripcion": "sim test",
                    "match": "all",
                    "condiciones": [{"campo": "flags_fraude_previos", "operador": ">=", "valor": 3}],
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["casos_evaluados"] >= 250
        assert data["cambian_decision"] > 0
        assert "RECHAZAR→LLM/ESCALAR" in data["transiciones"]

        # Verificar que R1 no cambió en DB
        resp = client.get("/rules/R1")
        assert resp.status_code == 200
        valor = resp.json()["config"]["condiciones"][0]["valor"]
        assert valor == 2, f"R1 debió seguir=2, pero es {valor}"

    def test_simulate_delete(self, client):
        resp = client.post(
            "/rules/simulate",
            json={"accion": "delete", "regla_id": "R1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cambian_decision"] > 0


# ── Usuarios ──────────────────────────────────────────────────────────


class TestUsers:
    def test_list_users(self, client):
        resp = client.get("/users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 3
        for u in data:
            assert "nombre" in u
            assert "email" in u
