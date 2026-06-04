"""
Multi-round CE scanning using persistent named scan sessions.

CE's persistent scans maintain their state inside the CE process between
Python connections — critical because each CEClient subprocess is stateless.
Each field gets its own named session so scans for multiple fields run in parallel.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Optional

from src.mcp.ce_client import CEClient, ScanPage, ScanResult


def _is_anyio_cleanup(exc: BaseException) -> bool:
    """True when exc is anyio TaskGroup cleanup noise (operations already completed)."""
    name = type(exc).__name__
    msg = str(exc)
    return (name in ("ExceptionGroup", "BaseExceptionGroup")
            or "TaskGroup" in msg
            or "cancel scope" in msg)


@dataclass
class FieldScanResult:
    field: str
    scan_name: str
    rounds: int
    final_count: int
    candidates: list[str]   # top addresses after all rounds
    scan_type: str


class FieldScanSession:
    """
    Single-field multi-round scan. Owns a named persistent CE scan.
    The scan state survives across multiple CEClient connections.
    """

    MAX_ROUNDS = 8
    TARGET_COUNT = 5

    def __init__(
        self,
        ce_server_path: str,
        field: str,
        session_id: str,
        scan_type: str = "float",
        python_exe: str = "python",
    ):
        self._ce_path = ce_server_path
        self._python_exe = python_exe
        self.field = field
        self.scan_name = f"bm_{session_id}_{field}"
        self.scan_type = scan_type
        self.rounds = 0
        self.last_count: int = 0

    async def start(self, value: str) -> int:
        """First scan — initialise the named session and run initial pass."""
        count = 0
        try:
            async with CEClient(self._ce_path, python_exe=self._python_exe) as ce:
                await ce.persistent_create(self.scan_name)
                count = await ce.persistent_first_scan(self.scan_name, value, self.scan_type)
        except BaseException as exc:
            if not _is_anyio_cleanup(exc):
                raise
        self.rounds = 1
        self.last_count = count
        return count

    async def refine(self, value: Optional[str] = None, mode: str = "exact") -> int:
        """Next scan round. Pass value=None for comparison modes like 'decreased'."""
        count = 0
        try:
            async with CEClient(self._ce_path, python_exe=self._python_exe) as ce:
                count = await ce.persistent_next_scan(self.scan_name, value, mode)
        except BaseException as exc:
            if not _is_anyio_cleanup(exc):
                raise
        self.rounds += 1
        self.last_count = count
        return count

    async def get_results(self, limit: int = 10) -> list[str]:
        results: list = []
        try:
            async with CEClient(self._ce_path, python_exe=self._python_exe) as ce:
                page = await ce.persistent_results(self.scan_name, limit)
                results = [r.address for r in page.results]
        except BaseException as exc:
            if not _is_anyio_cleanup(exc):
                raise
        return results

    async def cleanup(self) -> None:
        try:
            async with CEClient(self._ce_path, python_exe=self._python_exe) as ce:
                await ce.persistent_destroy(self.scan_name)
        except BaseException:
            pass  # best effort

    async def run_interactive(
        self,
        initial_value: str,
        get_next_value: Callable[[], str],
    ) -> FieldScanResult:
        """
        Full scan loop:
          1. First scan with initial observed value
          2. Prompt caller for next value (VLM observation or user input)
          3. Refine until ≤ TARGET_COUNT candidates or MAX_ROUNDS hit
        """
        count = await self.start(initial_value)
        print(f"[Scan:{self.field}] Round 1 -> {count} candidates")

        for _ in range(self.MAX_ROUNDS - 1):
            if count <= self.TARGET_COUNT:
                break
            new_val = get_next_value()
            count = await self.refine(new_val)
            print(f"[Scan:{self.field}] Round {self.rounds} -> {count} candidates")

        candidates = await self.get_results(limit=10)
        return FieldScanResult(
            field=self.field,
            scan_name=self.scan_name,
            rounds=self.rounds,
            final_count=count,
            candidates=candidates,
            scan_type=self.scan_type,
        )


async def scan_all_fields_parallel(
    ce_server_path: str,
    session_id: str,
    observed_deltas: list[dict],
    scan_type: str = "float",
    python_exe: str = "python",
    max_rounds: int = 8,
    target_count: int = 5,
) -> dict[str, list[str]]:
    """
    Run scan sessions for all observed fields in parallel.
    Each field gets its own named CE scan session.

    Returns: {field_name: [address_str, ...]}
    """

    async def _scan_one(delta: dict) -> tuple[str, list[str]]:
        field = delta["field"]
        # Scan for the new (post-change) value first; old_value is for reference only
        initial = str(delta["new_value"])
        sess = FieldScanSession(ce_server_path, field, session_id, scan_type, python_exe)

        try:
            count = await sess.start(initial)
            print(f"[Scan:{field}] Round 1 -> {count} candidates")

            for _ in range(max_rounds - 1):
                if count <= target_count:
                    break
                prompt = f"[Scan:{field}] Enter new observed value for {field} (current={initial}): "
                try:
                    new_val = input(prompt).strip()
                except EOFError:
                    break  # non-interactive / headless — stop after first scan round
                if not new_val:
                    break
                count = await sess.refine(new_val)
                initial = new_val
                print(f"[Scan:{field}] Round {sess.rounds} -> {count} candidates")

            candidates = await sess.get_results(limit=10)
            return field, candidates
        finally:
            await sess.cleanup()

    # Run sequentially — CE pipe is single-instance; parallel connections fail
    results = []
    for delta in observed_deltas:
        results.append(await _scan_one(delta))
    return {field: addrs for field, addrs in results}
