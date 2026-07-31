-- 02_add_features.sql
-- Migración: añade las 16 columnas de features del step 02 a la tabla casos.
-- Idempotente: usa ADD COLUMN IF NOT EXISTS.

ALTER TABLE casos ADD COLUMN IF NOT EXISTS burn_rate               NUMERIC(12, 6);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS freq_densidad           NUMERIC(10, 6);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS flag_inconsistencia_gps BOOLEAN;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS flag_mentira_gps_alta   BOOLEAN;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS flag_retraso_critico    BOOLEAN;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS flag_account_abuse      BOOLEAN;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS score_riesgo_previo     NUMERIC(10, 2);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS longitud_reclamo        INTEGER;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS flag_palabras_criticas  BOOLEAN;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS riesgo_ciudad           NUMERIC(6, 4);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS riesgo_vertical         NUMERIC(6, 4);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS gps_paradoja_score      NUMERIC(5, 4);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS sospecha_nuevo_recurrente BOOLEAN;
ALTER TABLE casos ADD COLUMN IF NOT EXISTS ratio_deviation         NUMERIC(10, 4);
ALTER TABLE casos ADD COLUMN IF NOT EXISTS score_texto             NUMERIC(5, 4);
