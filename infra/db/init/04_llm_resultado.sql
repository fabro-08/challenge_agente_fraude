-- 04_llm_resultado.sql
-- Agrega columna para almacenar el análisis completo del LLM (JSON estructurado)
-- para casos ambiguos procesados por el nodo llm_classify.
-- Incluye: resumen, veredicto y señales_explicadas con peso.
-- Idempotente: usa ADD COLUMN IF NOT EXISTS.

ALTER TABLE casos ADD COLUMN IF NOT EXISTS llm_resultado JSONB;
