# Diccionario de datos — Caso 3: Revisión de Compensaciones

> Dataset `casos` en PostgreSQL. `cases` = 18 columnas, 250 filas (150 originales + 100 sintéticas); con features y `resolution_case` el modelo completo suma ~42 columnas.

---

## 1. Columnas originales (Excel Caso3_Compensaciones)

| Campo | Tipo | Descripción | Únicos / Rango |
|---|---|---|---|
| `caso_id` | VARCHAR(20) | ID del caso. `COMP-XXXX` = original, `COMP-SYN-XXXX` = sintético | 250 únicos |
| `usuario_id` | VARCHAR(50) | ID del usuario que reclama | 249 usuarios |
| `antiguedad_usuario_dias` | INTEGER | Días desde el registro del usuario en Rappi | 6–1796, p50=339d |
| `ciudad` | VARCHAR(100) | Ciudad de la entrega | **15 ciudades** (ver abajo) |
| `vertical` | VARCHAR(50) | Categoría del pedido | **3 únicos:** Comida, Mercado, Farmacia |
| `restaurante` | VARCHAR(150) | Nombre del comercio | 15 restaurantes |
| `valor_orden_mxn` | NUMERIC(12,2) | Monto pagado por el pedido | $99–$700 MXN, p50=$312 |
| `compensacion_solicitada_mxn` | NUMERIC(12,2) | Monto que el usuario pide como compensación | $70–$693 MXN, p50=$237, p99=$627 |
| `num_compensaciones_90d` | INTEGER | Compensaciones del usuario en últimos 90 días | 0–14, p50=3, p95=10 |
| `monto_compensado_90d_mxn` | NUMERIC(12,2) | Monto total ya compensado a este usuario en 90d | $0–$2,764 MXN, p95=$2,462 |
| `entrega_confirmada_gps` | VARCHAR(25) | Estado del GPS del repartidor | **4 valores:** `SÍ - confirmada`, `NO confirmada`, `Parcial`, `Señal perdida` |
| `tiempo_entrega_real_min` | INTEGER | Minutos que tardó la entrega real | 22–110 min, p50=59, p90=96 |
| `flags_fraude_previos` | INTEGER | Veces que este usuario fue marcado por fraude antes | 0, 1, 2, 3, 4 |
| `motivo_reclamo` | TEXT | Motivo declarado por el usuario | **7 motivos** (ver abajo) |
| `descripcion_reclamo` | TEXT | Texto libre del reclamo | Ej: *"La app dice que fue entregado pero no recibí nada. Estuve en casa todo el día."* |
| `recomendacion_agente` | TEXT | Columna de recomendación en el Excel fuente | **Vacía — no poblada por diseño** (ver Nota) |

> ### Nota de diseño — Por qué no se llena `recomendacion_agente`
>
> La decisión del agente **no se escribe en el `Dataset_caso_3.xlsx` original**:
> el archivo fuente se trata como input **read-only** para preservar integridad y
> reproducibilidad. La recomendación vive en `resolution_case.decision`
> (PostgreSQL) y el entregable es un **Excel derivado**
> (`data/150casos_analizados.xlsx`) con la columna `recomendacion`, justificación
> y señales separadas por origen (reglas vs LLM). Ese contrato separado
> (`decision_regla`/`decision_llm`, `justificacion_*`, `senales_*`) no cabe en una
> columna única del dataset original.

### Valores únicos de campos categóricos

```
ciudades (15): Barranquilla, Bogotá, Buenos Aires, Cali, CDMX, Córdoba,
               Guadalajara, Lima, Medellín, Monterrey, Puebla,
               Querétaro, Santiago, São Paulo, Tijuana

verticales (3): Comida, Farmacia, Mercado

GPS (4): SÍ - confirmada, NO confirmada, Parcial, Señal perdida

motivos (7): Orden no llegó, Orden llegó tarde, Producto en mal estado,
             Producto incorrecto, Producto incompleto, Cobro incorrecto,
             Orden cancelada sin reembolso

flags (5): 0, 1, 2, 3, 4
```

### Distribuciones numéricas

| Campo | Min | p25 | p50 | p75 | p90 | p95 | p99 | Max |
|---|---|---|---|---|---|---|---|---|
| antiguedad_usuario_dias | 6 | 120 | 339 | 940 | — | — | — | 1796 |
| valor_orden_mxn | $99 | — | $312 | — | — | $667 | — | $700 |
| compensacion_solicitada_mxn | $70 | — | $237 | — | — | — | $627 | $693 |
| tiempo_entrega_real_min | 22 | — | 59 | — | 96 | — | — | 110 |
| num_compensaciones_90d | 0 | — | 3 | — | — | 10 | — | 14 |
| comp_ratio | 0.10 | — | ~0.76 | — | — | 0.96 | 0.99 | 1.05 |

---

## 2. Features derivadas (step 02)

