#!/usr/bin/env python3
"""Exporta los 150 casos originales analizados a un Excel entregable.

Genera ``data/150casos_analizados.xlsx`` delegando en la lógica de la API
(``services.generar_excel_bytes``) para tener una única fuente de verdad
con el endpoint ``GET /export/excel``.

Uso:
    python scripts/export_casos_analizados.py [--output data/150casos_analizados.xlsx]
"""

import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import services


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/150casos_analizados.xlsx")
    args = parser.parse_args()

    excel = services.generar_excel_bytes(es_sintetico=False)

    output = args.output
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "wb") as fh:
        fh.write(excel)

    df = pd.read_excel(io.BytesIO(excel))
    print(f"Exportadas {len(df)} filas → {output}")
    print(df["recomendacion"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
