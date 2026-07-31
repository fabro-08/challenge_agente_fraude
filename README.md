# Agente de Decisión — Compensaciones CX (Rappi · Caso 03)

Agente que automatiza la revisión de casos de **posible fraude en compensaciones**.
Para cada caso emite una recomendación **APROBAR**, **RECHAZAR** o **ESCALAR**
con justificación y las señales usadas, para que un agente CS decida en segundos
en lugar de 15-25 minutos.

> El caso más interesante no es el fraude obvio ni el legítimo obvio, es el
> **ambiguo**. El sistema no fuerza una decisión binaria: escala con criterio.

---

## Resumen de la solución

| Componente | Qué hace |
|---|---|
| **Pipeline LangGraph** | `load_case → features → reglas → LLM → decisión final` |
| **Motor de reglas versionado** | 11 reglas gestionadas por fraude en DB (sin código) con historial y simulador |
| **LLM estructurado** | Analiza la descripción del reclamo en casos ambiguos y emite veredicto + señales explicadas |
| **API REST (FastAPI)** | `/analyze`, `/analyze/batch`, `/cases`, `/rules` (CRUD + simulación), `/stats` |
| **UI (Streamlit)** | Dashboard de KPIs, explorador de casos, configuración de reglas, políticas |
| **PostgreSQL 16** | 150 casos originales + 100 sintéticos, todos analizados y con checklist de reglas |

**Resultado sobre los 250 casos:** ESCALAR 132 · RECHAZAR 83 · APROBAR 35.
Sobre los **150 casos originales**: ESCALAR 79 · RECHAZAR 50 · APROBAR 21
(ver `data/150casos_analizados.xlsx`).

**Stack:** Python 3.12 · LangGraph · FastAPI · Streamlit · PostgreSQL 16 · Docker ·
Playwright/pytest (74 tests).

---

## Decisiones de negocio clave

1. **Sin modelo ML:** el dataset es pequeño (150 casos). Se usan **reglas heurísticas**
   (documentadas en `docs/politicas_decision.md`) + **LLM para texto libre** en casos ambiguos.
2. **ESCALAR no es un default:** solo se escala cuando hay ambigüedad real; el escalado
   forzoso (palabras críticas de marca) es una decisión explícita de seguridad.
3. **Reglas versionadas en DB:** fraude edita thresholds desde la UI, cada cambio genera
   nueva versión con autor, y el simulador muestra el impacto antes de guardar.

---

## Arquitectura

```
Agente CS (humano) ── HTTP :8501 ──► Streamlit UI
                                        │  HTTP :8000
                                        ▼
                                  FastAPI (src/api/)
                                        │
                                        ▼
                            LangGraph Pipeline (src/pipeline/)
                        load_case → features → reglas → llm → decision
                                        │  SQL :5432
                                        ▼
                              PostgreSQL 16 (infra/db/)
                    casos · analisis_casos · configuracion_reglas
                    reglas_versiones · resultados_reglas · usuarios_fraude
```

Flujo de decisión: reglas **RECHAZAR** primero (prevenir fraude), luego **APROBAR**
(no penalizar legítimos) y el resto **ESCALAR + LLM**. Detalle en
`docs/architecture.md` y `docs/politicas_decision.md`.

---

## Quickstart

Requisitos: Docker + Docker Compose v2, Python ≥ 3.12.

```bash
# 1. Levanta DB + API + UI (seed automático: 250 casos analizados)
make up

# 2. Verifica el entorno (lint, typecheck, 74 tests, healthchecks)
./init.sh
```

Accesos:

- UI Streamlit: http://localhost:8501
- API FastAPI: http://localhost:8000 (docs en http://localhost:8000/docs)
- PostgreSQL: `make psql`

> `docker compose up` en un volumen nuevo inicializa la base con el estado final
> (`infra/db/init/09_seed_completo.sql`): los 250 casos ya analizados y las 11
> reglas seedeadas. No requiere corridas previas del pipeline.

