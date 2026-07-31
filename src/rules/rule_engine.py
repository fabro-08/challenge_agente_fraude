"""Motor de reglas heurísticas para detección de fraude en compensaciones.

Evalúa cada caso de compensación y emite una de tres decisiones:

- ``APROBAR``: el reclamo es consistente, no hay señales de fraude.
- ``RECHAZAR``: hay señales claras de fraude o inconsistencia.
- ``ESCALAR``: el caso es ambiguo, requiere revisión humana.

Las reglas se aplican en orden de precedencia:
1. ESCALAR forzoso (seguridad de marca → ``flag_palabras_criticas``)
2. RECHAZAR (cualquier regla de rechazo dispara)
3. APROBAR (todas las condiciones deben cumplirse)
4. resto → ESCALAR
"""

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds.yaml"
MOTIVOS_RETRASO = ["Orden llegó tarde", "Producto en mal estado"]

T = dict[str, Any]


def _cargar_thresholds(path: Path | None = None) -> T:
    """Carga los umbrales desde ``thresholds.yaml``.

    Args:
        path: Ruta al archivo YAML. Por defecto ``src/rules/thresholds.yaml``.

    Returns:
        Diccionario con las reglas y sus umbrales.

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    path = path or THRESHOLDS_PATH
    with open(path) as f:
        return yaml.safe_load(f)


class RuleEngine:
    """Motor de reglas de decisión.

    Args:
        thresholds: Dict con las reglas. Si es ``None``, carga de ``thresholds.yaml``.
    """

    def __init__(self, thresholds: T | None = None):
        self.t = thresholds or _cargar_thresholds()

    # ── RECHAZAR ──────────────────────────────────────────────────────

    def _rechazar_row(self, row: dict) -> tuple[bool, list[str]]:
        """Evalúa si un caso individual debe ser rechazado.

        Args:
            row: Diccionario con las columnas del caso (incluyendo features).

        Returns:
            Tupla (rechazar, señales_que_dispararon).
        """
        r = self.t["rechazar"]
        senales: list[str] = []

        if row.get("flags_fraude_previos", 0) >= r["flags_minimos"]["valor"]:
            senales.append(f"flags_fraude_previos >= {r['flags_minimos']['valor']}")

        if row.get("comp_ratio", 0) > r["comp_ratio_maximo"]["valor"]:
            senales.append(f"comp_ratio > {r['comp_ratio_maximo']['valor']}")

        if row.get("freq_densidad", 0) > r["freq_densidad_maximo"]["valor"]:
            senales.append(f"freq_densidad > {r['freq_densidad_maximo']['valor']}")

        if row.get("compensacion_solicitada_mxn", 0) > r["compensacion_p99"]["valor"]:
            senales.append(f"compensacion > p99 ({r['compensacion_p99']['valor']})")

        if bool(row.get("flag_inconsistencia_gps", False)):
            senales.append("flag_inconsistencia_gps")

        if bool(row.get("flag_account_abuse", False)):
            senales.append("flag_account_abuse")

        if row.get("score_riesgo_previo", 0) > r["score_riesgo_previo_maximo"]["valor"]:
            senales.append(f"score_riesgo_previo > {r['score_riesgo_previo_maximo']['valor']}")

        return len(senales) > 0, senales

    def rechazar(self, df: pd.DataFrame) -> pd.Series:
        """Devuelve una máscara booleana con los casos que deben RECHAZARSE.

        Args:
            df: DataFrame con columnas originales + features.

        Returns:
            Serie booleana: True = RECHAZAR.
        """
        return df.apply(lambda r: self._rechazar_row(r.to_dict())[0], axis=1)

    # ── APROBAR ───────────────────────────────────────────────────────

    def _aprobar_row(self, row: dict) -> tuple[bool, list[str]]:
        """Evalúa si un caso individual debe ser aprobado.

        NOTA: solo debe llamarse si ``_rechazar_row()`` ya dió False.

        Args:
            row: Diccionario del caso.

        Returns:
            Tupla (aprobar, señales).
        """
        a = self.t["aprobar"]
        senales: list[str] = []

        # Regla 1: retraso crítico con motivo coherente
        if bool(row.get("flag_retraso_critico", False)):
            if row.get("motivo_reclamo") in a["retraso_critico_con_motivo"]["motivos_elegibles"]:
                senales.append("flag_retraso_critico + motivo coherente")
                return True, senales

        # Regla 2: usuario sano
        c = a["usuario_sano"]["condiciones"]
        if (
            row.get("flags_fraude_previos", 0) <= c["flags_max"]
            and row.get("comp_ratio", 1) <= c["comp_ratio_max"]
            and row.get("entrega_confirmada_gps") == "SÍ - confirmada"
            and row.get("num_compensaciones_90d", 99) <= c["comps_90d_max"]
            and row.get("antiguedad_usuario_dias", 0) >= c["antiguedad_min"]
        ):
            senales.append("usuario_sano")
            return True, senales

        # Regla 3: GPS ok + sin retraso + ratio normal + antiguo
        c2 = a["gps_ok_sano"]["condiciones"]
        if (
            row.get("entrega_confirmada_gps") == "SÍ - confirmada"
            and not bool(row.get("flag_retraso_critico", False))
            and row.get("comp_ratio", 1) <= c2["comp_ratio_max"]
            and row.get("antiguedad_usuario_dias", 0) >= c2["antiguedad_min"]
        ):
            senales.append("gps_ok_sano")
            return True, senales

        return False, senales

    def aprobar(self, df: pd.DataFrame) -> pd.Series:
        """Devuelve una máscara booleana con los casos que deben APROBARSE.

        Args:
            df: DataFrame con columnas originales + features.

        Returns:
            Serie booleana: True = APROBAR.
        """
        return df.apply(lambda r: self._aprobar_row(r.to_dict())[0], axis=1)

    # ── ESCALAR forzoso ───────────────────────────────────────────────

    def _escalar_forzoso_row(self, row: dict) -> tuple[bool, list[str]]:
        """Evalúa si el caso debe ESCALARSE por seguridad de marca.

        Args:
            row: Diccionario del caso.

        Returns:
            Tupla (escalar, señales).
        """
        if bool(row.get("flag_palabras_criticas", False)):
            return True, ["flag_palabras_criticas: seguridad de marca"]
        return False, []

    def escalar_forzoso(self, df: pd.DataFrame) -> pd.Series:
        """Devuelve una máscara booleana con casos que deben ESCALARSE.

        Args:
            df: DataFrame del dataset.

        Returns:
            Serie booleana: True = ESCALAR forzoso.
        """
        return df.apply(lambda r: self._escalar_forzoso_row(r.to_dict())[0], axis=1)

    # ── Decisión completa ─────────────────────────────────────────────

    def decide(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aplica todas las reglas y añade columnas de decisión al DataFrame.

        Orden de precedencia:
        1. ESCALAR forzoso (seguridad de marca)
        2. RECHAZAR (cualquier regla de rechazo)
        3. APROBAR (todas las condiciones deben cumplirse)
        4. resto → ESCALAR

        Args:
            df: DataFrame con columnas originales + features.

        Returns:
            DataFrame con las columnas adicionales:
            - ``recomendacion``: APROBAR / RECHAZAR / ESCALAR
            - ``senales_usadas``: lista de señales que dispararon
            - ``justificacion``: texto explicativo
        """
        df = df.copy()
        recomendaciones: list[str] = []
        todas_senales: list[str] = []
        justificaciones: list[str] = []

        for _, row in df.iterrows():
            r = row.to_dict()

            # 1. ESCALAR forzoso
            es, sen_es = self._escalar_forzoso_row(r)
            if es:
                recomendaciones.append("ESCALAR")
                todas_senales.append(" | ".join(sen_es))
                justificaciones.append(
                    "ESCALAR por seguridad de marca: el reclamo contiene "
                    "palabras críticas que requieren revisión humana."
                )
                continue

            # 2. RECHAZAR
            rej, sen_re = self._rechazar_row(r)
            if rej:
                recomendaciones.append("RECHAZAR")
                todas_senales.append(" | ".join(sen_re))
                justificaciones.append(
                    f"RECHAZAR por señales de fraude: {'; '.join(sen_re)}."
                )
                continue

            # 3. APROBAR
            apr, sen_ap = self._aprobar_row(r)
            if apr:
                recomendaciones.append("APROBAR")
                todas_senales.append(" | ".join(sen_ap))
                justificaciones.append(
                    f"APROBAR: caso consistente ({'; '.join(sen_ap)})."
                )
                continue

            # 4. resto → ESCALAR
            recomendaciones.append("ESCALAR")
            todas_senales.append("ambiguo: requiere análisis LLM")
            justificaciones.append(
                "ESCALAR por ambigüedad: las reglas no encuentran señales "
                "claras ni de fraude ni de legitimidad. "
                "Requiere análisis del texto del reclamo por LLM."
            )

        df["recomendacion"] = recomendaciones
        df["senales_usadas"] = todas_senales
        df["justificacion"] = justificaciones
        return df

    def explain(self, row: dict) -> str:
        """Genera una justificación textual legible para un caso.

        Args:
            row: Diccionario del caso (incluyendo features).

        Returns:
            Texto explicativo de la decisión.
        """
        df = pd.DataFrame([row])
        result = self.decide(df)
        return result.iloc[0]["justificacion"]
