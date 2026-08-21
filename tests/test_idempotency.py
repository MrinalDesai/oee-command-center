"""The idempotency rule that the Aug-20 autonomous run proved necessary:
an event in NEW / INVESTIGATING / ACTIONED must block re-alerting."""

BLOCKING = {"NEW", "INVESTIGATING", "ACTIONED"}


def should_open_new_event(open_statuses: set[str]) -> bool:
    return not (open_statuses & BLOCKING)


def test_actioned_blocks_realert():
    assert should_open_new_event({"ACTIONED"}) is False


def test_new_blocks_realert():
    assert should_open_new_event({"NEW"}) is False


def test_resolved_allows_new_event():
    assert should_open_new_event({"RESOLVED"}) is True


def test_empty_history_allows_event():
    assert should_open_new_event(set()) is True


def test_sql_contains_the_fix():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "sql" / "03_detection.sql")
    if not sql.exists():
        import pytest
        pytest.skip("sql not present")
    text = sql.read_text()
    assert "'ACTIONED'" in text, "idempotency fix missing from detection SQL"
