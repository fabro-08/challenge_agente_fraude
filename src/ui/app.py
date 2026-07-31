"""App Streamlit — UI para agentes CS de Rappi Caso 03.

Usa ``st.navigation`` nativo para 4 páginas: Dashboard, Explorar Casos,
Reglas de Decisión y Políticas. Sin entradas extra en el sidebar.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    layout="wide",
    page_title="Rappi — Revisión de Compensaciones",
    page_icon="🛵",
)

# ── CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
    body { font-family: 'Inter', sans-serif; }
    .stApp { font-family: 'Inter', sans-serif; }

    section[data-testid="stSidebar"] {
        background-color: #1e1e1e;
    }

    .badge-APROBAR, .badge-RECHAZAR, .badge-ESCALAR, .badge-PENDIENTE {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 14px;
        color: white;
    }
    .badge-APROBAR { background-color: #28a745; }
    .badge-RECHAZAR { background-color: #dc3545; }
    .badge-ESCALAR { background-color: #fd7e14; }
    .badge-PENDIENTE { background-color: #6c757d; }
    .badge-ESCALAR_FORZOSO { background-color: #fd7e14; }
</style>
""",
    unsafe_allow_html=True,
)

# ── Branding en sidebar ────────────────────────────────────────────────
with st.sidebar:
    st.image(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/9/96/Rappi_logo.svg/200px-Rappi_logo.svg.png",
        width=120,
    )
    st.title("Rappi")
    st.markdown("**Revisión de Compensaciones**")
    st.divider()
    st.caption("Caso 03 — Agente de Decisión")
    st.caption("Fraude & Compensaciones CX")

# ── Navegación nativa (sin "app", sin selectbox) ──────────────────────
dashboard = st.Page("pages/dashboard.py", title="Dashboard", icon="📊")
cases = st.Page("pages/cases.py", title="Explorar Casos", icon="🔍")
rules = st.Page("pages/rules.py", title="Reglas de Decisión", icon="⚙️")
policies = st.Page("pages/policies.py", title="Políticas", icon="📋")

pg = st.navigation([dashboard, cases, rules, policies])
pg.run()
