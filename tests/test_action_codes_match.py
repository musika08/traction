"""The helper's allow-list and factory set must stay in step with the Python binding model."""

import os
import re

from traction import bindings

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINDINGS_CS = os.path.join(ROOT, "helper", "src", "Bindings.cs")


def _block(name: str) -> str:
    with open(BINDINGS_CS, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"\b" + name + r"\s*=\s*(?:new\s*string\[\]\[\]\s*)?\{(.*?)\n\s*\};", src, re.S)
    assert m, name + " not found in Bindings.cs"
    return m.group(1)


def _codes(text: str) -> list:
    return re.findall(r'"([0-9A-F]{2}(?:-[0-9A-F]{2})+)"', text)


def _defaults() -> set:
    codes = set()
    for zone in bindings.all_zones():
        for name in bindings.SETS:
            codes.update(bindings.zone_slots(zone, {}, name))
    return codes


def test_allow_list_is_actions_plus_defaults():
    allowed = _codes(_block("Allowed"))
    assert len(allowed) == len(set(allowed)), "duplicate code in Bindings.Allowed"
    expected = {a[2] for a in bindings.ACTIONS} | _defaults() | set(bindings.SHIFT.values())
    assert set(allowed) == expected


def test_factory_zones_match_gamepad_defaults():
    rows = re.findall(r"new\[\]\s*\{([^}]*)\}", _block("GamepadDefaults"))
    assert [_codes(r) for r in rows] == [bindings.zone_slots(z, {}, "gamepad") for z in bindings.all_zones()]

