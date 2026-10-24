"""Button mapping model: turns the owner's choices into the controller's binding-zone slots.

A zone holds two buttons; its report carries four slots: first button, first button's combo, second button, second
button's combo. Settings shape: {"back_left": <action id | "shift">, "back_right": <...>, "combos": {<button id>:
<action id>}}; a missing key means the factory binding. "shift" is the factory code of the back button (02-8E left,
02-8F right). Only the Gamepad mode uses the owner's set; Desktop gets G-Helper's desktop defaults.
"""

# (id, label, code)
ACTIONS = [
    ("nothing", "Nothing", "00-00"),
    ("a", "A", "01-01"), ("b", "B", "01-02"), ("x", "X", "01-03"), ("y", "Y", "01-04"),
    ("lb", "LB", "01-05"), ("rb", "RB", "01-06"),
    ("ls", "Left stick click", "01-07"), ("rs", "Right stick click", "01-08"),
    ("du", "D-pad up", "01-09"), ("dd", "D-pad down", "01-0A"),
    ("dl", "D-pad left", "01-0B"), ("dr", "D-pad right", "01-0C"),
    ("lt", "LT", "01-0D"), ("rt", "RT", "01-0E"),
    ("view", "View", "01-11"), ("menu", "Menu", "01-12"),
    ("mouse_left", "Left click", "03-01"), ("mouse_right", "Right click", "03-02"),
    ("mouse_middle", "Middle click", "03-03"),
    ("scroll_up", "Scroll up", "03-04"), ("scroll_down", "Scroll down", "03-05"),
    ("esc", "Esc", "02-76"), ("enter", "Enter", "02-5A"), ("tab", "Tab", "02-0D"),
    ("backspace", "Backspace", "02-66"), ("space", "Space", "02-29"),
    ("up", "Up arrow", "02-98"), ("down", "Down arrow", "02-99"),
    ("left", "Left arrow", "02-9A"), ("right", "Right arrow", "02-9B"),
    ("page_up", "Page Up", "02-96"), ("page_down", "Page Down", "02-97"),
    ("win", "Windows key", "02-82"),
    ("show_desktop", "Show desktop", "04-02-82-23"),
    ("screenshot", "Screenshot", "04-03-82-88-1B"),
    ("task_manager", "Task Manager", "04-03-8C-88-76"),
    ("close_window", "Close window", "04-02-8A-0C"),
    ("alt_tab", "Alt+Tab", "04-02-8A-0D"),
    ("win_tab", "Win+Tab", "04-02-82-0D"),
    ("volume_up", "Volume up", "05-03"), ("volume_down", "Volume down", "05-02"),
    ("touch_keyboard", "Show touch keyboard", "05-19"),
]

# (id, label, zone, side): side 0 is the zone's first button, 1 the second.
BUTTONS = [
    ("du", "D-pad up", 1, 0), ("dd", "D-pad down", 1, 1),
    ("dl", "D-pad left", 2, 0), ("dr", "D-pad right", 2, 1),
    ("ls", "Left stick click", 3, 0), ("rs", "Right stick click", 3, 1),
    ("lb", "LB", 4, 0), ("rb", "RB", 4, 1),
    ("a", "A", 5, 0), ("b", "B", 5, 1),
    ("x", "X", 6, 0), ("y", "Y", 6, 1),
    ("view", "View", 7, 0), ("menu", "Menu", 7, 1),
    ("back_left", "Left back button", 8, 0), ("back_right", "Right back button", 8, 1),
    ("lt", "LT", 9, 0), ("rt", "RT", 9, 1),
]

NONE = "00-00"
SHIFT = {"back_left": "02-8E", "back_right": "02-8F"}
BACK = tuple(SHIFT)
_CODE = {a[0]: a[2] for a in ACTIONS}
_BUTTON = {b[0]: b for b in BUTTONS}

# G-Helper gamepad defaults: id -> (button code, combo code).
_GAMEPAD = {
    "du": ("01-09", "05-19"), "dd": ("01-0A", "04-02-82-23"),
    "dl": ("01-0B", "04-04-8C-88-8A-05"), "dr": ("01-0C", "04-04-8C-88-8A-06"),
    "ls": ("01-07", NONE), "rs": ("01-08", "04-04-8C-88-8A-0C"),
    "lb": ("01-05", NONE), "rb": ("01-06", NONE),
    "a": ("01-01", NONE), "b": ("01-02", NONE),
    "x": ("01-03", "04-03-82-88-1B"), "y": ("01-04", "04-04-8C-88-8A-44"),
    "view": ("01-11", NONE), "menu": ("01-12", NONE),
    "lt": ("01-0D", NONE), "rt": ("01-0E", NONE),
    "back_left": ("02-8E", "02-8E"), "back_right": ("02-8F", "02-8F"),
}
# G-Helper desktop (Mouse mode) button codes that differ from the gamepad ones; combos stay as gamepad.
_DESKTOP = {
    "du": "02-98", "dd": "02-99", "dl": "02-9A", "dr": "02-9B", "ls": "02-88", "rs": "03-01",
    "lb": "02-0D", "rb": "03-01", "a": "02-5A", "b": "02-76", "x": "02-97", "y": "02-96",
    "lt": "04-02-88-0D", "rt": "03-02",
}


def clean(raw) -> dict:
    """Keep only known ids; anything else falls back to the factory binding. Never raises."""
    out = {"back_left": "shift", "back_right": "shift", "combos": {}}
    if not isinstance(raw, dict):
        return out
    for k in BACK:
        v = raw.get(k)
        if isinstance(v, str) and (v == "shift" or v in _CODE):
            out[k] = v
    combos = raw.get("combos")
    if isinstance(combos, dict):
        for k, v in combos.items():
            if isinstance(k, str) and k in _BUTTON and k not in BACK and isinstance(v, str) and v in _CODE:
                out["combos"][k] = v
    return out


def _slots(bid: str, b: dict, desktop: bool) -> list:
    """The button's slot and its combo slot."""
    base, combo = _GAMEPAD[bid]
    if desktop:
        return [_DESKTOP.get(bid, base), combo]
    if bid in BACK:
        v = b[bid]
        code = SHIFT[bid] if v == "shift" else _CODE[v]
        return [code, code]
    c = b["combos"].get(bid)
    return [base, _CODE[c] if c is not None else combo]


def zone_slots(zone: int, bindings: dict, desktop: bool) -> list:
    """Four codes for the zone: first button, its combo, second button, its combo."""
    b = clean(bindings)
    out: list = []
    for bid, _label, _z, _side in sorted((x for x in BUTTONS if x[2] == zone), key=lambda x: x[3]):
        out += _slots(bid, b, desktop)
    return out


def changed_zones(bindings: dict) -> list:
    """Sorted zones where the owner chose something."""
    b = clean(bindings)
    zones = set()
    for k in BACK:
        if b[k] != "shift":
            zones.add(_BUTTON[k][2])
    for k in b["combos"]:
        zones.add(_BUTTON[k][2])
    return sorted(zones)


def all_zones() -> list:
    """Every binding zone, 1 to 9."""
    return list(range(1, 10))
