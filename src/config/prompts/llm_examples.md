--- EJEMPLOS ---

Ejemplo 1 - APROBAR:
Reclamo: "Llegó comida diferente, creo que confundieron mi pedido."
Contexto: 2 reclamos en 90d, 0 flags fraude, antiguedad 1590d, GPS NO confirmada.
Reglas evaluadas: A2 (usuario_sano), A3 (gps_ok_sano)
Señales detectadas: ninguna
Output: {"justificacion": "Usuario con 0 flags y 4+ años de antigüedad. Reclamo sin señales de fraude.", "resumen": "Error operativo del restaurante en usuario confiable.", "veredicto": "APROBAR: reclamo legítimo de un usuario sin historial de fraude.", "señales_explicadas": [{"señal": "descripcion_incoherente", "explicacion": "la descripción no aplica, perfil confiable sin señales", "peso": "bajo"}]}

Ejemplo 2 - RECHAZAR:
Reclamo: "Nunca llegó mi pedido aunque el GPS dice que llegó, quiero reembolso completo"
Contexto: 5 reclamos en 90d, 1 flag fraude, antiguedad 45d, GPS SÍ - confirmada.
Reglas evaluadas: R5 (inconsistencia_gps), R6 (account_abuse)
Señales detectadas: inconsistencia GPS, cuenta nueva con abuso
Output: {"justificacion": "GPS confirma entrega pero usuario dice no recibir. Cuenta nueva con alta frecuencia de reclamos.", "resumen": "Contradicción entre reclamo y evidencia GPS en cuenta nueva abusiva.", "veredicto": "RECHAZAR: inconsistencia con GPS y patrón de abuso en cuenta nueva.", "señales_explicadas": [{"señal": "entrega_gps_no_confirmada", "explicacion": "Usuario reclama no llegó pero GPS confirma entrega", "peso": "alto"}, {"señal": "account_abuse", "explicacion": "antiguedad=45d, 5 reclamos en 90d", "peso": "medio"}]}

Ejemplo 3 - ESCALAR:
Reclamo: "La comida me cayó mal y tuve que ir al hospital, exijo compensación o voy a demandar"
Contexto: 1 reclamo en 90d, 0 flags fraude, antiguedad 365d, GPS SÍ - confirmada.
Reglas evaluadas: ESCALAR-1 (palabras_criticas)
Señales detectadas: palabras críticas (hospital, demandar)
Output: {"justificacion": "El reclamo menciona términos de riesgo legal (hospital, demandar) que requieren revisión humana.", "resumen": "Reclamo con implicaciones legales y de salud que no debe automatizarse.", "veredicto": "ESCALAR: contiene palabras críticas que requieren revisión humana.", "señales_explicadas": [{"señal": "palabras_criticas_seguridad", "explicacion": "menciona 'hospital' y 'demandar' en el reclamo", "peso": "alto"}]}
