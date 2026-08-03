# Verificación por step

> Cómo verificar que cada step está completo ANTES de declararlo `done`.
> Ejecutar siempre `./init.sh` después de cualquier modificación.

---

## Verificación global (obligatoria siempre)

```bash
./init.sh
```

Todos los bloques deben dar `[OK]` (o `[SKIP]` si el servicio aún no aplica).

---

## Verificación específica por step

### Step 01 — EDA

```bash
jupyter nbconvert --to notebook --execute notebooks/01_eda.ipynb
```

- [ ] Notebook ejecuta completo sin errores (0 celdas con error)
- [ ] Cada gráfico renderiza inline con su explicación en markdown
- [ ] Incluye percentiles p50/p90/p95/p99 de variables clave
- [ ] Sección final de conclusiones con señales candidatas para reglas
- [ ] No genera archivos de imagen en disco

### Step 02 — Feature Engineering

```bash
python -c "from src.features.feature_builder import FeatureEngineer; print('import ok')"
```

- [ ] `FeatureEngineer` agrega las 9 columnas derivadas documentadas
- [ ] No introduce NaN en features numéricas críticas (comp_ratio, comps_por_dia)
- [ ] Tests unitarios pasan: `pytest tests/test_features.py`

### Step 03 — Reglas heurísticas

```bash
python -c "from src.rules.rule_engine import RuleEngine; print('import ok')"
```

- [ ] `RuleEngine.decide(df)` clasifica los 150 casos sin NaN en `recomendacion`
- [ ] `thresholds.yaml` existe con todos los umbrales y justificación
- [ ] `docs/politicas_decision.md` documenta cada regla
- [ ] Tests: `pytest tests/test_rules.py`

### Step 04 — Infraestructura

```bash
docker compose -f infra/docker-compose.yml up -d --wait
docker ps
```

- [ ] 3 contenedores running (db, api, ui)
- [ ] Healthcheck de `db` en estado healthy
- [ ] Tabla `casos` existe: `docker exec <db> psql -U rappi -d rappi_cases -c "\dt"`
- [ ] Los 150 casos están seedeados: `SELECT COUNT(*) FROM casos;` → 150

### Step 05 — Datos sintéticos

```bash
jupyter nbconvert --to notebook --execute notebooks/05_synthetic.ipynb
```

- [ ] Genera `data/synthetic_casos.parquet` con 100 casos
- [ ] KS-test p > 0.05 en las variables numéricas; chi-cuadrado p > 0.05 en las categóricas
- [ ] Sintéticos insertados en PostgreSQL con `es_sintetico=TRUE` (100 registros)
- [ ] Restricciones lógicas respetadas (compensación ≤ 3× valor de orden)

### Step 06 — Pipeline LangGraph

```bash
python -c "from src.pipeline.graph import build_graph; print('import ok')"
```

- [ ] El grafo compila sin errores
- [ ] `graph.invoke(case)` retorna: `final_decision`, `decision_regla`/`decision_llm`, `justificacion_regla`/`justificacion_llm`, `senales_regla`/`senales_llm` y checklist de reglas
- [ ] APROBAR/RECHAZAR por reglas NO llaman al LLM; ESCALAR forzado y AMBIGUO sí
- [ ] ESCALAR forzoso (palabras críticas) → `final_decision=ESCALAR` forzado, `decision_regla=ESCALAR`, el LLM solo aporta análisis
- [ ] Señales de reglas con formato `campo operador umbral = valor real` (ej. `flags_fraude_previos >= 2 = 3`)
- [ ] Caso ambiguo → decide el LLM vía `decision_llm` (no fuerza decisión binaria)
 - [ ] Tests: `pytest tests/test_pipeline.py`

### Step 06 — Reglas (thresholds.yaml)

```bash
pytest tests/test_rules.py
```

- [ ] `RuleEngine` clasifica los 250 casos desde `src/rules/thresholds.yaml` (sin DB)
- [ ] El flujo del agente aplica las reglas: APROBAR/RECHAZAR por reglas sin LLM, ESCALAR forzado y AMBIGUO con LLM
- [ ] `senales_regla` y `justificacion_regla` se generan desde `RuleEngine`
- [ ] No existen tablas `configuracion_reglas`/`reglas_versiones`/`usuarios_fraude`

### Step 07 — API

```bash
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/analyze -H "Content-Type: application/json" -d '{...}'
```

