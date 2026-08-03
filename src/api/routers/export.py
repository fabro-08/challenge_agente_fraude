"""Router de export: entregables descargables (Excel y políticas).

Los Excel se generan en memoria (bytes) y se devuelven como descarga
(``Content-Disposition: attachment``); el servidor no escribe archivos.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from src.api import services

logger = __import__("logging").getLogger(__name__)
router = APIRouter()

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Raíz del repo: /repo/src/api/routers/export.py → parents[3] = /repo
_POLITICAS_PATH = Path(__file__).resolve().parents[3] / "docs" / "politicas_decision.md"


@router.get("/export/excel")
def export_excel(es_sintetico: bool = False):
    """Genera el Excel descargable de casos analizados en memoria.

    Args:
        es_sintetico: ``False`` = 150 casos originales (default);
            ``True`` = 250 casos (originales + sintéticos).
    """
    try:
        excel = services.generar_excel_bytes(es_sintetico=es_sintetico)
    except Exception as e:
        raise HTTPException(500, f"Error al generar el Excel: {e}") from e
    nombre = "250casos_analizados.xlsx" if es_sintetico else "150casos_analizados.xlsx"
    return Response(
        content=excel,
        media_type=XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/export/politicas")
def export_politicas():
    """Sirve las políticas de decisión (markdown) para descarga."""
    if not _POLITICAS_PATH.exists():
        raise HTTPException(404, "No se encontró docs/politicas_decision.md")
    contenido = _POLITICAS_PATH.read_text(encoding="utf-8")
    return Response(
        content=contenido,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="politicas_decision.md"'},
    )
