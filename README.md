# Agente de Decisión — Compensaciones CX (Rappi · Caso 03)

Agente que automatiza la revisión de casos de **posible fraude en compensaciones**.
Para cada caso emite una recomendación **APROBAR**, **RECHAZAR** o **ESCALAR**
con justificación y las señales usadas, para que un agente CS decida en segundos
en lugar de 15-25 minutos.

> El caso más interesante no es el fraude obvio ni el legítimo obvio, es el
> **ambiguo**. El sistema no fuerza una decisión binaria: escala con criterio.

---

## Índice — Dónde encontrar cada cosa

| Necesito | Dónde |
|---|---|
| Entender la solución y arrancar | `README.md` (abajo: Quickstart) |
| Criterios de decisión (qué y por qué) | `docs/politicas_decision.md` |
| Cambiar / crear reglas (cómo) | `docs/reglas_operacion.md` |
| Arquitectura y flujo del agente | `docs/architecture.md` |
| Variables y features del dataset | `docs/diccionario_datos.md` |
| Análisis exploratorio del dataset (EDA) | `docs/reporte_eda.md` |
| Cómo verificar cada step | `docs/verification.md` |
| Convenciones de código | `docs/conventions.md` |
| Auto-evaluación del estado final | `CHECKPOINTS.md` |
| Mapa interno de navegación (agentes) | `AGENTS.md` |

---

## Resumen de la solución

| Componente | Qué hace |
|---|---|
| **Pipeline LangGraph** | `load_case → features → reglas → LLM → decisión final` |
| **Motor de reglas (YAML)** | 11 reglas en `src/rules/thresholds.yaml` (RuleEngine), usadas por el flujo del agente |
| **LLM estructurado** | Analiza la descripción del reclamo en casos ambiguos y emite veredicto + señales explicadas |
| **API REST (FastAPI)** | `/analyze`, `/analyze/batch`, `/cases`, `/stats`, `/export/*` |
| **UI (Streamlit)** | Dashboard de KPIs, explorador de casos por origen, políticas, documentación, descarga de entregables |
| **PostgreSQL 16** | 150 casos originales + 100 sintéticos, todos analizados con decisión, justificación y señales |

**Resultado sobre los 250 casos:** APROBAR 73 · RECHAZAR 117 · ESCALAR 60.
Sobre los **150 casos originales**: APROBAR 51 · RECHAZAR 68 · ESCALAR 31
(ver `data/150casos_analizados.xlsx`).

> La distribución exacta puede variar con reprocesos (el batch re-analyza casos).
> Estas cifras corresponden al estado actual de `resolution_case`.

**Stack:** Python 3.12 · LangGraph · FastAPI · Streamlit · PostgreSQL 16 · Docker ·
Playwright/pytest (55 passed).

---

## Decisiones de negocio clave

1. **Sin modelo ML:** el dataset es pequeño (150 casos). Se usan **reglas heurísticas**
   (documentadas en `docs/politicas_decision.md`) + **LLM para texto libre** en casos
   ambiguos y en escalados forzosos (aportando análisis, sin poder cambiar la decisión).
2. **ESCALAR no es un default:** solo se escala cuando hay ambigüedad real; el escalado
   forzoso (palabras críticas de marca) es una decisión explícita de seguridad que pasa
   por el LLM pero conserva `fuente='reglas'`.
3. **Reglas desde thresholds.yaml:** el flujo del agente usa el motor `RuleEngine`
   con umbrales en `src/rules/thresholds.yaml` (documentado en
   `docs/politicas_decision.md`). No hay reglas gestionadas en base de datos.

4. **Cómo cambiar/crear reglas:** guía operativa paso a paso en
   `docs/reglas_operacion.md` (umbrales, condiciones, palabras críticas, reproceso).
5. **No se escribe en `recomendacion_agente`:** el `Dataset_caso_3.xlsx` original
   se mantiene **read-only**; la decisión vive en `resolution_case` y se entrega en
   el Excel derivado `data/150casos_analizados.xlsx` (columna `recomendacion`).

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
                  load_case → features → apply_rules
                         │                     │
                         │  regla APROBAR ──────┴──► decision: APROBAR
                         │  regla RECHAZAR ─────────► decision: RECHAZAR
                         │  ESCALAR forzoso ─────────► decision: ESCALAR (fuente=reglas)
                         │  AMBIGUO ──► llm_classify ──► decision: APROBAR|RECHAZAR|ESCALAR (fuente=llm)
                                        │  SQL :5432
                                        ▼
                               PostgreSQL 16 (infra/db/)
                     cases · features · resolution_case
