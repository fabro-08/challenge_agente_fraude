-- 02_add_features.sql
-- Tabla `features`: features derivadas por caso (capa 2 de 3).
-- Relación 1:1 con `cases`. Permite reprocesar el feature engineering
-- sin tocar los datos crudos ni las decisiones ya tomadas.
-- `version` es la etiqueta del feature set (la audita `resolution_case.features_version`).

CREATE TABLE IF NOT EXISTS features (
    caso_id                     VARCHAR(20) PRIMARY KEY
                               REFERENCES cases(caso_id) ON DELETE CASCADE,

    -- Features del step 02
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

    -- Metadata
    version                     TEXT NOT NULL DEFAULT 'v1',
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_features_version ON features(version);
