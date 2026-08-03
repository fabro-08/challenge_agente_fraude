-- 06_batch_runs.sql
-- Proceso batch durable en PostgreSQL.
--
-- Antes, el estado de un job batch vivía en un `dict` en memoria dentro del
-- proceso de la API (`services._jobs`) con un thread daemon. Si el proceso se
-- reiniciaba, los jobs en vuelo morían sin rastro y no había recuperación ni
-- auditoría.
--
-- Este script introduce el estado del batch en DB:
--   - batch_runs       → cabecera del lote (estado, filtros, totales, decisiones)
--   - batch_run_items  → 1 fila por caso (estado, intentos, error) → permite
--                        retry por caso y semántica *at-least-once* sin
--                        reprocesar el lote completo.
--   - resolution_case.batch_run_id → qué lote generó cada análisis (auditoría).
--
-- Diseño:
--   - Cada item reclama con un UPDATE ... RETURNING transaccional → no hay
--     duplicación de trabajo si hay varios workers.
--   - Al arrancar la API, `recuperar_runs_huerfanos()` revierte a `error` los
--     runs `running` (los items re-ejecutables quedan disponibles).
--   - Los nombres respetan el estilo snake_case de `04`/`05`.

-- Cabecera del lote batch. Un "run" agrupa un disparo de procesamiento a bunch
-- de casos seleccionados por los filtros del request.
CREATE TABLE IF NOT EXISTS batch_runs (
    id            BIGSERIAL PRIMARY KEY,
    run_id        TEXT        NOT NULL UNIQUE,     -- uuid legible para la UI/API
    estado        TEXT        NOT NULL DEFAULT 'running'
                              CHECK (estado IN ('queued', 'running', 'done', 'error')),
    tipo_filtro   TEXT        NOT NULL,            -- todos|pendientes|sintetico|seleccion|aleatorio
    parametros    JSONB,                           -- filtros con qque se lanzó el lote
    persistir     BOOLEAN     NOT NULL DEFAULT TRUE,  -- False = modo demo en memoria
    total         INT         NOT NULL DEFAULT 0,
    procesados    INT         NOT NULL DEFAULT 0,
    errores       INT         NOT NULL DEFAULT 0,
    decisiones    JSONB,                           -- {"APROBAR": n, "RECHAZAR": n, "ESCALAR": n}
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalizado_en TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_batch_runs_estado ON batch_runs(estado);
CREATE INDEX IF NOT EXISTS idx_batch_runs_creado_en ON batch_runs (creado_en DESC);

-- Item del lote: un caso a procesar. La PK (run_id, caso_id) evita duplicar
-- el mismo caso dentro de un mismo run.
CREATE TABLE IF NOT EXISTS batch_run_items (
    id          BIGSERIAL PRIMARY KEY,
    run_id      BIGINT NOT NULL REFERENCES batch_runs(id) ON DELETE CASCADE,
    caso_id     TEXT   NOT NULL,
    estado      TEXT   NOT NULL DEFAULT 'queued'
                       CHECK (estado IN ('queued', 'running', 'done', 'failed')),
    intentos    INT    NOT NULL DEFAULT 0,
    error       TEXT,
    fila_demo    JSONB,   -- solo modo demo (persistir=FALSE): fila del Excel
    procesado_en TIMESTAMPTZ,
    UNIQUE (run_id, caso_id)
);

CREATE INDEX IF NOT EXISTS idx_batch_run_items_estado ON batch_run_items (estado);

-- Auditoría: a qué lote debe cada análisis. Un caso puede haber sido analizado
-- por varios runs a lo largo del tiempo; `batch_run_id` apunta al más reciente.
ALTER TABLE resolution_case
    ADD COLUMN IF NOT EXISTS batch_run_id BIGINT;