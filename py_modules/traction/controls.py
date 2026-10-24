"""Touchscreen and the ASUS controller (mode + grip vibration), moved from Overdrive ba0307a controls.py unchanged in
behaviour.

Thin layer over the helper's commands. Every function returns {"ok", "message", ...}; a helper refusal or a missing
feature is reported, never raised.

get_touchscreen spawns PowerShell in the helper and can take up to 5 s, so read_controls keeps the last touchscreen
status for TOUCH_TTL seconds and a state poll never waits on it more than once per that time. set_touchscreen returns
at once (the change lands later): it drops the cache, so the next read asks the real device, and for TOUCH_SETTLE
seconds every read asks again until the device shows the requested state (the panel polls that long).
A failed read changes nothing: the last good status is reported (not found when there is none yet) and the cache time
is not refreshed, so the next read asks again; a failure never hides the toggle or passes for the requested state.
"""
import logging
import time
from typing import Optional

from . import bindings
from .helper_client import is_transport_failure
from .settings import CONTROLLER_MODES, Settings

TOUCH_TTL = 30.0
TOUCH_SETTLE = 15.0             # seconds after set_touchscreen in which reads skip the cache until the change shows
# set_bindings: up to 5 s of pad polling after the write, then the factory reset (17 HID writes) when the pad went.
BINDINGS_TIMEOUT = 20.0

clock = time.monotonic          # tests replace it
_touch = {"at": None, "value": None, "want": None, "until": None}
_bindings_logged: set = set()   # binding-write failures already logged (once per kind until a write lands)
_bindings_calls = [0]           # set_bindings calls in flight (get_state reads nothing meanwhile)

# A reply that failed on the way (helper restarted, did not answer, not running), not a device refusal.
transport_failure = is_transport_failure


def reset_cache() -> None:
    _touch.update(at=None, value=None, want=None, until=None)
    _bindings_logged.clear()


def bindings_in_flight() -> bool:
    """True while a set_bindings call runs: a read sent now would queue behind its pad polling and factory reset, and
    two timed-out reads in a row get the helper killed (mid-reset). get_state shows the last reading instead."""
    return _bindings_calls[0] > 0


def _result(ok: bool, message: str = "", **extra) -> dict:
    return {"ok": ok, "message": message, **extra}


def _data(reply: dict) -> Optional[dict]:
    data = reply.get("data") if reply.get("ok") else None
    return data if isinstance(data, dict) else None


def _msg(reply: dict, fallback: str) -> str:
    return str(reply.get("message") or fallback)


async def touchscreen_status(client) -> dict:
    now = clock()
    settling = _touch["want"] is not None and now < _touch["until"]
    if not settling:
        _touch["want"] = _touch["until"] = None
    cached = _touch["at"] is not None and now - _touch["at"] < TOUCH_TTL
    if cached and not (settling and _touch["value"]["enabled"] != _touch["want"]):
        return _touch["value"]
    d = _data(await client.call("get_touchscreen", {}, timeout=15.0))
    if d is None:   # a failed read: keep the last good status and its time (asked again at the next read)
        return _touch["value"] or {"found": False, "enabled": False}
    value = {"found": bool(d.get("found")), "enabled": bool(d.get("enabled"))}
    _touch["at"], _touch["value"] = clock(), value
    return value


async def read_controller(client) -> "tuple[dict, dict]":
    """({"found": bool}, the controller_info reply)."""
    r = await client.call("controller_info", {})
    d = _data(r)
    return {"found": bool(d.get("found")) if d is not None else False}, r


async def read_controls(client) -> dict:
    """The state get_state shows for the controller and the touchscreen. A command the helper cannot serve marks its
    feature not found; nothing here raises."""
    controller, _ = await read_controller(client)
    touch = await touchscreen_status(client)
    return {"ok": True, "message": "", "controller": controller,
            "touchscreen": {"found": touch["found"], "enabled": touch["enabled"]}}


async def set_touchscreen(client, enabled: bool) -> dict:
    r = await client.call("set_touchscreen", {"enabled": bool(enabled)})
    if not r.get("ok"):
        return _result(False, _msg(r, "The touchscreen was not changed."))
    # The change lands a little later: show only what the device reports (C4). Until it shows the requested state
    # (or TOUCH_SETTLE passes), every read asks the device again.
    # The last good status is kept (cache time dropped): a failed read meanwhile reports it, never the target.
    _touch.update(at=None, want=bool(enabled), until=clock() + TOUCH_SETTLE)
    return _result(True, "", enabled=bool(enabled))


