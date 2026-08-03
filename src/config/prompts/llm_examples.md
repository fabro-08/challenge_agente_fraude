--- EJEMPLOS ---

Ejemplo 1 - APROBAR:
Reclamo: "Llegó comida diferente, creo que confundieron mi pedido."
Contexto: 2 reclamos en 90d, 0 flags fraude, antiguedad 1590d, GPS SÍ - confirmada.
Reglas evaluadas: A2 (usuario_sano), A3 (gps_ok_sano)
Señales detectadas: ninguna
Output: {"justificacion": "Usuario con 0 flags y 4+ años de antigüedad. El relato es coherente y no hay señales de abuso.", "señales_explicadas": [{"señal": "historial_intachable", "explicacion": "Usuario con más de 4 años en la plataforma y 0 flags", "peso": "alto"}, {"señal": "frecuencia_reclamos_normal", "explicacion": "2 reclamos en 90 días es aceptable para su antigüedad", "peso": "medio"}], "resumen": "Error operativo del restaurante en usuario confiable.", "veredicto": "APROBAR"}

Ejemplo 2 - RECHAZAR:
Reclamo: "Nunca llegó mi pedido, quiero reembolso completo."
Contexto: 5 reclamos en 90d, 1 flag fraude, antiguedad 45d, GPS SÍ - confirmada.
Reglas evaluadas: R5 (inconsistencia_gps), R6 (account_abuse)
Señales detectadas: inconsistencia GPS, cuenta nueva con abuso
Output: {"justificacion": "El GPS confirma la entrega pero el usuario alega no recibirlo. Además, es una cuenta nueva con un volumen de reclamos inaceptable.", "señales_explicadas": [{"señal": "descripcion_incoherente", "explicacion": "Usuario reclama que no llegó pero el GPS confirma la entrega", "peso": "alto"}, {"señal": "account_abuse", "explicacion": "Cuenta de 45 días con 5 reclamos y 1 flag previo", "peso": "alto"}], "resumen": "Contradicción entre reclamo y evidencia GPS en cuenta nueva abusiva.", "veredicto": "RECHAZAR"}

Ejemplo 3 - ESCALAR:
Reclamo: "La comida me cayó mal y tuve que ir al hospital, exijo compensación o voy a demandar"
Contexto: 1 reclamo en 90d, 0 flags fraude, antiguedad 365d, GPS SÍ - confirmada.
Reglas evaluadas: ESCALAR-1 (palabras_criticas)
Señales detectadas: palabras críticas (hospital, demandar)
Output: {"justificacion": "El reclamo menciona términos de riesgo de salud y legal (hospital, demandar) que requieren revisión humana obligatoria.", "señales_explicadas": [{"señal": "palabras_criticas_seguridad", "explicacion": "Menciona 'hospital' y 'demandar' en el texto del reclamo", "peso": "alto"}], "resumen": "Reclamo con implicaciones legales y de salud.", "veredicto": "ESCALAR"}