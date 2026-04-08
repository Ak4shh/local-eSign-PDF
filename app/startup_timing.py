"""
Lightweight startup telemetry for PDF eSign.

Usage:
    from app.startup_timing import mark, write_log

    mark("python_import_complete")
    mark("qapp_created")
    ...
    write_log()   # call once after the window is shown

Log file: %LOCALAPPDATA%\\PDF eSign\\logs\\startup.jsonl
Each launch appends one JSON object with phase timestamps (seconds since
process start) and derived durations.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Tuple

# Process start reference point — captured as early as possible.
# If the runtime hook sets _PDF_ESIGN_T0 we use that; otherwise fall back
# to the time this module is first imported.
_T0: float = float(os.environ.get("_PDF_ESIGN_T0", "0")) or time.perf_counter()

_phases: List[Tuple[str, float]] = []


def mark(phase: str) -> None:
    """Record a named phase with elapsed seconds since process start."""
    _phases.append((phase, time.perf_counter() - _T0))


def write_log() -> None:
    """Append one startup record to the JSONL log file."""
    if not _phases:
        return

    phases_dict: Dict[str, float] = {name: round(t, 4) for name, t in _phases}

    # Derive sequential durations between adjacent phases
    durations: Dict[str, float] = {}
    prev_name, prev_t = "start", 0.0
    for name, t in _phases:
        durations[f"{prev_name}_to_{name}"] = round(t - prev_t, 4)
        prev_name, prev_t = name, t

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "frozen": getattr(sys, "frozen", False),
        "phases": phases_dict,
        "durations_s": durations,
        "total_s": round(_phases[-1][1], 4) if _phases else None,
    }

    try:
        log_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "PDF eSign",
            "logs",
        )
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "startup.jsonl")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass  # Telemetry must never crash the app