async def write_zones(client, chosen: dict, mode: str, zones, logger: Optional[logging.Logger] = None,
                      watch: bool = True) -> dict:
    """Writes each zone's four slots for `mode` from that mode's set ("desktop": the owner's Desktop set over
    G-Helper's desktop defaults; gamepad/auto: the Gamepad set over the gamepad defaults). Stops at the first failure;
    `written` lists the zones that landed. `reset` is True when the pad went away after a write (the helper then wrote
    the factory set, or tried to: data.reset true or false); a refusal before the write ("Windows does not see the
    gamepad", data null) is not a reset: nothing was written. `uncertain` is the zone whose reply failed on the way
    (it may have landed), else None. watch False asks the helper for no pad check, no polling and no factory reset
    (Desktop mode hides the XInput pad). Each kind of failure is logged once until a write lands."""
    set_name = "desktop" if mode == "desktop" else "gamepad"
    log = logger or logging.getLogger("traction")
    written = []
    for zone in zones:
        args = {"zone": zone, "slots": bindings.zone_slots(zone, chosen, set_name)}
        if not watch:
            args["watch"] = False
        _bindings_calls[0] += 1
        try:
            r = await client.call("set_bindings", args, timeout=BINDINGS_TIMEOUT)
        finally:
            _bindings_calls[0] -= 1
        if r.get("ok"):
            written.append(zone)
            continue
        message = _msg(r, "The buttons were not changed.")
        data = r.get("data")
        reset = isinstance(data, dict) and "reset" in data
        if message not in _bindings_logged:
            _bindings_logged.add(message)
            log.warning(f"Button bindings: zone {zone} not written: {message}")
        transport = transport_failure(r)
        return _result(False, message, reset=reset, transport=transport, written=written,
                       uncertain=zone if transport else None)
    if zones:
        _bindings_logged.clear()
    return _result(True, "", reset=False, transport=False, written=written, uncertain=None)


def note_written(settings: Settings, chosen: dict, mode: str, written, uncertain: Optional[int] = None) -> bool:
    """Updates settings.touched_zones after zones were written from `chosen` for `mode`: a zone with an owner choice
    (in either set, or a back switch off) is touched, and so is every zone written in Desktop, since desktop slots are
    not the Gamepad factory set; a zone leaves only after a Gamepad (non-desktop) factory write. The `uncertain` zone
    (its reply failed on the way, so it may hold what was sent) is touched, so a later write puts it right. True when
    the set changed (the caller saves)."""
    changed = set(bindings.zones_with_choices(chosen))
    before = set(settings.touched_zones)
    for zone in written:
        if zone in changed or mode == "desktop":
            settings.touched_zones.add(zone)
        elif mode != "desktop":
            settings.touched_zones.discard(zone)
    if uncertain is not None:
        settings.touched_zones.add(uncertain)
    return settings.touched_zones != before


def forget_bindings(settings: Settings) -> None:
    """After the helper's factory reset (the pad went away): no owner choice in either set, both back switches on
    (Shift), and no touched zone is left."""
    settings.bindings = bindings.clean(None)
    settings.touched_zones = set()


async def apply_bindings(client, settings: Settings, mode: str, logger: Optional[logging.Logger] = None) -> dict:
    """Writes the zones with a choice in either set plus the touched ones, from `mode`'s set (factory slots where that
    set has no choice), so the pad matches the active set whatever the firmware did on the mode switch; Desktop writes
    are not watched (the pad is hidden in Desktop mode). When the pad went away after a write (the helper reset it to
    the factory set) the stored bindings and touched zones are cleared and saved, so no later reapply writes them
    again; the caller then has the mode and vibration rewritten (`reset` True)."""
    zones = sorted(set(bindings.zones_with_choices(settings.bindings)) | set(settings.touched_zones))
    if not zones:
        return _result(True, "", reset=False, transport=False, written=[], uncertain=None)
    chosen = bindings.clean(settings.bindings)
    r = await write_zones(client, chosen, mode, zones, logger, watch=mode != "desktop")
    if r["reset"]:
        forget_bindings(settings)
        save = True
    else:
        save = note_written(settings, chosen, mode, r["written"], r["uncertain"])
    if save:
        try:
            settings.save()
        except OSError as e:
            (logger or logging.getLogger("traction")).error(f"Could not save the button bindings: {e}")
    return r


async def apply_controller(client, settings: Settings, mode: Optional[str] = None,
                           logger: Optional[logging.Logger] = None) -> dict:
    """Writes the controller mode ("auto" starts in Gamepad), right after it the changed button zones for that mode,
    then the grip vibration. Every failure is reported. A failed bindings write (pad not seen, pad reset) does not
    fail the mode: its message is in `warning`. The bindings are skipped when the mode write failed (desktop slots
    must not land on a pad left in Gamepad, nor the other way round). `reset` is True when the helper wrote the
    factory set (Gamepad, vibration 100): the caller has the next reapply tick write the mode and vibration again."""
    mode = mode or settings.controller_mode
    if mode not in CONTROLLER_MODES:
        return _result(False, "Unknown controller mode.", reset=False)
    problems = []
    warning = ""
    reset = False
    r = await client.call("set_controller_mode", {"mode": "desktop" if mode == "desktop" else "gamepad"})
    if not r.get("ok"):
        problems.append(_msg(r, "The controller mode was not applied."))
        if transport_failure(r):   # the helper is gone: the vibration write would only fail the same way
            return _result(False, " ".join(problems), mode=mode, warning="", reset=False)
    else:
        b = await apply_bindings(client, settings, mode, logger)
        reset = bool(b["reset"])
        if b["transport"]:
            problems.append(b["message"])
            return _result(False, " ".join(problems), mode=mode, warning="", reset=reset)
        if not b["ok"]:
            warning = b["message"]
    r = await client.call("set_vibration", {"strength": 100 if settings.grip_vibration else 0})
    if not r.get("ok"):
        problems.append(_msg(r, "The grip vibration was not applied."))
    return _result(not problems, " ".join(problems), mode=mode, warning=warning, reset=reset)
