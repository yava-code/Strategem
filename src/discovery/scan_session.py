"""
Multi-round CE scanning using persistent named scan sessions.

CE's persistent scans maintain their state inside the CE process between
Python connections — critical because each CEClient subprocess is stateless.
Each field gets its own named session so scans for multiple fields run in parallel.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from src.mcp.ce_client import CEClient, ScanPage, ScanResult


def _read_field_from_log(log_file: str, field: str) -> Optional[str]:
    """
    Try to read the current value of `field` from a log file.
    Supports dummy_target.py log format: '  Health: 90.0 / 100.0  ...'
    Returns value as string, or None.
    """
    try:
        text = Path(log_file).read_text(encoding="utf-8", errors="replace")
        lines = [l for l in text.splitlines() if "Health:" in l and "Turn:" in l]
        if not lines:
            return None
        last = lines[-1]
        m = re.search(r"Health:\s+([\d.]+)", last)
        if m:
            val = float(m.group(1))
            return str(int(val)) if val == int(val) else str(val)
    except Exception:
        pass
    return None


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

    async def start(self, value: str, limit: int = 20) -> tuple[int, list[str]]:
        """First scan. Returns (count, addresses) — both fetched in ONE connection."""
        count, addrs = 0, []
        try:
            async with CEClient(self._ce_path, python_exe=self._python_exe) as ce:
                await ce.persistent_create(self.scan_name)
                count = await ce.persistent_first_scan(self.scan_name, value, self.scan_type)
                if count > 0:
                    page = await ce.persistent_results(self.scan_name, limit)
                    addrs = [r.address for r in page.results]
        except BaseException as exc:
            if not _is_anyio_cleanup(exc):
                raise
        self.rounds = 1
        self.last_count = count
        return count, addrs

    async def refine(self, value: Optional[str] = None, mode: str = "exact",
                     limit: int = 20) -> tuple[int, list[str]]:
        """Next scan round. Returns (count, addresses) in ONE connection."""
        count, addrs = 0, []
        try:
            async with CEClient(self._ce_path, python_exe=self._python_exe) as ce:
                count = await ce.persistent_next_scan(self.scan_name, value, mode)
                if count > 0:
                    page = await ce.persistent_results(self.scan_name, limit)
                    addrs = [r.address for r in page.results]
        except BaseException as exc:
            if not _is_anyio_cleanup(exc):
                raise
        self.rounds += 1
        self.last_count = count
        return count, addrs

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
        count, candidates = await self.start(initial_value)
        print(f"[Scan:{self.field}] Round 1 -> {count} candidates")

        for _ in range(self.MAX_ROUNDS - 1):
            if count <= self.TARGET_COUNT:
                break
            new_val = get_next_value()
            count, candidates = await self.refine(new_val)
            print(f"[Scan:{self.field}] Round {self.rounds} -> {count} candidates")

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
    log_file: Optional[str] = None,
) -> dict[str, list[str]]:
    """
    Run scan sessions for all observed fields in parallel.
    Each field gets its own named CE scan session.

    Returns: {field_name: [address_str, ...]}
    """

    async def _scan_one(delta: dict) -> tuple[str, list[str]]:
        field = delta["field"]

        # If log_file is available, use the CURRENT value from it as the first scan value
        # (handles the case where the target already ticked before memory_scout runs)
        raw_val = delta["new_value"]
        if log_file and field == "health":
            log_val = _read_field_from_log(log_file, field)
            if log_val:
                raw_val = float(log_val)

        # Use int-string for whole numbers so CE parses correctly ("100" not "100.0")
        initial = str(int(raw_val)) if isinstance(raw_val, float) and raw_val == int(raw_val) else str(raw_val)
        sess = FieldScanSession(ce_server_path, field, session_id, scan_type, python_exe)

        try:
            count, best_candidates = await sess.start(initial)
            print(f"[Scan:{field}] Round 1 -> {count} candidates")

            for _ in range(max_rounds - 1):
                if count <= target_count:
                    break
                # Auto-refine: read updated value from log
                new_val: Optional[str] = None
                if log_file and field == "health":
                    new_val = _read_field_from_log(log_file, field)
                    if new_val and new_val == initial:
                        new_val = None  # value hasn't changed yet
                if new_val is None:
                    break  # headless — stop after first round
                prev_count, prev_addrs = count, best_candidates
                count, round_addrs = await sess.refine(new_val)
                initial = new_val
                print(f"[Scan:{field}] Round {sess.rounds} (auto={new_val}) -> {count} candidates")
                if count == 0:
                    print(f"[Scan:{field}] Refinement zeroed — keeping {prev_count} candidates")
                    count, best_candidates = prev_count, prev_addrs
                    break
                best_candidates = round_addrs

            return field, best_candidates
        finally:
            await sess.cleanup()

    # Run sequentially — CE pipe is single-instance; parallel connections fail
    results = []
    for delta in observed_deltas:
        results.append(await _scan_one(delta))
    return {field: addrs for field, addrs in results}
