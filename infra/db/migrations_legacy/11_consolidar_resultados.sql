-- 11_consolidar_resultados.sql
-- Consolidación de resultados en `resolution_case`:
--   1) Nuevo JSONB `reglas_checklist` (reemplaza la tabla `resultados_reglas`).
--   2) Renombra `justificacion` → `justificacion_llm` (campo completado por el LLM).
--   3) Elimina la tabla `resultados_reglas`.
--
-- Idempotente y transaccional: cada paso se protege con guards y se puede
-- re-ejecutar sin efecto. Ejecutar contra una BD ya migrada (después del
-- refactor 3-capas, migración 10).

BEGIN;

-- ── 1) Nueva columna JSONB con el checklist por regla ─────────────────

ALTER TABLE public.resolution_case ADD COLUMN IF NOT EXISTS reglas_checklist JSONB;

-- Poblar el checklist desde resultados_reglas (si la tabla aún existe y el
-- JSON está vacío para no pisar datos ya consolidados).
DO $$
BEGIN
    IF to_regclass('public.resultados_reglas') IS NOT NULL THEN
        UPDATE public.resolution_case rc
        SET reglas_checklist = sub.checklist
        FROM (
            SELECT rr.caso_id,
                   jsonb_agg(
                       jsonb_build_object(
                           'regla_id',     cr.regla_id,
                           'version_id',   rr.version_id,
                           'version',      rv.version,
                           'nombre',       cr.nombre,
                           'tipo_regla',   cr.tipo_regla,
                           'se_disparo',   rr.se_disparo,
                           'valor_actual', rr.valor_actual,
                           'detalle',      rr.detalle
                       ) ORDER BY cr.regla_id
                   ) AS checklist
            FROM resultados_reglas rr
            JOIN reglas_versiones rv ON rv.version_id = rr.version_id
            JOIN configuracion_reglas cr ON cr.regla_id = rv.regla_id
            GROUP BY rr.caso_id
        ) sub
        WHERE rc.caso_id = sub.caso_id
          AND rc.reglas_checklist IS NULL;
    END IF;
END $$;

-- ── 2) Renombrar justificacion → justificacion_llm ────────────────────

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'resolution_case'
          AND column_name  = 'justificacion'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = 'resolution_case'
          AND column_name  = 'justificacion_llm'
    ) THEN
        ALTER TABLE public.resolution_case
            RENAME COLUMN justificacion TO justificacion_llm;
    END IF;
END $$;

-- Los campos LLM solo aplican cuando la decisión proviene del LLM: la
-- justificación de casos resueltos por reglas queda cubierta por el checklist.
UPDATE public.resolution_case
SET justificacion_llm = NULL
WHERE fuente = 'reglas';

-- ── 3) Eliminar la tabla resultados_reglas (checklist consolidado) ────

DROP TABLE IF EXISTS public.resultados_reglas;

-- ── Índices ───────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_resolution_case_decision ON resolution_case(decision);
CREATE INDEX IF NOT EXISTS idx_resolution_case_fuente ON resolution_case(fuente);
CREATE INDEX IF NOT EXISTS idx_resolution_case_resultado_reglas ON resolution_case(resultado_reglas);

COMMIT;
