from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from d01.common import write_report
from d01.diagnostics import environment_report
from d01.ingestion.audit import AuditError, audit_records, inventory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="D01 G0 preparation; no competition solver yet")
    sub = parser.add_subparsers(dest="command", required=True)
    env = sub.add_parser("environment", help="Inventory environment; optionally run small CUDA probes")
    env.add_argument("--gpu-test", action="store_true")
    env.add_argument("--output", required=True)
    inv = sub.add_parser("inventory", help="Read-only file inventory, not a successful dataset audit")
    inv.add_argument("--root", type=Path, default=Path("data/raw"))
    inv.add_argument("--output", required=True)
    audit = sub.add_parser("audit", help="Audit JSON/JSONL using explicit field mapping")
    audit.add_argument("--input", type=Path, required=True)
    audit.add_argument("--id-field", required=True)
    audit.add_argument("--text-field", required=True)
    audit.add_argument("--group-field")
    audit.add_argument("--records-key")
    audit.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "environment":
            report = environment_report(args.gpu_test)
            code = 0 if report["status"] in {"PASS", "INVENTORY_ONLY"} else 1
        elif args.command == "inventory":
            report = inventory(args.root)
            code = 0 if report["status"] == "READY_FOR_FORMAT_AUDIT" else 2
        else:
            report = audit_records(args.input, id_field=args.id_field, text_field=args.text_field,
                                   group_field=args.group_field, records_key=args.records_key)
            code = 0 if report["status"] == "STRUCTURALLY_VALID" else 1
        write_report(args.output, report)
        print(json.dumps({"status": report["status"], "report": args.output,
                          "official_schema_validated": report.get("official_schema_validated", False)},
                         ensure_ascii=False))
        return code
    except (OSError, ValueError, AuditError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
