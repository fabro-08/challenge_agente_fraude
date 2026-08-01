-- 05_analisis_casos.sql
-- Tabla `resolution_case`: TODOS los resultados por caso (capa 3 de 3).
-- Separa la salida del pipeline de los datos crudos (`cases`) y de las
-- features (`features`).
--
-- Resultado consolidado (contrato actual):
--   - decision             → decisión final (APROBAR|RECHAZAR|ESCALAR)
--   - fuente               → de dónde sale la decisión final (reglas|llm)
--   - decision_regla       → resultado del motor de reglas (APROBAR|RECHAZAR|AMBIGUO|ESCALAR)
--   - decision_llm         → veredicto del LLM (NULL si el LLM no participó)
--   - reglas_checklist     → checklist por regla (JSONB)
--   - justificacion_regla  → descripción de la(s) regla(s) disparada(s)
--                            ("R1 — <descripcion>"); NULL si no aplica
--   - justificacion_llm    → justificación generada por el LLM; NULL si no aplica
--   - senales_regla        → señales de reglas ("campo op umbral = valor real")
--   - senales_llm          → señales canónicas generadas por el LLM
--   - llm_resultado        → payload crudo del LLM (NULL si no participó)
--
-- Nota de diseño:
--   - La decisión final de un ESCALAR forzoso (palabras críticas) sale de la
--     regla (fuente='reglas') aunque el LLM haya participado aportando análisis.
--   - Para casos AMBIGUOS la decisión sale del LLM (fuente='llm').
-- score_confianza se eliminó: se usa jerarquía determinista, no score continuo.
--
-- Upsert: la PK sobre caso_id + ON CONFLICT permite re-analizar un caso
-- (overwrite) sin historial de reprocesos.

CREATE TABLE IF NOT EXISTS resolution_case (
    caso_id             VARCHAR(20) PRIMARY KEY REFERENCES cases(caso_id) ON DELETE CASCADE,
    features_version    TEXT        NOT NULL DEFAULT 'v1',
    fuente              VARCHAR(10) NOT NULL CHECK (fuente IN ('reglas', 'llm')),
    decision            VARCHAR(20) NOT NULL,
    decision_regla      VARCHAR(20) NULL CHECK (
        decision_regla IN ('APROBAR', 'RECHAZAR', 'AMBIGUO', 'ESCALAR')),
    reglas_checklist    JSONB       NULL,
    decision_llm        VARCHAR(20) NULL CHECK (
        decision_llm IN ('APROBAR', 'RECHAZAR', 'ESCALAR')),
    justificacion_llm   TEXT,
    justificacion_regla TEXT,
    senales_llm         TEXT,
    senales_regla       TEXT,
    llm_resultado       JSONB       NULL,
    created_at          TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_resolution_case_decision ON resolution_case(decision);
CREATE INDEX IF NOT EXISTS idx_resolution_case_fuente ON resolution_case(fuente);
CREATE INDEX IF NOT EXISTS idx_resolution_case_decision_regla ON resolution_case(decision_regla);
