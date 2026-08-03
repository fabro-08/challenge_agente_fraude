# Operación de Reglas — Cómo cambiar o crear reglas

> Guía operativa para modificar los criterios de decisión del agente.
> Complementa `docs/politicas_decision.md` (que explica el *qué* y el *porqué*);
> aquí está el *cómo* editarlas y re-procesar para ver el efecto.

**Las reglas NO viven en una base de datos.** Son dos archivos:

| Archivo | Rol |
|---|---|
| `src/rules/thresholds.yaml` | **Datos:** valores/umbrales y textos de cada regla. Es un archivo de configuración. |
| `src/rules/rule_engine.py` | **Lógica:** *qué* condición evalúa cada regla y en qué orden (`RuleEngine`). |
| `src/pipeline/features.py` | **Features/features de palabras críticas** (regex) que disparan el ESCALAR forzoso. |

El motor `RuleEngine` se instancia **por caso** dentro del nodo `apply_rules`
(`src/pipeline/nodes/apply_rules.py`), así que **los cambios en `thresholds.yaml`
toman efecto al instante**, sin reiniciar nada. Los cambios en `rules_engine.py`
o `features.py` (código) requieren **reiniciar la API**.

---

## Qué quiero hacer → dónde edito

| Qué quiero | Dónde edito | Detalle |
|---|---|---|
| **Cambiar un umbral numérico** | `src/rules/thresholds.yaml` → `valor` | p. ej. `rechazar.flags_minimos.valor`. Los umbrales en RECHAZAR usan `valor`; los de APROBAR usan `condiciones`. |
| **Cambiar valores de una condición APROBAR** | `src/rules/thresholds.yaml` → `aprobar.<regla>.condiciones` | p. ej. `usuario_sano.condiciones.antiguedad_min`, `gps_ok_sano.condiciones`. |
| **Cambiar la lista de motivos elegibles (demora)** | `src/rules/thresholds.yaml` → `aprobar.retraso_critico_con_motivo.motivos_elegibles` | Es una lista de strings. |
| **Agregar / modificar una CONDICIÓN (lógica) de una regla** | `src/rules/rule_engine.py` → `_rechazar_row()` / `_aprobar_row()` | El motor lee campos con nombres fijos. Para agregar una condición nueva (p. ej. "y además no hubo demora") tenés que escribir el código. Si el valor es configurable, además registralo en el YAML. |
| **Crear una regla nueva / señal nueva** | `src/rules/rule_engine.py` + (opcional) YAML | Nueva rama en el motor + umbral en `thresholds.yaml` + documentarla en `docs/politicas_decision.md`. |
| **Agregar/quitar palabras críticas del ESCALAR forzado** | `src/pipeline/features.py` → regex `PALABRAS_CRITICAS` (~línea 22) | No es YAML: es el patrón que crea el flag `flag_palabras_criticas`. |
| **Agregar una feature nueva** | Feature engineering (step 02) | Un umbral no sirve si la columna derivada no existe: primero hay que agregar y persistir la feature. |

---

## Flujo paso a paso tras una edición

1. **Editar** el archivo correspondiente (YAML y/o código).
2. **Validar**:
   ```bash
   ./init.sh              # lint + typecheck + tests + healthchecks
   pytest tests/ -q       # incluye los tests de RuleEngine
   ```
3. **Re-procesar** para que la DB vea el efecto (los casos ya en `resolution_case`
   no cambian solos; hay que re-analizarlos). Cualquiera de estas vías:
   - **UI**: Dashboard → sección **Batch** → `persistir=true` → ejecutar (Todos / Solo pendientes).
   - **API**: `POST /analyze` (un caso) o `POST /analyze/batch ` con `"persistir": true`.
   - **Script**: `python scripts/run_batch.py`.
   - **Notebook**: `notebooks/06_pipeline.ipynb`.
4. **Regenerar entregables** si cambió el output:
   ```bash
   curl -s http://localhost:8000/export/excel -o data/150casos_analizados.xlsx
   # o python scripts/export_casos_analizados.py
   ```
5. **Actualizar la documentación y cifras**:
   - `docs/politicas_decision.md` si cambió un criterio.
   - Cifras/distribución y sección nueva del `README.md` si cambió la distribución.

---

## Ejemplos

### Ejemplo 1 — Bajar el umbral de rechazo por flags (2 → 1)
En `src/rules/thresholds.yaml`:
```yaml
rechazar:
  flags_minimos:
    valor: 1     # antes: 2
```
Lee el YAML → tdd toma efecto al instante. Re-procesa los casos para ver el impacto.

### Ejemplo 2 — Agregar una condición a `usuario_sano` ("y además sin demora")
En `src/rules/rule_engine.py`, dentro de `_aprobar_row()` → bloque `usuario_sano`:
```python
and not bool(row.get("flag_retraso_critico", False))
```
Como es código, **reinicia la API** después de editar. Si quieres que el límite sea
configurable, agrega un campo en `thresholds.yaml` y leelo.

### Ejemplo 3 — Sumar una palabra crítica al ESCALAR forzado
En `src/pipeline/features.py` (~línea 22):
```python
PALABRAS_CRITICAS = re.compile(
    r"alergi|intoxic|polic[ií]a|sangre|insult|denunci|abogado|demanda|hospital|veneno|fiscal",
    re.IGNORECASE,
)
```
Cualquier reclamo que mencione "fiscal" ahora disparará `flag_palabras_criticas`
y el caso se ESCALARÁ forzado (seguridad de marca).

---

## Notas importantes

- **Cambio de YAML** → inmediato. **Cambio de código** (`rule_engine.py`,
  `features.py`) → reiniciar la API (y si está en Docker, `docker compose restart api`).
- Los `reglas_checklist` quedan en `[]`: la justificación y las señales las genera
  el motor desde el YAML (`justificacion_regla` / `senales_regla`), no de una
  config en base de datos.
- El KPI de la UI "Reglas YAML" cuenta las entradas de `thresholds.yaml`
  (`reglas_yaml` en el endpoint `/stats`). Si agregas un bloque nuevo, ese número
  sube.
- Nunca hardcodear umbrales en la lógica: todo valor de decisión sale del
  `src/rules/thresholds.yaml`.