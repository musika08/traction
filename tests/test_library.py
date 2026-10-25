"""The Library button model (library.py): choices, Armoury Crate's saved ids and the slots sent to the helper."""
import os
import re

from traction import library

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESS_CS = os.path.join(ROOT, "helper", "src", "PressBindings.cs")
BINDINGS_CS = os.path.join(ROOT, "helper", "src", "Bindings.cs")
SLOT_FORM = re.compile(r"^[0-9A-F]{2}(?:-[0-9A-F]{2}){8}$")
OWNER = {"LibBtnSFunctId": 33, "LibBtnLFunctId": 8, "CCBtnSFunctId": 9, "CCBtnLFunctId": 10}


def reader(values):
    def read(name):
        if name not in values:
            raise FileNotFoundError(name)
        return values[name]
    return read


def well_formed(slot):
    assert isinstance(slot, str) and len(slot) == 26 and SLOT_FORM.match(slot), slot


def test_choices_order_and_labels():
    ids = [c[0] for c in library.CHOICES]
    assert library.CHOICES[0] == ("armoury", "Armoury Crate setting") and library.ARMOURY == "armoury"
    assert ids[1:12] == ["asus_show_desktop", "asus_task_manager", "asus_screen_capture", "asus_volume_up",
                         "asus_volume_down", "asus_mic_mute", "asus_touch_keyboard", "asus_game_bar",
                         "asus_xbox_library", "asus_controller_overview", "asus_launch_armoury"]
    assert ids[12:] == ["esc", "enter", "tab", "backspace", "space", "up", "down", "left", "right", "page_up",
                        "page_down", "win", "close_window", "alt_tab", "win_tab"]
    assert dict(library.CHOICES)["asus_launch_armoury"] == "Launch Armoury Crate"
    assert dict(library.CHOICES)["esc"] == "Esc" and dict(library.CHOICES)["alt_tab"] == "Alt+Tab"
    assert len(ids) == len(set(ids))


def test_slot_for_id():
    d = "05-00-27-00-00-00-00-00-00"
    assert library.slot_for_id(0x21, d) == "04-00-00-03-8C-88-76-00-00"
    assert library.slot_for_id(8, d) == "05-00-28-00-00-00-00-00-00"
    assert library.slot_for_id(9, d) == "05-00-17-00-00-00-00-00-00"
    assert library.slot_for_id(10, d) == "05-00-04-00-00-00-00-00-00"
    assert library.slot_for_id(0x22, d) == "04-00-00-02-82-0D-00-00-00"
    assert library.slot_for_id(0x2A, d) == "04-00-00-03-82-88-57-00-00"
    for unknown in (0x60, None, 0, 13, 0x20, 0x2B, -1, True, "33", 8.0):
        assert library.slot_for_id(unknown, d) == d, unknown
    for i in list(range(1, 13)) + list(range(0x21, 0x2B)):
        well_formed(library.slot_for_id(i, d))


def test_slot_for_choice():
    a = library.LIB_SINGLE
    assert library.slot_for_choice("armoury", a) == a
    assert library.slot_for_choice("asus_show_desktop", a) == "05-00-1C-00-00-00-00-00-00"
    assert library.slot_for_choice("esc", a) == "04-00-00-01-76-00-00-00-00"
    assert library.slot_for_choice("alt_tab", a) == "04-00-00-02-8A-0D-00-00-00"
    for junk in ("nothing", "a", "", None, 5):
        assert library.slot_for_choice(junk, a) == a
    for cid, _label in library.CHOICES:
        well_formed(library.slot_for_choice(cid, a))


def test_slots_keep_command_center():
    ids = library.armoury_ids(reader(OWNER))
    assert ids == {"lib_single": 33, "lib_long": 8, "cc_single": 9, "cc_long": 10}
    out = library.slots({"single": "asus_show_desktop", "long": "esc"}, ids)
    assert out == {"single": ["05-00-1C-00-00-00-00-00-00", "05-00-17-00-00-00-00-00-00"],
                   "long": ["04-00-00-01-76-00-00-00-00", "05-00-04-00-00-00-00-00-00"]}
    # "armoury" keeps Armoury Crate's own Library choice
    assert library.slots({"single": "armoury", "long": "armoury"}, ids) == {
        "single": ["04-00-00-03-8C-88-76-00-00", "05-00-17-00-00-00-00-00-00"],
        "long": ["05-00-28-00-00-00-00-00-00", "05-00-04-00-00-00-00-00-00"]}
    for pair in out.values():
        for slot in pair:
            well_formed(slot)


