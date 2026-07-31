-- 03_reglas.sql
-- Motor de reglas genérico versionado (step 06b).
-- El equipo de fraude gestiona reglas sin tocar código: thresholds, activación
-- y nuevas reglas viven en DB con historial completo de cambios.
-- Idempotente: usa CREATE TABLE IF NOT EXISTS.

-- ── Reglas activas (puntero al estado actual) ────────────────────────

CREATE TABLE IF NOT EXISTS configuracion_reglas (
    regla_id       VARCHAR(50) PRIMARY KEY,   -- "R1", "A2", "ESCALAR-1"
    nombre         VARCHAR(200) NOT NULL,
    tipo_regla     VARCHAR(20)  NOT NULL       -- RECHAZAR | APROBAR | ESCALAR_FORZOSO
                   CHECK (tipo_regla IN ('RECHAZAR', 'APROBAR', 'ESCALAR_FORZOSO')),
    prioridad      INTEGER      NOT NULL DEFAULT 0,
    activo         BOOLEAN      NOT NULL DEFAULT TRUE,
    version_actual INTEGER      NOT NULL DEFAULT 1,
    created_at     TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ── Historial de versiones (auditoría) ───────────────────────────────

CREATE TABLE IF NOT EXISTS reglas_versiones (
    version_id          SERIAL PRIMARY KEY,
    regla_id            VARCHAR(50) NOT NULL REFERENCES configuracion_reglas(regla_id),
    version             INTEGER     NOT NULL,
    config              JSONB       NOT NULL,   -- definición declarativa de la regla
    cambio_descripcion  TEXT,
    updated_by          VARCHAR(100),           -- nombre del analista de fraude
    updated_at          TIMESTAMP   NOT NULL DEFAULT NOW(),
    UNIQUE (regla_id, version)
);

CREATE INDEX IF NOT EXISTS idx_reglas_versiones_regla ON reglas_versiones(regla_id);

-- ── Resultados por caso × regla (checklist para la UI) ───────────────

CREATE TABLE IF NOT EXISTS resultados_reglas (
    id           SERIAL PRIMARY KEY,
    caso_id      VARCHAR(20) NOT NULL REFERENCES casos(caso_id),
    version_id   INTEGER     NOT NULL REFERENCES reglas_versiones(version_id),
    se_disparo   BOOLEAN     NOT NULL,
    valor_actual TEXT,                        -- valor del campo en el caso evaluado
    detalle      TEXT,                        -- explicación legible para el agente CS
    created_at   TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_resultados_reglas_caso ON resultados_reglas(caso_id);
CREATE INDEX IF NOT EXISTS idx_resultados_reglas_version ON resultados_reglas(version_id);

-- ── Analistas de fraude (selector en UI al editar reglas) ────────────

CREATE TABLE IF NOT EXISTS usuarios_fraude (
    usuario_id  SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL,
    email       VARCHAR(150),
    activo      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- Seed de analistas (idempotente por email)
INSERT INTO usuarios_fraude (nombre, email)
SELECT v.nombre, v.email
FROM (VALUES
    ('Ana Martínez',  'ana.martinez@rappi.com'),
    ('Carlos Ruiz',   'carlos.ruiz@rappi.com'),
    ('Sofía Herrera', 'sofia.herrera@rappi.com')
) AS v(nombre, email)
WHERE NOT EXISTS (
    SELECT 1 FROM usuarios_fraude u WHERE u.email = v.email
);
