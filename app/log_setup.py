"""Configuración centralizada de logging con rotación de archivos.

Llama a setup_logging() una vez al arrancar el proceso.
Crea tres archivos en logs/:
  - app.log      — todo INFO+
  - alerts.log   — solo mensajes del namespace "dashboard" y notificaciones
  - database.log — solo mensajes del namespace "database"

Arquitectura thread-safe (Windows):
  Todos los hilos escriben a un QueueHandler (queue.Queue thread-safe).
  Un QueueListener dedicado drena la cola y escribe a los RotatingFileHandlers
  desde un único hilo de fondo — elimina el WinError 32 en doRollover().
"""

import logging
import logging.handlers
import queue
from pathlib import Path

_configured = False
_listener: logging.handlers.QueueListener | None = None


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler que ignora WinError 32 cuando otro proceso tiene el archivo abierto."""
    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            pass  # otro proceso (ej. dashboard) tiene app.log abierto → saltar rotación


class _NamespaceFilter(logging.Filter):
    def __init__(self, prefixes: list):
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(record.name.startswith(p) for p in self.prefixes)


def setup_logging(log_dir: str = "logs") -> None:
    global _configured, _listener
    if _configured:
        return
    _configured = True

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # ── Consola (escribe directamente — no necesita cola) ─────────────────
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # ── File handlers (solo los usa el QueueListener, no el root) ─────────
    app_h = _SafeRotatingFileHandler(
        f"{log_dir}/app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    app_h.setLevel(logging.INFO)
    app_h.setFormatter(fmt)

    alerts_h = _SafeRotatingFileHandler(
        f"{log_dir}/alerts.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    alerts_h.setLevel(logging.INFO)
    alerts_h.setFormatter(fmt)
    alerts_h.addFilter(_NamespaceFilter(["dashboard", "app.notifications", "outcome_tracker"]))

    db_h = _SafeRotatingFileHandler(
        f"{log_dir}/database.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    db_h.setLevel(logging.INFO)
    db_h.setFormatter(fmt)
    db_h.addFilter(_NamespaceFilter(["database"]))

    # ── Cola thread-safe → un solo hilo escribe a disco ───────────────────
    log_queue: queue.Queue = queue.Queue(maxsize=-1)  # sin límite
    queue_h = logging.handlers.QueueHandler(log_queue)
    queue_h.setLevel(logging.INFO)
    root.addHandler(queue_h)

    _listener = logging.handlers.QueueListener(
        log_queue, app_h, alerts_h, db_h,
        respect_handler_level=True,
    )
    _listener.start()

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("streamlit").setLevel(logging.WARNING)


def stop_logging() -> None:
    """Detiene el QueueListener limpiamente al cerrar el proceso."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None
