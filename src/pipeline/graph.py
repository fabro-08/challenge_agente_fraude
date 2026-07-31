"""Grafo LangGraph del pipeline de decisión de fraude.

Flujo:

    load_case → compute_features → apply_rules
                                        │
                            ┌───────────┼───────────┐
                            ▼           ▼           ▼
                        RECHAZAR    APROBAR     ambiguo
                            │           │           │
                            ▼           ▼     llm_classify
                       final_decision   │           │
                            │           │     final_decision
                            ▼           ▼           │
                       generate_output ◄────────────┘
                            │
                           END
"""

from langgraph.graph import END, StateGraph

from src.pipeline.nodes.apply_rules import apply_rules
from src.pipeline.nodes.compute_features import compute_features
from src.pipeline.nodes.final_decision import final_decision
from src.pipeline.nodes.generate_output import generate_output
from src.pipeline.nodes.llm_classify import llm_classify
from src.pipeline.nodes.load_case import load_case
from src.pipeline.state import CaseState


def _route_after_rules(state: CaseState) -> str:
    """Decide el siguiente nodo tras apply_rules.

    Args:
        state: Estado con ``rule_result``.

    Returns:
        Nombre del siguiente nodo: 'final_decision' o 'llm_classify'.
    """
    if state.get("rule_result") in ("APROBAR", "RECHAZAR"):
        return "final_decision"
    return "llm_classify"


def build_graph() -> StateGraph:
    """Construye y compila el grafo de decisión.

    Returns:
        StateGraph compilado listo para ``invoke()``.
    """
    graph = StateGraph(CaseState)

    # Nodos
    graph.add_node("load_case", load_case)
    graph.add_node("compute_features", compute_features)
    graph.add_node("apply_rules", apply_rules)
    graph.add_node("llm_classify", llm_classify)
    graph.add_node("final_decision", final_decision)
    graph.add_node("generate_output", generate_output)

    # Flujo principal
    graph.set_entry_point("load_case")
    graph.add_edge("load_case", "compute_features")
    graph.add_edge("compute_features", "apply_rules")

    # Condicional: reglas deciden o van al LLM
    graph.add_conditional_edges(
        "apply_rules",
        _route_after_rules,
        {
            "final_decision": "final_decision",
            "llm_classify": "llm_classify",
        },
    )

    # LLM → decisión final
    graph.add_edge("llm_classify", "final_decision")

    # Decisión final → output
    graph.add_edge("final_decision", "generate_output")
    graph.add_edge("generate_output", END)

    return graph.compile()