```

Flujo de decisión: reglas **RECHAZAR** primero (prevenir fraude), luego **APROBAR**
(no penalizar legítimos). Lo que queda **AMBIGUO** lo decide el LLM; un **ESCALAR
forzoso** (palabras críticas) pasa por el LLM solo para aportar análisis, pero la
decisión final queda en `ESCALAR` con `fuente='reglas'`. Detalle en
`docs/architecture.md` y `docs/politicas_decision.md`.

---

## Quickstart

Requisitos: Docker + Docker Compose v2, Python ≥ 3.12.

```bash
# 1. Levanta DB + API + UI (seed automático: 250 casos analizados)
make up

# 2. Verifica el entorno (lint, typecheck, tests, healthchecks)
./init.sh
```

Accesos:

- UI Streamlit: http://localhost:8501
- API FastAPI: http://localhost:8000 (docs en http://localhost:8000/docs)
- PostgreSQL: `make psql`

> `docker compose up` en un volumen nuevo inicializa la base con el estado final
> (`infra/db/init/09_seed_completo.sql`): los 250 casos ya analizados. Las reglas
> viven en `src/rules/thresholds.yaml` (no en DB). No requiere corridas previas del pipeline.

### Verificación completa

```bash
./init.sh                 # todos los bloques [OK]
pytest tests/ -q          # 55 passed
```

---

## Desplegar agente (otra máquina)

Pasos para levantar el agente completo en una máquina limpia con solo Docker
(para que lo prueben otros).

**Requisitos:** Docker + Docker Compose v2. No hace falta Python en la máquina.

```bash
# 1. Obtener el código
git clone <url-del-repo> && cd case3_project

# 2. Crear credenciales del LLM (obligatorio: no están en el repo)
cp .env.example .env        # completar OPENROUTER_API_KEY=sk-or-v1-...
#   Sin key la UI y los casos ya sembrados cargan, pero el re-análisis LLM degrada.

# 3. Levantar los 3 servicios (db + api + ui)
make up                     # docker compose -f infra/docker-compose.yml up -d --wait
#   En un volumen nuevo, PostgreSQL ejecuta infra/db/init/*.sql en orden y
#   siembra automáticamente los 250 casos ya analizados (sin pasos extra).

# 4. Abrir la UI
#   http://localhost:8501

