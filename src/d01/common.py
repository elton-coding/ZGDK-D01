from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_report(path: str | Path, report: dict) -> None:
    """Reports are new files inside the project; never overwrite raw inputs."""
    target = Path(path).resolve()
    relative = target.relative_to(PROJECT_ROOT)
    protected = {".git", ".venv"}
    if relative.parts[0] in protected or relative.parts[:2] in {
        ("data", "raw"), (".local", "reference")
    }:
        raise ValueError("Report output points into a protected input/environment directory")
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite existing report: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
