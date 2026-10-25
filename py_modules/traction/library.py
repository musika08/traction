"""The Library button's single and long press (spec section 6, Part B revised).

Two controller reports (helper set_press_bindings) each carry a Library slot and a Command Center slot. A slot is 9
bytes written as upper-case hex joined by dashes ("05-00-1C-00-00-00-00-00-00", 26 characters; the helper's parser
takes nothing else): an ASUS action `05 00 <code> 00..`, or a key/shortcut `04 00 00 <n> k1..kn 00..`.

The owner picks a choice per press; "armoury" (the default) keeps Armoury Crate's saved choice, read from its
registry key. Command Center's slots are always Armoury Crate's setting. A missing, unreadable, non-numeric or unknown
registry value falls back to Armoury Crate's installed defaults, never a zero slot.
"""
from typing import Callable, Optional

from . import bindings

ARMOURY = "armoury"
PRESSES = ("single", "long")
REGISTRY_KEY = r"Software\ASUS\ARMOURY CRATE Service\GamepadCustomize"
REGISTRY_VALUES = {"lib_single": "LibBtnSFunctId", "lib_long": "LibBtnLFunctId",
                   "cc_single": "CCBtnSFunctId", "cc_long": "CCBtnLFunctId"}


def _asus(code: int) -> str:
    return "-".join(["05", "00", "%02X" % code] + ["00"] * 6)


def _keys(keys) -> str:
    keys = list(keys)
    return "-".join(["04", "00", "00", "%02X" % len(keys)] + ["%02X" % k for k in keys] + ["00"] * (5 - len(keys)))


# Armoury Crate's installed defaults (no saved choice).
LIB_SINGLE = _asus(0x27)
LIB_LONG = _asus(0x16)
CC_SINGLE = _asus(0x17)
CC_LONG = _asus(0x04)

# Armoury Crate's saved ids: 1..12 an ASUS action, 0x21..0x2A a shortcut (GamepadCustomizePlugin's combo table).
_ID_CODES = [0x19, 0x1C, 0x03, 0x02, 0x01, 0x16, 0x1E, 0x28, 0x17, 0x04, 0x26, 0x27]
_ID_SHORTCUTS = {0x21: (0x8C, 0x88, 0x76), 0x22: (0x82, 0x0D), 0x23: (0x82, 0x1C), 0x24: (0x8A, 0x0C),
                 0x25: (0x82, 0x1B), 0x26: (0x82, 0x55), 0x27: (0x8C, 0x8A, 0xC0), 0x28: (0x82, 0x78),
                 0x29: (0x82, 0x33), 0x2A: (0x82, 0x88, 0x57)}

_ASUS_CHOICES = [("asus_show_desktop", "Show desktop", 0x1C), ("asus_task_manager", "Task Manager", 0x1A),
                 ("asus_screen_capture", "Screen capture", 0x16), ("asus_volume_up", "Volume up", 0x03),
                 ("asus_volume_down", "Volume down", 0x02), ("asus_mic_mute", "Mic mute", 0x01),
                 ("asus_touch_keyboard", "Touch keyboard", 0x19), ("asus_game_bar", "Game Bar", 0x26),
                 ("asus_xbox_library", "Xbox Library", 0x27), ("asus_controller_overview", "Controller Overview", 0x28),
                 ("asus_launch_armoury", "Launch Armoury Crate", 0x04)]
_KEY_CHOICES = ("esc", "enter", "tab", "backspace", "space", "up", "down", "left", "right", "page_up", "page_down",
                "win", "close_window", "alt_tab", "win_tab")


def _key_slot(code: str) -> str:
    """bindings.ACTIONS' "02-xx" (key) or "04-n-k1..kn" (shortcut) as a slot."""
    p = [int(x, 16) for x in code.split("-")]
    if p[0] == 0x02:
        return _keys(p[1:])
    if p[0] == 0x04 and p[1] == len(p) - 2:
        return _keys(p[2:])
    raise ValueError(f"not a key or shortcut code: {code!r}")


_ACTION = {a[0]: a for a in bindings.ACTIONS}
_SLOT = {cid: _asus(code) for cid, _label, code in _ASUS_CHOICES}
_SLOT.update({cid: _key_slot(_ACTION[cid][2]) for cid in _KEY_CHOICES})

CHOICES = (((ARMOURY, "Armoury Crate setting"),) + tuple((cid, label) for cid, label, _code in _ASUS_CHOICES)
           + tuple((cid, _ACTION[cid][1]) for cid in _KEY_CHOICES))
CHOICE_IDS = frozenset(c[0] for c in CHOICES)


def default_library() -> dict:
    return {press: ARMOURY for press in PRESSES}


def clean(raw) -> dict:
    """{"single": id, "long": id}; anything unknown is "armoury". Never raises."""
    out = default_library()
    if isinstance(raw, dict):
        for press in PRESSES:
            v = raw.get(press)
            if isinstance(v, str) and v in CHOICE_IDS:
                out[press] = v
    return out


def chosen(settings_library) -> bool:
    """True when at least one press is not Armoury Crate's setting."""
    return any(v != ARMOURY for v in clean(settings_library).values())


def _registry_read(name: str):
    import winreg   # Windows only; here so the module imports anywhere
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
        return winreg.QueryValueEx(key, name)[0]


# The reader armoury_ids uses when none is passed (tests replace it: they never read the real registry).
registry_read: Callable[[str], object] = _registry_read


def armoury_ids(read: Optional[Callable[[str], object]] = None) -> dict:
    """Armoury Crate's saved ids: {lib_single, lib_long, cc_single, cc_long}, each an int or None (missing, unreadable
    or not a number)."""
    read = read or registry_read
    out = {}
    for k, name in REGISTRY_VALUES.items():
        try:
            v = read(name)
        except Exception:
            v = None
        out[k] = v if type(v) is int else None
    return out


def slot_for_id(id: Optional[int], default: str) -> str:
    """The slot for an Armoury Crate saved id; `default` for anything unknown."""
    if type(id) is not int:
        return default
    if 1 <= id <= len(_ID_CODES):
        return _asus(_ID_CODES[id - 1])
    if id in _ID_SHORTCUTS:
        return _keys(_ID_SHORTCUTS[id])
    return default


def slot_for_choice(choice: str, armoury_slot: str) -> str:
    """The owner's choice as a slot; "armoury" (or anything unknown) is `armoury_slot`."""
    return _SLOT.get(choice, armoury_slot) if isinstance(choice, str) else armoury_slot


def slots(settings_library: dict, ids: dict) -> dict:
    """set_press_bindings' args: {"single": [library, command center], "long": [...]}. Command Center always keeps
    Armoury Crate's setting."""
    lib = clean(settings_library)
    ids = ids if isinstance(ids, dict) else {}
    return {
        "single": [slot_for_choice(lib["single"], slot_for_id(ids.get("lib_single"), LIB_SINGLE)),
                   slot_for_id(ids.get("cc_single"), CC_SINGLE)],
        "long": [slot_for_choice(lib["long"], slot_for_id(ids.get("lib_long"), LIB_LONG)),
                 slot_for_id(ids.get("cc_long"), CC_LONG)],
    }
