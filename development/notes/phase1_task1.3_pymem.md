# Task 1.3 — Windows Memory Scanner Fallback

**File:** `src/auto_analyzer.py` → `MemoryScrapingStrategy`

- `pymem` attach + `pattern_scan_all` on a `10.0f` float signature to resolve a
  base pointer, then samples candidate offsets repeatedly so the classifier sees
  a value range (not a constant).
- Each candidate offset is emitted as `offset`/`source` access metadata.

**Verified:** falls back to an offset-based 4-dim schema when `pymem` is not
installed.
