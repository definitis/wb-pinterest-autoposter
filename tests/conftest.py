from __future__ import annotations

from pathlib import Path

import pytest

from wb_autoposter.storage import Store


@pytest.fixture
def fixture_path() -> Path:
    return Path(__file__).parents[1] / "data" / "fake_wb_products.json"


@pytest.fixture
def store(tmp_path: Path) -> Store:
    db = Store(tmp_path / "app.sqlite3")
    db.init_db()
    return db
