"""Circuit breaker del proveedor LLM (fail-fast anti-flood).

Cuando el proveedor (OpenRouter) está caído o la API key se agotó, cada caso
ambiguo dispararía una llamada que va a fallar igual → flood de llamadas,
consumo de crédito/tiempo y ruido. Este "fusible" corta las llamadas si hay
muchos fallos de proveedor en una ventana corta, degradando a ESCALAR
directamente (revisión manual) hasta que el proveedor se recupere.

Estados:
- cerrado: se llama al proveedor normalmente.
- abierto: no se llama al proveedor; se degrada.
- half-open: tras la ventana se permite 1 intento de prueba; si funciona,
  el fusible vuelve a cerrarse.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class CircuitProveedor:
    """Fusible de corte por fallos de proveedor. Thread-safe."""

    def __init__(self, umbral: int = 3, ventana_s: float = 60.0) -> None:
        self.umbral = max(1, int(umbral))
        self.ventana_s = max(1.0, float(ventana_s))
        self._lock = threading.Lock()
        self._fallos: deque[float] = deque()
        self.abierto = False

    def registrar_fallo(self) -> None:
        """Registra un fallo de proveedor y abre el fusible si se supera el umbral."""
        now = time.monotonic()
        with self._lock:
            while self._fallos and self._fallos[0] < now - self.ventana_s:
                self._fallos.popleft()
            self._fallos.append(now)
            if len(self._fallos) >= self.umbral:
                self.abierto = True

    def registrar_exito(self) -> None:
        """Un éxito resetea el conteo y cierra el fusible."""
        with self._lock:
            self._fallos.clear()
            self.abierto = False

    def permitido(self) -> bool:
        """True si se puede llamar al proveedor (estado cerrado o half-open)."""
        with self._lock:
            if not self.abierto:
                return True
            # Half-open: reintenta 1 intento tras una ventana sin fallos.
            if self._fallos and (time.monotonic() - self._fallos[-1]) >= self.ventana_s:
                self.abierto = False
                self._fallos.clear()
                return True
            return False

    def estado(self) -> str:
        with self._lock:
            return "abierto" if self.abierto else "cerrado"


# Instancia global compartida por el proceso (configurable desde model.yaml).
INSTANCIA = CircuitProveedor()
