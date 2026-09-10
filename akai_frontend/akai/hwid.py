"""Hardware fingerprint (HWID) collection.

The code shown on the login screen is deterministic for one machine:
motherboard serial + CPU identifier (MAC address only as a last resort),
folded through SHA-256 into the ``AKAI-XXXX-XXXX-XXXX`` form.  Nothing is
sent anywhere from this module — the server receives the same visible code
and stores only its digest.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import uuid
from pathlib import Path
from typing import Dict, Optional

_PREFIX = "AKAI"


def _run(argv) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=6, shell=False)
        return (proc.stdout or "").strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _wmic_value(output: str, header: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line and header.lower() not in line.lower():
            return line
    return ""


def _windows_ids() -> Dict[str, str]:
    board = _wmic_value(_run(["wmic", "baseboard", "get", "serialnumber"]),
                        "serialnumber")
    cpu = _wmic_value(_run(["wmic", "cpu", "get", "processorid"]), "processorid")
    if not board or not cpu:  # wmic is deprecated on newer Windows builds
        ps = _run(["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_BaseBoard).SerialNumber + '|' + "
                   "(Get-CimInstance Win32_Processor | Select -First 1).ProcessorId"])
        if ps and "|" in ps:
            b, c = ps.split("|", 1)
            board = board or b.strip()
            cpu = cpu or c.strip()
    return {"board": board, "cpu": cpu}


def _linux_ids() -> Dict[str, str]:
    board = _read("/sys/class/dmi/id/board_serial") or _read(
        "/sys/class/dmi/id/board_vendor") + _read("/sys/class/dmi/id/board_name")
    cpu = ""
    for line in _read("/proc/cpuinfo").splitlines():
        if line.lower().startswith("serial"):
            cpu = line.split(":", 1)[1].strip()
            break
    if not cpu:
        cpu = _read("/sys/class/dmi/id/product_uuid")
    return {"board": board, "cpu": cpu}


def collect_identifiers() -> Dict[str, str]:
    """Best-effort stable identifiers for this machine."""
    if platform.system() == "Windows":
        ids = _windows_ids()
    else:
        ids = _linux_ids()
    strong = bool(ids.get("board")) or bool(ids.get("cpu"))
    if not strong:  # VMs / restricted environments: fall back to node identity
        ids["node"] = f"{platform.node()}:{uuid.getnode()}"
    return {key: value for key, value in ids.items() if value}


def compute_hwid(identifiers: Optional[Dict[str, str]] = None) -> str:
    """Stable ``AKAI-XXXX-XXXX-XXXX`` fingerprint for the given identifiers."""
    ids = identifiers if identifiers is not None else collect_identifiers()
    parts = [ids[key] for key in sorted(ids) if ids[key]]
    if not parts:  # extremely restricted sandbox: still produce a stable code
        parts = [platform.node() or "akai", str(uuid.getnode())]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest().upper()
    body = digest[:12]
    return f"{_PREFIX}-{body[0:4]}-{body[4:8]}-{body[8:12]}"
