"""Reproduce G0 preparation checks; exit 2 means external prerequisites are missing."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from d01.common import sha256_file, utc_now, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="New directory name within runs/")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.run_id):
        parser.error("run-id must contain only letters, digits, hyphens and underscores")
    run = ROOT / "runs" / args.run_id
    run.mkdir(parents=True, exist_ok=False)
    commands = [
        ("tests", [sys.executable, "-m", "pytest", "-q", f"--junitxml={run / 'tests.xml'}",
                   f"--basetemp={run / 'pytest-temp'}"]),
        ("environment", [sys.executable, "scripts/d01.py", "environment", "--gpu-test",
                         "--output", str(run / "environment.json")]),
        ("inventory", [sys.executable, "scripts/d01.py", "inventory", "--root", "data/raw",
                       "--output", str(run / "inventory.json")]),
        ("synthetic_adapter_audit", [sys.executable, "scripts/d01.py", "audit", "--input",
                                     "tests/fixtures/audit_records.jsonl", "--id-field", "source_id",
                                     "--text-field", "text", "--group-field", "case_id",
                                     "--output", str(run / "synthetic_adapter_audit.json")]),
    ]
    results = []
    for name, command in commands:
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=240,
                                    env={**os.environ, "PYTHONUTF8": "1"})
            entry = {"name": name, "command": command, "exit_code": result.returncode}
            (run / f"{name}.stdout.txt").write_text(result.stdout, encoding="utf-8")
            (run / f"{name}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired:
            entry = {"name": name, "command": command, "exit_code": 124, "error": "timeout"}
        results.append(entry)
        print(f"{name}: exit {entry['exit_code']}", flush=True)
    contract_path = ROOT / "configs/official_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    blockers = []
    inventory_path = run / "inventory.json"
    inventory_result = json.loads(inventory_path.read_text(encoding="utf-8")) if inventory_path.exists() else None
    if inventory_result is None or inventory_result["file_count"] == 0:
        blockers.append("official_validation_data_not_received")
    elif inventory_result["status"] != "READY_FOR_FORMAT_AUDIT":
        blockers.append("input_inventory_has_unresolved_access_or_link_issues")
    if not contract["model"]["model_id"] or not contract["model"]["revision"]:
        blockers.append("official_model_id_and_revision_unconfirmed")
    if not contract["output_contract"]["official_schema_received"]:
        blockers.append("official_output_contract_not_received")
    # Neither an arbitrary filename nor a manual checkbox can certify these later gates.
    blockers.extend(["official_data_adapter_and_business_group_audit_not_validated",
                     "specified_27b_model_and_quantization_resource_test_not_performed"])
    internal_failures = [r["name"] for r in results
                         if r["exit_code"] != 0 and not (r["name"] == "inventory" and r["exit_code"] == 2)]
    source_paths = [*sorted((ROOT / "src").rglob("*.py")),
                    *sorted((ROOT / "scripts").glob("*.py")),
                    *sorted((ROOT / "tests").glob("*.py")), contract_path,
                    *sorted((ROOT / "tests/fixtures").glob("*.jsonl")),
                    ROOT / "requirements/g0.in", ROOT / "requirements/g0-windows-py311.lock.txt",
                    ROOT / "configs/model_candidates.json", ROOT / "scripts/setup_g0.ps1",
                    ROOT / "pyproject.toml", ROOT / "题目分析报告.md", ROOT / "术语表格.md"]
    pdf = ROOT / ".local/reference/D01.pdf"
    if pdf.exists():
        source_paths.append(pdf)
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    packages = {item.metadata["Name"]: item.version for item in importlib.metadata.distributions()}
    report = {"created_at_utc": utc_now(), "scope": "G0 preparation only; not G1 solver P1",
              "status": "FAIL" if internal_failures else "PARTIAL_BLOCKED",
              "competition_model_tested": False, "official_score": None,
              "commands": results, "internal_failures": internal_failures, "blockers": blockers,
              "contract_sha256": sha256_file(contract_path),
              "git": {"head": git.stdout.strip(), "dirty": bool(dirty.stdout.strip())},
              "python": sys.version, "dependencies": dict(sorted(packages.items())),
              "input_files": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha256_file(p)}
                              for p in source_paths],
              "reproduce_command": ".venv/Scripts/python.exe scripts/run_g0.py --run-id NEW_UNIQUE_RUN_ID"}
    write_report(run / "g0_status.json", report)
    print(json.dumps({"status": report["status"], "report": str(run / "g0_status.json"),
                      "blockers": blockers}, ensure_ascii=False))
    return 1 if internal_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
