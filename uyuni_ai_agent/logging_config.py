import logging


def setup_logging(level="INFO"):
    """Configure root logger with a standard format.

    Call once at application startup (main.py).
    Level can be overridden via settings.yaml `logging.level`.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
