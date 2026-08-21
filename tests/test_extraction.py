"""Document extraction: validation logic + prompt/schema contract."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extract_reports import FIELDS, validate  # noqa: E402


def test_field_schema_matches_ground_truth_columns():
    idx = Path(__file__).resolve().parents[1] / "reports" / "reports_index.csv"
    if not idx.exists():
        import pytest
        pytest.skip("corpus not generated")
    header = idx.read_text().splitlines()[0].split(",")
    for key in ["report_id", "fault_pattern_id", "asset_id", "model_no",
                "linked_wo", "technician"]:
        assert key in header and key in FIELDS


def test_validate_scores_perfect_extraction(capsys):
    idx = Path(__file__).resolve().parents[1] / "reports" / "reports_index.csv"
    if not idx.exists():
        import pytest
        pytest.skip("corpus not generated")
    import csv
    truth = list(csv.DictReader(open(idx)))
    rows = [{f: t.get(f, "") for f in FIELDS} for t in truth]
    validate(rows, idx)
    out = capsys.readouterr().out
    assert "(100.0%)" in out


def test_validate_catches_wrong_field(capsys):
    idx = Path(__file__).resolve().parents[1] / "reports" / "reports_index.csv"
    if not idx.exists():
        import pytest
        pytest.skip("corpus not generated")
    import csv
    truth = list(csv.DictReader(open(idx)))
    rows = [{f: t.get(f, "") for f in FIELDS} for t in truth]
    rows[0]["asset_id"] = "AST-999"
    validate(rows, idx)
    out = capsys.readouterr().out
    assert "(100.0%)" not in out and "miss" in out
