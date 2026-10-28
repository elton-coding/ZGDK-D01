import json

import pytest

import d01.common
from d01.cli import main
from d01.common import write_report


def test_missing_data_has_explicit_blocked_report_and_exit_2(tmp_path, monkeypatch):
    monkeypatch.setattr(d01.common, "PROJECT_ROOT", tmp_path)
    report = tmp_path / "runs" / "inventory.json"
    assert main(["inventory", "--root", str(tmp_path / "data/raw"), "--output", str(report)]) == 2
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "BLOCKED"


def test_output_cannot_overwrite_a_report_or_raw_input(tmp_path, monkeypatch):
    monkeypatch.setattr(d01.common, "PROJECT_ROOT", tmp_path)
    report = tmp_path / "runs" / "report.json"
    write_report(report, {"status":"test"})
    with pytest.raises(FileExistsError):
        write_report(report, {})
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "test"
    with pytest.raises(ValueError, match="protected"):
        write_report(tmp_path / "data/raw/input.json", {})
    with pytest.raises(ValueError):
        write_report(tmp_path.parent / "outside-report.json", {})


def test_invalid_mapping_does_not_become_success(tmp_path, monkeypatch):
    monkeypatch.setattr(d01.common, "PROJECT_ROOT", tmp_path)
    data = tmp_path / "records.json"
    data.write_text('[{"id":"a","text":"甲"}]', encoding="utf-8")
    report = tmp_path / "runs" / "audit.json"
    assert main(["audit", "--input", str(data), "--id-field", "wrong", "--text-field", "text",
                 "--output", str(report)]) == 1
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "INVALID"