def test_registry_unreadable_uses_defaults():
    defaults = {"single": [library.LIB_SINGLE, library.CC_SINGLE], "long": [library.LIB_LONG, library.CC_LONG]}
    assert defaults == {"single": ["05-00-27-00-00-00-00-00-00", "05-00-17-00-00-00-00-00-00"],
                        "long": ["05-00-16-00-00-00-00-00-00", "05-00-04-00-00-00-00-00-00"]}

    def broken(name):
        raise OSError("access denied")
    for read in (broken, reader({}), reader({k: "33" for k in OWNER}), reader({k: None for k in OWNER}),
                 reader({k: 0x60 for k in OWNER}), reader({k: 0 for k in OWNER}), reader({k: b"\x21" for k in OWNER})):
        out = library.slots(library.default_library(), library.armoury_ids(read))
        assert out == defaults
        for pair in out.values():
            for slot in pair:
                well_formed(slot)
                assert slot != "00-00-00-00-00-00-00-00-00"
    # one value missing: only that one falls back
    some = library.armoury_ids(reader({"CCBtnSFunctId": 9}))
    assert some == {"lib_single": None, "lib_long": None, "cc_single": 9, "cc_long": None}
    assert library.slots({}, None) == defaults
    assert library.slots("junk", "junk") == defaults


def test_tests_never_read_the_real_registry():
    # conftest replaces the default reader: armoury_ids() with no reader reads nothing real.
    assert library.registry_read is not library._registry_read
    assert library.armoury_ids() == {k: None for k in library.REGISTRY_VALUES}


def test_clean_and_chosen():
    assert library.clean(None) == {"single": "armoury", "long": "armoury"}
    assert library.clean({"single": "esc", "long": "bogus"}) == {"single": "esc", "long": "armoury"}
    assert library.chosen({"single": "armoury", "long": "esc"}) and not library.chosen(library.default_library())


# ---------- the helper's allow-list (helper/src/PressBindings.cs) ----------

def _cs(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _bytes_block(src, name):
    m = re.search(r"\b" + name + r"\s*=\s*\{(.*?)\};", src, re.S)
    assert m, name + " not found in PressBindings.cs"
    return {int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1))}


def _allowed_keys():
    """PressBindings.KeysFromBindings: the key bytes of Bindings.Allowed's "02-xx" and "04-n-k.." codes."""
    m = re.search(r"\bAllowed\s*=\s*(?:new\s*string\[\]\s*)?\{(.*?)\n\s*\};", _cs(BINDINGS_CS), re.S)
    assert m, "Allowed not found in Bindings.cs"
    keys = set()
    for code in re.findall(r'"([0-9A-F]{2}(?:-[0-9A-F]{2})+)"', m.group(1)):
        p = code.split("-")
        start = 1 if p[0] == "02" else 2 if p[0] == "04" else len(p)
        keys.update(int(x, 16) for x in p[start:] if int(x, 16) != 0)
    return keys


def _helper_allows(slot, functions, keys):
    """PressBindings.IsAllowedSlot, in Python."""
    if not SLOT_FORM.match(slot):
        return False
    b = [int(x, 16) for x in slot.split("-")]
    if b[0] == 0x05:
        return b[1] == 0 and b[2] in functions and not any(b[3:])
    if b[0] == 0x04:
        n = b[3]
        if b[1] or b[2] or not 1 <= n <= 3:
            return False
        return all(k and k in keys for k in b[4:4 + n]) and not any(b[4 + n:])
    return False


def test_choices_codes_in_helper_allow_list():
    src = _cs(PRESS_CS)
    functions = _bytes_block(src, "FunctionCodes")
    keys = _allowed_keys() | _bytes_block(src, "ArmouryShortcutKeys")
    assert 0x1C in functions and 0x8C in keys   # the parse found the lists
    for cid, _label in library.CHOICES[1:]:
        slot = library.slot_for_choice(cid, "")
        assert _helper_allows(slot, functions, keys), (cid, slot)
    for i in list(range(1, 13)) + list(range(0x21, 0x2B)):
        slot = library.slot_for_id(i, "")
        assert _helper_allows(slot, functions, keys), (hex(i), slot)
    for slot in (library.LIB_SINGLE, library.LIB_LONG, library.CC_SINGLE, library.CC_LONG):
        assert _helper_allows(slot, functions, keys), slot
    assert not _helper_allows("05-00-FF-00-00-00-00-00-00", functions, keys)   # the check itself refuses junk