| Campo | Tipo | Descripción |
|---|---|---|
| `comp_ratio` | NUMERIC(10,4) | `compensacion_solicitada / valor_orden`. >1 = pide más de lo que pagó |
| `burn_rate` | NUMERIC(12,6) | `monto_compensado_90d / antiguedad_dias` — gasto diario en reclamos |
| `freq_densidad` | NUMERIC(10,6) | `num_compensaciones_90d / antiguedad_dias` — reclamos por día |
| `comps_por_dia` | NUMERIC(10,6) | Similar a freq_densidad (variante) |
| `monto_promedio_comp` | NUMERIC(12,2) | Compensación promedio por reclamo |
| `gps_match_ok` | BOOLEAN | `entrega_confirmada_gps == "SÍ - confirmada"` |
| `entrega_demorada` | BOOLEAN | `tiempo_entrega_real_min > p90 (96 min)` |
| `flag_inconsistencia_gps` | BOOLEAN | Reclama "no llegó" pero GPS confirma entrega |
| `flag_mentira_gps_alta` | BOOLEAN | GPS confirma + >2 reclamos en 90d (**paradoja GPS**) |
| `flag_retraso_critico` | BOOLEAN | `tiempo_entrega_real_min > p90 (96)` |
| `flag_account_abuse` | BOOLEAN | `antiguedad < 90d` Y `num_compensaciones_90d > p95 (10)` |
| `score_riesgo_previo` | NUMERIC(10,2) | `flags_fraude × 2 + num_compensaciones × 0.5`. p90 = 10.0 |
| `longitud_reclamo` | INTEGER | Cantidad de palabras en `descripcion_reclamo` |
| `flag_palabras_criticas` | BOOLEAN | Reclamo contiene: _alergi, intoxic, policía, sangre, insult, denunci, abogado, demanda, hospital, veneno_ |
| `riesgo_ciudad` | NUMERIC(6,4) | Proporción de RECHAZOS en esa ciudad |
| `riesgo_vertical` | NUMERIC(6,4) | Proporción de RECHAZOS en esa vertical |
| `gps_paradoja_score` | NUMERIC(5,4) | Score de la paradoja GPS: GPS confirmado + alta frecuencia de reclamos |
| `sospecha_nuevo_recurrente` | BOOLEAN | Cuenta nueva (< 90d) con patrón de reclamos |
| `ratio_deviation` | NUMERIC(10,4) | Desviación del `comp_ratio` vs. media de su ciudad/vertical |
| `score_texto` | NUMERIC(5,4) | Placeholder (se llena con LLM en el pipeline) |

---

## 3. Salidas del pipeline (steps 06–07)

La decisión vive en `resolution_case` (separada de los datos crudos de `cases`),
con el contrato separado por origen (reglas vs LLM).

| Campo | Tipo | Descripción |
|---|---|---|
| `decision` | VARCHAR(20) | Decisión final: **APROBAR**, **RECHAZAR** o **ESCALAR** |
| `fuente` | VARCHAR(10) | `reglas` (heurística determinista) o `llm` (caso ambiguo analizado por el LLM). ESCALAR forzoso queda en `reglas` |
| `decision_regla` | VARCHAR(10) | Resultado del motor de reglas: APROBAR, RECHAZAR, AMBIGUO o ESCALAR |
| `decision_llm` | VARCHAR(10) | Veredicto discreto del LLM (solo casos que pasan por LLM) |
| `justificacion_regla` | TEXT | Bloques por regla que disparó, separados por línea en blanco: `R1 — <descripción>` seguido de la `<explicacion>` preseteada en la config de la regla (`R1 — Usuario con 2 o más flags de fraude previos\nEl usuario tiene 2 o más flags de fraude previos: ya está señalado por el sistema.`) |
| `justificacion_llm` | TEXT | Justificación del LLM sin prefijo de decisión |
| `senales_regla` | TEXT | Señales de reglas `campo operador umbral = valor real`, separadas por `\|` |
| `senales_llm` | TEXT | Señales canónicas del LLM (snake_case), separadas por `\|` |
| `reglas_checklist` | JSONB | Checklist por regla (solo motor en DB). Con reglas desde `thresholds.yaml` queda `[]` |
| `llm_resultado` | JSONB | Análisis del LLM: `{resumen, veredicto, señales_explicadas[{señal, explicacion, peso}], error?}` (`error` presente si hubo fallback del LLM: `provider_error`/`parsing`/`circuit_open`) |
| `fallback` | TEXT | Motivo(s) de degradación del agente (`reglas_yaml`, `llm_circuit_open`, `llm_provider_error`, `llm_parsing`, ...), separados por `\|`. `NULL` si no hubo fallback |

### Distribución de decisiones (250 casos: 150 originales + 100 sintéticos)

| Decisión | Casos | % |
|---|---|---|
| APROBAR | 82 | 32.8% |
| RECHAZAR | 107 | 42.8% |
| ESCALAR | 61 | 24.4% |

Sobre los **150 casos originales**: APROBAR 56 · RECHAZAR 63 · ESCALAR 31
(`data/150casos_analizados.xlsx`).

> La distribución exacta varía con reprocesos (el batch re-analyza casos); estas
> cifras corresponden al estado actual de `resolution_case`.

---

## 4. Metadata

| Campo | Tipo | Descripción |
|---|---|---|
| `es_sintetico` | BOOLEAN | `TRUE` = generado sintéticamente (100 casos). `FALSE` = dataset original (150) |
| `created_at` | TIMESTAMP | Fecha de inserción en la DB |
