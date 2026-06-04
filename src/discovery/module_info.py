from __future__ import annotations

from typing import Optional

from src.mcp.ce_client import CEClient


async def get_module_base(ce: CEClient, module_name: str) -> Optional[int]:
    """
    Returns the runtime base address of a loaded module.
    Uses CE enum_modules which returns all DLLs with their base addresses.
    """
    modules = await ce.list_modules()
    lower = module_name.lower()
    for mod in modules:
        # CE returns: {name, address, path, size, is_64bit}
        name = mod.get("name", mod.get("moduleName", "")).lower()
        if name == lower or name.endswith(f"\\{lower}") or name.endswith(f"/{lower}"):
            # "address" is the CE key; fall back to legacy "baseAddress"/"base"
            raw = mod.get("address", mod.get("baseAddress", mod.get("base", "0x0")))
            return int(raw, 16) if isinstance(raw, str) else int(raw)
    return None


def live_to_static(live_addr: int | str, module_base: int) -> int:
    if isinstance(live_addr, str):
        live_addr = int(live_addr, 16)
    return live_addr - module_base


def fmt_offset(offset: int) -> str:
    return hex(offset)


def parse_addr(addr: str) -> int:
    addr = addr.strip()
    if addr.startswith("0x") or addr.startswith("0X"):
        return int(addr, 16)
    # Try decimal
    try:
        return int(addr)
    except ValueError:
        return int(addr, 16)
