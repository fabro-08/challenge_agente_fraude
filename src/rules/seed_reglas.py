"""Seed de reglas: migra ``thresholds.yaml`` a ``reglas_versiones`` v1.

El YAML queda como source of truth de bootstrap (entornos nuevos). Una vez
poblada la DB, el pipeline y la API leen exclusivamente de ``configuracion_reglas``.

Mapeo de reglas (paridad con ``docs/politicas_decision.md``):

    RECHAZAR:  R1 flags, R2 comp_ratio, R3 freq_densidad, R4 compensación p99,
               R5 inconsistencia GPS, R6 account abuse, R7 score riesgo previo
    APROBAR:   A1 retraso crítico con motivo, A2 usuario sano, A3 gps ok sano
    ESCALAR:   ESCALAR-1 palabras críticas (lista editable por fraude)

Uso::

    python -m src.rules.seed_reglas
"""

import yaml

from src.rules import repository
from src.rules.rule_engine import THRESHOLDS_PATH

# Stems equivalentes al regex del step 02:
# r'alergi|intoxic|polic[ií]a|sangre|insult|denunci|abogado|demanda|hospital|veneno'
PALABRAS_CRITICAS = [
    "alergi", "intoxic", "policía", "policia", "sangre",
    "insult", "denunci", "abogado", "demanda", "hospital", "veneno",
]

GPS_CONFIRMADA = "SÍ - confirmada"


def construir_seed(thresholds_path: str | None = None) -> list[tuple[str, str, str, int, dict]]:
    """Transforma thresholds.yaml en definiciones declarativas de reglas.

    Returns:
        Lista de (regla_id, nombre, tipo_regla, prioridad, config) lista para
        ``repository.insertar_seed()``.
    """
    with open(thresholds_path or THRESHOLDS_PATH) as f:
        t = yaml.safe_load(f)

    r = t["rechazar"]
    a = t["aprobar"]

    reglas: list[tuple[str, str, str, int, dict]] = []

    # ── ESCALAR_FORZOSO (prioridad 0: se evalúa primero) ─────────────
    reglas.append((
        "ESCALAR-1",
        "Palabras críticas de seguridad de marca",
        "ESCALAR_FORZOSO",
        0,
        {
            "descripcion": t["escalar_forzoso"]["flag_palabras_criticas"]["descripcion"],
            "explicacion": t["escalar_forzoso"]["flag_palabras_criticas"]["explicacion"],
            "match": "all",
            "condiciones": [
                {
                    "campo": "descripcion_reclamo",
                    "operador": "contains_any",
                    "valor": PALABRAS_CRITICAS,
                }
            ],
        },
    ))

    # ── RECHAZAR (R1-R7) ──────────────────────────────────────────────
    rechazos = [
        ("R1", "flags_fraude_previos", ">=", r["flags_minimos"]),
        ("R2", "comp_ratio", ">", r["comp_ratio_maximo"]),
        ("R3", "freq_densidad", ">", r["freq_densidad_maximo"]),
        ("R4", "compensacion_solicitada_mxn", ">", r["compensacion_p99"]),
        ("R5", "flag_inconsistencia_gps", "==", r["flag_inconsistencia_gps"]),
        ("R6", "flag_account_abuse", "==", r["flag_account_abuse"]),
        ("R7", "score_riesgo_previo", ">", r["score_riesgo_previo_maximo"]),
    ]
    for i, (regla_id, campo, operador, cfg) in enumerate(rechazos, start=1):
        reglas.append((
            regla_id,
            f"{campo} {operador} {cfg['valor']}",
            "RECHAZAR",
            i,
            {
                "descripcion": cfg["descripcion"],
                "explicacion": cfg["explicacion"],
                "match": "all",
                "condiciones": [{"campo": campo, "operador": operador, "valor": cfg["valor"]}],
            },
        ))

    # ── APROBAR (A1-A3) ───────────────────────────────────────────────
    a1 = a["retraso_critico_con_motivo"]
    reglas.append((
        "A1",
        "Retraso crítico con motivo coherente",
        "APROBAR",
        1,
        {
            "descripcion": a1["descripcion"],
            "explicacion": a1["explicacion"],
            "match": "all",
            "condiciones": [
                {"campo": "flag_retraso_critico", "operador": "==", "valor": True},
                {"campo": "motivo_reclamo", "operador": "in", "valor": a1["motivos_elegibles"]},
            ],
        },
    ))

    a2 = a["usuario_sano"]["condiciones"]
    reglas.append((
        "A2",
        "Usuario sano (perfil conservador)",
        "APROBAR",
        2,
        {
            "descripcion": a["usuario_sano"]["descripcion"],
            "explicacion": a["usuario_sano"]["explicacion"],
            "match": "all",
            "condiciones": [
                {"campo": "flags_fraude_previos", "operador": "<=", "valor": a2["flags_max"]},
                {"campo": "comp_ratio", "operador": "<=", "valor": a2["comp_ratio_max"]},
                {"campo": "entrega_confirmada_gps", "operador": "==", "valor": GPS_CONFIRMADA},
                {"campo": "num_compensaciones_90d", "operador": "<=", "valor": a2["comps_90d_max"]},
                {"campo": "antiguedad_usuario_dias", "operador": ">=", "valor": a2["antiguedad_min"]},
            ],
        },
    ))

    a3 = a["gps_ok_sano"]["condiciones"]
    reglas.append((
        "A3",
        "GPS confirmada con usuario antiguo",
        "APROBAR",
        3,
        {
            "descripcion": a["gps_ok_sano"]["descripcion"],
            "explicacion": a["gps_ok_sano"]["explicacion"],
            "match": "all",
            "condiciones": [
                {"campo": "entrega_confirmada_gps", "operador": "==", "valor": GPS_CONFIRMADA},
                {"campo": "flag_retraso_critico", "operador": "==", "valor": False},
                {"campo": "comp_ratio", "operador": "<=", "valor": a3["comp_ratio_max"]},
                {"campo": "antiguedad_usuario_dias", "operador": ">=", "valor": a3["antiguedad_min"]},
            ],
        },
    ))

    return reglas


def main() -> None:
    """Ejecuta el seed: inserta las 11 reglas v1 si la tabla está vacía."""
    reglas = construir_seed()
    n = repository.insertar_seed(reglas, updated_by="seed: thresholds.yaml")
    if n:
        print(f"[OK] Seed insertado: {n} reglas v1 en reglas_versiones")
    else:
        print("[SKIP] configuracion_reglas ya tiene reglas, seed no aplicado")


if __name__ == "__main__":
    main()
