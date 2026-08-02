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

### Step 06b — Motor genérico de reglas

```bash
python -m src.rules.seed_reglas
pytest tests/test_generic_engine.py -v
```

- [ ] 3 tablas creadas: `configuracion_reglas`, `reglas_versiones`, `usuarios_fraude` (el checklist por regla se consolida en `resolution_case.reglas_checklist`)
- [ ] Seed inserta 11 reglas v1 (R1-R7, A1-A3, ESCALAR-1) — idempotente
- [ ] Paridad: motor genérico decide igual que `RuleEngine` sobre los 250 casos
- [ ] `graph.invoke(case)` consolida el checklist en `resolution_case.reglas_checklist` (JSONB) con `version_id` y `version`
- [ ] Actualizar una regla crea nueva versión (historial en `reglas_versiones`)
- [ ] Simulador devuelve transiciones sin escribir en DB
- [ ] Tests: `pytest tests/test_generic_engine.py` (incluye mark `integration`)

### Step 07 — API

```bash
curl -s http://localhost:8000/health
curl -s -X POST http://localhost:8000/analyze -H "Content-Type: application/json" -d '{...}'
```

- [ ] `GET /health` → 200
- [ ] `POST /analyze` → recomendación + justificación
- [ ] `POST /analyze/batch` → procesa todos los casos de la DB
- [ ] OpenAPI docs en `http://localhost:8000/docs`

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

- [ ] 90 tests pasan (unitarios + integración + E2E browser)
- [ ] Playwright interactúa con las 4 páginas sin crashes
- [ ] Reporte HTML (`log_review/test_report.html`) y Markdown (`log_review/test_e2e_*.md`) generados
- [ ] Screenshots de cada página en `log_review/`
- [ ] API performance: `/health` < 2s, UI carga < 20s
