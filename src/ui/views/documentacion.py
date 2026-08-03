"""Documentación — página que muestra la documentación del proyecto.

Escanea los Markdown de ``docs/`` (y README.md / CHECKPOINTS.md en la raíz) y los
renderiza con ``st.markdown``. ``politicas_decision.md`` se excluye porque tiene
su propia página ("Políticas"). Para ``architecture.md`` se reutiliza el grafo
HTML del proceso del agente en lugar del bloque Mermaid crudo.

Las imágenes locales (``![alt](ruta)``) se renderizan con ``st.image`` porque
``st.markdown`` no carga rutas relativas.
"""

from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from src.ui.flow import proceso_agente_html

DOCS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs"
ROOT = Path(__file__).resolve().parent.parent.parent.parent
EXCLUIDOS = {"politicas_decision.md"}
EXTRA = {"README.md", "CHECKPOINTS.md"}

# Línea que es únicamente una imagen markdown: ![alt](ruta)
_IMG_LINE = re.compile(r"^\s*!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)\s*$")


def _descubrir_docs() -> list[tuple[str, Path]]:
    """Devuelve [(etiqueta, ruta)] de los documentos disponibles (auto-scan)."""
    docs: list[tuple[str, Path]] = []
    if DOCS_DIR.is_dir():
        for p in sorted(DOCS_DIR.glob("*.md")):
            if p.name not in EXCLUIDOS:
                docs.append((p.stem.replace("_", " ").title(), p))
    for nombre in sorted(EXTRA):
        p = ROOT / nombre
        if p.is_file():
            docs.append((p.stem, p))
    return docs


def _render_markdown(contenido: str, base_dir: Path) -> None:
    """Renderiza markdown, mostrando imágenes locales con ``st.image``.

    Divide el texto en bloques separados por líneas de imagen (``![alt](ruta)``);
    cada bloque se renderiza con ``st.markdown`` (preserva tablas/code fences) y
    cada imagen con ``st.image``.

    Args:
        contenido: Texto markdown del documento.
        base_dir: Carpeta desde la que se resuelven las rutas relativas de imagen.
    """
    parts = _IMG_LINE.split(contenido)
    for i, part in enumerate(parts):
        if i % 3 == 0:
            if part.strip():
                st.markdown(part)
        elif i % 3 == 1:
            alt = part
        else:
            ruta = (base_dir / part).resolve()
            if ruta.is_file():
                st.image(str(ruta), caption=alt)
            else:
                st.markdown(f"![{alt}]({part})")


def _render_con_grafo(contenido: str, base_dir: Path) -> None:
    """Renderiza el contenido markdown insertando el grafo en el bloque Mermaid."""
    inicio = contenido.find("```mermaid")
    fin = contenido.find("```", inicio + len("```mermaid"))
    if inicio == -1 or fin == -1:
        _render_markdown(contenido, base_dir)
        return
    antes = contenido[:inicio]
    despues = contenido[fin + 3:]
    if antes.strip():
        _render_markdown(antes, base_dir)
    st.html(proceso_agente_html())
    if despues.strip():
        _render_markdown(despues, base_dir)


def render_documentacion() -> None:
    """Renderiza la página de Documentación."""
    st.title("Documentación")

    docs = _descubrir_docs()
    if not docs:
        st.info("No se encontraron documentos en docs/.")
        return

    etiqueta = st.selectbox(
        "Documento",
        [e for e, _ in docs],
        key="doc_selector",
    )
    ruta = dict(docs)[etiqueta]

    try:
        contenido = ruta.read_text(encoding="utf-8")
    except OSError as e:
        st.error(f"No se pudo leer {ruta.name}: {e}")
        return

    if ruta.name == "architecture.md":
        _render_con_grafo(contenido, ruta.parent)
    else:
        _render_markdown(contenido, ruta.parent)

    st.divider()
    st.caption(f"Fuente: `{ruta}`")


render_documentacion()
