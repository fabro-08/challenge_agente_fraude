# Políticas de Decisión — Caso 3: Revisión de Compensaciones

> Documento que explica los criterios con los que el agente decide
> **APROBAR**, **RECHAZAR** o **ESCALAR** cada caso de compensación.
>
> Los thresholds numéricos se derivaron del análisis exploratorio (EDA) sobre
> 150 casos originales. Desde el step 06b viven **versionados en PostgreSQL**
> (`configuracion_reglas` / `reglas_versiones`) y se editan desde la UI sin código.
> `src/rules/thresholds.yaml` es solo el seed de bootstrap para entornos nuevos
> (`python -m src.rules.seed_reglas`).

---

## Arquitectura de decisión

El motor sigue un flujo jerárquico con **precedencia estricta**:

```
┌─────────────────────────────────────────────────────┐
│ 1. ESCALAR forzoso (seguridad de marca)             │
│    flag_palabras_criticas = True   → ESCALAR        │
├─────────────────────────────────────────────────────┤
│ 2. RECHAZAR (señales de fraude)                     │
│    Cualquier regla de RECHAZAR True → RECHAZAR      │
├─────────────────────────────────────────────────────┤
│ 3. APROBAR (señales de legitimidad)                 │
│    Todas las condiciones deben cumplirse → APROBAR   │
├─────────────────────────────────────────────────────┤
│ 4. ESCALAR por ambigüedad                           │
│    Ninguna regla concluyente → ESCALAR + LLM         │
└─────────────────────────────────────────────────────┘
```

**Filosofía:** RECHAZAR primero (prevenir fraude), APROBAR después (no penalizar a legítimos),
ESCALAR el resto (ambigüedad → revisión humana con contexto).

---

## 1. ESCALAR forzoso — Seguridad de marca

### Regla: palabras críticas en el reclamo

Si la `descripcion_reclamo` contiene palabras como *alergia, intoxicado, policía,
sangre, insultó, denunciar, abogado, demanda, hospital, veneno*, el caso se
**ESCALA automáticamente a un humano**.

**Justificación:** estos términos implican riesgos legales o de salud que un
sistema automático no debe evaluar. Un falso negativo aquí (no escalar algo que
debía escalarse) tiene un costo reputacional y legal muy alto.

**Señal:** `flag_palabras_criticas = True` (feature del step 02).

---

## 2. RECHAZAR — Señales de fraude

Cualquiera de las siguientes condiciones dispara un RECHAZAR inmediato.

### R1 — Múltiples flags de fraude previos

**Condición:** `flags_fraude_previos >= 2`

**Justificación:** un usuario con 2+ flags de fraude previos ya está señalado
por el sistema. El EDA muestra correlación de r=0.74 entre flags y número de
reclamos recientes.

### R2 — Compensación desproporcionada

**Condición:** `comp_ratio > 0.99`

**Justificación:** el usuario pide más del 99% del valor de la orden como
compensación. El ratio típico es ~0.8 (80%). Nadie en el dataset superó 1.0
(100%). Pedir el valor completo o más es señal de fraude.

### R3 — Frecuencia de reclamos anómala

**Condición:** `freq_densidad > 0.66` (p95 del dataset)

**Justificación:** mide cuántos reclamos por día de exposición ha hecho el
usuario. Una densidad > p95 indica un patrón de reclamos muy por encima del
comportamiento normal.

### R4 — Compensación superior al p99

**Condición:** `compensacion_solicitada_mxn > 604.64`

**Justificación:** solo el 1% de las compensaciones supera este monto.
Montos tan altos son atípicos y merecen rechazo automático.

### R5 — Inconsistencia GPS

**Condición:** `flag_inconsistencia_gps = True`

**Justificación:** el usuario afirma "Orden no llegó" pero el GPS confirma
(parcial o totalmente) que la entrega se realizó. Es una contradicción directa
entre el reclamo y la telemetría.

