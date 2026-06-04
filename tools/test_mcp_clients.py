"""
End-to-end validation of src/mcp/ce_client.py and src/mcp/ghidra_client.py.
Runs against the live dummy target + the Ghidra qud project.

Usage:
  python tools/test_mcp_clients.py --pid <PID> --health <CURRENT_HEALTH>
"""
import asyncio
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.mcp.ce_client import CEClient
from src.mcp.ghidra_client import GhidraClient

CE_SERVER   = r"D:\CE\cheatengine-mcp-bridge\MCP_Server\mcp_cheatengine.py"
GHIDRA_SVR  = r"D:\hgidra\ghidra-mcp\bridge_mcp_ghidra.py"


async def test_ce(pid: int, current_health: float) -> bool:
    print(f"\n[CE] Connecting to server: {CE_SERVER}")
    async with CEClient(CE_SERVER) as ce:
        # 1. Attach
        result = await ce.attach(str(pid))
        print(f"[CE] attach({pid}) -> success={result.success}, name={result.process_name}")
        if not result.success:
            return False

        # 2. Persistent scan
        scan_name = "test_health_scan"
        await ce.persistent_create(scan_name)
        count = await ce.persistent_first_scan(scan_name, str(int(current_health)), "float")
        print(f"[CE] first_scan({current_health}) -> {count} candidates")

        # 3. List modules to test module_base resolution
        modules = await ce.list_modules()
        print(f"[CE] list_modules() -> {len(modules)} modules")
        py_mod = next((m for m in modules if "python" in m.get("moduleName", m.get("name","")).lower()), None)
        if py_mod:
            base_key = "baseAddress" if "baseAddress" in py_mod else "base"
            print(f"[CE] python.exe base = {py_mod.get(base_key)}")

        await ce.persistent_destroy(scan_name)

    print("[CE] PASS")
    return True


async def test_ghidra() -> bool:
    print(f"\n[Ghidra] Connecting to server: {GHIDRA_SVR}")
    async with GhidraClient(GHIDRA_SVR) as gh:
        # 1. Open CoQ.exe that's already in the project
        ok = await gh.load_binary("/CoQ.exe")
        print(f"[Ghidra] load_binary('/CoQ.exe') -> {ok}")

        # 2. Decompile wWinMain (known to exist, addr=0x140001000)
        fn = await gh.decompile("140001000")
        print(f"[Ghidra] decompile(0x140001000) -> {fn.name} ({len(fn.pseudocode)} chars)")
        assert "UnityMain" in fn.pseudocode or len(fn.pseudocode) > 10, "Decompile returned empty"

        # 3. XRefs to wWinMain
        xrefs = await gh.xrefs_to("140001000")
        print(f"[Ghidra] get_xrefs_to(0x140001000) -> {len(xrefs)} xrefs")
        assert len(xrefs) > 0, "No xrefs found"

        # 4. String search
        strs = await gh.strings(filter_str="Unity", limit=5)
        print(f"[Ghidra] list_strings('Unity') -> {len(strs)} results")

    print("[Ghidra] PASS")
    return True


async def main(pid: int, health: float):
    ce_ok = ghidra_ok = False
    try:
        ce_ok = await test_ce(pid, health)
    except Exception as exc:
        print(f"[CE] FAIL: {exc}")

    try:
        ghidra_ok = await test_ghidra()
    except Exception as exc:
        print(f"[Ghidra] FAIL: {exc}")

    print(f"\n{'='*50}")
    print(f"CE MCP client    : {'PASS' if ce_ok else 'FAIL'}")
    print(f"Ghidra MCP client: {'PASS' if ghidra_ok else 'FAIL'}")
    print(f"{'='*50}")
    return ce_ok and ghidra_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True, help="PID of dummy_target.py")
    parser.add_argument("--health", type=float, required=True, help="Current health value in target")
    args = parser.parse_args()
    ok = asyncio.run(main(args.pid, args.health))
    sys.exit(0 if ok else 1)
