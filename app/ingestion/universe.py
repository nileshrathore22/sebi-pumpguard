from pathlib import Path

import yaml

from app.core.logging import get_logger

log = get_logger(__name__)


def load_universe(path: Path) -> list[str]:
    data = yaml.safe_load(path.read_text())
    symbols = [str(s).strip().upper() for s in data.get("symbols", []) if str(s).strip()]
    if not data.get("confirmed", False):
        log.warning("universe not yet confirmed by a human", extra={"path": str(path)})
    if len(set(symbols)) != len(symbols):
        raise ValueError("duplicate symbols in universe")
    return symbols