### Verificación completa

```bash
./init.sh                 # todos los bloques [OK]
pytest tests/ -q          # 74 tests
```

---

## Demo sugerida (en vivo)

El estado precargado permite mostrar la demo sin depender del LLM en tiempo real.

| Paso | Qué mostrar | Caso |
|---|---|---|
| 1 | **Fraude claro** (RECHAZAR) | `COMP-0062` — 4 flags, score 13.5 |
| 2 | **Legítimo** (APROBAR) | `COMP-0078` — 0 flags, ratio 0.59, GPS confirmada |
| 3 | **Ambiguo** (ESCALAR + LLM) | `COMP-0004` — sin señales concluyentes |
| 4 | **Escalado forzoso por marca** | `COMP-0072` — perfil limpio pero palabras críticas |
| 5 | **Re-análisis on-demand** | botón "Re-analizar" en el detalle |
| 6 | **Batch parametrizado** | `POST /analyze/batch {"limite": 5}` → poll `/jobs/{id}` |
| 7 | **Editar regla + simular** | pestaña "Reglas" de la UI (versión + impacto sin guardar) |

Los casos 1-4 ya tienen `llm_resultado` persistido, así que la demo carga al
instante. El re-análisis de un caso ambiguo tarda ~15-24 s (espera del LLM);
el batch corre en background y es parametrizable con `limite`.

```bash
# Batch con límite (ej.: 5 casos)
curl -s -X POST http://localhost:8000/analyze/batch \
  -H "Content-Type: application/json" -d '{"limite": 5}'
# → {"job_id": "...", "total_casos": 5, ...}
curl -s http://localhost:8000/jobs/<job_id>
```

---

## Entregables

| Entregable | Ubicación |
|---|---|
| 150 casos con recomendación + justificación + señales | `data/150casos_analizados.xlsx` (regenerable con `python scripts/export_casos_analizados.py`) |
| Políticas de decisión (criterios y manejo de ambigüedad) | `docs/politicas_decision.md` |
| Notebooks EDA / features / reglas / pipeline / sintéticos | `notebooks/` |
| Arquitectura | `docs/architecture.md` |
| Diccionario de datos | `docs/diccionario_datos.md` |
| Tests y reportes | `tests/` · `log_review/` |

---

## Estructura del repositorio

```
case3_project/
├── init.sh                → verificación de entorno (lint, tests, healthchecks)
├── Makefile               → up / down / psql / seed
├── CHECKPOINTS.md         → criterios objetivos del estado final
├── data/                  → dataset original, sintéticos y output analizado
├── docs/                  → arquitectura, políticas, diccionario, convenciones
├── notebooks/             → 01-EDA · 02-features · 03-reglas · 05-synthetic · 06-pipeline
├── src/
│   ├── api/               → FastAPI (routers, schemas, services)
│   ├── pipeline/          → LangGraph (state, graph, nodes)
│   ├── rules/             → motor genérico, repository, simulador, seed
│   └── ui/                → Streamlit (dashboard, casos, reglas, políticas)
├── scripts/               → utilidades (export Excel)
├── tests/                 → 74 tests (unitarios + integración + E2E Playwright)
├── infra/
│   ├── docker-compose.yml → db + api + ui
│   ├── db/init/           → esquema + seed reproducible
│   └── db/migrations_legacy/ → migraciones históricas (no aplican en bootstrap)
└── log_review/            → reportes de tests y screenshots E2E
```

---

## Testing

- **74 tests:** 8 unitarios (reglas) + 36 motor genérico + 20 API + 10 E2E Playwright.
- Reporte HTML en `log_review/test_report.html` y Markdown en `log_review/test_e2e_*.md`.
- Screenshots de cada pantalla en `log_review/`.

```bash
pytest tests/ --html=log_review/test_report.html --self-contained-html
```
