import logging
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "py_modules"))
sys.path.insert(0, ROOT)

# Stand-in for the loader's `decky` module so main.py imports outside Decky.
# Tests never use the real settings or runtime directories: they pass paths under tmp_path.
if "decky" not in sys.modules:
    decky = types.ModuleType("decky")
    decky.logger = logging.getLogger("traction-test")
    sys.modules["decky"] = decky


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_registry(monkeypatch):
    # No test may read Armoury Crate's real registry key: the default reader finds nothing (the defaults are used).
    from traction import library

    def missing(name):
        raise FileNotFoundError(name)
    monkeypatch.setattr(library, "registry_read", missing)
