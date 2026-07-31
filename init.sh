#!/usr/bin/env bash
# init.sh - Verificación e inicialización del entorno
#
# Este script lo ejecuta el agente al COMENZAR una sesión y antes de
# declarar cualquier tarea como `done`. Si falla, la sesión no debe avanzar.
#
# Salida esperada: códigos de salida claros y bloques marcados con [OK]/[FAIL]/[SKIP].

set -u
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()    { printf "${GREEN}[OK]${NC}   %s\n" "$1"; }
warn()  { printf "${YELLOW}[WARN]${NC} %s\n" "$1"; }
fail()  { printf "${RED}[FAIL]${NC} %s\n" "$1"; }
skip()  { printf "${BLUE}[SKIP]${NC} %s\n" "$1"; }

EXIT_CODE=0
COMPOSE_FILE="infra/docker-compose.yml"

echo "--- 1. Verificando entorno ---------------------------"

# Python disponible
if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 no está instalado"
    exit 1
fi
ok "python3 -> $(python3 --version 2>&1)"

# Versión mínima 3.12
PY_VERSION_OK=$(python3 -c 'import sys; print(int(sys.version_info >= (3, 12)))')
if [ "$PY_VERSION_OK" != "1" ]; then
    fail "Se requiere Python >= 3.12 (encontrado: $(python3 --version 2>&1))"
    EXIT_CODE=1
else
    ok "Python >= 3.12"
fi

# pip disponible
if ! command -v pip3 >/dev/null 2>&1; then
    fail "pip3 no está instalado"
    EXIT_CODE=1
else
    ok "pip3 disponible"
fi

# Docker daemon corriendo
if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon no está corriendo. Arráncalo (Docker Desktop / colima / lima)."
    EXIT_CODE=1
else
    ok "Docker daemon corriendo"
fi

# docker compose disponible
if ! docker compose version >/dev/null 2>&1; then
    fail "docker compose (plugin v2) no disponible"
    EXIT_CODE=1
else
    ok "docker compose -> $(docker compose version --short 2>/dev/null || echo 'v2')"
fi

echo "--- 2. Dependencias Python ---------------------------"

if [ -f pyproject.toml ]; then
    if python3 -c "import fastapi, streamlit, pandas" >/dev/null 2>&1; then
        ok "dependencias Python disponibles (pyproject.toml + uv.lock)"
    else
        warn "faltan dependencias del proyecto. Ejecuta: uv sync (o pip install -e .)"
    fi
else
    skip "pyproject.toml aún no existe (dependencias por declarar)"
fi

echo "--- 3. Infraestructura Docker ------------------------"

if [ ! -f "$COMPOSE_FILE" ]; then
    skip "$COMPOSE_FILE no existe todavía (lo crea @infrastructure en step 04)"
