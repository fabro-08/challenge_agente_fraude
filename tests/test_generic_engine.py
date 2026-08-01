"""Tests del motor genérico de reglas (step 06b).

Cubre:
- Evaluación de condiciones (todos los operadores).
- Evaluación de reglas (match all/any).
- Precedencia de decisión (ESCALAR_FORZOSO > RECHAZAR > APROBAR > AMBIGUO).
- Paridad con el RuleEngine original sobre los casos reales (integración DB).
- Versionado en repository (crear/actualizar/historial).
- Simulador (transiciones sin persistir).

Los tests de integración requieren la DB corriendo con el seed aplicado
(``docker compose up`` + ``python -m src.rules.seed_reglas``).
"""

import pandas as pd
import pytest

from src.rules.generic_engine import (
    GenericRuleEngine,
    RuleDefinition,
    evaluar_condicion,
)
from src.rules.rule_engine import RuleEngine


# ── Fixtures ──────────────────────────────────────────────────────────


def _regla(
    regla_id: str,
    tipo: str,
    condiciones: list[dict],
    match: str = "all",
    prioridad: int = 1,
) -> RuleDefinition:
    """Helper para construir reglas de test."""
    return RuleDefinition(
        regla_id=regla_id,
        version_id=1,
        nombre=f"Test {regla_id}",
        tipo_regla=tipo,
        prioridad=prioridad,
        config={"descripcion": f"Regla {regla_id}", "match": match, "condiciones": condiciones},
    )


@pytest.fixture
def engine_basico() -> GenericRuleEngine:
    """Motor con una regla de cada tipo."""
    return GenericRuleEngine([
        _regla("ESCALAR-1", "ESCALAR_FORZOSO", [
            {"campo": "descripcion_reclamo", "operador": "contains_any", "valor": ["abogado"]},
        ], prioridad=0),
        _regla("R1", "RECHAZAR", [
            {"campo": "flags_fraude_previos", "operador": ">=", "valor": 2},
        ]),
        _regla("A1", "APROBAR", [
            {"campo": "flags_fraude_previos", "operador": "==", "valor": 0},
            {"campo": "comp_ratio", "operador": "<=", "valor": 0.8},
        ]),
    ])


# ── Operadores ────────────────────────────────────────────────────────


class TestOperadores:
    """Verifica cada operador del evaluador de condiciones."""

    @pytest.mark.parametrize("actual,op,esperado,resultado", [
        (3, ">=", 2, True),
        (2, ">=", 2, True),
        (1, ">=", 2, False),
        (0.5, ">", 0.99, False),
        (1.0, ">", 0.99, True),
        (604.64, ">", 604.64, False),
        ("SÍ - confirmada", "==", "SÍ - confirmada", True),
        ("Parcial", "==", "SÍ - confirmada", False),
        (True, "==", True, True),
        (False, "==", True, False),
        ("Orden llegó tarde", "in", ["Orden llegó tarde", "Mal estado"], True),
        ("Otro", "in", ["Orden llegó tarde"], False),
        ("Otro", "not_in", ["Orden llegó tarde"], True),
        (None, ">=", 2, False),          # NULL nunca dispara
        (None, "==", True, False),
    ])
    def test_comparaciones(self, actual, op, esperado, resultado):
        cond = {"campo": "x", "operador": op, "valor": esperado}
        assert evaluar_condicion(cond, {"x": actual}).se_cumple is resultado

    @pytest.mark.parametrize("texto,palabras,resultado", [
        ("Mi hijo tiene alergia al maní", ["alergi"], True),
        ("Voy a hablar con mi ABOGADO", ["abogado"], True),   # case-insensitive
        ("Me intoxicaron la comida", ["intoxic"], True),
        ("Me intoxiqué con la comida", ["intoxic"], False),  # stem 'intoxic' ≠ 'intoxiqu'
        ("Todo bien, solo llegó frío", ["alergi", "veneno"], False),
        ("", ["alergi"], False),
        (None, ["alergi"], False),
    ])
    def test_contains_any(self, texto, palabras, resultado):
        cond = {"campo": "desc", "operador": "contains_any", "valor": palabras}
        assert evaluar_condicion(cond, {"desc": texto}).se_cumple is resultado

    def test_contains_all(self):
        cond = {"campo": "desc", "operador": "contains_all", "valor": ["frío", "tarde"]}
        assert evaluar_condicion(cond, {"desc": "Llegó frío y tarde"}).se_cumple is True
        assert evaluar_condicion(cond, {"desc": "Llegó frío"}).se_cumple is False

    def test_campo_inexistente_no_dispara(self):
        cond = {"campo": "no_existe", "operador": ">=", "valor": 1}
        assert evaluar_condicion(cond, {}).se_cumple is False

    def test_coercion_numerica_desde_string(self):
        """Valores numéricos que vienen como string (DB) deben compararse bien."""
        cond = {"campo": "comp_ratio", "operador": ">", "valor": 0.99}
        assert evaluar_condicion(cond, {"comp_ratio": "1.5"}).se_cumple is True
        assert evaluar_condicion(cond, {"comp_ratio": "0.5"}).se_cumple is False


