import asyncio
import os
import sys
import types

import decky  # type: ignore

# The loader appends py_modules to sys.path; older Windows builds did not, so make sure.
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_PY_MODULES = os.path.join(PLUGIN_DIR, "py_modules")
if _PY_MODULES not in sys.path:
    sys.path.append(_PY_MODULES)

from traction import bindings, controls, device, library  # noqa: E402
from traction.armoury_record import RECORD_DIR, ArmouryLocked, ArmouryRecord  # noqa: E402
from traction.armoury_switch import ArmourySwitch, migrate_from_settings  # noqa: E402
from traction.controller_auto import ControllerAuto  # noqa: E402
from traction.helper_client import HelperClient  # noqa: E402
from traction.overdrive_compat import (UPDATE_NOTE, find_overdrive, find_overdrive_settings,  # noqa: E402
                                       old_overdrive, overdrive_holds_armoury_record, read_old_record)
from traction.reapply import Reapplier  # noqa: E402
from traction.settings import CONTROLLER_MODES, Settings, migrate_from_overdrive  # noqa: E402
from traction.wake_win32 import last_wake_id  # noqa: E402

NAME = "Traction"
HELPER_EXE = "traction-helper.exe"
NOT_ALLY = "Traction supports the ROG Ally family only"
BUSY = "Traction is switching Armoury Crate services. Try again when it finishes."
NO_CONTROLLER = "The controller was not found; the choice is saved and applied when it is back."
ARMOURY_RUNNING = "Armoury Crate is running, so these settings may be overwritten."
LIBRARY_ARMOURY = ("Armoury Crate is running, so its Library setting applies. Turn on Use Traction instead of Armoury "
                   "Crate to change it here.")
NOT_MOVED = ("Overdrive's Armoury Crate record has not moved to the shared record yet. Open Overdrive once, then "
             "try again.")
MOVE_FAILED = ("Overdrive's Armoury Crate record could not be moved to the shared record yet, try again in a "
               "moment.")
OVERDRIVE_POLL = 5.0             # seconds between checks of an old Overdrive's version
MOVE_WAIT = 2.0                  # how long a move of Overdrive's orphaned record waits for the record lock
# The reply to an edit of the set whose mode is not on the pad (stored only).
SAVED_FOR = {"gamepad": "Saved. It applies when the controller is in Gamepad mode.",
             "desktop": "Saved. It applies when the controller is in Desktop mode."}
ACTION_IDS = frozenset(a[0] for a in bindings.ACTIONS)
BUTTON_ZONES = {b[0]: b[2] for b in bindings.BUTTONS}
BACK_ZONE = 8
BACK_SIDES = {"left": "back_left", "right": "back_right"}   # M2 = left back button, M1 = right
SLOTS = ("primary", "secondary")
UNREAD = {"controller": {"found": False}, "touchscreen": {"found": False, "enabled": False}}


class TractionHelperClient(HelperClient):
    """The shared HelperClient, running bin\\traction-helper.exe (the shared copy names Overdrive's exe)."""

    @property
    def exe_path(self) -> str:
        return os.path.join(self._plugin_dir, "bin", HELPER_EXE)


def settings_path() -> str:
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")


def overdrive_settings_path() -> str:
    """Overdrive's settings file: Decky gives each plugin <settings root>\\<plugin folder>, and Overdrive keeps
    overdrive.json in its folder (Overdrive main.py settings_path). The folder is the installed Overdrive's, found
    by its plugin.json name; with none installed, the first <settings root>\\*\\overdrive.json; "" when there is
    none."""
    root = os.path.dirname(os.path.normpath(decky.DECKY_PLUGIN_SETTINGS_DIR))
    folder = find_overdrive(plugins_dir())
    if folder is not None:
        return os.path.join(root, folder, "overdrive.json")
    return find_overdrive_settings(root)


def plugins_dir() -> str:
    """Decky's plugins folder (Traction's own folder's parent), where an installed Overdrive is looked for."""
    return os.path.dirname(os.path.normpath(getattr(decky, "DECKY_PLUGIN_DIR", "") or PLUGIN_DIR))