# 5. (Opcional) Verificar la base
make psql                   # select count(*) from resolution_case; → 250
```

Notas:

- La **API es interna** (`api:8000`, sin puerto mapeado al host): la UI se comunica
  con ella dentro de Docker. Para exponerla al host, agregar `ports: ["8000:8000"]`
  al servicio `api` en `infra/docker-compose.yml`.
- `./init.sh` y `pytest` necesitan un entorno Python local (`.venv`) con las
  dependencias del repo; **no son necesarios** para correr el agente por Docker.
- La documentación (página "Documentación" de la UI) y el reporte EDA se sirven
  desde `docs/` vía volumen `:ro`.
- Para reiniciar con base limpia: `docker compose -f infra/docker-compose.yml down -v`
  (borra el volumen `pgdata` y vuelve a ejecutar el seed al levantar).

---

## Export de entregables (API)

| Endpoint | Devuelve |
|---|---|
| `GET /export/excel?es_sintetico=false` (default) | Excel de los **150 casos originales** (bytes, descarga) |
| `GET /export/excel?es_sintetico=true` | Excel de los **250 casos** (originales + sintéticos) |
| `GET /export/politicas` | `docs/politicas_decision.md` descargable |
| `GET /jobs/{id}/excel` | Excel del batch demo (modo memoria) |

Los Excel se generan en memoria y se sirven como descarga; el servidor no escribe
archivos. Desde la UI están en la sección **"Entregables"** del Dashboard, y la
notebook `06_pipeline.ipynb` los regenera vía API.

```bash
curl -s http://localhost:8000/export/excel -o data/150casos_analizados.xlsx
curl -s "http://localhost:8000/export/excel?es_sintetico=true" -o data/250casos_analizados.xlsx
```

---

## Scripts de operación (CLI)

Los scripts en `scripts/` son entrypoints de terminal que **reutilizan la misma
lógica de `src/`** que la API (no hay código duplicado). Sirven para operar sin
tener FastAPI corriendo.

| Script | Qué hace | Comando |
|---|---|---|
| `run_batch.py` | Procesa casos con el pipeline (mismo worker que `POST /analyze/batch`) y persiste en `resolution_case` con auditoría (`batch_run_id`) | `python scripts/run_batch.py [--sintetico\|--pendientes\|--todos] [--limite N] [--case-ids COMP-0009 ...]` · `--demo` no escribe en `resolution_case` |
| `export_casos_analizados.py` | Genera `data/150casos_analizados.xlsx` (igual que `GET /export/excel`) | `python scripts/export_casos_analizados.py [--output data/150casos_analizados.xlsx]` |
| `backfill_features.py` | Rellena huecos de la tabla `features` (casos sin fila) con cálculo determinista. No toca `cases` ni `resolution_case` | `python scripts/backfill_features.py` |

Nota: las **features** las calcula el propio pipeline (`compute_features`) al
procesar; `backfill_features.py` solo es un respaldo sanitizador (migración 3-capas).

---

## Entregables

| Entregable | Ubicación |
|---|---|
| 150 casos con recomendación + justificación + señales | `data/150casos_analizados.xlsx` (regenerable con `python scripts/export_casos_analizados.py` o `GET /export/excel`) |
| Políticas de decisión (criterios y manejo de ambigüedad) | `docs/politicas_decision.md` (descargable desde la UI / `GET /export/politicas`) |
| Notebooks EDA / features / reglas / pipeline / sintéticos | `notebooks/` |
| Arquitectura | `docs/architecture.md` |
| Diccionario de datos | `docs/diccionario_datos.md` |
| Tests y reportes | `tests/` · `log_review/` |

---

## Qué dejaría diferente con más tiempo

- **Modelo de scoring / micro-ML:** con solo 150 casos el dataset no alcanza para
  entrenar un modelo sólido, así que opté por reglas heurísticas + LLM. Con más
  histórico, sumaría un score supervisado calibrado contra las decisiones reales.
- **Conexión entre casos (fraude organizado):** hoy el agente analiza cada solicitud
  de forma aislada. Con un `user360` y relaciones entre pedidos/users detectaría
  redes de fraude que a nivel individual no se ven.
- **Calibración continua:** falta un circuito de feedback del agente CS sobre las
  decisiones (¿fue correcta la APROBAR/RECHAZAR?) como ground truth para ajustar
  umbrales y veredictos del LLM con el tiempo.
- **Prueba de carga explícita a 200+/día:** el batch es durable y concurrente, pero
  validaría formalmente throughput y latencia bajo la demanda real del contexto.
- **Versionado y CI/CD de umbrales:** gestionar `thresholds.yaml` con versionado y
  despliegue para auditar qué reglas produjeron cada decisión histórica.

---

## Estructura del repositorio

```
case3_project/
├── init.sh                → verificación de entorno (lint, tests, healthchecks)
├── Makefile               → up / down / psql / seed
├── CHECKPOINTS.md         → criterios objetivos del estado final
├── data/                  → dataset original, sintéticos y output analizado
├── docs/                  → arquitectura, políticas, diccionario, reporte EDA, convenciones
├── notebooks/             → 01-EDA · 02-features · 03-reglas · 05-synthetic · 06-pipeline
├── src/
│   ├── api/               → FastAPI (routers, schemas, services)
│   ├── batch/             → worker del batch durable (repository, rows)
│   ├── config/            → config del modelo LLM (model.yaml, settings)
│   ├── pipeline/          → LangGraph (state, graph, nodes, circuit breaker LLM)
│   ├── rules/             → RuleEngine (thresholds.yaml), señales canónicas
│   └── ui/                → Streamlit (dashboard, casos, políticas, documentación)
├── scripts/               → utilidades (export Excel, run_batch)
├── tests/                 → unitarios + integración + E2E Playwright
├── infra/
│   ├── docker-compose.yml → db + api + ui
│   ├── db/init/           → esquema + seed reproducible
│   └── db/migrations_legacy/ → migraciones históricas (no aplican en bootstrap)
└── log_review/            → reportes de tests y screenshots E2E
```

---

## Testing

- **55 passed:** RuleEngine (YAML) + contrato de salida + API (incluye export y batch durable) + E2E Playwright (sin motor de reglas en DB).
- Reporte HTML en `log_review/test_report.html` y Markdown en `log_review/test_e2e_*.md`.
- Screenshots de cada pantalla en `log_review/`.

```bash
pytest tests/ --html=log_review/test_report.html --self-contained-html
```
