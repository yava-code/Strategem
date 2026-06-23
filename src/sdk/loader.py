from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from src.sdk.annotations import bm


def load_adapter(path: str | Path, *, reset: bool = True) -> ModuleType:
    adapter_path = Path(path).resolve()
    if not adapter_path.exists():
        raise FileNotFoundError(f"Adapter not found: {adapter_path}")
    if reset:
        bm.reset_registry()

    digest = hashlib.sha1(str(adapter_path).encode("utf-8")).hexdigest()[:10]
    module_name = f"bridge_adapter_{adapter_path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, adapter_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load adapter module: {adapter_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
