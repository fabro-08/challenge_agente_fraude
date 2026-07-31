-- 01_create_tables.sql
-- Esquema base del Caso 03: revisión de compensaciones por posible fraude.
-- Columnas mapeadas desde data/Dataset_caso_3.xlsx (pestaña Caso3_Compensaciones).

CREATE TABLE IF NOT EXISTS casos (
    -- Identidad
    caso_id                     VARCHAR(20) PRIMARY KEY,
    usuario_id                  VARCHAR(50) NOT NULL,

    -- Columnas originales del dataset
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

    -- Columna objetivo (vacía en el dataset, la llena el agente)
    recomendacion_agente        VARCHAR(20),

    -- Features derivadas (step 02)
    comp_ratio                  NUMERIC(10, 4),
    comps_por_dia               NUMERIC(10, 6),
    monto_promedio_comp         NUMERIC(12, 2),
    gps_match_ok                BOOLEAN,
    entrega_demorada            BOOLEAN,

    -- Salidas del pipeline (steps 06-07)
    justificacion               TEXT,
    senales_usadas              TEXT,

    -- Metadata
    es_sintetico                BOOLEAN DEFAULT FALSE,
    created_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_casos_usuario_id ON casos(usuario_id);
CREATE INDEX IF NOT EXISTS idx_casos_recomendacion ON casos(recomendacion_agente);
CREATE INDEX IF NOT EXISTS idx_casos_ciudad ON casos(ciudad);
CREATE INDEX IF NOT EXISTS idx_casos_es_sintetico ON casos(es_sintetico);
