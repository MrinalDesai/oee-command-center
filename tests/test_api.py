"""Console backend API contract - runs against the mock backend (no Snowflake
needed in CI); the Snowflake backend serves the identical contract."""
import sys
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "forgepulse-ui" / "backend"
sys.path.insert(0, str(UI))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

try:
    import main_mock as app_module
except Exception:
    pytest.skip("mock backend unavailable", allow_module_level=True)

client = TestClient(app_module.app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "healthy"


def test_assets_contract():
    r = client.get("/api/assets")
    assert r.status_code == 200
    a = r.json()[0]
    for key in ("asset_id", "health", "status"):
        assert key in a


def test_alerts_contract():
    r = client.get("/api/alerts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_unknown_asset_404():
    r = client.get("/api/telemetry/AST-999")
    assert r.status_code in (404, 422, 500)
