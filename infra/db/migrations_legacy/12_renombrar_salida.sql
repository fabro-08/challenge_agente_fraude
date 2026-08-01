-- 12_renombrar_salida.sql
-- Nuevo contrato de salida en `resolution_case`: separa por origen la decisión,
-- la justificación y las señales de un caso.
--
--   resultado_reglas  → decision_regla   (APROBAR|RECHAZAR|AMBIGUO|ESCALAR)
--   resultado_llm     → decision_llm     (APROBAR|RECHAZAR|ESCALAR|NULL)
--   + justificacion_regla TEXT           (descripción de la regla disparada)
--   + senales_llm      TEXT              (señales generadas por el LLM)
--   + senales_regla    TEXT              (señales "campo op umbral = valor real")
--   - senales_usadas                     (reemplazada por senales_regla/llm)
--
-- Backfill: `senales_llm` se deriva del payload JSONB `llm_resultado` cuando el
-- LLM participó. `justificacion_regla`/`senales_regla` requieren re-análisis
-- del caso (se regeneran en el full re-run del pipeline).
-- Idempotente: las columnas nuevas se agregan con IF NOT EXISTS y el DROP de
-- senales_usadas es condicional.

ALTER TABLE resolution_case RENAME COLUMN resultado_reglas TO decision_regla;
ALTER TABLE resolution_case RENAME COLUMN resultado_llm TO decision_llm;

ALTER TABLE resolution_case
    ADD COLUMN IF NOT EXISTS justificacion_regla TEXT,
    ADD COLUMN IF NOT EXISTS senales_llm TEXT,
    ADD COLUMN IF NOT EXISTS senales_regla TEXT;

UPDATE resolution_case
SET senales_llm = (
    SELECT string_agg(s->>'señal', ' | ')
    FROM jsonb_array_elements(COALESCE(llm_resultado->'señales_explicadas', '[]'::jsonb)) AS s
)
WHERE llm_resultado IS NOT NULL;

ALTER TABLE resolution_case DROP COLUMN IF EXISTS senales_usadas;
