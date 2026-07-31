-- 05_analisis_casos.sql
-- Tabla de resultados del pipeline (step 06-07).
-- Separa la salida del pipeline (decision, justificacion, LLM)
-- de los datos crudos en `casos`.
--
-- llm_resultado es NULL cuando la decisión proviene de reglas (heurísticas).
-- score_confianza se eliminó: se usa jerarquía determinista, no score continuo.

CREATE TABLE IF NOT EXISTS analisis_casos (
    id              SERIAL PRIMARY KEY,
    caso_id         VARCHAR(20) NOT NULL REFERENCES casos(caso_id) ON DELETE CASCADE,
    fuente          VARCHAR(10) NOT NULL CHECK (fuente IN ('reglas', 'llm')),
    decision        VARCHAR(20) NOT NULL,
    justificacion   TEXT,
    senales_usadas  TEXT,
    llm_resultado   JSONB       NULL,
    created_at      TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analisis_casos_caso ON analisis_casos(caso_id);
CREATE INDEX IF NOT EXISTS idx_analisis_casos_decision ON analisis_casos(decision);
CREATE INDEX IF NOT EXISTS idx_analisis_casos_fuente ON analisis_casos(fuente);

-- Upsert: un caso puede ser re-analizado (overwrite).
CREATE UNIQUE INDEX IF NOT EXISTS idx_analisis_casos_caso_unico ON analisis_casos(caso_id);
