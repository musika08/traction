import re

from traction import bindings

V2_FACTORY = {"gamepad": {}, "desktop": {}, "m1_secondary": True, "m2_secondary": True}


def test_factory_zone5_both_sets():
    assert bindings.zone_slots(5, {}, "gamepad") == ["01-01", "00-00", "01-02", "00-00"]
    assert bindings.zone_slots(5, {}, "desktop") == ["02-5A", "00-00", "02-76", "00-00"]


def test_constants():
    assert bindings.SETS == ("gamepad", "desktop")
    assert bindings.FACTORY == "factory"


def test_gamepad_primary_and_secondary():
    b = bindings.set_choice({}, "gamepad", "a", "primary", "mouse_left")
    b = bindings.set_choice(b, "gamepad", "a", "secondary", "screenshot")
    assert bindings.zone_slots(5, b, "gamepad") == ["03-01", "04-03-82-88-1B", "01-02", "00-00"]
    # the desktop set is unaffected by a gamepad choice
    assert bindings.zone_slots(5, b, "desktop") == ["02-5A", "00-00", "02-76", "00-00"]
    assert bindings.zones_with_choices(b) == [5]


def test_desktop_choice_only_in_desktop():
    b = bindings.set_choice({}, "desktop", "b", "secondary", "win")
    assert bindings.zone_slots(5, b, "desktop") == ["02-5A", "00-00", "02-76", "02-82"]
    assert bindings.zone_slots(5, b, "gamepad") == ["01-01", "00-00", "01-02", "00-00"]


def test_back_buttons_factory_shift():
    assert bindings.zone_slots(8, {}, "gamepad") == ["02-8E", "02-8E", "02-8F", "02-8F"]
    assert bindings.zone_slots(8, {}, "desktop") == ["02-8E", "02-8E", "02-8F", "02-8F"]


def test_m1_switch_off_with_primary():
    b = bindings.set_back_secondary({}, "back_right", False)
    b = bindings.set_choice(b, "gamepad", "back_right", "primary", "b")
    assert bindings.zone_slots(8, b, "gamepad") == ["02-8E", "02-8E", "01-02", "02-8F"]
    # no primary in the desktop set: M1 does nothing
    assert bindings.zone_slots(8, b, "desktop") == ["02-8E", "02-8E", "00-00", "02-8F"]


def test_m1_switch_off_without_primary_does_nothing():
    b = bindings.set_back_secondary({}, "back_right", False)
    assert bindings.zone_slots(8, b, "gamepad") == ["02-8E", "02-8E", "00-00", "02-8F"]
    assert b["m1_secondary"] is False and b["m2_secondary"] is True


def test_m2_switch_off():
    b = bindings.set_back_secondary({}, "back_left", False)
    b = bindings.set_choice(b, "gamepad", "back_left", "primary", "a")
    assert bindings.zone_slots(8, b, "gamepad") == ["01-01", "02-8E", "02-8F", "02-8F"]


def test_primary_ignored_while_switch_on():
    b = bindings.set_choice({}, "gamepad", "back_right", "primary", "b")
    assert bindings.zone_slots(8, b, "gamepad") == ["02-8E", "02-8E", "02-8F", "02-8F"]
    assert bindings.set_back_secondary(b, "back_right", False)["gamepad"]["back_right"] == {"primary": "b"}


def test_v1_conversion():
    b = bindings.clean({"back_right": "b", "combos": {"a": "screenshot"}})
    assert b == {"gamepad": {"back_right": {"primary": "b"}, "a": {"secondary": "screenshot"}}, "desktop": {},
                 "m1_secondary": False, "m2_secondary": True}
    assert bindings.zone_slots(8, b, "gamepad") == ["02-8E", "02-8E", "01-02", "02-8F"]
    assert bindings.zone_slots(5, b, "gamepad") == ["01-01", "04-03-82-88-1B", "01-02", "00-00"]


def test_v1_shift_and_old_keys_only():
    b = bindings.clean({"back_left": "shift", "back_right": "shift"})
    assert b == V2_FACTORY
    b = bindings.clean({"back_left": "x"})
    assert b["m2_secondary"] is False and b["m1_secondary"] is True
    assert b["gamepad"] == {"back_left": {"primary": "x"}}


def test_v1_junk_dropped():
    raw = {"back_left": "rocket", "combos": {"a": "rocket", "zz": "b", "back_left": "b"}, "x": 1}
    assert bindings.clean(raw) == V2_FACTORY