# ── Evaluación de reglas y precedencia ────────────────────────────────


class TestPrecedencia:
    """Verifica el orden de decisión del motor."""

    def test_rechazar_cuando_dispara_regla(self, engine_basico):
        caso = {"flags_fraude_previos": 3, "comp_ratio": 0.5, "descripcion_reclamo": "ok"}
        ev = engine_basico.evaluate_case(caso)
        assert ev.decision == "RECHAZAR"
        assert any("R1" in s for s in ev.signals)

    def test_aprobar_cuando_no_hay_fraude(self, engine_basico):
        caso = {"flags_fraude_previos": 0, "comp_ratio": 0.5, "descripcion_reclamo": "ok"}
        ev = engine_basico.evaluate_case(caso)
        assert ev.decision == "APROBAR"

    def test_escalar_forzoso_gana_a_rechazar(self, engine_basico):
        """Palabras críticas fuerzan ESCALAR aunque haya señales de fraude."""
        caso = {
            "flags_fraude_previos": 5,
            "comp_ratio": 0.5,
            "descripcion_reclamo": "Voy a llamar a mi abogado",
        }
        ev = engine_basico.evaluate_case(caso)
        assert ev.decision == "ESCALAR"
        assert any("ESCALAR-1" in s for s in ev.signals)

    def test_ambiguo_sin_reglas_disparadas(self, engine_basico):
        caso = {"flags_fraude_previos": 1, "comp_ratio": 0.9, "descripcion_reclamo": "ok"}
        ev = engine_basico.evaluate_case(caso)
        assert ev.decision == "AMBIGUO"

    def test_match_any(self):
        """Con match=any basta una condición para disparar."""
        regla = _regla("R9", "RECHAZAR", [
            {"campo": "a", "operador": ">=", "valor": 10},
            {"campo": "b", "operador": ">=", "valor": 10},
        ], match="any")
        engine = GenericRuleEngine([regla])
        assert engine.evaluate_case({"a": 0, "b": 15}).decision == "RECHAZAR"
        assert engine.evaluate_case({"a": 0, "b": 0}).decision == "AMBIGUO"

    def test_checklist_completo(self, engine_basico):
        """rule_results incluye TODAS las reglas, disparadas o no."""
        caso = {"flags_fraude_previos": 3, "comp_ratio": 0.5, "descripcion_reclamo": "ok"}
        ev = engine_basico.evaluate_case(caso)
        assert len(ev.rule_results) == 3
        disparadas = [r.regla_id for r in ev.rule_results if r.se_disparo]
        assert disparadas == ["R1"]


# ── Paridad con el motor original (integración DB) ────────────────────


@pytest.mark.integration
class TestParidad:
    """El motor genérico con reglas v1 debe decidir igual que el RuleEngine YAML."""

    def test_paridad_250_casos(self):
        from src.rules.repository import DB_CONFIG, cargar_reglas_activas

        conn = __import__("psycopg2").connect(**DB_CONFIG)
        try:
            df = pd.read_sql(
                "SELECT c.*, f.* FROM cases c "
                "LEFT JOIN features f ON f.caso_id = c.caso_id "
                "ORDER BY c.caso_id",
                conn,
            )
        finally:
            conn.close()

        original = RuleEngine().decide(df)
        generico = GenericRuleEngine(cargar_reglas_activas())

        diferencias = 0
        for i, row in df.iterrows():
            ev = generico.evaluate_case(row.to_dict())
            dec_gen = "ESCALAR" if ev.decision == "AMBIGUO" else ev.decision
            if dec_gen != original.loc[i, "recomendacion"]:
                diferencias += 1

        assert diferencias == 0, f"{diferencias} casos difieren entre motores"

    def test_reglas_activas_son_11(self):
        from src.rules.repository import cargar_reglas_activas

        reglas = cargar_reglas_activas()
        assert len(reglas) == 11
        assert all(r.version_id > 0 for r in reglas)


