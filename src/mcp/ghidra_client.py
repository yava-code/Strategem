from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Optional

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
class XRef:
    from_address: str
    ref_type: str
    function_name: Optional[str] = None

@dataclass
class DecompiledFunction:
    address: str
    name: str
    pseudocode: str

@dataclass
class FunctionInfo:
    address: str
    name: str
    signature: Optional[str] = None

@dataclass
class StructField:
    name: str
    offset: int
    type_name: str
    size: int

@dataclass
class StructLayout:
    name: str
    total_size: int
    fields: list[StructField]

@dataclass
class CallGraphPath:
    start: str
    end: str
    paths: list[list[str]]
    summary: str

@dataclass
class AoBMatch:
    address: str
    context: Optional[str] = None


# ---------------------------------------------------------------------------
# GhidraClient
# ---------------------------------------------------------------------------

class GhidraClient:
    """
    Async context manager wrapping the Ghidra MCP bridge (bridge_mcp_ghidra.py).
    Ghidra must be running with the MCP plugin active before connecting.

    Usage:
        async with GhidraClient(server_path="D:/hgidra/ghidra-mcp/bridge_mcp_ghidra.py") as gh:
            await gh.load_binary("C:/Games/Game.exe")
            xrefs = await gh.xrefs_to("0x1A3F80")
    """

    def __init__(
        self,
        server_path: str,
        python_exe: str = sys.executable,
    ):
        if not _MCP_OK:
            raise ImportError("mcp package not installed. Run: pip install mcp>=1.5.0")
        if not os.path.isfile(server_path):
            raise FileNotFoundError(f"Ghidra MCP server not found: {server_path}")

        self._params = StdioServerParameters(
            command=python_exe,
            args=[server_path],
        )
        self._session: Optional[ClientSession] = None
        self._stdio_ctx = None
        self._session_ctx = None
        self._active_program: Optional[str] = None

    async def __aenter__(self) -> "GhidraClient":
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
            raise RuntimeError("GhidraClient not connected — use as async context manager")
        # Inject active program if set and not overridden
        if self._active_program and "program" not in kwargs:
            kwargs["program"] = self._active_program
        result = await self._session.call_tool(tool, kwargs)
        if result.isError:
            content = result.content[0].text if result.content else "unknown error"
            raise RuntimeError(f"Ghidra tool '{tool}' returned error: {content}")
        raw = result.content[0].text if result.content else "{}"
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Some tools return plain text; wrap it
            return {"text": raw}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load_binary(self, path: str, auto_analyze: bool = False) -> bool:
        """Open a binary in Ghidra. Returns True on success."""
        data = await self._call("open_program", path=path, auto_analyze=auto_analyze, program="")
        self._active_program = path
        return data.get("success", True)

    async def xrefs_to(self, address: str, limit: int = 100) -> list[XRef]:
        """All code that reads/writes the given static address or offset."""
        data = await self._call("get_xrefs_to", address=address, limit=limit)

        # Ghidra MCP returns xrefs as plain text:
        #   "From <addr>[ in <fn>] [<TYPE>]"
        if "text" in data:
            return _parse_xrefs_text(data["text"])

        # Structured JSON fallback (future Ghidra MCP versions)
        refs = []
        for r in data.get("xrefs", data.get("references", [])):
            refs.append(XRef(
                from_address=r.get("from_address", r.get("fromAddress", "")),
                ref_type=r.get("type", r.get("refType", "")),
                function_name=r.get("function_name", r.get("functionName")),
            ))
        return refs

    async def decompile(self, address: str) -> DecompiledFunction:
        data = await self._call("decompile_function", address=address)
        # Ghidra MCP returns decompile as plain text
        code = data.get("text") or data.get("decompiled") or data.get("code", "")
        name = data.get("name", data.get("function_name", "unknown"))
        return DecompiledFunction(address=address, name=name, pseudocode=code)

    async def function_at(self, address: str) -> Optional[FunctionInfo]:
        data = await self._call("get_function_by_address", address=address)
        if not data.get("name"):
            return None
        return FunctionInfo(
            address=address,
            name=data.get("name", ""),
            signature=data.get("signature"),
        )

    async def byte_pattern(self, pattern: str, mask: str = "") -> list[AoBMatch]:
        kwargs: dict = {"pattern": pattern}
        if mask:
            kwargs["mask"] = mask
        data = await self._call("search_byte_patterns", **kwargs)
        matches = []
        for m in data.get("matches", data.get("results", [])):
            addr = m if isinstance(m, str) else m.get("address", "")
            matches.append(AoBMatch(address=addr))
        return matches

    async def call_graph(
        self,
        start_function: str,
        end_function: str,
        analysis_type: str = "summary",
    ) -> CallGraphPath:
        data = await self._call(
            "analyze_call_graph",
            start_function=start_function,
            end_function=end_function,
            analysis_type=analysis_type,
        )
        return CallGraphPath(
            start=start_function,
            end=end_function,
            paths=data.get("paths", []),
            summary=data.get("summary", data.get("text", "")),
        )

    async def strings(self, filter_str: str = "", limit: int = 200) -> list[dict]:
        data = await self._call("list_strings", filter=filter_str, limit=limit)
        return data.get("strings", data.get("results", []))

    async def create_struct(self, name: str, fields: list[dict]) -> bool:
        import json as _json
        data = await self._call("create_struct", name=name, fields=_json.dumps(fields))
        return data.get("success", True)

    async def struct_layout(self, name: str) -> Optional[StructLayout]:
        data = await self._call("get_struct_layout", struct_name=name)
        if not data.get("fields"):
            return None
        fields = [
            StructField(
                name=f.get("name", f"field_{i}"),
                offset=f.get("offset", 0),
                type_name=f.get("type", "undefined"),
                size=f.get("size", 0),
            )
            for i, f in enumerate(data.get("fields", []))
        ]
        return StructLayout(
            name=name,
            total_size=data.get("total_size", data.get("size", 0)),
            fields=fields,
        )

    async def search_functions(self, query: str, limit: int = 50) -> list[FunctionInfo]:
        data = await self._call("search_functions", query=query, limit=limit)
        return [
            FunctionInfo(address=f.get("address", ""), name=f.get("name", ""))
            for f in data.get("functions", data.get("results", []))
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_xrefs_text(text: str) -> list[XRef]:
    """
    Parses the Ghidra MCP plain-text xrefs format:
      From <hex_addr>[ in <function_name>] [<REF_TYPE>]
    """
    refs: list[XRef] = []
    # Match: "From 14000013c [DATA]" or "From 1400011ed in __scrt_common_main_seh [UNCONDITIONAL_CALL]"
    pattern = re.compile(
        r"From\s+([0-9a-fA-F]+)"        # address
        r"(?:\s+in\s+(\S+))?"            # optional: in <fn_name>
        r"\s+\[([^\]]+)\]"              # [REF_TYPE]
    )
    for line in text.strip().splitlines():
        m = pattern.search(line.strip())
        if m:
            refs.append(XRef(
                from_address=m.group(1),
                function_name=m.group(2),
                ref_type=m.group(3),
            ))
    return refs
