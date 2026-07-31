"""Punto de entrada de la API REST del agente de decisión de fraude.

Construye la app FastAPI, inicializa el grafo LangGraph al arranque
(lifespan) y monta los routers de casos, reglas y usuarios.
"""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import services
from src.api.routers import cases, rules, users
from src.pipeline.graph import build_graph

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa el grafo LangGraph al arrancar el servidor."""
    load_dotenv()
    try:
        graph = build_graph()
        services.set_graph(graph)
        logger.info("Grafo LangGraph compilado correctamente")
    except Exception as e:
        logger.error("Error al compilar el grafo: %s", e)
    yield


app = FastAPI(
    title="Rappi Caso 03 — Agente de decisión de fraude",
    description=(
        "API REST del pipeline de decisión de fraude en compensaciones CX.\n\n"
        "**Dominios:**\n"
        "- Casos: analizar, listar, detalle con checklist de reglas, KPIs.\n"
        "- Reglas: gestión versionada de thresholds (equipo fraude, sin código).\n"
        "- Simulación: evaluar impacto de cambios sin persistir.\n"
        "- Usuarios: selector de analistas para auditoría."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cases.router)
app.include_router(rules.router)
app.include_router(users.router)
