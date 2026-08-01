"""Motor genérico de reglas: evalúa definiciones declarativas (JSONB) de fraude.

A diferencia de ``RuleEngine`` (step 03, lógica hardcodeada + thresholds.yaml),
este motor interpreta la configuración de cada regla almacenada en la tabla
``reglas_versiones``. El equipo de fraude puede entonces modificar thresholds,
activar/desactivar reglas o crear nuevas sin tocar código.

Esquema de una regla (campo ``config`` JSONB)::

    {
      "descripcion": "Usuario con 2+ flags de fraude previos",
      "match": "all",                      # all = AND, any = OR
      "condiciones": [
        {"campo": "flags_fraude_previos", "operador": ">=", "valor": 2}
      ]
    }

Operadores soportados:
    ``>``, ``>=``, ``<``, ``<=``, ``==``, ``!=``  — comparación (numérica o texto)
    ``in``, ``not_in``                            — pertenencia a lista
    ``contains_any``, ``contains_all``            — subtexto (case-insensitive)

Los ``campo`` válidos son cualquier columna de ``cases`` (datos crudos) o
``features`` (features derivadas). Si el campo no existe o es NULL en el caso,
la condición evalúa a False (safe default).

Precedencia de decisión (idéntica al motor original):
    1. ESCALAR_FORZOSO: cualquiera que dispare → ESCALAR
    2. RECHAZAR: cualquiera que dispare → RECHAZAR (se colectan todas las señales)
    3. APROBAR: la primera que dispare → APROBAR
    4. resto → AMBIGUO (el pipeline lo deriva al LLM)
"""

from dataclasses import dataclass, field
from typing import Any

OPERADORES_COMPARACION = {">", ">=", "<", "<=", "==", "!="}
OPERADORES_LISTA = {"in", "not_in"}
OPERADORES_TEXTO = {"contains_any", "contains_all"}
OPERADORES_VALIDOS = OPERADORES_COMPARACION | OPERADORES_LISTA | OPERADORES_TEXTO

DECISIONES = ("RECHAZAR", "APROBAR", "ESCALAR_FORZOSO")


@dataclass
class RuleDefinition:
    """Defición activa de una regla, cargada desde DB.

    Attributes:
        regla_id: Identificador estable (ej. "R1", "A2", "ESCALAR-1").
        version_id: PK de ``reglas_versiones`` — ancla cada resultado a su versión.
        nombre: Nombre corto legible.
        tipo_regla: RECHAZAR | APROBAR | ESCALAR_FORZOSO.
        prioridad: Orden de evaluación dentro de su tipo (menor = primero).
        config: Dict con ``descripcion``, ``match`` y ``condiciones``.
    """

    regla_id: str
    version_id: int
    nombre: str
    tipo_regla: str
    prioridad: int
    config: dict[str, Any]

    @property
    def descripcion(self) -> str:
        return str(self.config.get("descripcion", self.nombre))


@dataclass
class ConditionResult:
    """Resultado de evaluar una condición individual."""

    campo: str
    operador: str
    valor_esperado: Any
    valor_actual: Any
    se_cumple: bool


@dataclass
class RuleResult:
    """Resultado de evaluar una regla contra un caso."""

    regla_id: str
    version_id: int
    nombre: str
    tipo_regla: str
    se_disparo: bool
    detalle: str
    valor_actual: str
    descripcion: str = ""
    condiciones: list[ConditionResult] = field(default_factory=list)


@dataclass
class CaseEvaluation:
    """Evaluación completa de un caso contra todas las reglas activas.

    Attributes:
        decision: RECHAZAR | APROBAR | ESCALAR | AMBIGUO.
        signals: Señales legibles que dispararon (para justificación).
        rule_results: Checklist completo (una entrada por regla activa evaluada).
    """

    decision: str
    signals: list[str]
    rule_results: list[RuleResult]


def _evaluar_comparacion(actual: Any, operador: str, esperado: Any) -> bool:
    """Evalúa operadores de comparación con coerción numérica tolerante."""
    if actual is None or esperado is None:
        return False

    # Coerción: si el esperado es numérico, intentar convertir el actual
    if isinstance(esperado, (int, float)) and not isinstance(esperado, bool):
        try:
            actual = float(actual)
        except (TypeError, ValueError):
            return False

    if operador == ">":
        return actual > esperado
    if operador == ">=":
        return actual >= esperado
    if operador == "<":
        return actual < esperado
    if operador == "<=":
        return actual <= esperado
    if operador == "==":
        return actual == esperado
    if operador == "!=":
        return actual != esperado
    return False


def _evaluar_texto(actual: Any, operador: str, esperado: Any) -> bool:
    """Evalúa contains_any / contains_all sobre texto (case-insensitive)."""
    if actual is None:
        return False
    texto = str(actual).lower()
    palabras = [str(p).lower() for p in (esperado if isinstance(esperado, list) else [esperado])]
    if operador == "contains_any":
        return any(p in texto for p in palabras)
    if operador == "contains_all":
        return all(p in texto for p in palabras)
    return False


