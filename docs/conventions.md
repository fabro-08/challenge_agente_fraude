# Convenciones de código

> Reglas de estilo obligatorias para todo el código del proyecto.
> Cualquier agente que escriba código DEBE seguir estas convenciones.

---

## Python

- **Versión:** Python 3.12 (verificado por `init.sh`)
- **Type hints:** obligatorios en TODAS las funciones públicas (PEP 484)
- **Docstrings:** en español, formato Google style
- **Indentación:** 4 espacios
- **Largo de línea:** máximo 88 caracteres (Black)
- **Naming:**
  - `snake_case` → variables, funciones, módulos
  - `PascalCase` → clases
  - `UPPER_SNAKE` → constantes

## Imports

Orden obligatorio (enforzado por isort):

```python
# 1. stdlib
import os
from datetime import datetime

# 2. third-party
import pandas as pd
import numpy as np

# 3. locales
from src.features.feature_builder import FeatureEngineer
```

## Docstrings (ejemplo)

```python
def calcular_comp_ratio(monto_compensacion: float, valor_orden: float) -> float:
    """Calcula el ratio entre compensación solicitada y valor de la orden.

    Args:
        monto_compensacion: Monto solicitado como compensación.
        valor_orden: Valor original de la orden.

    Returns:
        Ratio compensación/orden. Retorna 0.0 si valor_orden es 0.
    """
    ...
```

## Estructura del repositorio

```
case3_project/
├── AGENTS.md            → mapa de navegación para agentes
├── init.sh              → hook de verificación de entorno
├── CHECKPOINTS.md       → criterios objetivos de "done"
├── README.md            → guía de arranque y demo
├── data/                → datasets (mantener Dataset original, ignorar generados)
│   └── Dataset_caso_3.xlsx
├── docs/                → documentación del proyecto
├── .harness/            → coordinación interna de agentes (no versionado)
├── notebooks/           → notebooks Jupyter ejecutados (EDA, análisis)
├── scripts/             → utilidades (export de resultados)
├── src/                 → código fuente
│   ├── api/
│   ├── pipeline/
│   ├── rules/
│   └── ui/
├── tests/               → tests (pytest + Playwright E2E)
├── infra/               → Dockerfiles, docker-compose y esquema DB
└── log_review/          → reportes de tests y screenshots
```

## Linting y formato

| Herramienta | Uso | Config |
|---|---|---|
| ruff | linting | `pyproject.toml` |
| isort | ordenar imports | `pyproject.toml` |
| mypy | type checking | modo strict progresivo |
| pytest | tests | `tests/` |

## Git

- Commits en español con prefijos: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- No hacer commits directos sin que `init.sh` pase en verde
