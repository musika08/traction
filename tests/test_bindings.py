import re

from traction import bindings


def test_factory_zone5():
    assert bindings.zone_slots(5, {}, False) == ["01-01", "00-00", "01-02", "00-00"]


def test_back_right_b():
    b = {"back_right": "b"}
    assert bindings.zone_slots(8, b, False) == ["02-8E", "02-8E", "01-02", "01-02"]
    assert bindings.changed_zones(b) == [8]


def test_combo_a_screenshot():
    b = {"combos": {"a": "screenshot"}}
    assert bindings.zone_slots(5, b, False) == ["01-01", "04-03-82-88-1B", "01-02", "00-00"]
    assert bindings.changed_zones(b) == [5]


def test_desktop_defaults():
    b = {"combos": {"a": "screenshot"}}
    assert bindings.zone_slots(5, b, True) == ["02-5A", "00-00", "02-76", "00-00"]


def test_desktop_ignores_back_choice():
    assert bindings.zone_slots(8, {"back_left": "a"}, True) == ["02-8E", "02-8E", "02-8F", "02-8F"]


def test_clean_drops_unknown():
    raw = {"back_left": "rocket", "combos": {"a": "rocket", "zz": "b"}, "x": 1}
    assert bindings.clean(raw) == {"back_left": "shift", "back_right": "shift", "combos": {}}


def test_clean_keeps_valid_and_survives_junk():
    raw = {"back_left": "a", "back_right": "shift", "combos": {"x": "win", "back_left": "b"}}
    assert bindings.clean(raw) == {"back_left": "a", "back_right": "shift", "combos": {"x": "win"}}
    assert bindings.clean(None) == {"back_left": "shift", "back_right": "shift", "combos": {}}
    assert bindings.clean({"combos": "x", "back_left": 5})["combos"] == {}


def test_factory_all_zones_match_ghelper():
    assert bindings.changed_zones({}) == []
    assert bindings.all_zones() == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert bindings.zone_slots(1, {}, False) == ["01-09", "05-19", "01-0A", "04-02-82-23"]
    assert bindings.zone_slots(8, {}, False) == ["02-8E", "02-8E", "02-8F", "02-8F"]
    assert bindings.zone_slots(9, {}, True) == ["04-02-88-0D", "00-00", "03-02", "00-00"]


def test_actions_unique_and_codes_valid():
    ids = [a[0] for a in bindings.ACTIONS]
    assert len(ids) == len(set(ids))
    rx = re.compile(r"^(00-00|0[1235]-[0-9A-F]{2}|04-0[1-5](-[0-9A-F]{2})+)$")
    for _id, _label, code in bindings.ACTIONS:
        assert rx.match(code), code
