# AGENTS.md — Mapa de navegación para agentes

> Este archivo es el **punto de entrada** para cualquier agente que trabaje en este
> repositorio. NO es una biblia de reglas: es un **mapa**. Lee solo lo que
> necesites cuando lo necesites (divulgación progresiva).

**Proyecto:** Agente de decisión para casos de posible fraude en compensaciones CX (Rappi — Caso 03).

---

## 1. Antes de empezar (obligatorio)

1. Ejecuta `./init.sh` y verifica que termina sin errores. Si falla, **para**
   y resuelve el entorno antes de tocar código.
2. Lee `.harness/current.md` para entender en qué estado quedó la última sesión.
3. Lee `feature_list.json` y elige **un** step con estado `pending` cuyas
   dependencias estén en `done`. No trabajes en más de uno a la vez.
4. Marca el step como `in_progress` en `.harness/current.md` antes de empezar.

## 2. Mapa del repositorio

| Archivo / carpeta | Qué contiene | Cuándo leerlo |
| :--- | :--- | :--- |
| `feature_list.json` | 8 steps con estado y dependencias | Siempre, al empezar |
| `.harness/current.md` | Agente activo + step en progreso | Siempre, al empezar |
| `.harness/history.md` | Bitácora append-only de sesiones | Si necesitas contexto histórico |
| `.harness/steps/*.md` | Criterios de aceptación por step | Antes de ejecutar un step |
| `.harness/objetivo_case3.md` | Descripción del challenge (Rappi) | Para entender el problema |
| `docs/architecture.md` | Arquitectura del sistema (3-tier + LangGraph) | Antes de implementar |
| `docs/conventions.md` | Reglas de estilo: Python 3.12, type hints, docstrings | Antes de escribir código |
| `docs/verification.md` | Cómo verificar cada step | Antes de declarar `done` |
| `CHECKPOINTS.md` | Criterios objetivos de "estado final correcto" | Para auto-evaluarte |
| `data/Dataset_caso_3.xlsx` | Dataset (pestaña `Caso3_Compensaciones`, 150 casos) | Steps 01, 04, 05 |
| `.opencode/agents/` | Definiciones de los 6 subagentes | Si orquestas trabajo |

## 3. Agentes disponibles

| Agente | Steps | Rol |
| :--- | :--- | :--- |
| `@data-engine` | 01, 02, 03 | EDA, feature engineering, reglas heurísticas |
| `@infrastructure` | 04 | Docker + PostgreSQL + seeds |
| `@synthetic-generator` | 05 | Datos sintéticos validados estadísticamente |
| `@pipeline-api` | 06, 07 | LangGraph + FastAPI |
| `@streamlit-ui` | 08 | UI para agentes CS |
| `@tester` | 09 | Testing E2E (Playwright + pytest) |
| `@reviewer` | transversal | Revisión de calidad → `log_review/` |

## 4. Dependencias entre steps

```
01-eda ──┬── 02-features ── 03-reglas ──┐
         │                              ├── 06-pipeline ── 06b-motor ── 07-api ── 08-ui ── 09-testing
         └── 05-synthetic ──────────────┘
04-infra (paralelo, sin dependencias)
```

`04-infra` y `05-synthetic` pueden ejecutarse en paralelo con la cadena 01→03.

## 5. Al terminar un step

1. Ejecuta `./init.sh` → debe dar todo `[OK]` (o `[SKIP]` donde aplique).
2. Ejecuta la verificación específica del step (`docs/verification.md`).
3. Añade entrada en `.harness/history.md` con: agente, step, archivos tocados, verificación.
4. Cambia el estado del step a `done` en `feature_list.json`.
5. Limpia `.harness/current.md` (volver a `idle`).

## 6. Decisiones de negocio clave

- **No se entrena modelo ML:** el dataset es pequeño (150 casos). Se usan reglas heurísticas + LLM para texto libre.
- **ESCALAR no es un default:** solo se escala cuando hay ambigüedad real. El caso ambiguo es lo que más se evalúa.
- **Reglas gestionadas por fraude en DB:** desde el step 06b, las reglas viven en
  `configuracion_reglas`/`reglas_versiones` (versionadas, editables sin código).
  `src/rules/thresholds.yaml` queda solo como seed de bootstrap para entornos nuevos
  (`python -m src.rules.seed_reglas`). Nunca hardcodear thresholds en la lógica.
