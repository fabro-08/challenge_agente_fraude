-- 10_migrate_3capas.sql
-- Migración in-place al esquema de 3 capas:
--
--     casos + analisis_casos  →  cases (crudo) + features + resolution_case
--
-- Preserva todos los datos existentes (250 casos, sus features y decisiones,
-- incluidos los resultados del LLM) sin re-ejecutar el pipeline.
--
-- Idempotente: si ya se ejecutó (la tabla `casos` ya no existe), no hace nada.
-- Se ejecuta contra la BD viva:
--     docker exec -i rappi_db psql -U rappi -d rappi_cases \
--         < infra/db/migrations_legacy/10_migrate_3capas.sql

BEGIN;

-- ── 1) Preservar datos legacy (renombrar antes de crear las nuevas) ────
DO $$
BEGIN
    IF to_regclass('public.casos') IS NOT NULL THEN
        ALTER TABLE public.resultados_reglas DROP CONSTRAINT IF EXISTS resultados_reglas_caso_id_fkey;
        ALTER TABLE public.casos RENAME TO casos_legacy;
        ALTER TABLE public.analisis_casos RENAME TO analisis_casos_legacy;
    END IF;
END $$;

-- ── 2) Esquema nuevo (mismo DDL que init/*.sql) ────────────────────────

CREATE TABLE IF NOT EXISTS cases (
    caso_id                     VARCHAR(20) PRIMARY KEY,
    usuario_id                  VARCHAR(50) NOT NULL,
    antiguedad_usuario_dias     INTEGER,
    ciudad                      VARCHAR(100),
    vertical                    VARCHAR(50),
    restaurante                 VARCHAR(150),
    valor_orden_mxn             NUMERIC(12, 2),
    compensacion_solicitada_mxn NUMERIC(12, 2),
    num_compensaciones_90d      INTEGER DEFAULT 0,
    monto_compensado_90d_mxn    NUMERIC(12, 2) DEFAULT 0,
    entrega_confirmada_gps      VARCHAR(25),
    tiempo_entrega_real_min     INTEGER,
    flags_fraude_previos        INTEGER DEFAULT 0,
    motivo_reclamo              TEXT,
    descripcion_reclamo         TEXT,
    recomendacion_agente        VARCHAR(20),
    es_sintetico                BOOLEAN DEFAULT FALSE,
    created_at                  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS features (
    caso_id                     VARCHAR(20) PRIMARY KEY
                               REFERENCES cases(caso_id) ON DELETE CASCADE,
    comp_ratio                  NUMERIC(10, 4),
    comps_por_dia               NUMERIC(10, 6),
    monto_promedio_comp         NUMERIC(12, 2),
    gps_match_ok                BOOLEAN,
    entrega_demorada            BOOLEAN,
    burn_rate                   NUMERIC(12, 6),
    freq_densidad               NUMERIC(10, 6),
    flag_inconsistencia_gps     BOOLEAN,
    flag_mentira_gps_alta       BOOLEAN,
    flag_retraso_critico        BOOLEAN,
    flag_account_abuse          BOOLEAN,
    score_riesgo_previo         NUMERIC(10, 2),
    longitud_reclamo            INTEGER,
    flag_palabras_criticas      BOOLEAN,
    riesgo_ciudad               NUMERIC(6, 4),
    riesgo_vertical             NUMERIC(6, 4),
    gps_paradoja_score          NUMERIC(5, 4),
    sospecha_nuevo_recurrente   BOOLEAN,
    ratio_deviation             NUMERIC(10, 4),
    score_texto                 NUMERIC(5, 4),
    version                     TEXT NOT NULL DEFAULT 'v1',
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS resolution_case (
    caso_id            VARCHAR(20) PRIMARY KEY REFERENCES cases(caso_id) ON DELETE CASCADE,
    features_version   TEXT        NOT NULL DEFAULT 'v1',
    fuente             VARCHAR(10) NOT NULL CHECK (fuente IN ('reglas', 'llm')),
    decision           VARCHAR(20) NOT NULL,
    resultado_reglas   VARCHAR(20) NULL CHECK (
        resultado_reglas IN ('APROBAR', 'RECHAZAR', 'AMBIGUO', 'ESCALAR')),
    resultado_llm      VARCHAR(20) NULL CHECK (
        resultado_llm IN ('APROBAR', 'RECHAZAR', 'ESCALAR')),
    justificacion      TEXT,
    senales_usadas     TEXT,
    llm_resultado      JSONB       NULL,
    created_at         TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP   NOT NULL DEFAULT NOW()
);

-- ── 3) Copiar datos desde las tablas legacy ────────────────────────────

DO $$
BEGIN
    IF to_regclass('public.casos_legacy') IS NOT NULL THEN
        INSERT INTO cases (caso_id, usuario_id, antiguedad_usuario_dias, ciudad,
                           vertical, restaurante, valor_orden_mxn,
                           compensacion_solicitada_mxn, num_compensaciones_90d,
                           monto_compensado_90d_mxn, entrega_confirmada_gps,
                           tiempo_entrega_real_min, flags_fraude_previos,
                           motivo_reclamo, descripcion_reclamo,
                           recomendacion_agente, es_sintetico, created_at)
        SELECT caso_id, usuario_id, antiguedad_usuario_dias, ciudad, vertical,
               restaurante, valor_orden_mxn, compensacion_solicitada_mxn,
               num_compensaciones_90d, monto_compensado_90d_mxn,
               entrega_confirmada_gps, tiempo_entrega_real_min,
               flags_fraude_previos, motivo_reclamo, descripcion_reclamo,
               recomendacion_agente, es_sintetico, created_at
        FROM casos_legacy;

        INSERT INTO features (caso_id, comp_ratio, comps_por_dia,
                              monto_promedio_comp, gps_match_ok, entrega_demorada,
                              burn_rate, freq_densidad, flag_inconsistencia_gps,
                              flag_mentira_gps_alta, flag_retraso_critico,
                              flag_account_abuse, score_riesgo_previo,
                              longitud_reclamo, flag_palabras_criticas,
                              riesgo_ciudad, riesgo_vertical, gps_paradoja_score,
                              sospecha_nuevo_recurrente, ratio_deviation,
                              score_texto, version, created_at, updated_at)
        SELECT caso_id, comp_ratio, comps_por_dia, monto_promedio_comp,
               gps_match_ok, entrega_demorada, burn_rate, freq_densidad,
               flag_inconsistencia_gps, flag_mentira_gps_alta,
               flag_retraso_critico, flag_account_abuse, score_riesgo_previo,
               longitud_reclamo, flag_palabras_criticas, riesgo_ciudad,
               riesgo_vertical, gps_paradoja_score, sospecha_nuevo_recurrente,
               ratio_deviation, score_texto, 'v1', NOW(), NOW()
        FROM casos_legacy;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.analisis_casos_legacy') IS NOT NULL THEN
        INSERT INTO resolution_case (caso_id, features_version, fuente, decision,
                                     resultado_reglas, resultado_llm,
                                     justificacion, senales_usadas, llm_resultado,
                                     created_at, updated_at)
        SELECT caso_id, 'v1', fuente, decision, resultado_reglas, resultado_llm,
               justificacion, senales_usadas, llm_resultado, created_at, updated_at
        FROM analisis_casos_legacy;
    END IF;
END $$;

-- ── 4) Restaurar FK de resultados_reglas e índices ─────────────────────

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'resultados_reglas_caso_id_fkey'
    ) THEN
        ALTER TABLE public.resultados_reglas
            ADD CONSTRAINT resultados_reglas_caso_id_fkey
            FOREIGN KEY (caso_id) REFERENCES public.cases(caso_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_cases_usuario_id ON cases(usuario_id);
CREATE INDEX IF NOT EXISTS idx_cases_recomendacion ON cases(recomendacion_agente);
CREATE INDEX IF NOT EXISTS idx_cases_ciudad ON cases(ciudad);
CREATE INDEX IF NOT EXISTS idx_cases_es_sintetico ON cases(es_sintetico);
CREATE INDEX IF NOT EXISTS idx_features_version ON features(version);
CREATE INDEX IF NOT EXISTS idx_resolution_case_decision ON resolution_case(decision);
CREATE INDEX IF NOT EXISTS idx_resolution_case_fuente ON resolution_case(fuente);
CREATE INDEX IF NOT EXISTS idx_resolution_case_resultado_reglas ON resolution_case(resultado_reglas);

-- ── 5) Eliminar tablas legacy ──────────────────────────────────────────

DO $$
BEGIN
    IF to_regclass('public.casos_legacy') IS NOT NULL THEN
        DROP TABLE public.analisis_casos_legacy;
        DROP TABLE public.casos_legacy;
    END IF;
END $$;

COMMIT;