# ── Versionado (integración DB) ───────────────────────────────────────


@pytest.mark.integration
class TestVersionado:
    """Verifica crear/actualizar reglas con historial de versiones."""

    def test_actualizar_crea_nueva_version(self):
        from src.rules import repository

        # Crear regla de test
        try:
            repository.crear_regla(
                regla_id="TEST-1",
                nombre="Regla de test",
                tipo_regla="RECHAZAR",
                config={"descripcion": "t", "match": "all",
                        "condiciones": [{"campo": "x", "operador": ">=", "valor": 1}]},
                updated_by="pytest",
            )
        except Exception:
            pass  # ya existe de un test anterior

        vid = repository.actualizar_regla(
            regla_id="TEST-1",
            config={"descripcion": "t2", "match": "all",
                    "condiciones": [{"campo": "x", "operador": ">=", "valor": 5}]},
            updated_by="pytest",
            cambio_descripcion="test de versionado",
        )
        assert vid > 0

        versiones = repository.obtener_versiones("TEST-1")
        assert len(versiones) >= 2
        assert versiones[0]["updated_by"] == "pytest"

        # Cleanup: eliminar la regla de test (no dejar basura en DB)
        import psycopg2

        conn = psycopg2.connect(**repository.DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM reglas_versiones WHERE regla_id = 'TEST-1'")
                cur.execute("DELETE FROM configuracion_reglas WHERE regla_id = 'TEST-1'")
            conn.commit()
        finally:
            conn.close()


# ── Simulador (integración DB) ────────────────────────────────────────


@pytest.mark.integration
class TestSimulador:
    """Verifica que la simulación detecta transiciones sin persistir."""

    def test_simular_subir_threshold_r1(self):
        from src.rules.repository import DB_CONFIG
        from src.rules.simulator import simular_cambio

        def mutador(reglas):
            for r in reglas:
                if r.regla_id == "R1":
                    r.config = dict(r.config)
                    r.config["condiciones"] = [
                        {**c, "valor": 3} for c in r.config["condiciones"]
                    ]
            return reglas

        res = simular_cambio(mutador)

        assert res["casos_evaluados"] == 250
        assert res["cambian_decision"] > 0
        assert "RECHAZAR→LLM/ESCALAR" in res["transiciones"]

        # La simulación NO debe haber persistido nada
        conn = __import__("psycopg2").connect(**DB_CONFIG)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM resolution_case WHERE reglas_checklist IS NOT NULL")
                n_resultados = cur.fetchone()[0]
                cur.execute("SELECT config->'condiciones'->0->>'valor' FROM reglas_versiones v JOIN configuracion_reglas c ON c.regla_id = v.regla_id AND c.version_actual = v.version WHERE v.regla_id = 'R1'")
                valor_r1 = cur.fetchone()[0]
        finally:
            conn.close()

        assert n_resultados == 250, "La simulación no debe persistir checklist en resolution_case"
        assert valor_r1 == "2", "La simulación no debe modificar la config activa"

    def test_simular_regla_nueva(self):
        from src.rules.generic_engine import RuleDefinition
        from src.rules.simulator import simular_cambio

        def mutador(reglas):
            reglas.append(RuleDefinition(
                regla_id="SIM-1", version_id=999999, nombre="Simulada",
                tipo_regla="RECHAZAR", prioridad=99,
                config={"descripcion": "s", "match": "all",
                        "condiciones": [{"campo": "ciudad", "operador": "==", "valor": "CIUDAD_INEXISTENTE"}]},
            ))
            return reglas

        res = simular_cambio(mutador)
        assert res["cambian_decision"] == 0  # regla que no matchea nada
