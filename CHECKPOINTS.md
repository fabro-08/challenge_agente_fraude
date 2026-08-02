# CHECKPOINTS

> Criterios objetivos de "estado final correcto" del proyecto.
> Usar para auto-evaluación antes de declarar el proyecto completo.

---

## Por step

- [ ] **01-EDA:** `notebooks/01_eda.ipynb` ejecuta sin errores, outline + explicaciones por gráfico, percentiles documentados
- [ ] **02-Features:** 9 columnas derivadas, sin NaN en features críticas, tests pasan
- [ ] **03-Reglas:** 150 casos clasificados sin NaN, `thresholds.yaml`, `docs/politicas_decision.md`
- [ ] **04-Infra:** 3 contenedores healthy, tabla `casos` con 150 registros (`es_sintetico=FALSE`)
- [ ] **05-Synthetic:** 100 casos sintéticos, KS-test p > 0.05, en DB con `es_sintetico=TRUE`
- [ ] **06-Pipeline:** grafo compila, invoke retorna `decision` + `fuente` + `decision_regla`/`decision_llm` + `senales_regla`/`senales_llm` + `justificacion_regla`/`justificacion_llm`
- [ ] **07-API:** `/health` 200, `/analyze/batch` persiste resultados, OpenAPI en `/docs`
- [ ] **08-UI:** dashboard con KPIs, filtros funcionales, detalle de caso legible
- [ ] **09-Testing:** 90 tests pasan (unitarios + API + E2E Playwright), reportes HTML y MD en `log_review/`

## Proyecto completo

- [ ] `./init.sh` → todos los bloques `[OK]`
- [ ] Los 150 casos originales tienen recomendación + justificación + señales en PostgreSQL
- [ ] El agente no fuerza decisión binaria en casos ambiguos → ESCALAR con criterio
- [ ] `docs/politicas_decision.md` explica los criterios de decisión
- [ ] `@reviewer` ejecutado → sin hallazgos críticos abiertos en `log_review/`
- [ ] Demo: `docker compose up` levanta todo y la UI muestra los casos analizados
- [ ] `.harness/history.md` tiene entrada por cada step completado
