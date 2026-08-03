"""Grafo HTML/CSS reutilizable del proceso del agente (offline, sin deps)."""

from __future__ import annotations


def proceso_agente_html() -> str:
    """Devuelve el diagrama HTML/CSS del pipeline de decisión.

    Flujo: ``load_case → compute_features → apply_rules`` y las tres vías
    (APROBAR/RECHAZAR por reglas, ESCALAR forzoso y AMBIGUO). Fuente de verdad
    en ``src/pipeline/graph.py``.
    """
    css = """
    .pag-flow { display:flex; flex-direction:column; align-items:center; gap:8px;
                font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }
    .pag-node { border:1px solid #d0d7de; border-radius:8px; padding:8px 18px;
                background:#f6f8fa; font-size:14px; font-weight:600; color:#24292f; }
    .pag-node b { color:#57606a; font-weight:500; }
    .pag-arrow { color:#57606a; font-size:14px; line-height:1; }
    .pag-branch { display:flex; gap:14px; justify-content:center; width:100%; flex-wrap:wrap; }
    .pag-card { border:1px solid #d0d7de; border-radius:8px; padding:8px 12px; width:230px;
                background:#ffffff; box-shadow:0 1px 2px rgba(0,0,0,.04); }
    .pag-card .t { font-weight:600; font-size:13px; }
    .pag-card .d { font-size:11px; color:#57606a; margin-top:2px; }
    .ok { border-left:4px solid #2da44e; } .no { border-left:4px solid #cf222e; }
    .esc{ border-left:4px solid #d4760a; } .llm{ border-left:4px solid #8250df; }
    """
    return f"""
    <style>{css}</style>
    <div class="pag-flow">
      <div class="pag-node">load_case</div>
      <div class="pag-arrow">▼</div>
      <div class="pag-node">compute_features</div>
      <div class="pag-arrow">▼</div>
      <div class="pag-node">apply_rules <b>(thresholds.yaml)</b></div>
      <div class="pag-arrow">▼</div>
      <div class="pag-branch">
        <div class="pag-card ok">
          <div class="t">APROBAR / RECHAZAR</div>
          <div class="d">regla concluyente · sin LLM · fuente=reglas</div>
        </div>
        <div class="pag-card esc">
          <div class="t">ESCALAR forzoso</div>
          <div class="d">palabras críticas · → LLM aporta análisis · fuente=reglas</div>
        </div>
        <div class="pag-card llm">
          <div class="t">AMBIGUO</div>
          <div class="d">→ LLM decide · fuente=llm</div>
        </div>
      </div>
      <div class="pag-arrow">▼</div>
      <div class="pag-node">llm_classify <b>(solo ESCALAR forzoso y AMBIGUO)</b></div>
      <div class="pag-arrow">▼</div>
      <div class="pag-node">final_decision <b>(APROBAR · RECHAZAR · ESCALAR)</b></div>
      <div class="pag-arrow">▼</div>
      <div class="pag-node">generate_output <b>(justificación + señales + checklist)</b></div>
      <div class="pag-arrow">▼</div>
      <div class="pag-node">persistir resolution_case / fila demo <b>(batch durable)</b></div>
    </div>
    """
