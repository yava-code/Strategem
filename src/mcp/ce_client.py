from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# MCP SDK import — optional; falls back to a stub that raises clearly.
# ---------------------------------------------------------------------------
try:
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters
    _MCP_OK = True
except ImportError:
    _MCP_OK = False

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    address: str
    value: str

@dataclass
class ScanPage:
    total: int
    results: list[ScanResult]

@dataclass
class PointerStep:
    depth: int
    address: str
    value: Any

@dataclass
class StructField:
    offset: int
    guessed_type: str
    value: Any

@dataclass
class RawStruct:
    base_address: str
    fields: list[StructField]

@dataclass
class AttachResult:
    success: bool
    process_id: Optional[int]
    process_name: Optional[str]

@dataclass
class AoBResult:
    count: int
    addresses: list[str]


# ---------------------------------------------------------------------------
# CEClient
# ---------------------------------------------------------------------------

class CEClient:
    """
    Async context manager that maintains a persistent stdio session
    with the Cheat Engine MCP bridge (mcp_cheatengine.py).

    Usage:
        async with CEClient(server_path="D:/CE/.../mcp_cheatengine.py") as ce:
            await ce.attach("Game.exe")
            await ce.scan("100.0", scan_type="float")
    """

    def __init__(
        self,
        server_path: str,
        python_exe: str = sys.executable,
    ):
        if not _MCP_OK:
            raise ImportError("mcp package not installed. Run: pip install mcp>=1.5.0")
        if not os.path.isfile(server_path):
            raise FileNotFoundError(f"CE MCP server not found: {server_path}")

        self._params = StdioServerParameters(
            command=python_exe,
            args=[server_path],
        )
        self._session: Optional[ClientSession] = None
        self._stdio_ctx = None
        self._session_ctx = None

    async def __aenter__(self) -> "CEClient":
        self._stdio_ctx = stdio_client(self._params)
        read, write = await self._stdio_ctx.__aenter__()
        self._session_ctx = ClientSession(read, write)
        self._session = await self._session_ctx.__aenter__()
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session_ctx:
            await self._session_ctx.__aexit__(*exc)
        if self._stdio_ctx:
            await self._stdio_ctx.__aexit__(*exc)

    async def _call(self, tool: str, **kwargs: Any) -> dict:
        if self._session is None:
            raise RuntimeError("CEClient not connected — use as async context manager")
        result = await self._session.call_tool(tool, kwargs)
        if result.isError:
            content = result.content[0].text if result.content else "unknown error"
            raise RuntimeError(f"CE tool '{tool}' returned error: {content}")
        raw = result.content[0].text if result.content else "{}"
        return json.loads(raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def attach(self, process_name_or_pid: str) -> AttachResult:
        data = await self._call("open_process", process_id_or_name=process_name_or_pid)
        return AttachResult(
            success=data.get("success", False),
            process_id=data.get("process_id"),
            process_name=data.get("process_name"),
        )

    async def scan(
        self,
        value: str,
        scan_type: str = "float",
        protection: str = "+W-C",
    ) -> int:
        """First scan. Returns candidate count."""
        data = await self._call("scan_all", value=value, type=scan_type, protection=protection)
        return data.get("count", 0)

    async def refine(self, value: str, mode: str = "exact") -> int:
        """Next scan round. Returns remaining candidate count."""
        data = await self._call("next_scan", value=value, scan_type=mode)
        return data.get("count", 0)

    async def results(self, limit: int = 100, offset: int = 0) -> ScanPage:
        data = await self._call("get_scan_results", limit=limit, offset=offset)
        items = [
            ScanResult(address=r.get("address", ""), value=r.get("value", ""))
            for r in data.get("results", [])
        ]
        return ScanPage(total=data.get("total", len(items)), results=items)

    async def pointer_rescan(self, value: str, previous_file: Optional[str] = None) -> int:
        kwargs: dict = {"value": value}
        if previous_file:
            kwargs["previous_results_file"] = previous_file
        data = await self._call("pointer_rescan", **kwargs)
        return data.get("result_count", 0)

    async def read_chain(self, base: str, offsets: list[int]) -> list[PointerStep]:
        data = await self._call("read_pointer_chain", base=base, offsets=offsets)
        steps = []
        for i, step in enumerate(data.get("chain", [])):
            steps.append(PointerStep(
                depth=i,
                address=step.get("address", ""),
                value=step.get("value"),
            ))
        return steps

    async def dissect(self, address: str, size: int = 256) -> RawStruct:
        data = await self._call("dissect_structure", address=address, size=size)
        fields = [
            StructField(
                offset=f.get("offset", 0),
                guessed_type=f.get("type", "unknown"),
                value=f.get("value"),
            )
            for f in data.get("fields", [])
        ]
        return RawStruct(base_address=address, fields=fields)

    async def rtti(self, address: str) -> Optional[str]:
        data = await self._call("get_rtti_classname", address=address)
        return data.get("classname") or data.get("class_name")

    async def aob_module(
        self,
        pattern: str,
        module_name: str,
        protection: str = "+X",
    ) -> AoBResult:
        data = await self._call(
            "aob_scan_module",
            pattern=pattern,
            module_name=module_name,
            protection=protection,
        )
        return AoBResult(
            count=data.get("count", 0),
            addresses=data.get("addresses", []),
        )

    async def module_base(self, module_name: str) -> Optional[int]:
        """Return the runtime base address of a loaded module."""
        data = await self._call("get_symbol_address", symbol=module_name)
        addr_str: str = data.get("address", "")
        if addr_str:
            return int(addr_str, 16)
        return None

    async def list_modules(self) -> list[dict]:
        data = await self._call("enum_modules")
        return data.get("modules", [])