else
    # Reset completo: bajar y subir, validando
    if ! docker compose -f "$COMPOSE_FILE" down --remove-orphans >/dev/null 2>&1; then
        warn "docker compose down devolvió error (puede ser la primera vez)"
    fi

    if docker compose -f "$COMPOSE_FILE" up -d --wait >/dev/null 2>&1; then
        ok "docker compose up -d --wait completado"
    else
        warn "docker compose up falló con --wait, reintentando una vez..."
        docker compose -f "$COMPOSE_FILE" down --remove-orphans >/dev/null 2>&1
        if docker compose -f "$COMPOSE_FILE" up -d --wait >/dev/null 2>&1; then
            ok "docker compose up OK tras reintento"
        else
            fail "docker compose up falló dos veces. Revisa: docker compose -f $COMPOSE_FILE ps"
            EXIT_CODE=1
        fi
    fi

    # Verificar que los contenedores esperados están corriendo
    for svc in db api ui; do
        STATUS=$(docker compose -f "$COMPOSE_FILE" ps --format json 2>/dev/null \
            | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    s = json.loads(line)
    if s.get('Service') == '$svc':
        print(s.get('State', ''))
" 2>/dev/null || true)
        if echo "$STATUS" | grep -q "running"; then
            ok "servicio '$svc' running"
        else
            skip "servicio '$svc' no running (puede no existir aún en compose)"
        fi
    done
fi

echo "--- 4. Base de datos PostgreSQL ----------------------"

if [ ! -f "$COMPOSE_FILE" ]; then
    skip "Sin compose, no hay DB que verificar"
else
    DB_CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps -q db 2>/dev/null || true)
    if [ -z "$DB_CONTAINER" ]; then
        skip "Contenedor 'db' no existe"
    else
        # pg_isready
        if docker exec "$DB_CONTAINER" pg_isready -U rappi -d rappi_cases >/dev/null 2>&1; then
            ok "PostgreSQL acepta conexiones (rappi_cases)"
        else
            fail "PostgreSQL no responde a pg_isready"
            EXIT_CODE=1
        fi

        # Tabla casos existe
        if docker exec "$DB_CONTAINER" psql -U rappi -d rappi_cases -c "\dt casos" 2>/dev/null | grep -q "casos"; then
            CASES_COUNT=$(docker exec "$DB_CONTAINER" psql -U rappi -d rappi_cases -tAc "SELECT COUNT(*) FROM casos;" 2>/dev/null || echo "0")
            ok "Tabla 'casos' existe con $CASES_COUNT registros"
        else
            skip "Tabla 'casos' no existe aún (seed pendiente, step 04)"
        fi
    fi
fi

echo "--- 5. Código: lint y type check ---------------------"

if [ -d src ]; then
    # ruff
    if python3 -m ruff --version >/dev/null 2>&1; then
        if python3 -m ruff check src/ --quiet; then
            ok "ruff check src/"
        else
            fail "ruff encontró problemas en src/"
            EXIT_CODE=1
        fi
    else
        skip "ruff no instalado (añadir a pyproject.toml)"
    fi

    # mypy
    if python3 -m mypy --version >/dev/null 2>&1; then
        if python3 -m mypy src/ --ignore-missing-imports --no-error-summary >/dev/null 2>&1; then
            ok "mypy src/"
        else
            warn "mypy reporta errores de tipado (revisar antes de done)"
        fi
    else
        skip "mypy no instalado (añadir a pyproject.toml)"
    fi

    # imports básicos
    if python3 -c "import compileall,sys; sys.exit(0 if compileall.compile_dir('src', quiet=2) else 1)" 2>/dev/null; then
        ok "src/ compila sin errores de sintaxis"
    else
        fail "src/ tiene errores de sintaxis"
        EXIT_CODE=1
    fi
else
    skip "src/ no existe todavía"
fi

echo "--- 6. Tests -----------------------------------------"

if [ -d tests ] && [ -n "$(find tests -name 'test_*.py' 2>/dev/null)" ]; then
    if python3 -m pytest --version >/dev/null 2>&1; then
        if python3 -m pytest tests/ -q --tb=short; then
            ok "pytest tests/ pasó"
        else
            fail "pytest tests/ falló"
            EXIT_CODE=1
        fi
    else
        skip "pytest no instalado (añadir a pyproject.toml)"
    fi
else
    skip "Sin tests todavía"
fi

echo "--- 7. API FastAPI -------------------------------------"

if curl -sf --max-time 3 http://localhost:8000/health >/dev/null 2>&1; then
    ok "API /health responde 200"
else
    skip "API no disponible en :8000 (la crea @pipeline-api en step 07)"
fi

echo "--- 8. UI Streamlit ------------------------------------"

if curl -sf --max-time 3 -o /dev/null http://localhost:8501 2>&1; then
    ok "UI Streamlit responde en :8501"
else
    skip "UI no disponible en :8501 (la crea @streamlit-ui en step 08)"
fi

echo "-------------------------------------------------------"

if [ "$EXIT_CODE" -eq 0 ]; then
    ok "init.sh completado sin errores críticos"
else
    fail "init.sh terminó con errores. No declarar ningún step como done."
fi

exit "$EXIT_CODE"
