-- 06_migrate_analisis.sql
-- Migración: mueve los resultados del pipeline desde `casos` a `analisis_casos`.
-- Luego elimina las columnas de salida del pipeline de `casos`.
--
-- Columnas a migrar:
--   recomendacion_agente → decision
--   justificacion        → justificacion
--   senales_usadas       → senales_usadas
--   score_confianza      → score_confianza
--   llm_resultado        → llm_resultado
--
-- fuente: 'llm' si llm_resultado IS NOT NULL, 'reglas' si no.

INSERT INTO analisis_casos (caso_id, fuente, decision, justificacion, senales_usadas, score_confianza, llm_resultado)
SELECT
    caso_id,
    CASE WHEN llm_resultado IS NOT NULL THEN 'llm' ELSE 'reglas' END,
    recomendacion_agente,
    justificacion,
    senales_usadas,
    score_confianza,
    llm_resultado
FROM casos
WHERE recomendacion_agente IS NOT NULL
ON CONFLICT (caso_id) DO UPDATE SET
    fuente          = EXCLUDED.fuente,
    decision        = EXCLUDED.decision,
    justificacion   = EXCLUDED.justificacion,
    senales_usadas  = EXCLUDED.senales_usadas,
    score_confianza = EXCLUDED.score_confianza,
    llm_resultado   = EXCLUDED.llm_resultado,
    updated_at      = NOW();

-- Eliminar columnas de salida del pipeline de `casos`.
-- (Los datos crudos y features permanecen en `casos`.)
ALTER TABLE casos DROP COLUMN IF EXISTS justificacion;
ALTER TABLE casos DROP COLUMN IF EXISTS senales_usadas;
ALTER TABLE casos DROP COLUMN IF EXISTS score_confianza;
ALTER TABLE casos DROP COLUMN IF EXISTS llm_resultado;
