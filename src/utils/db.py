"""Configuración de conexión a PostgreSQL (compartida)."""

import os

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "rappi_cases"),
    "user": os.getenv("DB_USER", "rappi"),
    "password": os.getenv("DB_PASSWORD", "rappi_pass"),
}