def evaluar_condicion(condicion: dict[str, Any], row: dict[str, Any]) -> ConditionResult:
    """Evalúa una condición individual contra los datos del caso.

    Args:
        condicion: Dict con ``campo``, ``operador`` y ``valor``.
        row: Diccionario del caso (columnas de ``cases`` + ``features``).

    Returns:
        ConditionResult con el valor encontrado y si se cumplió.
    """
    campo = str(condicion.get("campo", ""))
    operador = str(condicion.get("operador", ""))
    esperado = condicion.get("valor")
    actual = row.get(campo)

    if operador in OPERADORES_COMPARACION:
        cumple = _evaluar_comparacion(actual, operador, esperado)
    elif operador in OPERADORES_LISTA:
        lista = esperado if isinstance(esperado, list) else [esperado]
        cumple = (actual in lista) if operador == "in" else (actual not in lista)
    elif operador in OPERADORES_TEXTO:
        cumple = _evaluar_texto(actual, operador, esperado)
    else:
        cumple = False

    return ConditionResult(
        campo=campo,
        operador=operador,
        valor_esperado=esperado,
        valor_actual=actual,
        se_cumple=cumple,
    )


class GenericRuleEngine:
    """Evalúa casos contra un conjunto de reglas declarativas versionadas.

    Args:
        rules: Lista de RuleDefinition activas (típicamente desde
            ``repository.cargar_reglas_activas()``).
    """

    def __init__(self, rules: list[RuleDefinition]):
        self.rules = sorted(rules, key=lambda r: (DECISIONES.index(r.tipo_regla), r.prioridad))

    def evaluar_regla(self, regla: RuleDefinition, row: dict[str, Any]) -> RuleResult:
        """Evalúa una regla completa contra un caso.

        Args:
            regla: Definición de la regla.
            row: Diccionario del caso.

        Returns:
            RuleResult con ``se_disparo``, ``detalle`` y desglose por condición.
        """
        condiciones_cfg = regla.config.get("condiciones", [])
        match = regla.config.get("match", "all")

        resultados = [evaluar_condicion(c, row) for c in condiciones_cfg]

        if not resultados:
            se_disparo = False
        elif match == "any":
            se_disparo = any(r.se_cumple for r in resultados)
        else:
            se_disparo = all(r.se_cumple for r in resultados)

        detalle = self._construir_detalle(regla, resultados, se_disparo)
        valor_actual = "; ".join(f"{r.campo}={r.valor_actual}" for r in resultados)

        return RuleResult(
            regla_id=regla.regla_id,
            version_id=regla.version_id,
            nombre=regla.nombre,
            tipo_regla=regla.tipo_regla,
            se_disparo=se_disparo,
            detalle=detalle,
            valor_actual=valor_actual,
            descripcion=regla.descripcion,
            condiciones=resultados,
        )

    @staticmethod
    def _construir_detalle(
        regla: RuleDefinition, resultados: list[ConditionResult], se_disparo: bool
    ) -> str:
        """Genera explicación legible del resultado para el agente CS."""
        partes = []
        for r in resultados:
            marca = "✓" if r.se_cumple else "✗"
            partes.append(f"{r.campo}={r.valor_actual} ({r.operador} {r.valor_esperado}) {marca}")
        estado = "SE DISPARÓ" if se_disparo else "no se disparó"
        return f"{regla.nombre} {estado}: {'; '.join(partes)}"

    def evaluate_case(self, row: dict[str, Any]) -> CaseEvaluation:
        """Evalúa todas las reglas activas contra un caso.

        Args:
            row: Diccionario del caso (columnas originales + features).

        Returns:
            CaseEvaluation con decisión, señales y checklist completo.
        """
        resultados = [self.evaluar_regla(r, row) for r in self.rules]

        disparadas = [r for r in resultados if r.se_disparo]

        # 1. ESCALAR_FORZOSO
        forzadas = [r for r in disparadas if r.tipo_regla == "ESCALAR_FORZOSO"]
        if forzadas:
            return CaseEvaluation(
                decision="ESCALAR",
                signals=[f"{r.regla_id}: {r.nombre}" for r in forzadas],
                rule_results=resultados,
            )

        # 2. RECHAZAR
        rechazos = [r for r in disparadas if r.tipo_regla == "RECHAZAR"]
        if rechazos:
            return CaseEvaluation(
                decision="RECHAZAR",
                signals=[f"{r.regla_id}: {r.nombre}" for r in rechazos],
                rule_results=resultados,
            )

        # 3. APROBAR
        aprobaciones = [r for r in disparadas if r.tipo_regla == "APROBAR"]
        if aprobaciones:
            return CaseEvaluation(
                decision="APROBAR",
                signals=[f"{r.regla_id}: {r.nombre}" for r in aprobaciones],
                rule_results=resultados,
            )

        # 4. Ambiguo
        return CaseEvaluation(
            decision="AMBIGUO",
            signals=["ambiguo: requiere análisis LLM"],
            rule_results=resultados,
        )
