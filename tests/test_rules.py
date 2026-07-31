"""Tests unitarios del motor de reglas heurísticas.

Verifica que:
- Las reglas de RECHAZAR detectan casos con señales claras.
- Las reglas de APROBAR detectan casos legítimos.
- Los casos ambiguos quedan como ESCALAR.
- El orden de precedencia se respeta.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.rules.rule_engine import RuleEngine

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def engine() -> RuleEngine:
    """Carga el RuleEngine con thresholds por defecto."""
    return RuleEngine()


@pytest.fixture
def caso_fraude_claro() -> dict:
    """Caso con señales de fraude evidentes."""
    return {
        "caso_id": "TEST-FRAUD-1",
        "usuario_id": "USR-TEST-1",
        "antiguedad_usuario_dias": 15,
        "ciudad": "CDMX",
        "vertical": "Comida",
        "restaurante": "Test",
        "valor_orden_mxn": 150.0,
        "compensacion_solicitada_mxn": 500.0,
        "num_compensaciones_90d": 12,
        "monto_compensado_90d_mxn": 2000.0,
        "entrega_confirmada_gps": "NO confirmada",
        "tiempo_entrega_real_min": 30,
        "flags_fraude_previos": 3,
        "motivo_reclamo": "Orden no llegó",
        "descripcion_reclamo": "No me llegó nada",
        "comp_ratio": 3.33,
        "freq_densidad": 0.8,
        "score_riesgo_previo": 12.0,
        "flag_inconsistencia_gps": False,
        "flag_retraso_critico": False,
        "flag_account_abuse": True,
        "flag_palabras_criticas": False,
        "entrega_demorada": False,
    }


@pytest.fixture
def caso_legitimo() -> dict:
    """Caso de un usuario legítimo sin señales de riesgo."""
    return {
        "caso_id": "TEST-LEGIT-1",
        "usuario_id": "USR-TEST-2",
        "antiguedad_usuario_dias": 800,
        "ciudad": "CDMX",
        "vertical": "Comida",
        "restaurante": "Test",
        "valor_orden_mxn": 300.0,
        "compensacion_solicitada_mxn": 180.0,
        "num_compensaciones_90d": 1,
        "monto_compensado_90d_mxn": 180.0,
        "entrega_confirmada_gps": "SÍ - confirmada",
        "tiempo_entrega_real_min": 100,
        "flags_fraude_previos": 0,
        "motivo_reclamo": "Orden llegó tarde",
        "descripcion_reclamo": "La comida llegó después de 100 minutos",
        "comp_ratio": 0.6,
        "freq_densidad": 0.01,
        "score_riesgo_previo": 0.5,
        "flag_inconsistencia_gps": False,
        "flag_retraso_critico": True,
        "flag_account_abuse": False,
        "flag_palabras_criticas": False,
        "entrega_demorada": True,
    }


@pytest.fixture
def caso_ambiguo() -> dict:
    """Caso sin señales claras ni de fraude ni de legitimidad."""
    return {
        "caso_id": "TEST-AMB-1",
        "usuario_id": "USR-TEST-3",
        "antiguedad_usuario_dias": 150,
        "ciudad": "CDMX",
        "vertical": "Comida",
        "restaurante": "Test",
        "valor_orden_mxn": 250.0,
        "compensacion_solicitada_mxn": 175.0,
        "num_compensaciones_90d": 4,
        "monto_compensado_90d_mxn": 600.0,
        "entrega_confirmada_gps": "Parcial",
        "tiempo_entrega_real_min": 55,
        "flags_fraude_previos": 0,
        "motivo_reclamo": "Producto incorrecto",
        "descripcion_reclamo": "Me enviaron otro producto",
        "comp_ratio": 0.7,
        "freq_densidad": 0.04,
        "score_riesgo_previo": 2.0,
        "flag_inconsistencia_gps": False,
        "flag_retraso_critico": False,
        "flag_account_abuse": False,
        "flag_palabras_criticas": False,
        "entrega_demorada": False,
    }


class TestRuleEngine:
    """Suite de tests del RuleEngine."""

    def test_rechazar_fraude(self, engine: RuleEngine, caso_fraude_claro: dict):
        """Verifica que un caso con fraude claro sea RECHAZADO."""
        df = pd.DataFrame([caso_fraude_claro])
        result = engine.decide(df)
        assert result.iloc[0]["recomendacion"] == "RECHAZAR"
        assert len(result.iloc[0]["senales_usadas"]) > 0

    def test_aprobar_legitimo(self, engine: RuleEngine, caso_legitimo: dict):
        """Verifica que un caso legítimo sea APROBADO."""
        df = pd.DataFrame([caso_legitimo])
        result = engine.decide(df)
        assert result.iloc[0]["recomendacion"] == "APROBAR"

    def test_escalar_ambiguo(self, engine: RuleEngine, caso_ambiguo: dict):
        """Verifica que un caso ambiguo sea ESCALADO."""
        df = pd.DataFrame([caso_ambiguo])
        result = engine.decide(df)
        assert result.iloc[0]["recomendacion"] == "ESCALAR"
        assert "ambiguo" in result.iloc[0]["senales_usadas"]

    def test_escalar_palabras_criticas(self, engine: RuleEngine, caso_fraude_claro: dict):
        """Verifica que flag_palabras_criticas fuerza ESCALAR aunque haya fraude."""
        caso = caso_fraude_claro.copy()
        caso["flag_palabras_criticas"] = True
        df = pd.DataFrame([caso])
        result = engine.decide(df)
        # Debe ser ESCALAR (precedencia sobre RECHAZAR)
        assert result.iloc[0]["recomendacion"] == "ESCALAR"
        assert "seguridad de marca" in result.iloc[0]["justificacion"]

    def test_retraso_aproba(self, engine: RuleEngine):
        """Verifica que un retraso crítico con motivo coherente sea APROBADO."""
        caso = {
            "caso_id": "TEST-RETRASO-1",
            "flags_fraude_previos": 0,
            "comp_ratio": 0.6,
            "freq_densidad": 0.01,
            "compensacion_solicitada_mxn": 150.0,
            "flag_inconsistencia_gps": False,
            "flag_account_abuse": False,
            "flag_palabras_criticas": False,
            "score_riesgo_previo": 0.5,
            "flag_retraso_critico": True,
            "motivo_reclamo": "Orden llegó tarde",
            "entrega_confirmada_gps": "SÍ - confirmada",
            "num_compensaciones_90d": 1,
            "antiguedad_usuario_dias": 500,
        }
        df = pd.DataFrame([caso])
        result = engine.decide(df)
        assert result.iloc[0]["recomendacion"] == "APROBAR"

    def test_explain_genera_texto(self, engine: RuleEngine, caso_fraude_claro: dict):
        """Verifica que explain() retorna un texto no vacío."""
        texto = engine.explain(caso_fraude_claro)
        assert isinstance(texto, str)
        assert len(texto) > 20

    def test_decide_no_muta_input(self, engine: RuleEngine, caso_legitimo: dict):
        """Verifica que decide() no modifica el DataFrame original."""
        df = pd.DataFrame([caso_legitimo])
        cols_antes = set(df.columns)
        engine.decide(df)
        cols_despues = set(df.columns)
        assert cols_antes == cols_despues  # decide retorna copia

    def test_decide_150_casos(self, engine: RuleEngine):
        """Verifica que decide procesa los 150 casos sin NaN."""
        df = pd.read_parquet("data/casos_con_features.parquet")
        result = engine.decide(df)
        assert len(result) == 150
        assert not result["recomendacion"].isna().any()
        assert not result["senales_usadas"].isna().any()
        assert not result["justificacion"].isna().any()
        # Verificar que hay al menos 1 de cada tipo
        tipos = result["recomendacion"].unique()
        for t in ["APROBAR", "RECHAZAR", "ESCALAR"]:
            assert t in tipos, f"Falta categoría {t}"
