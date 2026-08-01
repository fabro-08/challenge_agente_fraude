-- 01_create_tables.sql
-- Esquema base del Caso 03: revisión de compensaciones por posible fraude.
-- Tabla `cases`: SOLO datos crudos del caso (capa 1 de 3).
-- Las features derivadas viven en `features` (02) y las decisiones del
-- pipeline en `resolution_case` (05).

CREATE TABLE IF NOT EXISTS cases (
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

    -- Metadata
    es_sintetico                BOOLEAN DEFAULT FALSE,
    created_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cases_usuario_id ON cases(usuario_id);
CREATE INDEX IF NOT EXISTS idx_cases_recomendacion ON cases(recomendacion_agente);
CREATE INDEX IF NOT EXISTS idx_cases_ciudad ON cases(ciudad);
CREATE INDEX IF NOT EXISTS idx_cases_es_sintetico ON cases(es_sintetico);
