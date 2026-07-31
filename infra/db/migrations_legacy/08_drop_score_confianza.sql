-- 08_drop_score_confianza.sql
-- Elimina la columna score_confianza de las tablas existentes.
-- La decisión ahora se basa en jerarquía determinista, no en score continuo.

-- Tabla analisis_casos
ALTER TABLE analisis_casos DROP COLUMN IF EXISTS score_confianza;

-- Tabla casos
ALTER TABLE casos DROP COLUMN IF EXISTS score_confianza;
