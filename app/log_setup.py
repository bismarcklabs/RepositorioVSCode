"""Configuración centralizada de logging con rotación de archivos.

Llama a setup_logging() una vez al arrancar el proceso.
Crea tres archivos en logs/:
  - app.log      — todo INFO+
  - alerts.log   — solo mensajes del namespace "dashboard" y notificaciones
  - database.log — solo mensajes del namespace "database"
"""

import logging
import logging.handlers
from pathlib import Path

_configured = False


class _NamespaceFilter(logging.Filter):
    def __init__(self, prefixes: list):
        super().__init__()
        self.prefixes = prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(record.name.startswith(p) for p in self.prefixes)


def setup_logging(log_dir: str = "logs") -> None:
    global _configured
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

    # ── Consola ──────────────────────────────────────────────────────────
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # ── app.log — todo INFO+ ──────────────────────────────────────────────
    app_h = logging.handlers.RotatingFileHandler(
        f"{log_dir}/app.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    app_h.setLevel(logging.INFO)
    app_h.setFormatter(fmt)
    root.addHandler(app_h)

    # ── alerts.log — dashboard + notificaciones ───────────────────────────
    alerts_h = logging.handlers.RotatingFileHandler(
        f"{log_dir}/alerts.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    alerts_h.setLevel(logging.INFO)
    alerts_h.setFormatter(fmt)
    alerts_h.addFilter(_NamespaceFilter(["dashboard", "app.notifications", "outcome_tracker"]))
    root.addHandler(alerts_h)

    # ── database.log — solo DB ────────────────────────────────────────────
    db_h = logging.handlers.RotatingFileHandler(
        f"{log_dir}/database.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    db_h.setLevel(logging.INFO)
    db_h.setFormatter(fmt)
    db_h.addFilter(_NamespaceFilter(["database"]))
    root.addHandler(db_h)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("streamlit").setLevel(logging.WARNING)
