"""Button mapping model (Armoury Crate style): turns the owner's choices into the controller's binding-zone slots.

A zone holds two buttons; its report carries four slots: first button, first button's combo, second button, second
button's combo. The combo slot is the button's Secondary function, the button slot its Primary. Settings shape:
{"gamepad": {<button id>: {"primary": <action id>, "secondary": <action id>}}, "desktop": {...}, "m1_secondary": bool,
"m2_secondary": bool}; a missing entry means the factory binding of that set (G-Helper gamepad or desktop defaults;
the factory secondary is the same for both). The two back buttons (M1 = back_right 02-8F, M2 = back_left 02-8E) have a
switch "use as secondary function" (default on, shared by both sets): on, both slots hold the factory Shift code; off,
the button slot holds its Primary (Nothing when none) and the secondary slot keeps the Shift code (the zone-8 report
proven on the device: 02-8E, 02-8E, 01-02, 02-8F for M1 as B). The v1 shape ({"back_left": <action id | "shift">,
"back_right": ..., "combos": {<button id>: <action id>}}) is converted by clean(): a v1 back-button action becomes
that button's Primary in both sets with its switch off (the switch is shared, so the button is not dead in Desktop).
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
SETS = ("gamepad", "desktop")
FACTORY = "factory"
_SWITCH = {"back_left": "m2_secondary", "back_right": "m1_secondary"}
_SLOTS = ("primary", "secondary")
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


def _blank() -> dict:
    return {"gamepad": {}, "desktop": {}, "m1_secondary": True, "m2_secondary": True}


def clean(raw) -> dict:
    """Keep only known ids (v2 shape, or a v1 dict converted); never raises. Empty entries are dropped."""
    out = _blank()
    if not isinstance(raw, dict):
        return out
    if any(k in raw for k in SETS) or any(k in raw for k in _SWITCH.values()):
        for name in SETS:
            sec = raw.get(name)
            if not isinstance(sec, dict):
                continue
            for bid, entry in sec.items():
                if not (isinstance(bid, str) and bid in _BUTTON and isinstance(entry, dict)):
                    continue
                kept = {}
                for slot in _SLOTS:
                    v = entry.get(slot)
                    if isinstance(v, str) and v in _CODE and not (slot == "secondary" and bid in BACK):
                        kept[slot] = v
                if kept:
                    out[name][bid] = kept
        for sw in _SWITCH.values():
            if isinstance(raw.get(sw), bool):
                out[sw] = raw[sw]
        return out
    for k in BACK:   # v1: a back button action becomes its gamepad Primary with the switch off
        v = raw.get(k)
        if isinstance(v, str) and v != "shift" and v in _CODE:
            for name in SETS:
                out[name][k] = {"primary": v}
            out[_SWITCH[k]] = False
    combos = raw.get("combos")
    if isinstance(combos, dict):
        for k, v in combos.items():
            if isinstance(k, str) and k in _BUTTON and k not in BACK and isinstance(v, str) and v in _CODE:
                out["gamepad"][k] = {"secondary": v}
    return out


def _is_id(v, known) -> bool:
    return isinstance(v, str) and v in known


def _slots(bid: str, b: dict, set_name: str) -> list:
    """The button's slot (Primary) and its combo slot (Secondary)."""
    base, combo = _GAMEPAD[bid]
    entry = b[set_name].get(bid, {})
    if bid in BACK:
        if b[_SWITCH[bid]]:
            return [SHIFT[bid], SHIFT[bid]]
        p = entry.get("primary")
        return [_CODE[p] if p is not None else NONE, SHIFT[bid]]
    if set_name == "desktop":
        base = _DESKTOP.get(bid, base)
    p, s = entry.get("primary"), entry.get("secondary")
    return [_CODE[p] if p is not None else base, _CODE[s] if s is not None else combo]


def zone_slots(zone: int, bindings: dict, set_name: str) -> list:
    """Four codes for the zone in the given set: first button, its combo, second button, its combo."""
    if not _is_id(set_name, SETS):
        raise ValueError(f"unknown mapping set: {set_name!r}")
    b = clean(bindings)
    name = set_name
    out: list = []
    for bid, _label, _z, _side in sorted((x for x in BUTTONS if x[2] == zone), key=lambda x: x[3]):
        out += _slots(bid, b, name)
    return out


def zones_with_choices(bindings: dict) -> list:
    """Sorted zones where the owner chose something in either set, or a back button's switch is off."""
    b = clean(bindings)
    zones = {_BUTTON[bid][2] for name in SETS for bid in b[name]}
    for k, sw in _SWITCH.items():
        if not b[sw]:
            zones.add(_BUTTON[k][2])
    return sorted(zones)


def set_choice(bindings: dict, set_name: str, button: str, slot: str, action) -> dict:
    """A new cleaned dict with the button's Primary or Secondary set; FACTORY (or None) removes it. Unknown ids,
    a Secondary on a back button, or an unknown set leave the settings as they were."""
    b = clean(bindings)
    if not (_is_id(set_name, SETS) and _is_id(button, _BUTTON) and _is_id(slot, _SLOTS)) or (
            slot == "secondary" and button in BACK):
        return b
    if action is None or action == FACTORY:
        entry = b[set_name].get(button)
        if entry is not None:
            entry.pop(slot, None)
            if not entry:
                del b[set_name][button]
        return b
    if _is_id(action, _CODE):
        b[set_name].setdefault(button, {})[slot] = action
    return b


def set_back_secondary(bindings: dict, side: str, on: bool) -> dict:
    """A new cleaned dict with the "use as secondary function" switch of back_left (M2) / back_right (M1) set."""
    b = clean(bindings)
    if _is_id(side, _SWITCH) and isinstance(on, bool):
        b[_SWITCH[side]] = on
    return b


def reset_button(bindings: dict, set_name: str, button: str) -> dict:
    """A new cleaned dict with the button's Primary and Secondary in that set back to factory."""
    b = clean(bindings)
    if _is_id(set_name, SETS) and _is_id(button, _BUTTON):
        b[set_name].pop(button, None)
    return b


def all_zones() -> list:
    """Every binding zone, 1 to 9."""
    return list(range(1, 10))


def keep_zones(old: dict, new: dict, zones) -> dict:
    """`new`'s choices for the buttons in `zones` (both sets; zone 8 also the back switches), `old`'s for every other
    button (a write that landed only in some zones: the stored set matches what the controller holds)."""
    o, n = clean(old), clean(new)
    zones = set(zones)
    out = _blank()
    for bid, _label, zone, _side in BUTTONS:
        src = n if zone in zones else o
        for name in SETS:
            if bid in src[name]:
                out[name][bid] = dict(src[name][bid])
    for bid, sw in _SWITCH.items():
        out[sw] = (n if _BUTTON[bid][2] in zones else o)[sw]
    return out
