import json

import pytest

from d01.ingestion.audit import AuditError, audit_records, inventory, read_records


def save(tmp_path, rows, *, suffix=".json"):
    path = tmp_path / ("input" + suffix)
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


def test_empty_dataset_is_not_success(tmp_path):
    with pytest.raises(AuditError, match="empty"):
        read_records(save(tmp_path, []))
    assert inventory(tmp_path / "missing")["status"] == "BLOCKED"


@pytest.mark.parametrize("content", ['[{"id":"a","id":"b"}]', '[{"x":NaN}]', '{broken',
                                     '[{"x":1e999}]', '[{"x":-1e999}]',
                                     '[{"nested":{"values":[1e999]}}]'])
def test_reject_corrupt_json_and_ambiguous_keys(tmp_path, content):
    path = tmp_path / "input.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(AuditError):
        read_records(path)


def test_duplicate_ids_and_empty_text_are_invalid(tmp_path):
    path = save(tmp_path, [{"id":"a","text":"甲"}, {"id":"a","text":" "}])
    result = audit_records(path, id_field="id", text_field="text")
    assert result["status"] == "INVALID"
    assert {x["code"] for x in result["issues"]} == {"duplicate_id", "missing_or_empty_text"}


def test_bom_explicit_mapping_and_duplicate_candidates_preserve_inputs(tmp_path):
    path = save(tmp_path, {"records":[{"sid":"source-01","body":"Ａ 甲","case":"c1"},
                                       {"sid":"source-02","body":"A甲","case":"c1"}]})
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    before = path.read_bytes()
    result = audit_records(path, id_field="sid", text_field="body", group_field="case", records_key="records")
    assert result["status"] == "STRUCTURALLY_VALID"
    assert result["normalized_duplicate_candidate_row_groups"] == [[0, 1]]
    assert result["exact_duplicate_row_groups"] == []
    assert result["business_group_count"] == 1
    assert not result["split_created"] and not result["official_schema_validated"]
    assert path.read_bytes() == before


def test_does_not_infer_business_groups_from_ids(tmp_path):
    path = save(tmp_path, [{"id":"patient123_train","text":"甲"}, {"id":"patient123_test","text":"乙"}])
    report = audit_records(path, id_field="id", text_field="text")
    assert report["business_group_count"] is None
    assert not report["split_created"]


def test_jsonl_and_invalid_record_shape(tmp_path):
    path = tmp_path / "input.jsonl"
    path.write_text('{"id":"a","text":"甲"}\n\n{"id":"b","text":"乙"}\n',encoding="utf-8")
    assert len(read_records(path)) == 2
    with pytest.raises(AuditError, match="array of objects"):
        read_records(save(tmp_path, [None]))


def test_missing_business_groups_are_not_silently_accepted(tmp_path):
    path = save(tmp_path, [{"id":"a","text":"甲"}])
    report = audit_records(path, id_field="id", text_field="text", group_field="case")
    assert report["status"] == "INVALID"
    assert report["issues"][0]["code"] == "missing_or_nonstring_group"


def test_inventory_does_not_follow_linked_directory(tmp_path):
    raw, outside = tmp_path / "raw", tmp_path / "outside"
    raw.mkdir()
    outside.mkdir()
    (outside / "unrelated.txt").write_text("unrelated", encoding="utf-8")
    try:
        (raw / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"OS does not permit creating a test symlink: {type(exc).__name__}")
    report = inventory(raw)
    assert report["files"] == []
    assert report["status"] == "BLOCKED" and report["issues"]