def record_dir() -> str:
    """The Armoury Crate record shared with Overdrive."""
    return RECORD_DIR


def _fail(message: str) -> dict:
    return {"ok": False, "message": message}


def _set_of(mode: str) -> str:
    """The mapping set a controller mode uses: Desktop its own, Gamepad and Auto (until it writes Desktop) Gamepad."""
    return "desktop" if mode == "desktop" else "gamepad"


def _buttons(chosen, live: str) -> dict:
    """get_state's buttons: which set is on the pad now, the two back switches (shared by both sets) and, for each
    set, every button's Primary and Secondary ("factory" where the owner has no choice)."""
    b = bindings.clean(chosen)
    sets = {name: {bid: {slot: b[name].get(bid, {}).get(slot, bindings.FACTORY) for slot in SLOTS}
                   for bid in BUTTON_ZONES}
            for name in bindings.SETS}
    return {"live": live, "m1_secondary": b["m1_secondary"], "m2_secondary": b["m2_secondary"], "sets": sets}


class Plugin:
    def __init__(self) -> None:
        self.client = None
        self.settings = None
        self.reapplier = None
        self.controller_auto = None
        self.armoury = None              # the Armoury Crate switch (its record is shared with Overdrive)
        self._old = False                # an Overdrive older than 0.2.0 drives the controller: Traction writes none
        self._plugins_dir = ""
        self._controls = None            # the last controller/touchscreen reading (shown while a switch runs)
        self._startup = None
        self._late_start = None          # the controller start once an old Overdrive was updated
        self._watch = None               # re-checks an old Overdrive's version every OVERDRIVE_POLL seconds
        self._sleep = asyncio.sleep      # the watch's sleep (tests pass a fake)
        self._move_failed = False        # the last move of Overdrive's orphaned Armoury record failed

    def _attach(self, client, settings, reapplier, record=None, old: bool = False, plugins: str = "") -> None:
        self.client, self.settings, self.reapplier = client, settings, reapplier
        self._old, self._plugins_dir = old, plugins
        if client is not None and record is not None:
            self.armoury = ArmourySwitch(client, record, NAME, logger=decky.logger,
                                         on_replaced=self._armoury_replaced)
        if reapplier is not None:
            reapplier.busy_check = self._busy
            reapplier.blocked = lambda: self._old
            reapplier.library_allowed = self._library_allowed
            if client is not None:
                # Traction has no Auto TDP: the loop asks frame_sample itself.
                self.controller_auto = ControllerAuto(client, reapplier, None, logger=decky.logger)

    def _busy(self) -> bool:
        return bool(self.armoury is not None and self.armoury.busy) or bool(getattr(self.client, "busy", False))

    def _refuse_write(self):
        """A reply refusing a write now (not an Ally, or Armoury services are being switched), else None.

        While an armoury_* call runs the single-threaded helper is busy for minutes; a write sent then would time out
        here yet still run later, so it is refused instead of queued."""
        if self.client is None:
            return _fail(NOT_ALLY)
        if self._busy():
            return _fail(BUSY)
        return None

    def _refuse_controller(self):
        """_refuse_write, plus the update note while an old Overdrive drives the controller."""
        return self._refuse_write() or (_fail(UPDATE_NOTE) if self._old else None)

    async def _main(self) -> None:
        if not device.is_ally():
            decky.logger.info(f"Traction: not an Ally ({device.product_name()!r}); helper not started")
            return
        settings = Settings.load(settings_path(), logger=decky.logger)   # an unreadable file is kept, never lost
        if migrate_from_overdrive(overdrive_settings_path(), settings):
            decky.logger.info(f"Traction: took the controller settings from Overdrive ({settings.controller_mode}, "
                              f"vibration {'on' if settings.grip_vibration else 'off'})")
            self.settings = settings
            self._save()
        plugins = plugins_dir()
        old = old_overdrive(plugins)
        runtime_dir = getattr(decky, "DECKY_PLUGIN_RUNTIME_DIR", "") or None
        client = TractionHelperClient(plugin_dir=PLUGIN_DIR, runtime_dir=runtime_dir, logger=decky.logger, name=NAME)
        # Two views of one record file: the switch's (changed only under its locks) and the reapplier's (read only).
        folder = record_dir()
        reapplier = Reapplier(client, settings, logger=decky.logger, record=ArmouryRecord(folder, decky.logger),
                              wake_source=last_wake_id)
        self._attach(client, settings, reapplier, ArmouryRecord(folder, decky.logger), old=old, plugins=plugins)
        client.start()
        self._startup = asyncio.ensure_future(self._startup_sequence())
        decky.logger.info("Traction started")

    def _desktop_not_kept_on_load(self) -> None:
        """C7: Desktop does not survive a plugin load. A stored Desktop becomes Gamepad (and is saved) before the
        first reapply, so the device and the panel agree on Gamepad after a Decky restart or a boot. Within a running
        session the reapplies (resume, AC change, helper restart) keep writing Desktop."""
        s = self.settings
        if s is None or s.controller_mode != "desktop":
            return
        s.controller_mode = "gamepad"
        decky.logger.info("Controller mode Desktop is not kept across a plugin load: Gamepad")
        self._save()

    async def _startup_sequence(self) -> None:
        self._desktop_not_kept_on_load()
        if self._old:
            decky.logger.info("Traction: an Overdrive older than 0.2.0 is installed; nothing is written to the "
                              "controller and the Armoury Crate switch is left to it")
            self._watch = asyncio.ensure_future(self._watch_overdrive())
            return
        await self._start_writes()

    async def _watch_overdrive(self) -> None:
        """While an old Overdrive blocks Traction: check its version every OVERDRIVE_POLL seconds (not only when the
        panel reads the state), and start what the load held back once it is 0.2.0 or newer."""
        while self._old:
            await self._sleep(OVERDRIVE_POLL)
            self._check_overdrive_updated()

    async def _start_writes(self) -> None:
        """The load-time Armoury check (P8 re-stop, recovery), the reapplier and, when stored, Controller Auto. An
        orphaned Overdrive record (no Overdrive installed to move it) is moved to the shared record first."""
        if self.armoury is not None:
            if self._overdrive_record_pending() and not self._overdrive_installed():
                await self._move_orphaned_record()
            await self.armoury.on_load()
            # Known before the first reapply: whether the Library button may be written (Armoury Crate not running).
            await self.armoury.check_installed()
        self.reapplier.start()
        if self.settings.controller_mode == "auto" and self.controller_auto is not None:
            self.controller_auto.start()   # the reapply writes Gamepad first; the loop decides from there

    def _check_overdrive_updated(self) -> None:
        """An old Overdrive updated while Traction runs: start what the load held back."""
        if not self._old or not self._plugins_dir or not self._startup_done() or old_overdrive(self._plugins_dir):
            return
        self._old = False
        decky.logger.info("Traction: Overdrive was updated; the controller settings are applied from now on")
        self._late_start = asyncio.ensure_future(self._start_writes())

    async def _unload(self) -> None:
        # Try not to kill the helper halfway through changing services: wait for the Armoury operation to finish,
        # bounded by its own call timeout. Decky does not wait that long: it kills the plugin process 5 s after
        # asking it to stop (decky-loader plugin/plugin.py kill_if_still_running), and the helper runs in the
        # plugin's job object with KILL_ON_JOB_CLOSE (localplatform/winprocess.py _create_job), so it dies too.
        # A switch cut short that way is put right at the next load (ArmourySwitch.on_load: recovery or the P8
        # re-stop).
        loop = asyncio.get_running_loop()
        while self.armoury is not None and self.armoury.busy and loop.time() < self.armoury.until:
            await asyncio.sleep(0.05)
        for task in (self._startup, self._watch, self._late_start):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        # Each step runs even when an earlier one failed. Gamepad first, whatever the stored mode, while the helper
        # still runs: Big Picture must never be left with a mouse-only controller. Nothing at all while an old
        # Overdrive drives the controller.
        if self.controller_auto is not None and not self._old:
            await _unload_step("put the controller back to Gamepad", self.controller_auto.stop())
        if self.reapplier is not None:
            await _unload_step("stop the reapplier", self.reapplier.stop())
        if self.client is not None:
            await _unload_step("stop the helper", self.client.stop())
        decky.logger.info("Traction unloaded")

    def _startup_done(self) -> bool:
        return self._startup is None or self._startup.done()

    # ---------- reads ----------

    async def get_support(self) -> dict:
        product = device.product_name()
        return {"supported": device.is_ally(lambda: product), "product": product}

    async def get_state(self) -> dict:
        support = await self.get_support()
        s = self.settings or Settings("")
        state = {
            "support": support,
            "armoury": {"installed": False, "replaced": False, "warning": ""},
            "controller": {"mode": s.controller_mode, "found": False},
            "vibration": bool(s.grip_vibration),
            "touchscreen": dict(UNREAD["touchscreen"]),
            "buttons": _buttons(s.bindings, _set_of(self._live_mode(s))),
            "library": self._library_state(s, False),
            "blocked": "", "note": "", "busy": False, "warning": "", "unavailable": "",
        }
        if self.client is None:
            return state
        self._check_overdrive_updated()
        state["blocked"] = UPDATE_NOTE if self._old else ""
        state["busy"] = self._busy()
        # No read while a long service switch or a set_bindings call (pad polling, maybe the factory reset) runs: it
        # would queue behind it, and two reads timing out in a row get the helper killed. The last reading is shown.
        quiet = state["busy"] or controls.bindings_in_flight()
        replaced = False
        if self.armoury is not None:
            replaced = self.armoury.replaced()   # the shared record: either plugin may switch
            if not quiet:
                await self.armoury.check_installed()
            warning = " ".join(w for w in (self.armoury.warning, self._record_pending_note()) if w)
            state["armoury"] = {"installed": self.armoury.installed, "replaced": replaced, "warning": warning}
        state["note"] = "" if replaced else ARMOURY_RUNNING
        state["library"] = self._library_state(s, self._library_allowed())
        if not quiet:
            controller, r = await controls.read_controller(self.client)
            touch = (self._controls or UNREAD)["touchscreen"]
            if not controls.transport_failure(r):
                touch = await controls.touchscreen_status(self.client)
                self._controls = {"controller": controller, "touchscreen": dict(touch)}
            elif self._controls is not None:
                controller = self._controls["controller"]
            # else: the helper is gone or hung; the touchscreen read would wait its 15 s. The last reading is shown
            # and read again at the next poll.
            state["controller"]["found"] = bool(controller["found"])
            state["touchscreen"] = {"found": bool(touch["found"]), "enabled": bool(touch["enabled"])}
        elif self._controls is not None:   # while quiet, the last reading: a call would queue behind the write
            state["controller"]["found"] = bool(self._controls["controller"]["found"])
            state["touchscreen"] = dict(self._controls["touchscreen"])
        state["unavailable"] = self.client.unavailable_reason or ""
        state["warning"] = " ".join(w for w in (s.warning, self.reapplier.warning) if w)
        return state

    # ---------- user changes ----------

    def _save(self) -> str:
        try:
            self.settings.save()
            return ""
        except OSError as e:
            decky.logger.error(f"Could not save Traction's settings: {e}")
            return f"Applied, but the setting could not be saved ({e})."

    async def _controller_found(self) -> bool:
        r = await self.client.call("controller_info", {})
        d = r.get("data") if r.get("ok") else None
        return isinstance(d, dict) and bool(d.get("found"))

    async def set_controller_mode(self, mode) -> dict:
        """Gamepad, Desktop or Auto. Saved once written, or when no controller is found (it applies when the
        controller is back). Auto writes Gamepad, then the Controller Auto loop decides."""
        refused = self._refuse_controller()
        if refused:
            return refused
        if mode not in CONTROLLER_MODES:
            return _fail("Controller mode must be gamepad, desktop or auto.")
        s, ca = self.settings, self.controller_auto
        # R10: stop() takes the reapplier's lock (not reentrant), so a running loop is stopped before user_change.
        # It writes Gamepad; Auto chosen again starts the loop afresh below.
        if ca is not None and ca.running:
            await ca.stop()
        result = None
        async with self.reapplier.user_change():
            if self._busy():   # an Armoury switch may have begun while this waited for the lock
                result = _fail(BUSY)
            else:
                note = ""
                if await self._controller_found():
                    r = await controls.apply_controller(self.client, s, mode)
                    if r.get("reset"):
                        self.reapplier.rerun = True   # the factory set wrote Gamepad and vibration 100
                    if not r.get("ok"):
                        result = _fail(str(r.get("message") or "The controller mode was not changed."))
                    else:
                        note = str(r.get("warning") or "")   # the buttons were not written, or were reset
                else:
                    note = NO_CONTROLLER
                if result is None:
                    s.controller_mode = mode
                    s.user_set = True   # a user choice: reapplies (resume, helper restart) write it again
                    result = {"ok": True, "message": " ".join(m for m in (note, self._save()) if m)}
        if ca is not None:
            if s.controller_mode == "auto":
                ca.start()   # Auto chosen, or a failed change away from Auto: the loop goes on
            elif ca.running:
                # A concurrent Auto choice started the loop after this call stopped it, then this call stored
                # Gamepad or Desktop. Stopped here, outside the lock (R10). The mode written is read under the lock
                # (C9), so a choice made while stop() waited for it is the one written.
                await ca.stop(lambda: s.controller_mode)
        return result

    async def set_grip_vibration(self, on) -> dict:
        refused = self._refuse_controller()
        if refused:
            return refused
        if not isinstance(on, bool):
            return _fail("Expected on or off.")
        s = self.settings
        async with self.reapplier.user_change():
            if self._busy():   # an Armoury switch may have begun while this waited for the lock
                return _fail(BUSY)
            note = ""
            if await self._controller_found():
                # Only the vibration is written: the controller mode (and a running Auto loop) is left alone.
                r = await self.client.call("set_vibration", {"strength": 100 if on else 0})
                if not r.get("ok"):
                    return _fail(str(r.get("message") or "The grip vibration was not changed."))
            else:
                note = NO_CONTROLLER
            s.grip_vibration = on
            s.user_set = True   # reapplied with the controller mode after sleep
            return {"ok": True, "message": " ".join(m for m in (note, self._save()) if m)}

    async def set_touchscreen(self, enabled) -> dict:
        """Works whatever Overdrive's version (Overdrive 0.1.0's touchscreen toggle is the same Windows device)."""
        refused = self._refuse_write()
        if refused:
            return refused
        if not isinstance(enabled, bool):
            return _fail("Expected on or off.")
        async with self.reapplier.user_change():
            if self._busy():   # an Armoury switch may have begun while this waited for the lock
                return _fail(BUSY)
            r = await controls.set_touchscreen(self.client, enabled)
        return {"ok": bool(r.get("ok")), "message": str(r.get("message") or "")}

    # ---------- buttons ----------

    def _live_mode(self, s=None) -> str:
        """The mode on the pad now: the stored one, or under Auto Desktop only when the loop wrote it after the latest
        reapply and no reapply runs (a reapply writes Gamepad under Auto), else Gamepad."""
        mode = (s or self.settings).controller_mode
        if mode == "auto":
            ca = self.controller_auto
            return "desktop" if ca is not None and ca.desktop_settled else "gamepad"
        return mode

    async def _change_buttons(self, change, zones, set_name=None) -> dict:
        """Under the reapplier's lock: builds the new bindings with `change(current)` from the bindings stored at that
        moment (a setter waiting for the lock never stores a stale set). A change to the set of the mode that is not on
        the pad (`set_name` other than the live set) is only stored, and the reply says in which mode it applies: the
        next write of that mode puts it on the pad (controls.apply_bindings writes the zones with a choice in either
        set). Otherwise (`set_name` None: the back switches, Reset of M1/M2 and Reset all, which act on the live set)
        `zones` are written for the live mode, watched in Gamepad, unwatched in Desktop (the pad is hidden there), then
        stored. Not stored when the write was refused (the pad not seen included: nothing was written); when only some
        zones landed (Reset all buttons), only those zones' new choices are stored and the next reapply tick writes the
        zones again. When the pad went away after the write, the helper reset it to the factory set: both sets are
        cleared, both switches go back on, the touched zones are cleared, and the next tick writes the mode and
        vibration again."""
        s = self.settings
        async with self.reapplier.user_change():
            if self._busy():   # an Armoury switch may have begun while this waited for the lock
                return _fail(BUSY)
            old = bindings.clean(s.bindings)
            new = change(bindings.clean(s.bindings))
            note = ""
            mode = self._live_mode()
            if set_name is not None and set_name != _set_of(mode):
                note = SAVED_FOR[set_name]   # the other set: stored only, written when its mode is
            elif await self._controller_found():
                r = await controls.write_zones(self.client, new, mode, zones, decky.logger, watch=mode != "desktop")
                if r.get("reset"):
                    controls.forget_bindings(s)
                    self.reapplier.rerun = True   # the factory set wrote Gamepad and vibration 100
                    return _fail(" ".join(m for m in (str(r.get("message") or ""), self._save()) if m))
                written = r.get("written") or []
                touched = controls.note_written(s, new, mode, written, r.get("uncertain"))
                if not r.get("ok"):
                    if r.get("uncertain") is not None:
                        s.user_set = True   # the zone may hold the new slots: reapplies must put it right
                    if written:   # some zones landed: store just those, and write the rest again next tick
                        s.bindings = bindings.keep_zones(old, new, written)
                        self.reapplier.rerun = True
                    if touched or written or r.get("uncertain") is not None:
                        self._save()
                    return _fail(str(r.get("message") or "The buttons were not changed."))
            else:
                note = NO_CONTROLLER
            s.bindings = new
            s.user_set = True   # reapplied with the controller mode after sleep
            failed = self._save()
            if failed and note in SAVED_FOR.values():
                note = ""   # not "Saved." when the save failed: the failure alone is shown
            return {"ok": True, "message": " ".join(m for m in (note, failed) if m)}

    @staticmethod
    def _check_button(set_name, button):
        """A refusal for an unknown set or button, else None."""
        if not isinstance(set_name, str) or set_name not in bindings.SETS:
            return _fail("Expected the Gamepad or Desktop set.")
        if not isinstance(button, str) or button not in BUTTON_ZONES:
            return _fail("Unknown button.")
        return None

    async def set_button(self, set_name, button, slot, action) -> dict:
        """One button's Primary or Secondary in the Gamepad or Desktop set; "factory" removes the choice (the zone is
        written with the factory slot). The live set writes that button's zone; the other set is only stored."""
        refused = self._refuse_controller() or self._check_button(set_name, button)
        if refused:
            return refused
        if not isinstance(slot, str) or slot not in SLOTS:
            return _fail("Expected the primary or secondary function.")
        if slot == "secondary" and button in bindings.BACK:
            return _fail("M1 and M2 have no secondary function.")
        if not isinstance(action, str) or (action != bindings.FACTORY and action not in ACTION_IDS):
            return _fail("Unknown button action.")
        return await self._change_buttons(lambda b: bindings.set_choice(b, set_name, button, slot, action),
                                          [BUTTON_ZONES[button]], set_name)

    async def set_back_secondary(self, side, on) -> dict:
        """The "use as secondary function" switch of the left (M2) or right (M1) back button, shared by both sets:
        writes zone 8 for the live mode."""
        refused = self._refuse_controller()
        if refused:
            return refused
        if not isinstance(side, str) or side not in BACK_SIDES:
            return _fail("Expected the left or right back button.")
        if not isinstance(on, bool):
            return _fail("Expected on or off.")
        return await self._change_buttons(lambda b: bindings.set_back_secondary(b, BACK_SIDES[side], on),
                                          [BACK_ZONE])

    async def reset_button(self, set_name, button) -> dict:
        """One button's Primary and Secondary in that set back to factory (live set: its zone is written). M1 and M2:
        that set's Primary is cleared and the shared switch turned back on (factory is the Shift key), so zone 8 is
        written for the live mode whatever set is edited."""
        refused = self._refuse_controller() or self._check_button(set_name, button)
        if refused:
            return refused
        return await self._change_buttons(lambda b: bindings.reset_button(b, set_name, button),
                                          [BUTTON_ZONES[button]], None if button in bindings.BACK else set_name)

    async def reset_all_buttons(self) -> dict:
        """Clears both sets and turns both back switches on, writing all 9 zones with the live set's factory slots
        (Desktop unwatched; the zones written in Desktop stay touched until the Gamepad factory write lands). A single
        press, no confirmation (owner rule). The Library button's presses go back to Armoury Crate's setting too
        (reset_library), when they are not already."""
        refused = self._refuse_controller()
        if refused:
            return refused
        result = await self._change_buttons(lambda _b: bindings.clean(None), bindings.all_zones())
        s = self.settings
        if library.chosen(s.library) or s.library_written:
            lib = await self._change_library(lambda _l: library.default_library())
            messages = []
            for m in (result["message"], lib["message"]):
                if m and m not in messages:
                    messages.append(m)
            result = {"ok": bool(result["ok"] and lib["ok"]), "message": " ".join(messages)}
        return result

    # ---------- the Library button ----------

    def _library_allowed(self) -> bool:
        """The Library button's reports may be written: no old Overdrive drives the controller and Armoury Crate is
        not running (Traction replaced it, or it is known not to be installed; not yet known counts as running)."""
        if self._old or self.client is None:
            return False
        a = self.armoury
        if a is None:
            return True
        return bool(a.replaced() or getattr(a, "_installed", None) is False)

    def _library_state(self, s, allowed: bool) -> dict:
        lib = library.clean(s.library)
        running = not allowed and self.client is not None and not self._old
        return {"single": lib["single"], "long": lib["long"], "allowed": bool(allowed),
                "note": LIBRARY_ARMOURY if running else ""}

    async def _change_library(self, change) -> dict:
        """Under the reapplier's lock: the new choices from `change(current)`. While Armoury Crate runs (or no
        controller is found) they are only stored; otherwise both reports are written first and the choices stored
        only when the write landed (a failed write keeps the old choices; the next reapply puts the controller
        right)."""
        s = self.settings
        async with self.reapplier.user_change():
            if self._busy():   # an Armoury switch may have begun while this waited for the lock
                return _fail(BUSY)
            old = library.clean(s.library)
            new = library.clean(change(dict(old)))
            if self.armoury is not None and not self.armoury.replaced():
                await self.armoury.check_installed()
            note = ""
            if self._library_allowed():
                if await self._controller_found():
                    s.library = new
                    r = await controls.apply_press_bindings(self.client, s, True, logger=decky.logger)
                    if not r.get("ok"):
                        s.library = old
                        self._save()
                        return _fail(str(r.get("message") or "The Library button was not changed."))
                else:
                    note = NO_CONTROLLER
            # else: Armoury Crate is running: stored only (get_state's library note says why)
            s.library = new
            s.user_set = True   # reapplied with the controller mode after sleep
            return {"ok": True, "message": " ".join(m for m in (note, self._save()) if m)}

    async def set_library_press(self, press, choice) -> dict:
        """What the Library button's single or long press does: one of library.CHOICES ids, "armoury" for Armoury
        Crate's own setting."""
        refused = self._refuse_controller()
        if refused:
            return refused
        if not isinstance(press, str) or press not in library.PRESSES:
            return _fail("Expected the single or long press.")
        if not isinstance(choice, str) or choice not in library.CHOICE_IDS:
            return _fail("Unknown Library button choice.")
        return await self._change_library(lambda lib: {**lib, press: choice})

    async def reset_library(self) -> dict:
        """Both presses back to Armoury Crate's setting: the reports are written once with it, then no more."""
        refused = self._refuse_controller()
        if refused:
            return refused
        return await self._change_library(lambda _l: library.default_library())

    # ---------- Armoury Crate ----------
    # The switch, the record and its rules are ArmourySwitch's (armoury_switch.py, shared with Overdrive).

    def _armoury_replaced(self) -> None:
        """Armoury Crate was stopped: Traction's settings are applied from now on ("then apply our stored
        settings", at the next poll)."""
        s = self.settings
        if not s.user_set:
            s.user_set = True
            self._save()
        self.reapplier.rerun = True

    async def set_armoury_replaced(self, on) -> dict:
        # An Overdrive older than 0.2.0 keeps the Armoury Crate record in its own settings: switching here would
        # work on a record it does not read, so the toggle is read-only until it is updated.
        refused = self._refuse_controller()
        if refused:
            return refused
        if not isinstance(on, bool):
            return _fail("Expected on or off.")
        if self._overdrive_record_pending():
            if self._overdrive_installed():
                return _fail(NOT_MOVED)        # Overdrive 0.2.0+ moves its own record when it loads
            # Overdrive is gone but left its record: Traction moves it, then runs the load-time check on it (P8
            # re-stop or recovery) as a load would have, before the switch.
            if await self._move_orphaned_record():
                await self.armoury.on_load()
            elif self._overdrive_record_pending():
                return _fail(MOVE_FAILED)
        return await self.armoury.set(on)

    def _overdrive_installed(self) -> bool:
        return find_overdrive(self._plugins_dir or plugins_dir()) is not None

    def _record_pending_note(self) -> str:
        if not self._overdrive_record_pending():
            return ""
        if self._overdrive_installed():
            return NOT_MOVED
        return MOVE_FAILED if self._move_failed else ""

    async def _move_orphaned_record(self) -> bool:
        """Overdrive is not installed but its overdrive.json (or the .bak when that is unreadable) still holds the
        old Armoury Crate record and the shared record does not exist: move it there with the shared
        migrate_from_settings, waiting up to MOVE_WAIT for the record lock without blocking the loop. overdrive.json
        is only read, never edited. True when the record was moved."""
        raw = read_old_record(overdrive_settings_path())
        why = "neither overdrive.json nor overdrive.json.bak could be read"
        if raw is not None:
            rec, run = raw.get("armoury_recorded"), raw.get("armoury_running")
            old = types.SimpleNamespace(armoury_replaced=raw.get("armoury_replaced") is True,
                                        armoury_recorded=rec if isinstance(rec, dict) else {},
                                        armoury_running=run if isinstance(run, list) else [])
            loop = asyncio.get_running_loop()
            deadline = loop.time() + MOVE_WAIT
            while True:
                try:
                    moved = migrate_from_settings(self.armoury.record, old, 0.0)
                except ArmouryLocked as e:
                    why = str(e)
                    if loop.time() < deadline:
                        await asyncio.sleep(0.05)
                        continue
                except OSError as e:
                    why = str(e)
                else:
                    self._move_failed = False
                    if moved:
                        decky.logger.info("Traction: Overdrive is not installed; its old Armoury Crate record was "
                                          "moved to the shared record")
                    return moved
                break
        self._move_failed = True
        decky.logger.warning(f"Traction: Overdrive's old Armoury Crate record was not moved to the shared record yet: "
                             f"{why}")
        return False

    def _overdrive_record_pending(self) -> bool:
        """Overdrive's own Armoury Crate record (overdrive.json, before 0.2.0) is not in the shared record yet: the
        shared record does not exist and overdrive.json still holds it. A switch now would build the shared record
        from start types that may already be stopped, and Overdrive's later move would then drop its originals."""
        if self.armoury is None or self.armoury.record.exists():
            return False
        return overdrive_holds_armoury_record(overdrive_settings_path())


async def _unload_step(what: str, coro) -> None:
    """One unload step; a failure is logged and the later steps still run."""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        decky.logger.error(f"Traction could not {what} at unload: {e}")
