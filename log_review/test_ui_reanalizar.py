"""E2E: botón 'Re-analizar' en /cases — valida el flujo completo sin error de timeout.

Cubre el fix de api_client (ANALYZE_TIMEOUT=120s): selecciona un caso ambiguo
(ESCALAR → LLM, ~15-25s), clickea 'Re-analizar' y verifica que aparezca
'Análisis completado' en vez de 'Error al re-analizar'.
"""

from playwright.sync_api import sync_playwright
import sys

URL = "http://localhost:8501/cases"
CASO_AMBIGUO = "COMP-0001"  # va al LLM (~16-24s)

results = []

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})

    # ── Navegar ─────────────────────────────────────────────────────
    try:
        page.goto(URL, timeout=30000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)
        results.append(("Navegación /cases", "PASS", "Página cargada"))
    except Exception as e:
        results.append(("Navegación /cases", "FAIL", str(e)))
        page.screenshot(path="log_review/reanalizar_ERROR_nav.png")
        b.close()
        print("ERROR de navegación:", e)
        sys.exit(1)

    # ── Seleccionar caso ambiguo ────────────────────────────────────
    try:
        cbs = page.locator("[role='combobox']")
        caso_combobox = cbs.nth(2)  # 0=Recomendación, 1=Origen, 2=caso
        caso_combobox.click(timeout=5000)
        page.wait_for_timeout(800)
        search = page.locator("input[placeholder='Elegí un caso…']")
        search.fill(CASO_AMBIGUO)
        page.wait_for_timeout(800)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        results.append(("Selección de caso", "PASS", f"Seleccionado {CASO_AMBIGUO}"))
    except Exception as e:
        results.append(("Selección de caso", "FAIL", str(e)))

    body = page.inner_text("body")
    if CASO_AMBIGUO in body:
        results.append(("Caso visible en detalle", "PASS", f"{CASO_AMBIGUO} presente"))
    else:
        results.append(("Caso visible en detalle", "FAIL", "No aparece en el detalle"))
    page.screenshot(path="log_review/reanalizar_step1_seleccion.png")

    # ── Click en 'Re-analizar' ──────────────────────────────────────
    try:
        btn = page.get_by_text("Re-analizar", exact=False).first
        btn.click(timeout=5000)
        results.append(("Click en Re-analizar", "PASS", "Botón clickeado"))
    except Exception as e:
        results.append(("Click en Re-analizar", "FAIL", str(e)))

    # ── Esperar resultado (hasta 90s; el análisis LLM tarda ~16-25s) ─
    page.screenshot(path="log_review/reanalizar_step2_click.png")
    exito = False
    error_visto = False
    try:
        page.wait_for_function(
            "() => document.body.innerText.includes('Análisis completado') || "
            "document.body.innerText.includes('Error al re-analizar')",
            timeout=90000,
        )
        body_final = page.inner_text("body")
        exito = "Análisis completado" in body_final
        error_visto = "Error al re-analizar" in body_final
    except Exception as e:
        results.append(("Espera de resultado", "FAIL", f"Timeout sin resultado: {e}"))

    if exito:
        results.append(("Resultado del análisis", "PASS", "'Análisis completado' visible"))
    elif error_visto:
        results.append(("Resultado del análisis", "FAIL", "'Error al re-analizar' visible"))
    else:
        results.append(("Resultado del análisis", "FAIL", "Sin mensaje de éxito ni error"))

    page.screenshot(path="log_review/reanalizar_step3_resultado.png")

    # ── Verificar que la decisión se refrescó ───────────────────────
    body_final = page.inner_text("body")
    decision_visible = any(d in body_final for d in ("APROBAR", "RECHAZAR", "ESCALAR"))
    results.append(
        ("Decisión refrescada", "PASS" if decision_visible else "FAIL", "APROBAR/RECHAZAR/ESCALAR en pantalla")
    )

    b.close()

# ── Reporte ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("REPORTE — Botón Re-analizar")
print("=" * 60)
for name, status, detail in results:
    icon = "✅" if status == "PASS" else "❌"
    print(f"  {icon} {status}: {name}")
    if detail:
        print(f"     {detail}")

failed = sum(1 for _, s, _ in results if s == "FAIL")
print(f"\nResumen: {len(results) - failed} PASS, {failed} FAIL")
print("Screenshots en log_review/: reanalizar_step{1,2,3}_*.png")
sys.exit(1 if failed else 0)