def test_clean_v2_roundtrip_and_junk():
    raw = {"gamepad": {"a": {"primary": "b", "secondary": "rocket", "extra": 1}, "zz": {"primary": "a"},
                       "x": "oops", "y": {}},
           "desktop": {"du": {"secondary": "esc"}}, "m1_secondary": 0, "m2_secondary": False}
    out = bindings.clean(raw)
    assert out == {"gamepad": {"a": {"primary": "b"}}, "desktop": {"du": {"secondary": "esc"}},
                   "m1_secondary": True, "m2_secondary": False}
    assert bindings.clean(out) == out
    assert bindings.clean(None) == V2_FACTORY
    assert bindings.clean("x") == V2_FACTORY
    assert bindings.clean({"gamepad": "x", "desktop": 5}) == V2_FACTORY


def test_factory_action_removes_and_reset_button():
    b = bindings.set_choice({}, "gamepad", "a", "primary", "b")
    b = bindings.set_choice(b, "gamepad", "a", "secondary", "win")
    b = bindings.set_choice(b, "gamepad", "a", "primary", bindings.FACTORY)
    assert b["gamepad"] == {"a": {"secondary": "win"}}
    b = bindings.set_choice(b, "gamepad", "a", "secondary", "factory")
    assert b == V2_FACTORY
    b = bindings.set_choice(b, "desktop", "a", "primary", "esc")
    assert bindings.reset_button(b, "desktop", "a") == V2_FACTORY
    # bad input leaves the dict unchanged
    assert bindings.set_choice({}, "gamepad", "zz", "primary", "a") == V2_FACTORY
    assert bindings.set_choice({}, "gamepad", "a", "primary", "rocket") == V2_FACTORY
    assert bindings.set_choice({}, "nope", "a", "primary", "a") == V2_FACTORY
    assert bindings.set_choice({}, "gamepad", "a", "third", "a") == V2_FACTORY


def test_setters_do_not_mutate_input():
    b = bindings.clean(None)
    bindings.set_choice(b, "gamepad", "a", "primary", "b")
    bindings.set_back_secondary(b, "back_right", False)
    assert b == V2_FACTORY


def test_zones_with_choices_both_sets_and_switches():
    assert bindings.zones_with_choices({}) == []
    b = bindings.set_choice({}, "gamepad", "a", "primary", "b")
    b = bindings.set_choice(b, "desktop", "du", "secondary", "esc")
    assert bindings.zones_with_choices(b) == [1, 5]
    b = bindings.set_back_secondary(b, "back_left", False)
    assert bindings.zones_with_choices(b) == [1, 5, 8]
    assert bindings.zones_with_choices(bindings.set_back_secondary({}, "back_right", False)) == [8]


def test_factory_all_zones_match_ghelper():
    assert bindings.all_zones() == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert bindings.zone_slots(1, {}, "gamepad") == ["01-09", "05-19", "01-0A", "04-02-82-23"]
    assert bindings.zone_slots(9, {}, "desktop") == ["04-02-88-0D", "00-00", "03-02", "00-00"]


def test_actions_unique_and_codes_valid():
    ids = [a[0] for a in bindings.ACTIONS]
    assert len(ids) == len(set(ids))
    rx = re.compile(r"^(00-00|0[1235]-[0-9A-F]{2}|04-0[1-5](-[0-9A-F]{2})+)$")
    for _id, _label, code in bindings.ACTIONS:
        assert rx.match(code), code


def test_keep_zones_takes_the_new_choices_only_in_those_zones():
    old = {"gamepad": {"du": {"secondary": "esc"}, "a": {"secondary": "tab"}, "x": {"secondary": "win"}},
           "desktop": {"b": {"primary": "a"}, "du": {"primary": "a"}},
           "m1_secondary": False, "m2_secondary": False}
    new = bindings.clean(None)
    out = bindings.keep_zones(old, new, [1, 8])
    assert out == {"gamepad": {"a": {"secondary": "tab"}, "x": {"secondary": "win"}},
                   "desktop": {"b": {"primary": "a"}}, "m1_secondary": True, "m2_secondary": True}
    assert bindings.keep_zones(old, new, []) == bindings.clean(old)
    new2 = bindings.set_choice({}, "desktop", "b", "primary", "esc")
    out2 = bindings.keep_zones(old, new2, [5])
    assert out2["desktop"] == {"b": {"primary": "esc"}, "du": {"primary": "a"}}
    assert out2["gamepad"] == {"du": {"secondary": "esc"}, "x": {"secondary": "win"}}
    assert out2["m1_secondary"] is False