### R6 — Cuenta nueva con abuso

**Condición:** `flag_account_abuse = True`
(antigüedad < 90 días Y reclamos en 90d > p95)

**Justificación:** el EDA mostró que usuarios de 0-30 días tienen una media de
8.6 reclamos y 2.8 flags de fraude, vs usuarios antiguos (365d+) con 1.5
reclamos y 0.2 flags. Una cuenta nueva con récord de reclamos es la señal más
fuerte del dataset.

### R7 — Score de riesgo previo elevado

**Condición:** `score_riesgo_previo > 10.0`
(fórmula: flags_fraude_previos × 2 + num_compensaciones_90d × 0.5)

**Justificación:** combina flags y frecuencia en un score continuo. El p90
del dataset es 10.0. Por encima de ese umbral, el historial del usuario es
inaceptable.

---

## 3. APROBAR — Señales de legitimidad

Todas las condiciones de la regla deben cumplirse simultáneamente.

### A1 — Retraso crítico con motivo coherente

**Condición:**
- `flag_retraso_critico = True` (tiempo_entrega > p90 = 96 min)
- `motivo_reclamo` es "Orden llegó tarde" o "Producto en mal estado"

**Justificación:** cuando el dato duro respalda la queja del usuario, el caso
se aprueba automáticamente. El sistema no debería penalizar a quien reporta
una demora real documentada por la telemetría.

### A2 — Usuario sano (perfil conservador)

**Condición:**
- `flags_fraude_previos = 0`
- `comp_ratio <= 0.8`
- `entrega_confirmada_gps = "SÍ - confirmada"`
- `num_compensaciones_90d <= 2`
- `antiguedad_usuario_dias >= 90`

**Justificación:** perfil de un usuario sin historial de fraude, que pide
una compensación razonable (< 80% del valor), cuya entrega fue confirmada,
con muy pocos reclamos recientes y cierta antigüedad. Es el perfil de menor
riesgo del dataset.

### A3 — GPS ok con usuario antiguo

**Condición:**
- `entrega_confirmada_gps = "SÍ - confirmada"`
- `flag_retraso_critico = False`
- `comp_ratio <= 1.0`
- `antiguedad_usuario_dias >= 90`

**Justificación:** similar a A2 pero más laxo en comp_ratio y reclamos.
Cubre casos donde la entrega está confirmada, no hay demora, la compensación
no excede el valor de la orden, y el usuario tiene historial.

---

## 4. ESCALAR por ambigüedad

**Condición:** ninguna regla de RECHAZAR ni de APROBAR se activó.

**Justificación:** el caso tiene señales mixtas o ninguna señal clara.
No forzamos una decisión binaria donde los datos no son concluyentes.
El pipeline pasa estos casos al **nodo LLM** (LangGraph) que analiza la
`descripcion_reclamo`. Si el LLM tampoco encuentra señales claras, el
caso queda ESCALADO.

**Señal:** `ambiguo: requiere análisis LLM` en `senales_usadas`.

---

## 5. Anexo: fuentes de los thresholds

| Threshold | Valor | Fuente |
|---|---|---|
| p90 tiempo_entrega_real_min | 96 min | EDA: percentil 90 de los 150 casos |
| p95 freq_densidad | 0.66 | EDA: percentil 95 de la feature derivada |
| p99 comp_ratio | 0.99 | EDA: percentil 99 de comp_ratio |
| p99 compensacion_solicitada | 604.64 MXN | EDA: percentil 99 del dataset |
| p95 num_compensaciones_90d | 10 | EDA: percentil 95 del dataset |
| p90 score_riesgo_previo | 10.0 | Feature: percentil 90 del score |

---

## 6. Cambios y versiones

| Versión | Fecha | Cambios |
|---|---|---|
| 1.0 | 2026-07-28 | Políticas iniciales basadas en EDA de 150 casos |
