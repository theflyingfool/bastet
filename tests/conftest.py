import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _clear_active_redactor():
    """`ACTIVE` is one Redactor per process; without this, a value or protected string registered by
    one test (e.g. a secret value, or a MissingSecret's protected words) leaks into every later test,
    silently changing what gets masked there."""
    from bastet.core.secrets.redact import ACTIVE

    ACTIVE.clear()
    yield
    ACTIVE.clear()
