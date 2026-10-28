from __future__ import annotations

import json
import math
import os
import re
import stat
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from d01.common import sha256_file, utc_now


class AuditError(ValueError):
    pass


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise AuditError(f"Non-finite JSON number: {value}")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise AuditError("Non-finite JSON number after exponent conversion")
    return parsed


def read_records(path: Path, records_key: str | None = None) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AuditError("Input is not UTF-8; choose an explicit conversion outside raw inputs") from exc
    def loads(value):
        return json.loads(value, object_pairs_hook=_unique_keys, parse_constant=_reject_nonfinite,
                          parse_float=_finite_float)
    try:
        if path.suffix.lower() == ".jsonl":
            if records_key is not None:
                raise AuditError("records_key is only supported for JSON arrays in a wrapper")
            records = [loads(line) for line in text.splitlines() if line.strip()]
        elif path.suffix.lower() == ".json":
            records = loads(text)
            if records_key is not None:
                if not isinstance(records, dict) or records_key not in records:
                    raise AuditError("Configured records_key is missing")
                records = records[records_key]
        else:
            raise AuditError("Explicit record audit supports .json and .jsonl only")
    except json.JSONDecodeError as exc:
        raise AuditError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise AuditError("Expected an array of objects; no input structure is guessed")
    if not records:
        raise AuditError("Dataset is empty")
    return records


def inventory(root: Path) -> dict:
    files = []
    problems = []
    if root.exists() and not root.is_dir():
        problems.append("input_root_is_not_a_directory")
    elif _is_link(root):
        problems.append("symlink_or_junction_input_root_not_followed")
    elif root.exists():
        def walk_error(error):
            problems.append(f"unreadable_directory:{error.filename}")
        for parent, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
            for name in list(directories):
                path = Path(parent) / name
                if _is_link(path):
                    problems.append(f"link_not_followed:{path.relative_to(root).as_posix()}")
                    directories.remove(name)
            directories.sort()
            for name in sorted(filenames):
                path = Path(parent) / name
                if _is_link(path):
                    problems.append(f"link_not_followed:{path.relative_to(root).as_posix()}")
                    continue
                files.append({"path": path.relative_to(root).as_posix(),
                              "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return {"created_at_utc": utc_now(), "kind": "input_inventory", "root": str(root.resolve()),
            "file_count": len(files), "files": files, "issues": problems,
            "status": "READY_FOR_FORMAT_AUDIT" if files and not problems else "BLOCKED",
            "official_schema_validated": False}


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def audit_records(path: Path, *, id_field: str, text_field: str,
                  group_field: str | None = None, records_key: str | None = None) -> dict:
    records = read_records(path, records_key)
    ids = Counter()
    lengths = []
    fields = Counter()
    exact = defaultdict(list)
    normalized = defaultdict(list)
    groups = defaultdict(list)
    issues = []
    for index, row in enumerate(records):
        fields.update(row.keys())
        source_id, text = row.get(id_field), row.get(text_field)
        if not isinstance(source_id, str) or not source_id.strip():
            issues.append({"row": index, "code": "missing_or_nonstring_id"})
        else:
            ids[source_id] += 1
        if not isinstance(text, str) or not text.strip():
            issues.append({"row": index, "code": "missing_or_empty_text"})
        else:
            lengths.append(len(text))
            exact[text].append(index)
            # Used only to flag duplicate candidates, never to replace original text.
            canonical = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
            normalized[canonical].append(index)
        if group_field is not None:
            group = row.get(group_field)
            if not isinstance(group, str) or not group.strip():
                issues.append({"row": index, "code": "missing_or_nonstring_group"})
            else:
                groups[group].append(index)
    for source_id, count in ids.items():
        if count > 1:
            issues.append({"code": "duplicate_id", "source_id": source_id, "count": count})
    exact_sets = [v for v in exact.values() if len(v) > 1]
    norm_sets = [v for v in normalized.values() if len(v) > 1]
    return {
        "created_at_utc": utc_now(), "kind": "explicit_adapter_audit",
        "input": {"path": str(path.resolve()), "sha256": sha256_file(path)},
        "adapter": {"id_field": id_field, "text_field": text_field,
                    "group_field": group_field, "records_key": records_key},
        "record_count": len(records), "unique_id_count": len(ids),
        "field_presence": dict(sorted(fields.items())),
        "text_characters": {"min": min(lengths, default=None), "max": max(lengths, default=None),
                            "total": sum(lengths), "unit": "Unicode code points, not tokens"},
        "exact_duplicate_row_groups": exact_sets,
        "normalized_duplicate_candidate_row_groups": norm_sets,
        "business_group_count": len(groups) if group_field else None,
        "issues": issues, "status": "INVALID" if issues else "STRUCTURALLY_VALID",
        "official_schema_validated": False,
        "split_created": False,
        "limitations": ["No semantic labels or business grouping are inferred from source_id",
                        "Normalized duplicates are candidates, not a complete near-duplicate detector",
                        "Official contract and entity/event leakage audit remain required"],
    }
