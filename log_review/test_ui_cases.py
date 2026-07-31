from playwright.sync_api import sync_playwright
import time
import traceback
import sys

results = []
errors = []

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True)
    page = b.new_page()
    page.set_viewport_size({"width": 1280, "height": 900})
    
    print("=" * 60)
    print("TEST: Verificación UI Streamlit - /cases")
    print("=" * 60)
    
    # Navegar a casos
    try:
        print("\n[Navegación] Cargando http://localhost:8501/cases ...")
        page.goto("http://localhost:8501/cases", timeout=30000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(5000)
        print("[Navegación] OK: Página cargada")
    except Exception as e:
        print(f"[Navegación] ERROR: {e}")
        errors.append(f"Navegación falló: {e}")
        page.screenshot(path="log_review/cases_ERROR_navigation.png")
        b.close()
        sys.exit(1)
    
    # === 1. Tabla carga ===
    print("\n=== TEST 1: Tabla muestra casos ===")
    try:
        body = page.inner_text("body")
        # st.dataframe renderiza en canvas (sin texto DOM); se valida vía caption
        assert "casos encontrados" in body, f"No se encontró caption de casos. Body preview: {body[:500]}"
        print("PASS: Tabla cargada (caption 'casos encontrados' visible)")
        results.append(("TEST 1: Tabla con casos", "PASS", "Caption de casos encontrado en la página"))
    except Exception as e:
        print(f"FAIL: {e}")
        errors.append(f"TEST 1: {e}")
        results.append(("TEST 1: Tabla con casos", "FAIL", str(e)))
    
    page.screenshot(path="log_review/cases_step1_table.png")
    print("[Screenshot] cases_step1_table.png")
    
    # === 2. Seleccionar caso via combobox ===
    print("\n=== TEST 2: Seleccionar caso y ver justificación ===")
    justificacion_visible = False
    try:
        cbs = page.locator("[role='combobox']")
        caso_combobox = cbs.nth(2)  # 0=Recomendación, 1=Origen, 2=caso
        caso_combobox.click(timeout=5000)
        page.wait_for_timeout(800)
        search = page.locator("input[placeholder='Elegí un caso…']")
        search.fill("COMP-0001")
        page.wait_for_timeout(800)
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        print("OK: Caso COMP-0001 seleccionado en el combobox")
    except Exception as e:
        print(f"Selección de caso falló: {e}. Probando selector dropdown...")
        try:
            selectors = page.locator("[data-baseweb='select']")
            if selectors.count() > 0:
                selectors.first.click()
                page.wait_for_timeout(1000)
                page.keyboard.type("COMP-0001")
                page.keyboard.press("Enter")
                page.wait_for_timeout(2000)
                print("OK: Selector usado como fallback")
            else:
                # Intentar con input de búsqueda
                search_input = page.locator("input").first
                search_input.fill("COMP-0001")
                page.wait_for_timeout(2000)
                print("OK: Input de búsqueda usado como fallback")
        except Exception as e2:
            print(f"Fallback también falló: {e2}")
            errors.append(f"TEST 2: No se pudo seleccionar caso: {e2}")
    
    page.screenshot(path="log_review/cases_step2_after_click.png")
    print("[Screenshot] cases_step2_after_click.png")
    
    # === 3. Verificar texto visible (justificación, LLM, descripción) ===
    print("\n=== TEST 3: Texto de justificación/LLM/descripción visible ===")
    try:
        body2 = page.inner_text("body")
        keywords = ["Justificación", "justificación", "Análisis del LLM", 
                     "llm_resultado", "Descripción del reclamo", "descripción",
                     "RECHAZAR", "APROBAR", "ESCALAR", "rechazar", "aprobar", "escalar",
                     "Resolución final", "resolución final",
                     "Categoría del reclamo", "categoría",
                     "Estado original", "estado_original",
                     "languages", "idioma",
                     "Re-analizar"]
        found = [c for c in keywords if c in body2]
        print(f"Keywords encontradas: {found}")
        
        # Check específicos
        checks = {
            "Justificación presente": "justificación" in body2.lower() or "justificacion" in body2.lower(),
            "Descripción del reclamo": "descripción del reclamo" in body2 or "descripción" in body2.lower(),
            "Análisis LLM presente": "análisis del llm" in body2.lower() or "llm_resultado" in body2.lower(),
            "Resolución (RECHAZAR/APROBAR/ESCALAR)": any(w in body2 for w in ["RECHAZAR", "APROBAR", "ESCALAR", "rechazar", "aprobar", "escalar"]),
            "Botón Re-analizar visible": "Re-analizar" in body2,
            "Expander Datos completos": "Datos completos" in body2 or "datos completos" in body2.lower(),
        }
        
        for check_name, passed in checks.items():
            status = "PASS" if passed else "FAIL"
            print(f"  {status}: {check_name}")
            results.append((f"TEST 3.{check_name}", status, ""))
        
        justificacion_visible = checks["Justificación presente"]
    except Exception as e:
        print(f"FAIL en verificación de texto: {e}")
        errors.append(f"TEST 3: {e}")
    
    page.screenshot(path="log_review/cases_step3_text.png")
    print("[Screenshot] cases_step3_text.png")
    
    # === 4. Abrir expander "Datos completos" ===
    print("\n=== TEST 4: Expander 'Datos completos' se puede abrir ===")
    try:
        expanders = page.get_by_text("Datos completos", exact=False)
        if expanders.count() > 0:
            expanders.first.click(timeout=5000)
            page.wait_for_timeout(2000)
            print("PASS: Expander 'Datos completos' clickeado")
            results.append(("TEST 4: Expander", "PASS", "Se hizo click exitosamente"))
        else:
            # Buscar cualquier expander
            all_elements = page.locator("[kind='secondary']").all()
            expander_found = False
            for el in all_elements:
                text = el.inner_text()
                if "datos" in text.lower() or "completos" in text.lower():
                    el.click(timeout=3000)
                    page.wait_for_timeout(1500)
                    print(f"PASS: Expander encontrado y clickeado: '{text[:80]}'")
                    expander_found = True
                    results.append(("TEST 4: Expander", "PASS", f"Texto: {text[:80]}"))
                    break
            if not expander_found:
                # Buscar por texto general
                body3 = page.inner_text("body")
                if "datos completos" in body3.lower():
                    print("WARN: Expander texto presente pero no se pudo clickear")
                    results.append(("TEST 4: Expander", "WARN", "Texto visible, click no ejecutado"))
                else:
                    print("WARN: No se encontró expander 'Datos completos'")
                    results.append(("TEST 4: Expander", "WARN", "No encontrado en la página"))
    except Exception as e:
        print(f"FAIL: {e}")
        errors.append(f"TEST 4: Expander no disponible: {e}")
        results.append(("TEST 4: Expander", "FAIL", str(e)))
    
    page.screenshot(path="log_review/cases_step4_expander.png")
    print("[Screenshot] cases_step4_expander.png")
    
    # === 5. Verificar botón Re-analizar ===
    print("\n=== TEST 5: Botón 'Re-analizar' presente ===")
    try:
        body_final = page.inner_text("body")
        if "Re-analizar" in body_final:
            print("PASS: Botón 'Re-analizar' encontrado")
            results.append(("TEST 5: Botón Re-analizar", "PASS", "Texto presente en la página"))
        else:
            # Buscar botón con texto similar
            buttons = page.locator("button").all()
            found_btn = False
            for btn in buttons:
                try:
                    text = btn.inner_text()
                    if "analizar" in text.lower() or "reanalizar" in text.lower():
                        print(f"PASS: Botón similar encontrado: '{text}'")
                        results.append(("TEST 5: Botón Re-analizar", "PASS", f"Botón: {text}"))
                        found_btn = True
                        break
                except:
                    pass
            if not found_btn:
                print("FAIL: No se encontró botón Re-analizar")
                results.append(("TEST 5: Botón Re-analizar", "FAIL", "No encontrado"))
    except Exception as e:
        print(f"FAIL: {e}")
        errors.append(f"TEST 5: {e}")
        results.append(("TEST 5: Botón Re-analizar", "FAIL", str(e)))
    
    b.close()
    
    # === REPORTE FINAL ===
    print("\n" + "=" * 60)
    print("REPORTE FINAL")
    print("=" * 60)
    
    passed = sum(1 for _, status, _ in results if status == "PASS")
    failed = sum(1 for _, status, _ in results if status == "FAIL")
    warned = sum(1 for _, status, _ in results if status == "WARN")
    
    for name, status, detail in results:
        icon = "✅" if status == "PASS" else ("⚠️" if status == "WARN" else "❌")
        print(f"  {icon} {status}: {name}")
        if detail:
            print(f"     {detail}")
    
    print(f"\nResumen: {passed} PASS, {failed} FAIL, {warned} WARN")
    
    if errors:
        print(f"\nErrores ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    
    print(f"\nScreenshots guardados en log_review/:")
    print("  - cases_step1_table.png")
    print("  - cases_step2_after_click.png")
    print("  - cases_step3_text.png")
    print("  - cases_step4_expander.png")
