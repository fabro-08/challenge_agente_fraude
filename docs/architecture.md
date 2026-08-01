# Arquitectura

> Visión general del sistema de automatización de revisión de compensaciones.
> Leer ANTES de implementar cualquier step.

---

## Problema

Rappi Trust & Safety recibe 200+ solicitudes de compensación/día marcadas como potencialmente fraudulentas. Hoy un agente CS revisa cada caso manualmente (15-25 min/caso). El agente automatiza esa revisión emitiendo: **APROBAR**, **RECHAZAR** o **ESCALAR** (casos ambiguos → revisión humana).

## Dataset de entrada

- **Archivo:** `data/Dataset_caso_3.xlsx`
- **Pestaña:** `Caso3_Compensaciones`
- **Registros:** 150 casos
- **Columnas:** user_id, antigüedad (días), ciudad, vertical, restaurante, valor de orden, monto compensación, compensaciones en 90d, monto total compensado 90d, confirmación GPS, tiempo de entrega real, flags de fraude previos, descripción del reclamo.
- **Nota:** el campo `recomendacion_agente` viene vacío — el agente lo llena.

## Diagrama de componentes

```
                        ┌─────────────────────────────┐
                        │  Agente CS (humano)         │
                        └──────────────┬──────────────┘
                                       │ HTTP :8501
                        ┌──────────────▼──────────────┐
                         │  Streamlit UI               │  infra/ui/
                         │  - Dashboard KPIs           │
                         │  - Explorador de casos      │
                         │  - Detalle + override       │
                         │  - Configuración de reglas  │
                         └──────────────┬──────────────┘
                                        │ HTTP :8000
                         ┌──────────────▼──────────────┐
                         │  FastAPI                    │  src/api/
                         │  POST /analyze              │
                         │  POST /analyze/batch        │
                         │  GET  /cases, /stats        │
                         │  CRUD /rules + /simulate    │
                         └──────────────┬──────────────┘
                                        │
                         ┌──────────────▼──────────────┐
                         │  LangGraph Pipeline         │  src/pipeline/
                         │  load_case → features       │
                         │  → rules → llm → decision   │
                         └──────────────┬──────────────┘
                                        │ SQL :5432
                         ┌──────────────▼──────────────┐
                         │  PostgreSQL 16              │  infra/db/
                         │  tabla: cases (crudo)       │
                         │  features (calculado)       │
                         │  resolution_case (resultados)│
                         │  configuracion_reglas       │
                         │  reglas_versiones           │
                         └─────────────────────────────┘

            ┌─────────────────────────────────────────┐
            │  Testing (Playwright + pytest)           │  tests/
            │  - Unitarios (RuleEngine)                │
            │  - Integración (API + Motor genérico)    │
            │  - E2E Browser (UI Streamlit)            │
            │  - Performance                           │
            └─────────────────────────────────────────┘
```

## Flujo de decisión (LangGraph)

```
load_case
   │
compute_features      ← FeatureEngineer (src/features/)
   │
apply_rules           ← motor genérico (src/rules/, reglas versionadas en DB)
   │
   ├─── regla RECHAZAR dispara ──► final_decision: RECHAZAR
   │
   ├─── regla APROBAR dispara ───► final_decision: APROBAR
   │
   ├─── ESCALAR forzoso (palabras críticas) ──► final_decision: ESCALAR
   │
   └─── ninguna regla concluyente
            │
       llm_classify   ← análisis de descripcion_reclamo con LLM
            │
       final_decision ──► veredicto LLM claro → APROBAR | RECHAZAR
                          veredicto ambiguo   → ESCALAR
```

> Decisión discreta y determinista por jerarquía de reglas (no score continuo).
> El LLM solo interviene en casos ambiguos y su veredicto estructurado queda en
> `analisis_casos.llm_resultado`.

## Reglas heurísticas (resumen — detalle en step 03)

| Regla | Condición | Decisión |
|---|---|---|
| R1 | flags_fraude_previos >= 2 | RECHAZAR |
| R2 | comp_ratio > 2.0 | RECHAZAR |
| R3 | frecuencia de reclamos > p95 | RECHAZAR |
| R4 | sin confirmación GPS + entrega demorada | RECHAZAR |
| R5 | monto compensación > p99 | RECHAZAR |
| R6 | flags=0 + comp_ratio < 0.8 + GPS ok + < 2 reclamos | APROBAR |
| R7 | GPS ok + entrega no demorada + comp_ratio < 1.0 + antigüedad > 90d | APROBAR |
| — | resto | ESCALAR (con LLM para texto) |

## Infraestructura Docker

| Servicio | Imagen | Puerto | Rol |
|---|---|---|---|
| `db` | postgres:16 | 5432 | Persistencia (volúmen `pgdata`) |
| `api` | python:3.12 | 8000 | FastAPI + LangGraph |
| `ui` | python:3.12 | 8501 | Streamlit |

## Escalamiento

- **200+ casos/día:** el pipeline es stateless; `/analyze/batch` procesa en lote
  y es parametrizable (`limite`, `es_sintetico`, `solo_pendientes`).
- **Datos sintéticos:** 100 casos generados por muestreo empírico + jitter
  gaussiano y descripciones con LLM (notebook `05_synthetic.ipynb`), validados con
  KS-test y chi-cuadrado, marcados con `es_sintetico=TRUE`.
- **Reglas en DB (step 06b):** la configuración de reglas vive en
  `configuracion_reglas` + `reglas_versiones` (versionado con autoría y descripción
  del cambio). El equipo de fraude edita thresholds, activa/desactiva o crea reglas
  desde la UI sin tocar código. Todos los resultados por caso se consolidan en
  `resolution_case` con el contrato separado por origen: `decision_regla`
  (APROBAR/RECHAZAR/AMBIGUO/ESCALAR), `decision_llm` (veredicto discreto),
  `justificacion_regla`/`justificacion_llm` y `senales_regla`/`senales_llm`
  (formato `campo operador umbral = valor_real`), más el checklist por regla en
  `reglas_checklist` JSONB y el análisis LLM crudo, anclado a la versión exacta de
  la regla que procesó el caso.
  `src/rules/thresholds.yaml` sobrevive solo como seed de bootstrap
  (`python -m src.rules.seed_reglas`).
