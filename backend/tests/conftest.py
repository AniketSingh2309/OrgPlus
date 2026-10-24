from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

# Tests never talk to Google or a real tenant.
os.environ.setdefault("ALLOWED_DOMAIN", "example.com")
os.environ.setdefault("NEXTAUTH_SECRET", "test-secret-test-secret-test-secret-123")


@pytest.fixture
def fixture() -> Any:
    def load(name: str) -> Any:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return load