- [ ] `GET /health` → 200
- [ ] `POST /analyze` → recomendación + justificación
- [ ] `POST /analyze/batch` → procesa todos los casos de la DB
- [ ] `POST /analyze/batch {"persistir": false}` (modo demo) → corre el pipeline **sin escribir** en `resolution_case` (contar filas antes/después); las filas demo quedan en `batch_run_items.fila_demo`
- [ ] `POST /analyze/batch {"aleatorio": true, "limite": 5}` → muestreo aleatorio
- [ ] `GET /export/excel` → Excel de 150 casos (magic `PK`, 28 columnas, distribución 65/58/27)
- [ ] `GET /export/excel?es_sintetico=true` → Excel de 250 casos
- [ ] `GET /export/politicas` → 200, `text/markdown`, contiene "Políticas"
- [ ] `GET /jobs/{id}/resultados` y `GET /jobs/{id}/excel` → filas y Excel del job demo
- [ ] OpenAPI docs en `http://localhost:8000/docs`

### Batch durable en PostgreSQL (refactor batch)

El proceso batch ya no vive en un dict en memoria: el estado reside en
`batch_runs` / `batch_run_items`. Verificar que el batch es **durable**:

```bash
python scripts/run_batch.py --pendientes            # CLI → mismo worker que la API
docker exec rappi_db psql -U rappi -d rappi_cases \
  -c "SELECT run_id, estado, procesados, errores FROM batch_runs ORDER BY id DESC LIMIT 5;"
docker exec rappi_db psql -U rappi -d rappi_cases \
  -c "SELECT count(*) FROM batch_run_items WHERE estado='failed';"
```

- [ ] `./init.sh` aplica la migración `06_batch_runs.sql` (tablas `batch_runs`, `batch_run_items`, columna `resolution_case.batch_run_id`)
- [ ] `python scripts/run_batch.py --pendientes` → crea un run; a los segundos `estado` = `done`, `procesados` = total, sin errores
- [ ] `resolution_case.batch_run_id` queda poblado para los casos del run (auditoría de qué lote generó cada análisis)
- [ ] Retry por caso: un caso que falla se reintenta (2 intentos) antes de marcarse `failed`
- [ ] **Recuperación:** con un run en `estado='running'` sin worker (simular `UPDATE batch_run_items SET estado='running'`), reiniciar `rappi_api` → el run pasa a `error` y sus items a `queued`
- [ ] Modo demo (`--demo` o `persistir=false`): no escribe en `resolution_case`, pero las filas quedan en `batch_run_items.fila_demo` y el Excel descargable sigue funcionando

### Robustez: fallbacks y guardrails

```bash
docker exec rappi_db psql -U rappi -d rappi_cases -c "\d resolution_case"  # columna fallback
docker exec rappi_db psql -U rappi -d rappi_cases -c "SELECT fallback, COUNT(*) FROM resolution_case GROUP BY fallback;"
```

- [ ] `resolution_case` tiene la columna `fallback` (migración `ALTER TABLE ... ADD COLUMN`) y aparece en el Excel exportado (28 columnas) y en `GET /cases/{id}`
- [ ] El dialto `fallback` se muestra como badge en el detalle del caso cuando está presente
- [ ] Batch durable: `BATCH_MAX_CONCURRENCIA` limita los workers; un caso lento se corta con `caso_timeout_s` y el job dinámico escala con el volumen (no corta lotes grandes)
- [ ] Circuit breaker LLM: tras `llm_circuit_umbral` fallos en la ventana, los ambiguos van a `ESCALAR circuit_open` sin re-llamar (verificar unit: `python -c "from src.pipeline.nodes.llm_circuit import CircuitProveedor; ..."`)
- [ ] Guardrail anti inyección: el `llm_system.txt` trata la entrada como dato, no como instrucción

### Step 08 — UI Streamlit

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
```

- [ ] Dashboard muestra KPIs y gráficos
- [ ] Tabla filtra por recomendación/ciudad/vertical
- [ ] Detalle de caso muestra justificación y señales
- [ ] Toggle "Incluir sintéticos" funciona

### Step 09 — Testing E2E

```bash
pytest tests/test_e2e.py -v --browser chromium
pytest tests/ --html=log_review/test_report.html --self-contained-html
```

- [ ] 108 tests pasan (unitarios + integración + E2E browser)
- [ ] Playwright interactúa con las 4 páginas sin crashes
- [ ] Reporte HTML (`log_review/test_report.html`) y Markdown (`log_review/test_e2e_*.md`) generados
- [ ] Screenshots de cada página en `log_review/`
- [ ] API performance: `/health` < 2s, UI carga < 20s
