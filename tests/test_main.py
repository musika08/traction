import asyncio
import json
import os

import pytest

import main
from fake_helper import FakeClient, fail, ok
from traction import controls
from traction.armoury_record import ArmouryRecord
from traction.reapply import Reapplier
from traction.settings import Settings

UPDATE = "Update Overdrive to 0.2.0 or newer to use Traction's controller settings."
RUNNING = "Armoury Crate is running, so these settings may be overwritten."
BUSY = "Traction is switching Armoury Crate services. Try again when it finishes."


class Clock:
    def time(self):
        return 1_700_000_000.0

    def monotonic(self):
        return 5_000.0


def record_folder(tmp_path) -> str:
    return str(tmp_path / "armoury")


def saved_record(tmp_path) -> ArmouryRecord:
    r = ArmouryRecord(record_folder(tmp_path))
    r.load()
    return r


def settings_file(tmp_path) -> str:
    return str(tmp_path / "settings" / "traction" / "settings.json")


def plugin_with(tmp_path, client=None, old=False, **fields):
    """armoury_replaced/recorded/running go to the shared record (saved), the other fields to the settings."""
    p = main.Plugin()
    s = Settings.load(settings_file(tmp_path))
    rec = ArmouryRecord(record_folder(tmp_path))
    armoury = {k[len("armoury_"):]: v for k, v in fields.items() if k.startswith("armoury_")}
    for k, v in fields.items():
        if not k.startswith("armoury_"):
            setattr(s, k, v)
    if armoury:
        for k, v in armoury.items():
            setattr(rec, k, v)
        rec.save()
    c = client or FakeClient()
    reapplier = Reapplier(c, s, clock=Clock(), power_source=lambda: True,
                          record=ArmouryRecord(record_folder(tmp_path)))
    p._attach(c, s, reapplier, rec, old=old)
    return p, c, s


@pytest.fixture(autouse=True)
def _record_in_tmp(monkeypatch, tmp_path):
    # No test may touch C:\ProgramData or the real Decky folders: every path goes to the test's temp folder.
    monkeypatch.setattr(main, "record_dir", lambda: record_folder(tmp_path))
    monkeypatch.setattr(main, "settings_path", lambda: settings_file(tmp_path))
    monkeypatch.setattr(main, "overdrive_settings_path",
                        lambda: str(tmp_path / "settings" / "overdrive" / "overdrive.json"))
    monkeypatch.setattr(main, "plugins_dir", lambda: str(tmp_path / "plugins"))


@pytest.fixture(autouse=True)
def _no_real_helper(monkeypatch):
    # Belt and braces: no test in this file may ever spawn a process.
    async def refuse(*a, **k):
        raise AssertionError("tests must not start a process")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse)


@pytest.fixture(autouse=True)
def _fresh_controls_cache():
    controls.reset_cache()
    yield
    controls.reset_cache()


def run(coro):
    return asyncio.run(coro)


def wait(coro, secs=2.0):
    """A deadlock on the reapplier's lock fails the test instead of hanging it."""
    return asyncio.wait_for(coro, secs)


def reply(r):
    async def h(_args):
        return r
    return h


def controller_found(c):
    c.handlers["controller_info"] = reply(ok({"found": True, "pid": "0x1B4C", "xbox": False}))


def install_overdrive(tmp_path, version, folder_name="overdrive"):
    folder = tmp_path / "plugins" / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps({"api_version": 1, "name": "Overdrive"}), encoding="utf-8")
    (folder / "package.json").write_text(json.dumps({"name": "overdrive", "version": version}), encoding="utf-8")


def overdrive_settings(tmp_path, data):
    folder = tmp_path / "settings" / "overdrive"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "overdrive.json").write_text(json.dumps(data), encoding="utf-8")


def ally_main(monkeypatch, client=None):
    """_main on an Ally with a FakeClient; returns the list the clients made go to."""
    clients = []

    def make_client(*a, **k):
        c = client or FakeClient()
        clients.append((c, k))
        return c
    monkeypatch.setattr(main.device, "is_ally", lambda read_product=None: True)
    monkeypatch.setattr(main, "TractionHelperClient", make_client)
    return clients


def controller_writes(c):
    return [x for x in c.calls if x[0] in ("set_controller_mode", "set_vibration")]


# ---------- start and stop ----------

def test_not_ally_starts_nothing(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(main.device, "is_ally", lambda read_product=None: False)
    monkeypatch.setattr(main, "TractionHelperClient", lambda *a, **k: made.append("client"))
    monkeypatch.setattr(main, "Reapplier", lambda *a, **k: made.append("reapplier"))

    async def go():
        p = main.Plugin()
        await p._main()
        state = await p.get_state()
        results = [await p.set_controller_mode("desktop"), await p.set_grip_vibration(False),
                   await p.set_touchscreen(False), await p.set_armoury_replaced(True),
                   await p.set_library_press("single", "esc"), await p.reset_library()]
        await p._unload()
        return state, results
    state, results = run(go())
    assert made == []
    assert state["support"]["supported"] is False
    assert state["blocked"] == "" and state["note"] == ""
    for r in results:
        assert r == {"ok": False, "message": "Traction supports the ROG Ally family only"}
    assert not os.path.exists(settings_file(tmp_path))


def test_ally_starts_client_and_reapplier_and_unload_stops_both(monkeypatch, tmp_path):
    clients = ally_main(monkeypatch)

    async def go():
        p = main.Plugin()
        await p._main()
        await p._startup
        assert p.reapplier._task is not None
        await p._unload()
        return p
    p = run(go())
    c, kwargs = clients[0]
    assert c.started and c.stopped
    assert kwargs["name"] == "Traction"
    assert p.reapplier._task is None
    assert not os.path.exists(settings_file(tmp_path))       # an untouched install writes no settings


def test_helper_client_runs_traction_helper(tmp_path):
    client = main.TractionHelperClient(plugin_dir=str(tmp_path), name="Traction")
    assert client.exe_path == os.path.join(str(tmp_path), "bin", "traction-helper.exe")
    assert client.restarted_text == "Traction helper restarted, try again"


def test_paths_follow_decky(monkeypatch, tmp_path):
    monkeypatch.undo()     # the real path functions, with a stand-in decky (on a temp folder)
    root = str(tmp_path / "homebrew")
    monkeypatch.setattr(main.decky, "DECKY_PLUGIN_SETTINGS_DIR", os.path.join(root, "settings", "traction"),
                        raising=False)
    monkeypatch.setattr(main.decky, "DECKY_PLUGIN_DIR", os.path.join(root, "plugins", "traction"), raising=False)
    assert main.settings_path() == os.path.join(root, "settings", "traction", "settings.json")
    assert main.plugins_dir() == os.path.join(root, "plugins")
    assert main.record_dir() == r"C:\ProgramData\decky\armoury"
    # final review T1: Overdrive is the plugin whose plugin.json is named Overdrive, whatever its folder
    assert main.overdrive_settings_path() == ""                         # not installed, no settings anywhere
    stray = tmp_path / "homebrew" / "settings" / "old-od"
    stray.mkdir(parents=True)
    (stray / "overdrive.json").write_text("{}", encoding="utf-8")
    assert main.overdrive_settings_path() == str(stray / "overdrive.json")   # not installed: found by scan
    install_overdrive(tmp_path / "homebrew", "0.2.0", folder_name="overdrive-main")
    assert main.overdrive_settings_path() == os.path.join(root, "settings", "overdrive-main", "overdrive.json")


def test_plugin_json_runs_as_root():
    with open(os.path.join(os.path.dirname(main.__file__), "plugin.json"), encoding="utf-8") as f:
        assert "root" in json.load(f)["flags"]


# ---------- state ----------

def test_get_state_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(main.device, "product_name", lambda read_product=None: "ROG Ally RC71L")

    async def go():
        p, c, s = plugin_with(tmp_path, controller_mode="auto", grip_vibration=False)
        controller_found(c)
        c.handlers["get_touchscreen"] = reply(ok({"found": True, "enabled": True, "instanceId": "x"}))
        return await wait(p.get_state())
    st = run(go())
    assert set(st) >= {"support", "armoury", "controller", "vibration", "touchscreen", "blocked", "note", "busy"}
    assert st["support"] == {"supported": True, "product": "ROG Ally RC71L"}
    assert st["armoury"] == {"installed": True, "replaced": False, "warning": ""}
    assert st["controller"] == {"mode": "auto", "found": True}
    assert st["vibration"] is False
    assert st["touchscreen"] == {"found": True, "enabled": True}
    assert st["blocked"] == "" and st["busy"] is False
    assert st["warning"] == "" and st["unavailable"] == ""


def test_note_while_armoury_runs(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        assert (await wait(p.get_state()))["note"] == RUNNING        # no record yet: Armoury Crate runs
        p2, c2, s2 = plugin_with(tmp_path / "b", armoury_replaced=True,
                                 armoury_recorded={"ArmouryCrateService": "Automatic"})
        assert (await wait(p2.get_state()))["note"] == ""
        other = ArmouryRecord(record_folder(tmp_path))                # Overdrive stops Armoury Crate
        other.replaced, other.recorded = True, {"ArmouryCrateService": "Automatic"}
        other.save()
        st = await wait(p.get_state())
        assert st["note"] == "" and st["armoury"]["replaced"] is True
    run(go())


def test_state_reads_shared_record(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        assert (await p.get_state())["armoury"]["replaced"] is False
        other = ArmouryRecord(record_folder(tmp_path))      # Overdrive switches Armoury Crate off
        other.replaced, other.recorded = True, {"ArmouryCrateService": "Automatic"}
        other.save()
        assert (await p.get_state())["armoury"] == {"installed": True, "replaced": True, "warning": ""}
        other.replaced, other.recorded = False, {}
        other.save()
        assert (await p.get_state())["armoury"]["replaced"] is False
    run(go())


def test_get_state_skips_touchscreen_when_the_helper_does_not_answer(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        st = await wait(p.get_state())
        assert st["controller"]["found"] is True
        c.handlers["controller_info"] = reply(fail("Traction helper did not answer in 10 s."))
        controls.reset_cache()
        n = len(c.calls)
        st = await wait(p.get_state())
        assert [cmd for cmd, _ in c.calls[n:]] == ["controller_info"]   # no touchscreen read behind a hung helper
        assert st["controller"]["found"] is True                         # the last reading is shown
    run(go())


# ---------- controller mode and vibration (ported from Overdrive ba0307a) ----------

def test_set_controller_mode_auto_starts_loop(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        ca = p.controller_auto
        assert (await p.set_controller_mode("mouse"))["ok"] is False
        r = await wait(p.set_controller_mode("auto"))
        assert r["ok"] is True, r
        assert ("set_controller_mode", {"mode": "gamepad"}) in c.writes()   # Auto starts in Gamepad
        assert ca._on is True
        saved = Settings.load(s.path)
        assert (saved.controller_mode, saved.user_set) == ("auto", True)   # reapplied after sleep
        c.calls.clear()
        r = await wait(p.set_controller_mode("desktop"))
        assert r["ok"] is True, r
        assert ca._on is False and ca._task is None
        assert c.writes()[-2:] == [("set_controller_mode", {"mode": "desktop"}), ("set_vibration", {"strength": 100})]
        assert Settings.load(s.path).controller_mode == "desktop"
        # a refused write saves nothing
        c.handlers["set_controller_mode"] = reply(fail("The controller refused the mode."))
        r = await wait(p.set_controller_mode("gamepad"))
        assert r["ok"] is False and "refused" in r["message"]
        assert Settings.load(s.path).controller_mode == "desktop" and s.controller_mode == "desktop"
    run(go())


def test_set_controller_mode_away_from_auto_stops_loop_outside_the_lock(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, controller_mode="auto", user_set=True)
        controller_found(c)
        ca = p.controller_auto
        ca.start()
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow(args):
            entered.set()
            await release.wait()
            return ok(dict(args))
        c.handlers["set_controller_mode"] = slow
        writing = asyncio.ensure_future(ca._write("desktop"))         # a loop write holds the reapplier's lock
        await wait(entered.wait())
        assert p.reapplier.lock.locked()
        release.set()
        r = await wait(p.set_controller_mode("gamepad"))             # stop() before user_change: no deadlock
        assert r["ok"] is True, r
        await wait(writing)
        assert ca._on is False
        assert c.writes()[-2] == ("set_controller_mode", {"mode": "gamepad"})
    run(go())


def test_concurrent_auto_and_desktop_leave_no_loop_running(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        ca = p.controller_auto
        # Both calls pass the "stop a running loop" check, then wait for the lock: Auto first, Desktop second.
        async with p.reapplier.lock:
            a = asyncio.ensure_future(p.set_controller_mode("auto"))
            b = asyncio.ensure_future(p.set_controller_mode("desktop"))
            for _ in range(5):
                await asyncio.sleep(0)
        ra, rb = await wait(a), await wait(b)
        assert ra["ok"] and rb["ok"], (ra, rb)
        assert s.controller_mode == "desktop" and Settings.load(s.path).controller_mode == "desktop"
        assert ca.running is False and ca._task is None          # the loop Auto started was stopped
        modes = [a["mode"] for cmd, a in c.writes() if cmd == "set_controller_mode"]
        assert modes[-1] == "desktop"                             # the stored choice is what the device has
    run(go())


def test_concurrent_auto_desktop_gamepad_ends_in_the_last_choice(tmp_path):
    async def go():
        # C9: the stray-loop stop decides its write under the lock, so the later Gamepad choice is what stays.
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        ca = p.controller_auto
        async with p.reapplier.lock:
            calls = [asyncio.ensure_future(p.set_controller_mode(m)) for m in ("auto", "desktop", "gamepad")]
            for _ in range(5):
                await asyncio.sleep(0)
        for t in calls:
            r = await wait(t)
            assert r["ok"], r
        assert s.controller_mode == "gamepad" and Settings.load(s.path).controller_mode == "gamepad"
        assert ca.running is False
        modes = [a["mode"] for cmd, a in c.writes() if cmd == "set_controller_mode"]
        assert modes[-1] == "gamepad", modes
        assert modes.count("desktop") == 1, modes                # Desktop only from the Desktop choice itself
    run(go())


def test_controller_choices_saved_when_controller_missing(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)                               # controller_info: found False
        r = await wait(p.set_controller_mode("desktop"))
        assert r["ok"] is True and "not found" in r["message"]
        r = await wait(p.set_grip_vibration(False))
        assert r["ok"] is True and "not found" in r["message"]
        assert c.writes() == []
        saved = Settings.load(s.path)
        assert (saved.controller_mode, saved.grip_vibration) == ("desktop", False)
    run(go())


def test_set_grip_vibration_saves_and_applies(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        gen = p.reapplier.generation
        r = await wait(p.set_grip_vibration(False))
        assert r == {"ok": True, "message": ""}
        assert p.reapplier.generation == gen + 1                       # a user change, under the shared lock
        assert c.writes() == [("set_vibration", {"strength": 0})]
        saved = Settings.load(s.path)
        assert (saved.grip_vibration, saved.user_set) == (False, True)
        assert (await wait(p.get_state()))["vibration"] is False
        c.handlers["set_vibration"] = reply(fail("The controller refused the vibration."))
        r = await wait(p.set_grip_vibration(True))
        assert r["ok"] is False
        assert s.grip_vibration is False and Settings.load(s.path).grip_vibration is False
        assert (await p.set_grip_vibration("yes"))["ok"] is False
    run(go())


def test_set_touchscreen_writes_and_reports(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        gen = p.reapplier.generation
        assert (await wait(p.set_touchscreen(False))) == {"ok": True, "message": ""}
        assert p.reapplier.generation == gen + 1
        assert c.writes() == [("set_touchscreen", {"enabled": False})]
        assert (await p.set_touchscreen("off"))["ok"] is False
        c.handlers["set_touchscreen"] = reply(fail("The touch screen was not found."))
        assert (await wait(p.set_touchscreen(True))) == {"ok": False, "message": "The touch screen was not found."}
        assert not os.path.exists(s.path)                              # Touch Screen is never stored
    run(go())


def test_setters_refused_while_busy(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        p.armoury._busy = True
        for name, arg in (("set_controller_mode", "desktop"), ("set_grip_vibration", False),
                          ("set_touchscreen", False), ("set_armoury_replaced", True)):
            assert (await wait(getattr(p, name)(arg))) == {"ok": False, "message": BUSY}, name
        p.armoury._busy = False
        assert c.writes() == []
        assert (s.controller_mode, s.grip_vibration) == ("gamepad", True)
        assert not os.path.exists(s.path)
    run(go())


def test_startup_starts_controller_auto_when_mode_is_auto(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, controller_mode="auto", user_set=True)
        p._startup = asyncio.ensure_future(p._startup_sequence())
        await wait(p._startup)
        assert p.controller_auto._on is True
        assert p.controller_auto.autotdp is None                     # Traction samples the frame rate itself
        await wait(p._unload())
        assert p.controller_auto._on is False

        p2, c2, s2 = plugin_with(tmp_path / "b", controller_mode="desktop")
        p2._startup = asyncio.ensure_future(p2._startup_sequence())
        await wait(p2._startup)
        assert p2.controller_auto._on is False
        await wait(p2._unload())
    run(go())


def test_load_turns_stored_desktop_into_gamepad(tmp_path, caplog):
    async def go():
        # C7: Desktop does not survive a plugin load (Decky restart, boot).
        p, c, s = plugin_with(tmp_path, controller_mode="desktop", user_set=True)
        controller_found(c)
        with caplog.at_level("INFO"):
            p._startup = asyncio.ensure_future(p._startup_sequence())
            await wait(p._startup)
        assert "Controller mode Desktop is not kept across a plugin load: Gamepad" in caplog.text
        assert s.controller_mode == "gamepad"                 # changed before the first reapply
        assert Settings.load(s.path).controller_mode == "gamepad"   # and saved: the panel shows Gamepad
        await wait(p.reapplier.apply_all())
        modes = [a["mode"] for cmd, a in c.writes() if cmd == "set_controller_mode"]
        assert modes and set(modes) == {"gamepad"}
        assert p.controller_auto.running is False
        # Within the session a chosen Desktop is reapplied (resume, AC change) as before.
        assert (await wait(p.set_controller_mode("desktop")))["ok"] is True
        n = len(c.writes())
        assert await wait(p.reapplier.apply_all()) is True
        modes = [a["mode"] for cmd, a in c.writes()[n:] if cmd == "set_controller_mode"]
        assert modes == ["desktop"]
        await wait(p._unload())
        # "auto" and "gamepad" are left as stored
        for i, mode in enumerate(("auto", "gamepad")):
            p2, c2, s2 = plugin_with(tmp_path / str(i), controller_mode=mode, user_set=True)
            p2._startup = asyncio.ensure_future(p2._startup_sequence())
            await wait(p2._startup)
            assert s2.controller_mode == mode
            await wait(p2._unload())
    run(go())


def test_unload_writes_gamepad_first(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, user_set=True, controller_mode="auto")
        controller_found(c)
        p._startup = asyncio.ensure_future(p._startup_sequence())
        await wait(p._startup)
        await wait(p.reapplier.apply_all())
        before = len(c.writes())
        await wait(p._unload())
        after = c.writes()[before:]
        assert after == [("set_controller_mode", {"mode": "gamepad"})]
        assert c.stopped and p.reapplier._task is None
        # Gamepad is written at every unload, whatever the stored mode (Big Picture needs its gamepad).
        p2, c2, s2 = plugin_with(tmp_path / "b")
        await wait(p2._unload())
        assert c2.writes() == [("set_controller_mode", {"mode": "gamepad"})]
    run(go())


def test_unload_goes_on_when_a_step_fails(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, user_set=True)
        p._startup = asyncio.ensure_future(p._startup_sequence())
        await wait(p._startup)

        async def boom(_args):
            raise RuntimeError("controller gone")
        c.handlers["set_controller_mode"] = boom
        await wait(p._unload())
        assert c.stopped and p.reapplier._task is None
    run(go())


# ---------- the Armoury Crate switch (shared record) ----------

def test_switch_on_applies_settings_next_poll(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        assert (await wait(p.set_armoury_replaced(True)))["ok"] is True
        assert p.reapplier.rerun is True and s.user_set is True
        assert Settings.load(s.path).user_set is True
        assert saved_record(tmp_path).replaced is True
        st = await wait(p.get_state())
        assert st["armoury"]["replaced"] is True and st["note"] == ""
        assert (await p.set_armoury_replaced("on"))["ok"] is False
        assert (await wait(p.set_armoury_replaced(False)))["ok"] is True
        assert saved_record(tmp_path).replaced is False
    run(go())


def test_switch_refused_while_the_other_plugin_holds_the_lock(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        p.armoury.lock_timeout = 0.1
        with ArmouryRecord(record_folder(tmp_path)).lock():
            r = await wait(p.set_armoury_replaced(True))
        assert r == {"ok": False,
                     "message": "Armoury Crate is being switched by another plugin, try again in a few minutes."}
        assert all(not cmd.startswith("armoury_") for cmd, _ in c.calls)
    run(go())


def test_busy_while_armoury_call_runs(tmp_path):
    async def go():
        c = FakeClient()
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_stop(args):
            entered.set()
            await release.wait()
            return ok({"startTypes": dict(c.armoury["startTypes"]), "running": list(c.armoury["running"])})
        c.handlers["armoury_stop"] = slow_stop
        p, c, s = plugin_with(tmp_path, client=c)
        controller_found(c)
        switch = asyncio.ensure_future(p.set_armoury_replaced(True))
        await entered.wait()
        assert await p.set_controller_mode("desktop") == {"ok": False, "message": BUSY}
        assert await p.set_armoury_replaced(False) == {"ok": False, "message": BUSY}
        assert c.writes() == [("armoury_stop", None)]          # nothing queued behind the service switch
        n = len(c.calls)
        st = await asyncio.wait_for(p.get_state(), 1)          # reads still work, and do not queue either
        assert st["busy"] is True and len(c.calls) == n
        release.set()
        assert (await switch)["ok"] is True
        assert (await p.get_state())["busy"] is False
        assert (await wait(p.set_controller_mode("desktop")))["ok"] is True
    run(go())


def test_load_restops_armoury_without_overwriting_record(tmp_path):
    async def go():
        recorded = {"ArmouryCrateService": "Automatic"}
        p, c, s = plugin_with(tmp_path, armoury_replaced=True, armoury_recorded=dict(recorded),
                              armoury_running=["ArmouryCrateService"])
        await wait(p._startup_sequence())
        assert [cmd for cmd, _ in c.calls][:2] == ["armoury_state", "armoury_stop"]
        rec = saved_record(tmp_path)
        assert rec.recorded["ArmouryCrateService"] == "Automatic"
        assert rec.running[0] == "ArmouryCrateService"
        assert p.reapplier._task is not None
        await p.reapplier.stop()
    run(go())


def test_load_restores_interrupted_switch_and_warns(tmp_path):
    async def go():
        recorded = {"ArmouryCrateSEService": "AutomaticDelayedStart", "LightingService": "Automatic"}
        p, c, s = plugin_with(tmp_path, armoury_replaced=False, armoury_recorded=dict(recorded),
                              armoury_running=["ArmouryCrateSEService"])
        await wait(p._startup_sequence())
        assert [cmd for cmd, _ in c.calls][:2] == ["armoury_state", "armoury_restore"]
        rec = saved_record(tmp_path)
        assert rec.recorded == {} and rec.replaced is False
        st = await wait(p.get_state())
        assert "did not finish, so Armoury Crate was put back" in st["armoury"]["warning"]
        await p.reapplier.stop()
    run(go())


def test_load_without_record_touches_no_service(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        await wait(p._startup_sequence())
        assert all(not cmd.startswith("armoury_") or cmd == "armoury_state" for cmd, _ in c.calls)
        assert (await wait(p.get_state()))["armoury"]["warning"] == ""
        await p.reapplier.stop()
    run(go())


def test_unload_waits_for_armoury_switch(tmp_path):
    async def go():
        c = FakeClient()
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_stop(args):
            entered.set()
            await release.wait()
            return ok({"startTypes": dict(c.armoury["startTypes"]), "running": list(c.armoury["running"])})
        c.handlers["armoury_stop"] = slow_stop
        p, c, s = plugin_with(tmp_path, client=c)
        switch = asyncio.ensure_future(p.set_armoury_replaced(True))
        await entered.wait()
        unload = asyncio.ensure_future(p._unload())
        await asyncio.sleep(0.2)
        assert not c.stopped and not unload.done()
        release.set()
        await wait(unload)
        assert c.stopped
        assert (await switch)["ok"] is True
        assert saved_record(tmp_path).replaced is True
    run(go())


# ---------- settings carried over from Overdrive (spec 3.3) ----------

def test_startup_takes_overdrive_values_once(monkeypatch, tmp_path):
    ally_main(monkeypatch)
    overdrive_settings(tmp_path, {"controller_mode": "auto", "grip_vibration": False, "mode": "turbo",
                                  "user_set": True})

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        assert (p.settings.controller_mode, p.settings.grip_vibration, p.settings.user_set) == ("auto", False, True)
        assert p.controller_auto.running is True
        await wait(p._unload())
    run(go())
    saved = Settings.load(settings_file(tmp_path))
    assert (saved.controller_mode, saved.grip_vibration, saved.user_set) == ("auto", False, True)
    # Traction's own file exists now: a later change in Overdrive's file is not taken again.
    overdrive_settings(tmp_path, {"controller_mode": "gamepad", "grip_vibration": True})

    async def again():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        mode = p.settings.controller_mode
        await wait(p._unload())
        return mode
    assert run(again()) == "auto"


def test_migrate_desktop_becomes_gamepad_at_load(monkeypatch, tmp_path):
    ally_main(monkeypatch)
    overdrive_settings(tmp_path, {"controller_mode": "desktop", "grip_vibration": True})

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        mode = p.settings.controller_mode
        await wait(p._unload())
        return mode
    assert run(go()) == "gamepad"
    assert Settings.load(settings_file(tmp_path)).controller_mode == "gamepad"


def test_unreadable_overdrive_settings_still_load(monkeypatch, tmp_path):
    ally_main(monkeypatch)
    folder = tmp_path / "settings" / "overdrive"
    folder.mkdir(parents=True)
    (folder / "overdrive.json").write_text("{", encoding="utf-8")

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        st = await wait(p.get_state())
        await wait(p._unload())
        return p, st
    p, st = run(go())
    assert (p.settings.controller_mode, p.settings.grip_vibration, p.settings.user_set) == ("gamepad", True, False)
    assert st["warning"] == ""


# ---------- an Overdrive older than 0.2.0 next to Traction (spec 3.4) ----------

def test_old_overdrive_blocks_controller_writes(monkeypatch, tmp_path):
    install_overdrive(tmp_path, "0.1.0")
    overdrive_settings(tmp_path, {"controller_mode": "auto", "grip_vibration": False})
    c = FakeClient()
    controller_found(c)
    ally_main(monkeypatch, client=c)

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        st = await wait(p.get_state())
        results = [await wait(p.set_controller_mode("desktop")), await wait(p.set_grip_vibration(True))]
        p.reapplier.rerun = True
        await wait(p.reapplier.tick())          # even a reapply poll (not started anyway) writes nothing
        await wait(p._unload())
        return p, st, results
    p, st, results = run(go())
    assert controller_writes(c) == []
    assert st["blocked"] == UPDATE
    assert p.reapplier._task is None and p.controller_auto.running is False
    for r in results:
        assert r == {"ok": False, "message": UPDATE}
    assert c.stopped


def test_old_overdrive_keeps_armoury_read_only_and_touchscreen_working(monkeypatch, tmp_path):
    install_overdrive(tmp_path, "0.1.0")
    c = FakeClient()
    ally_main(monkeypatch, client=c)
    rec = ArmouryRecord(record_folder(tmp_path))     # a record says replaced: on_load would re-stop the services
    rec.replaced, rec.recorded = True, {"ArmouryCrateService": "Automatic"}
    rec.save()

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        st = await wait(p.get_state())
        sw = await wait(p.set_armoury_replaced(False))
        touch = await wait(p.set_touchscreen(False))
        await wait(p._unload())
        return st, sw, touch
    st, sw, touch = run(go())
    assert sw == {"ok": False, "message": UPDATE}
    assert all(cmd not in ("armoury_stop", "armoury_restore") for cmd, _ in c.calls)   # on_load did nothing either
    assert st["armoury"]["replaced"] is True                                          # still read
    assert touch == {"ok": True, "message": ""}
    assert c.writes() == [("set_touchscreen", {"enabled": False})]
    assert saved_record(tmp_path).replaced is True


def test_new_overdrive_does_not_block(monkeypatch, tmp_path):
    for version in ("0.2.0", "0.10.0"):
        folder = tmp_path / version
        install_overdrive(folder, version)
        monkeypatch.setattr(main, "plugins_dir", lambda f=folder: str(f / "plugins"))
        c = FakeClient()
        controller_found(c)
        ally_main(monkeypatch, client=c)

        async def go():
            p = main.Plugin()
            await p._main()
            await wait(p._startup)
            st = await wait(p.get_state())
            r = await wait(p.set_controller_mode("desktop"))
            await wait(p._unload())
            return st, r
        st, r = run(go())
        assert st["blocked"] == "" and r["ok"] is True, version
        assert ("set_controller_mode", {"mode": "desktop"}) in c.writes()


def test_updating_overdrive_unblocks_at_the_next_state_read(monkeypatch, tmp_path):
    install_overdrive(tmp_path, "0.1.0")
    c = FakeClient()
    controller_found(c)
    ally_main(monkeypatch, client=c)

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        assert (await wait(p.get_state()))["blocked"] == UPDATE
        install_overdrive(tmp_path, "0.2.0")                     # Overdrive updated while Traction runs
        st = await wait(p.get_state())
        assert st["blocked"] == ""
        await wait(p._late_start)
        assert p.reapplier._task is not None
        r = await wait(p.set_grip_vibration(False))
        await wait(p._unload())
        return r
    assert run(go()) == {"ok": True, "message": ""}
    assert ("set_vibration", {"strength": 0}) in c.writes()


# ---------- Overdrive's old Armoury record not moved yet (fix round 1) ----------

NOT_MOVED = ("Overdrive's Armoury Crate record has not moved to the shared record yet. Open Overdrive once, then "
             "try again.")
OLD_RECORD = {"armoury_replaced": True, "armoury_recorded": {"ArmouryCrateService": "Automatic"},
              "armoury_running": ["ArmouryCrateService"]}


def test_switch_refused_while_overdrives_old_record_is_not_moved(tmp_path, monkeypatch):
    for i, old in enumerate(({"armoury_recorded": {"ArmouryCrateService": "Automatic"}},
                             {"armoury_replaced": True}, {"armoury_running": ["ArmouryCrateService"]}, OLD_RECORD)):
        base = tmp_path / str(i)
        overdrive_settings(base, old)
        install_overdrive(base, "0.2.0")        # Overdrive is installed: it moves its own record

        async def go():
            # this test's paths live under `base`: point the patched path functions there
            main_paths = {"record_dir": lambda: record_folder(base),
                          "plugins_dir": lambda: str(base / "plugins"),
                          "overdrive_settings_path": lambda: str(base / "settings" / "overdrive" / "overdrive.json")}
            for k, v in main_paths.items():
                monkeypatch.setattr(main, k, v)
            p, c, s = plugin_with(base)
            st = await wait(p.get_state())
            assert st["armoury"]["warning"] == NOT_MOVED
            for on in (True, False):
                assert (await wait(p.set_armoury_replaced(on))) == {"ok": False, "message": NOT_MOVED}
            assert all(not cmd.startswith("armoury_") or cmd == "armoury_state" for cmd, _ in c.calls)
            assert not os.path.exists(os.path.join(record_folder(base), "state.json"))   # no record created
            assert s.user_set is False and not os.path.exists(s.path)
        run(go())


def test_switch_works_once_the_shared_record_exists(tmp_path):
    overdrive_settings(tmp_path, OLD_RECORD)
    install_overdrive(tmp_path, "0.2.0")

    async def go():
        p, c, s = plugin_with(tmp_path)
        assert (await wait(p.set_armoury_replaced(True)))["message"] == NOT_MOVED
        moved = ArmouryRecord(record_folder(tmp_path))          # Overdrive 0.2.0 moved its record
        moved.replaced, moved.recorded = True, {"ArmouryCrateService": "Automatic"}
        moved.save()
        st = await wait(p.get_state())
        assert st["armoury"]["warning"] == "" and st["armoury"]["replaced"] is True
        r = await wait(p.set_armoury_replaced(False))
        assert r["ok"] is True, r
        assert ("armoury_restore", {"recorded": {"ArmouryCrateService": "Automatic"}, "running": []}) in c.calls
        assert saved_record(tmp_path).replaced is False
    run(go())


def test_unreadable_or_clean_overdrive_settings_do_not_block_the_switch(tmp_path, monkeypatch):
    cases = {"unreadable": "{", "not an object": "[]", "empty record": json.dumps(
        {"armoury_replaced": False, "armoury_recorded": {}, "armoury_running": []}),
        "wrong types": json.dumps({"armoury_replaced": "yes", "armoury_recorded": ["x"], "armoury_running": {}})}
    for i, (what, text) in enumerate(cases.items()):
        base = tmp_path / str(i)
        folder = base / "settings" / "overdrive"
        folder.mkdir(parents=True)
        (folder / "overdrive.json").write_text(text, encoding="utf-8")

        async def go():
            monkeypatch.setattr(main, "record_dir", lambda: record_folder(base))
            monkeypatch.setattr(main, "overdrive_settings_path", lambda: str(folder / "overdrive.json"))
            p, c, s = plugin_with(base)
            assert (await wait(p.get_state()))["armoury"]["warning"] == "", what
            assert (await wait(p.set_armoury_replaced(True)))["ok"] is True, what
            assert saved_record(base).replaced is True, what
        run(go())
    # no overdrive.json at all: not blocked either (test_switch_on_applies_settings_next_poll)


# ---------- final review T2: Overdrive not installed, its old record left in overdrive.json ----------

MOVE_FAILED = ("Overdrive's Armoury Crate record could not be moved to the shared record yet, try again in a "
               "moment.")


def test_orphaned_record_is_moved_at_startup_and_checked(monkeypatch, tmp_path):
    ally_main(monkeypatch)
    overdrive_settings(tmp_path, OLD_RECORD)
    path = tmp_path / "settings" / "overdrive" / "overdrive.json"
    before = path.read_bytes()

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        st = await wait(p.get_state())
        calls = [cmd for cmd, _ in p.client.calls]
        await wait(p._unload())
        return st, calls
    st, calls = run(go())
    rec = saved_record(tmp_path)
    assert rec.replaced is True and rec.recorded["ArmouryCrateService"] == "Automatic"
    assert rec.running[0] == "ArmouryCrateService"
    assert calls[:2] == ["armoury_state", "armoury_stop"]          # on_load ran on the moved record (P8)
    assert st["armoury"]["warning"] == "" and st["armoury"]["replaced"] is True
    assert path.read_bytes() == before                              # overdrive.json is never edited
    assert sorted(os.listdir(path.parent)) == ["overdrive.json"]


def test_orphaned_record_taken_from_bak_when_overdrive_json_is_unreadable(monkeypatch, tmp_path):
    ally_main(monkeypatch)
    folder = tmp_path / "settings" / "overdrive"
    folder.mkdir(parents=True)
    (folder / "overdrive.json").write_text("{", encoding="utf-8")
    (folder / "overdrive.json.bak").write_text(json.dumps(OLD_RECORD), encoding="utf-8")

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        await wait(p._unload())
    run(go())
    assert saved_record(tmp_path).replaced is True
    assert (folder / "overdrive.json").read_text(encoding="utf-8") == "{"


def test_orphaned_record_move_failure_refuses_the_switch_then_retries(tmp_path, monkeypatch):
    overdrive_settings(tmp_path, OLD_RECORD)

    async def go():
        p, c, s = plugin_with(tmp_path)
        real_save = p.armoury.record.save

        def broken_save():
            raise OSError("access denied")
        monkeypatch.setattr(p.armoury.record, "save", broken_save)
        await wait(p._startup_sequence())                          # the move at startup fails
        await p.reapplier.stop()
        assert not p.armoury.record.exists()
        assert all(not cmd.startswith("armoury_") or cmd == "armoury_state" for cmd, _ in c.calls)
        st = await wait(p.get_state())
        assert st["armoury"]["warning"] == MOVE_FAILED
        for on in (True, False):
            assert (await wait(p.set_armoury_replaced(on))) == {"ok": False, "message": MOVE_FAILED}
        assert all(not cmd.startswith("armoury_") or cmd == "armoury_state" for cmd, _ in c.calls)
        # the save works again: the switch moves the record, runs the load check on it, then switches
        monkeypatch.setattr(p.armoury.record, "save", real_save)
        c.calls.clear()
        r = await wait(p.set_armoury_replaced(False), 5)
        assert r["ok"] is True, r
        cmds = [cmd for cmd, _ in c.calls if cmd.startswith("armoury_") and cmd != "armoury_state"]
        assert cmds == ["armoury_stop", "armoury_restore"]          # P8 re-stop on the moved record, then off
        # the moved start type is what goes back (the P8 re-stop also adds services the fake reports as new)
        restore = [a for cmd, a in c.calls if cmd == "armoury_restore"][0]
        assert restore["recorded"]["ArmouryCrateService"] == "Automatic"
        assert restore["running"][0] == "ArmouryCrateService"
        assert saved_record(tmp_path).replaced is False
        assert (await wait(p.get_state()))["armoury"]["warning"] == ""
    run(go())


def test_orphaned_record_with_both_files_unreadable_is_refused(tmp_path):
    folder = tmp_path / "settings" / "overdrive"
    folder.mkdir(parents=True)
    (folder / "overdrive.json").write_text("{", encoding="utf-8")
    (folder / "overdrive.json.bak").write_text("{", encoding="utf-8")

    async def go():
        p, c, s = plugin_with(tmp_path)
        assert (await wait(p.set_armoury_replaced(True))) == {"ok": False, "message": MOVE_FAILED}
        assert not p.armoury.record.exists()
    run(go())


# ---------- final review T5: an old Overdrive is re-checked every 5 s ----------

def test_old_overdrive_is_rechecked_in_the_background(monkeypatch, tmp_path):
    install_overdrive(tmp_path, "0.1.0")
    c = FakeClient()
    controller_found(c)
    ally_main(monkeypatch, client=c)

    async def go():
        delays, ticks = [], asyncio.Queue()

        async def fake_sleep(d):
            delays.append(d)
            await ticks.get()
        p = main.Plugin()
        p._sleep = fake_sleep
        await p._main()
        await wait(p._startup)
        for _ in range(5):
            await asyncio.sleep(0)
        assert delays == [5.0] and p._old is True and p._late_start is None
        ticks.put_nowait(1)                                       # 5 s on: still old
        for _ in range(5):
            await asyncio.sleep(0)
        assert delays == [5.0, 5.0] and p._old is True
        install_overdrive(tmp_path, "0.2.0")                      # updated; no get_state call at all
        ticks.put_nowait(1)
        for _ in range(20):
            if p._late_start is not None:
                break
            await asyncio.sleep(0)
        assert p._old is False and p._late_start is not None
        await wait(p._late_start)
        await wait(p._watch)
        assert p.reapplier._task is not None
        await wait(p._unload())
    run(go())


def test_unload_stops_the_overdrive_recheck(monkeypatch, tmp_path):
    install_overdrive(tmp_path, "0.1.0")
    ally_main(monkeypatch)

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        watch = p._watch
        assert watch is not None and not watch.done()
        await wait(p._unload())
        assert watch.done()
    run(go())


# ---------- buttons (v2: Armoury Crate model, a Gamepad and a Desktop set) ----------

from fake_helper import PAD_NOT_SEEN, RESET_FAILED, RESET_MESSAGE  # noqa: E402
from traction import bindings  # noqa: E402

NO_CONTROLLER = "The controller was not found; the choice is saved and applied when it is back."
FACTORY = bindings.clean(None)
Z5_FACTORY = ["01-01", "00-00", "01-02", "00-00"]
Z5_DESKTOP = ["02-5A", "00-00", "02-76", "00-00"]
Z8_FACTORY = ["02-8E", "02-8E", "02-8F", "02-8F"]
Z8_M1_AS_B = ["02-8E", "02-8E", "01-02", "02-8F"]          # I1: the proven report
Z8_M1_OFF = ["02-8E", "02-8E", "00-00", "02-8F"]           # Review Focus 2: M1 does nothing, not Shift
SAVED_DESKTOP = "Saved. It applies when the controller is in Desktop mode."
SAVED_GAMEPAD = "Saved. It applies when the controller is in Gamepad mode."
Z1_GAMEPAD = ["01-09", "05-19", "01-0A", "04-02-82-23"]
# M2 as A in both sets (its switch off), as a v1 file with back_left "a" loads
M2_AS_A = {"gamepad": {"back_left": {"primary": "a"}}, "desktop": {"back_left": {"primary": "a"}},
           "m1_secondary": True, "m2_secondary": False}


def binding_writes(c):
    return [(a["zone"], a["slots"]) for cmd, a in c.calls if cmd == "set_bindings"]


def binding_args(c):
    return [a for cmd, a in c.calls if cmd == "set_bindings"]


def with_choices(*choices, **switches):
    """Bindings from (set, button, slot, action) tuples and m1_secondary/m2_secondary keywords."""
    b = bindings.clean(None)
    for set_name, button, slot, action in choices:
        b = bindings.set_choice(b, set_name, button, slot, action)
    b.update(switches)
    return b


def test_get_state_shows_buttons(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        st = (await wait(p.get_state()))["buttons"]
        assert set(st) == {"live", "m1_secondary", "m2_secondary", "sets"}
        assert st["live"] == "gamepad" and st["m1_secondary"] is True and st["m2_secondary"] is True
        assert set(st["sets"]) == {"gamepad", "desktop"}
        for name in ("gamepad", "desktop"):                                 # every button present
            assert st["sets"][name] == {b[0]: {"primary": "factory", "secondary": "factory"}
                                        for b in bindings.BUTTONS}
        s.bindings = with_choices(("gamepad", "x", "secondary", "esc"), ("desktop", "a", "primary", "tab"),
                                  ("gamepad", "back_right", "primary", "b"), m1_secondary=False)
        st = (await wait(p.get_state()))["buttons"]
        assert st["m1_secondary"] is False and st["m2_secondary"] is True
        assert st["sets"]["gamepad"]["x"] == {"primary": "factory", "secondary": "esc"}
        assert st["sets"]["gamepad"]["back_right"] == {"primary": "b", "secondary": "factory"}
        assert st["sets"]["desktop"]["a"] == {"primary": "tab", "secondary": "factory"}
        assert st["sets"]["desktop"]["x"] == {"primary": "factory", "secondary": "factory"}
        s.controller_mode = "desktop"
        assert (await wait(p.get_state()))["buttons"]["live"] == "desktop"
        s.controller_mode = "auto"
        assert (await wait(p.get_state()))["buttons"]["live"] == "gamepad"   # Auto starts in Gamepad
        p.controller_auto._written = "desktop"
        assert (await wait(p.get_state()))["buttons"]["live"] == "desktop"
        st = (await main.Plugin().get_state())["buttons"]                    # not an Ally: factory shown
        assert st["live"] == "gamepad" and st["sets"]["gamepad"]["a"] == {"primary": "factory",
                                                                          "secondary": "factory"}
    run(go())


def test_back_switch_and_primary_write_zone_8_and_save(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        gen = p.reapplier.generation
        r = await wait(p.set_back_secondary("right", False))
        assert r == {"ok": True, "message": ""}, r
        assert p.reapplier.generation == gen + 1                       # a user change, under the shared lock
        assert binding_writes(c) == [(8, Z8_M1_OFF)]
        assert [x[0] for x in c.writes()] == ["set_bindings"]          # only the affected zone, nothing else
        assert c.timeouts["set_bindings"] == [20.0]
        assert set(binding_args(c)[0]) == {"zone", "slots"}            # watched in Gamepad
        c.calls.clear()
        assert (await wait(p.set_button("gamepad", "back_right", "primary", "b"))) == {"ok": True, "message": ""}
        assert binding_writes(c) == [(8, Z8_M1_AS_B)]
        saved = Settings.load(s.path)
        assert saved.bindings["gamepad"]["back_right"] == {"primary": "b"} and saved.bindings["m1_secondary"] is False
        assert saved.user_set is True
        c.calls.clear()
        assert (await wait(p.set_back_secondary("right", True)))["ok"]  # switch on: Shift again, Primary kept
        assert binding_writes(c) == [(8, Z8_FACTORY)]
        assert Settings.load(s.path).bindings == with_choices(("gamepad", "back_right", "primary", "b"))
        c.calls.clear()
        assert (await wait(p.set_back_secondary("left", False)))["ok"]  # left = M2
        assert binding_writes(c) == [(8, ["00-00", "02-8E", "02-8F", "02-8F"])]
        c.calls.clear()
        for side, on in (("middle", True), ("left", "on"), ("left", None), (1, True), (None, False)):
            assert (await wait(p.set_back_secondary(side, on)))["ok"] is False, (side, on)
        assert (await wait(p.set_button("gamepad", "back_left", "secondary", "a")))["ok"] is False   # no Secondary
        assert c.calls == []
    run(go())


def test_set_button_and_factory_rewrites_factory_slots(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        assert (await wait(p.set_button("gamepad", "a", "secondary", "screenshot"))) == {"ok": True, "message": ""}
        assert binding_writes(c) == [(5, ["01-01", "04-03-82-88-1B", "01-02", "00-00"])]
        assert Settings.load(s.path).bindings["gamepad"] == {"a": {"secondary": "screenshot"}}
        c.calls.clear()
        assert (await wait(p.set_button("gamepad", "b", "primary", "x")))["ok"]
        assert binding_writes(c) == [(5, ["01-01", "04-03-82-88-1B", "01-03", "00-00"])]
        c.calls.clear()
        assert (await wait(p.set_button("gamepad", "a", "secondary", "factory")))["ok"]
        assert (await wait(p.set_button("gamepad", "b", "primary", "factory")))["ok"]
        assert binding_writes(c)[-1] == (5, Z5_FACTORY)                # the zone is written back to factory
        assert s.bindings == FACTORY and Settings.load(s.path).bindings == FACTORY
        c.calls.clear()
        bad = (("gamepad", "zz", "primary", "a"), ("gamepad", "a", "primary", "laser"), ("gamepad", "a", "primary", 3),
               ("tablet", "a", "primary", "a"), ("gamepad", "a", "third", "a"), (None, "a", "primary", "a"),
               ("gamepad", ["a"], "primary", "a"), ("gamepad", "a", None, "a"), (["gamepad"], "a", "primary", "a"))
        for args in bad:
            assert (await wait(p.set_button(*args)))["ok"] is False, args
        assert c.calls == []
    run(go())


def test_other_set_is_only_stored_until_its_mode_is_written(tmp_path):
    # Review Focus 3: editing the Desktop set while in Gamepad writes nothing; switching to Desktop then writes it.
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        assert (await wait(p.set_button("desktop", "a", "primary", "esc"))) == {"ok": True, "message": SAVED_DESKTOP}
        assert c.calls == []                                            # not even a controller check
        assert s.touched_zones == set() and s.user_set is True
        assert Settings.load(s.path).bindings["desktop"] == {"a": {"primary": "esc"}}
        assert (await wait(p.reset_button("desktop", "b"))) == {"ok": True, "message": SAVED_DESKTOP}
        assert c.calls == []
        assert (await wait(p.set_controller_mode("desktop")))["ok"]
        assert binding_writes(c) == [(5, ["02-76", "00-00", "02-76", "00-00"])]
        assert [a.get("watch") for a in binding_args(c)] == [False]     # Desktop writes are not watched
        c.calls.clear()
        assert (await wait(p.set_button("gamepad", "x", "secondary", "tab"))) == {"ok": True,
                                                                                 "message": SAVED_GAMEPAD}
        assert c.calls == []                                            # now Gamepad is the other set
        assert (await wait(p.set_controller_mode("gamepad")))["ok"]     # both sets' zones, Gamepad slots
        assert binding_writes(c) == [(5, Z5_FACTORY), (6, ["01-03", "02-0D", "01-04", "04-04-8C-88-8A-44"])]
    run(go())


def test_button_writes_follow_the_live_mode(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, controller_mode="desktop")
        controller_found(c)
        # Desktop has its own set now: the live Desktop set writes its zone, unwatched
        assert (await wait(p.set_button("desktop", "a", "secondary", "screenshot"))) == {"ok": True, "message": ""}
        assert binding_writes(c) == [(5, ["02-5A", "04-03-82-88-1B", "02-76", "00-00"])]
        assert [a.get("watch") for a in binding_args(c)] == [False]
        assert s.touched_zones == {5}
        c.calls.clear()
        s.controller_mode = "auto"
        p.controller_auto._written = "desktop"                         # Auto has Desktop on the pad now
        assert (await wait(p.set_button("desktop", "b", "primary", "enter")))["ok"]
        assert binding_writes(c) == [(5, ["02-5A", "04-03-82-88-1B", "02-5A", "00-00"])]
        c.calls.clear()
        assert (await wait(p.set_button("gamepad", "b", "secondary", "esc")))["ok"]
        assert c.calls == []                                            # the Gamepad set is not live
        assert (await wait(p.set_back_secondary("right", False)))["ok"]   # the switch acts on the live set
        assert binding_writes(c) == [(8, Z8_M1_OFF)] and binding_args(c)[0]["watch"] is False
        c.calls.clear()
        p.controller_auto._written = "gamepad"
        assert (await wait(p.set_button("gamepad", "b", "secondary", "esc")))["ok"]
        assert binding_writes(c) == [(5, ["01-01", "00-00", "01-02", "02-76"])]   # the Gamepad set only
        assert set(binding_args(c)[0]) == {"zone", "slots"}
    run(go())


def test_reset_all_buttons_writes_all_zones_then_clears(tmp_path):
    chosen = with_choices(("gamepad", "x", "secondary", "esc"), ("desktop", "y", "primary", "tab"),
                          ("gamepad", "back_left", "primary", "a"), m2_secondary=False, m1_secondary=False)

    async def go():
        p, c, s = plugin_with(tmp_path, bindings=chosen)
        controller_found(c)
        assert (await wait(p.reset_all_buttons())) == {"ok": True, "message": ""}
        writes = binding_writes(c)
        assert [z for z, _ in writes] == list(range(1, 10))
        assert writes[4] == (5, Z5_FACTORY) and writes[7] == (8, Z8_FACTORY)
        assert s.bindings == FACTORY and Settings.load(s.path).bindings == FACTORY   # both sets, switches on
        c.calls.clear()
        s.controller_mode = "desktop"
        s.bindings = chosen
        assert (await wait(p.reset_all_buttons())) == {"ok": True, "message": ""}
        writes = binding_writes(c)
        assert [z for z, _ in writes] == list(range(1, 10))              # the Desktop factory set, unwatched
        assert writes[4] == (5, Z5_DESKTOP) and writes[7] == (8, Z8_FACTORY)
        assert all(a.get("watch") is False for a in binding_args(c))
        assert s.bindings == FACTORY and s.touched_zones == set(range(1, 10))   # not the Gamepad factory set
        saved = Settings.load(s.path)
        assert saved.bindings == FACTORY and saved.touched_zones == set(range(1, 10))
        c.calls.clear()
        assert (await wait(p.set_controller_mode("gamepad")))["ok"]     # back to Gamepad: all 9 factory zones
        assert [z for z, _ in binding_writes(c)] == list(range(1, 10))
        assert s.touched_zones == set()
    run(go())


def test_reset_button_live_writes_other_set_stores(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=with_choices(
            ("gamepad", "a", "primary", "b"), ("gamepad", "a", "secondary", "win"), ("desktop", "a", "primary", "esc")))
        controller_found(c)
        assert (await wait(p.reset_button("gamepad", "a"))) == {"ok": True, "message": ""}
        assert binding_writes(c) == [(5, Z5_FACTORY)]
        assert s.bindings == with_choices(("desktop", "a", "primary", "esc"))
        c.calls.clear()
        assert (await wait(p.reset_button("desktop", "a")))["ok"]
        assert c.calls == [] and s.bindings == FACTORY and Settings.load(s.path).bindings == FACTORY
        for args in (("tablet", "a"), ("gamepad", "zz"), ("gamepad", 5), (None, "a")):
            assert (await wait(p.reset_button(*args)))["ok"] is False, args
        assert c.calls == []
    run(go())


def test_pad_lost_after_a_write_clears_the_buttons(tmp_path):
    # Review Focus 5: a reset reply while editing clears both sets and the switches go back on.
    for outcome, message in (("reset", RESET_MESSAGE), ("reset_failed", RESET_FAILED)):
        async def go():
            p, c, s = plugin_with(tmp_path, bindings=dict(M2_AS_A, m1_secondary=False), touched_zones={3, 8})
            s.bindings = bindings.set_choice(s.bindings, "desktop", "y", "secondary", "tab")
            controller_found(c)
            c.bindings_reply = outcome
            r = await wait(p.set_button("gamepad", "x", "secondary", "esc"))
            assert r == {"ok": False, "message": message}
            assert s.bindings == FACTORY and Settings.load(s.path).bindings == FACTORY
            assert s.touched_zones == set() and p.reapplier.rerun is True
            st = (await wait(p.get_state()))["buttons"]
            assert st["m1_secondary"] is True and st["m2_secondary"] is True
            assert st["sets"]["desktop"]["y"] == {"primary": "factory", "secondary": "factory"}
        run(go())


def test_pad_not_seen_changes_nothing(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=dict(M2_AS_A))
        controller_found(c)
        c.bindings_reply = "not_seen"
        for call in (p.set_button("gamepad", "x", "secondary", "esc"), p.set_back_secondary("left", True),
                     p.reset_button("gamepad", "back_left"), p.reset_all_buttons()):
            assert (await wait(call)) == {"ok": False, "message": PAD_NOT_SEEN}
        assert bindings.clean(s.bindings) == M2_AS_A                    # kept, as stored (the choices too)
        assert not os.path.exists(s.path)
        # a mode change still lands; the bindings refusal is reported with it
        r = await wait(p.set_controller_mode("desktop"))
        assert r["ok"] is True and r["message"] == PAD_NOT_SEEN
        assert Settings.load(s.path).controller_mode == "desktop"
        assert bindings.clean(s.bindings) == M2_AS_A
    run(go())


def test_buttons_saved_when_controller_missing(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        assert (await wait(p.set_back_secondary("left", False))) == {"ok": True, "message": NO_CONTROLLER}
        assert (await wait(p.set_button("gamepad", "back_left", "primary", "a"))) == {"ok": True,
                                                                                     "message": NO_CONTROLLER}
        assert (await wait(p.set_button("gamepad", "y", "secondary", "tab"))) == {"ok": True,
                                                                                 "message": NO_CONTROLLER}
        assert (await wait(p.set_button("desktop", "y", "primary", "esc"))) == {"ok": True,
                                                                               "message": SAVED_DESKTOP}
        assert binding_writes(c) == []
        saved = Settings.load(s.path)
        assert saved.bindings == with_choices(("gamepad", "back_left", "primary", "a"),
                                              ("gamepad", "y", "secondary", "tab"),
                                              ("desktop", "y", "primary", "esc"), m2_secondary=False)
        assert saved.user_set is True
        assert (await wait(p.reset_all_buttons())) == {"ok": True, "message": NO_CONTROLLER}
        assert Settings.load(s.path).bindings == FACTORY
    run(go())


def test_button_setters_refused_while_busy(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        p.armoury._busy = True
        for call in (p.set_back_secondary("left", False), p.set_button("gamepad", "a", "secondary", "esc"),
                     p.set_button("desktop", "a", "primary", "esc"), p.reset_button("gamepad", "a"),
                     p.reset_all_buttons()):
            assert (await wait(call)) == {"ok": False, "message": BUSY}
        p.armoury._busy = False
        assert c.writes() == [] and not os.path.exists(s.path)
    run(go())


def test_v1_setters_are_gone():
    for name in ("set_back_button", "set_combo", "reset_buttons"):
        assert not hasattr(main.Plugin, name), name


def test_mode_change_writes_both_sets_zones_for_the_new_mode(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=with_choices(("gamepad", "a", "secondary", "screenshot"),
                                                              ("desktop", "du", "primary", "page_up")))
        controller_found(c)
        seq = []
        for mode in ("gamepad", "desktop", "gamepad"):
            c.calls.clear()
            assert (await wait(p.set_controller_mode(mode)))["ok"]
            seq.append(binding_writes(c))
        gamepad = [(1, Z1_GAMEPAD), (5, ["01-01", "04-03-82-88-1B", "01-02", "00-00"])]
        assert seq == [gamepad, [(1, ["02-96", "05-19", "02-99", "04-02-82-23"]), (5, Z5_DESKTOP)], gamepad]
    run(go())


def test_v1_file_first_reapply_writes_the_v1_zone_8_bytes(tmp_path):
    # Review Focus 1: the owner's v1 mapping survives the update, and the pad gets the same zone 8 bytes.
    os.makedirs(os.path.dirname(settings_file(tmp_path)), exist_ok=True)
    with open(settings_file(tmp_path), "w", encoding="utf-8") as f:
        json.dump({"user_set": True, "touched_zones": [8],
                   "bindings": {"back_left": "shift", "back_right": "b", "combos": {"a": "screenshot"}}}, f)

    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        await wait(p.reapplier.apply_all())
        assert binding_writes(c) == [(5, ["01-01", "04-03-82-88-1B", "01-02", "00-00"]), (8, Z8_M1_AS_B)]
        st = (await wait(p.get_state()))["buttons"]
        assert st["m1_secondary"] is False
        assert st["sets"]["gamepad"]["back_right"]["primary"] == "b"
        assert st["sets"]["gamepad"]["a"]["secondary"] == "screenshot"
    run(go())


def test_old_overdrive_writes_no_bindings(monkeypatch, tmp_path):
    install_overdrive(tmp_path, "0.1.0")
    os.makedirs(os.path.dirname(settings_file(tmp_path)), exist_ok=True)
    with open(settings_file(tmp_path), "w", encoding="utf-8") as f:
        json.dump({"controller_mode": "auto", "user_set": True,
                   "bindings": {"back_right": "b", "combos": {"a": "screenshot"}}}, f)
    c = FakeClient()
    controller_found(c)
    ally_main(monkeypatch, client=c)

    async def go():
        p = main.Plugin()
        await p._main()
        await wait(p._startup)
        results = [await wait(p.set_back_secondary("left", False)),
                   await wait(p.set_button("gamepad", "x", "secondary", "esc")),
                   await wait(p.set_button("desktop", "x", "primary", "esc")),
                   await wait(p.reset_button("gamepad", "a")), await wait(p.reset_all_buttons())]
        p.reapplier.rerun = True
        await wait(p.reapplier.tick())
        await wait(p.reapplier.apply_all())
        await wait(p._unload())
        return p, results
    p, results = run(go())
    assert [x for x in c.calls if x[0] == "set_bindings"] == []
    for r in results:
        assert r == {"ok": False, "message": UPDATE}
    assert p.settings.bindings["gamepad"]["back_right"] == {"primary": "b"}


# ---------- buttons: fix round 1 (writes under the lock, zones returned to factory) ----------

def held_bindings(c, outcomes):
    """set_bindings waits for `release` on its first call and answers by outcomes (one per call, last repeats)."""
    entered, release = asyncio.Event(), asyncio.Event()
    seq = list(outcomes)
    first = [True]

    async def handler(args):
        if first[0]:
            first[0] = False
            entered.set()
            await release.wait()
        from fake_helper import bindings_reply
        return bindings_reply(seq.pop(0) if len(seq) > 1 else seq[0], args)
    c.handlers["set_bindings"] = handler
    return entered, release


def test_two_quick_setters_keep_both_changes(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        entered, release = held_bindings(c, ["ok"])
        first = asyncio.ensure_future(p.set_button("gamepad", "a", "secondary", "esc"))
        await wait(entered.wait())
        second = asyncio.ensure_future(p.set_button("gamepad", "x", "secondary", "tab"))   # waits for the lock
        third = asyncio.ensure_future(p.set_button("desktop", "x", "primary", "esc"))      # stored, after both
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        assert (await wait(first))["ok"] and (await wait(second))["ok"] and (await wait(third))["ok"]
        want = with_choices(("gamepad", "a", "secondary", "esc"), ("gamepad", "x", "secondary", "tab"),
                            ("desktop", "x", "primary", "esc"))
        assert s.bindings == want and Settings.load(s.path).bindings == want
    run(go())


def test_reset_reply_while_a_setter_waits_does_not_bring_the_old_set_back(tmp_path):
    async def go():
        old = bindings.set_choice(M2_AS_A, "gamepad", "b", "secondary", "esc")
        old = bindings.set_choice(old, "desktop", "a", "primary", "esc")
        p, c, s = plugin_with(tmp_path, bindings=old, touched_zones={5, 8})
        controller_found(c)
        entered, release = held_bindings(c, ["reset", "ok"])
        first = asyncio.ensure_future(p.set_button("gamepad", "y", "secondary", "tab"))   # loses the pad
        await wait(entered.wait())
        second = asyncio.ensure_future(p.set_button("gamepad", "x", "secondary", "tab"))
        for _ in range(5):
            await asyncio.sleep(0)
        release.set()
        assert (await wait(first)) == {"ok": False, "message": RESET_MESSAGE}
        assert (await wait(second))["ok"]
        # built from the cleared sets: the old back button, the choices of both sets stay gone, switches on
        assert s.bindings == with_choices(("gamepad", "x", "secondary", "tab"))
        assert s.touched_zones == {6}
        c.calls.clear()
        await wait(p.reapplier.apply_all())
        assert [z for z, _ in binding_writes(c)] == [6]
    run(go())


def test_factory_while_controller_missing_is_written_at_the_next_reapply(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        assert (await wait(p.set_button("gamepad", "a", "secondary", "screenshot")))["ok"]
        assert s.touched_zones == {5}
        c.handlers["controller_info"] = reply(ok({"found": False, "pid": "0x1B4C", "xbox": False}))
        assert (await wait(p.set_button("gamepad", "a", "secondary", "factory"))) == {"ok": True,
                                                                                     "message": NO_CONTROLLER}
        assert Settings.load(s.path).touched_zones == {5}         # still to be written back
        controller_found(c)
        c.calls.clear()
        await wait(p.reapplier.apply_all())
        assert binding_writes(c) == [(5, Z5_FACTORY)]              # factory slots, once
        assert s.touched_zones == set() and Settings.load(s.path).touched_zones == set()
        c.calls.clear()
        await wait(p.reapplier.apply_all())
        assert binding_writes(c) == []                             # then not again
    run(go())


def test_reset_while_controller_missing_restores_touched_zones_later(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        assert (await wait(p.set_back_secondary("right", False)))["ok"]
        assert (await wait(p.set_button("gamepad", "back_right", "primary", "b")))["ok"]
        c.handlers["controller_info"] = reply(ok({"found": False, "pid": "0x1B4C", "xbox": False}))
        assert (await wait(p.reset_all_buttons()))["ok"]
        assert s.bindings == FACTORY and s.touched_zones == {8}
        controller_found(c)
        c.calls.clear()
        await wait(p.reapplier.apply_all())
        assert binding_writes(c) == [(8, Z8_FACTORY)]
        assert s.touched_zones == set()
    run(go())


def test_desktop_then_gamepad_after_factory_rewrites_the_zone(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, controller_mode="desktop")
        controller_found(c)
        assert (await wait(p.set_button("desktop", "a", "secondary", "screenshot")))["ok"]
        c.calls.clear()
        assert (await wait(p.set_button("desktop", "a", "secondary", "factory")))["ok"]
        assert binding_writes(c) == [(5, Z5_DESKTOP)]               # written with desktop slots
        assert s.touched_zones == {5}                               # not yet the Gamepad factory set
        c.calls.clear()
        assert (await wait(p.set_controller_mode("gamepad")))["ok"]
        assert binding_writes(c) == [(5, Z5_FACTORY)]
        assert s.touched_zones == set()
        c.calls.clear()
        assert (await wait(p.set_controller_mode("desktop")))["ok"]
        assert binding_writes(c) == []
    run(go())


def test_reset_all_partial_keeps_unwritten_zones_touched(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=with_choices(("gamepad", "du", "secondary", "esc"),
                                                              ("gamepad", "a", "secondary", "tab"),
                                                              ("desktop", "dl", "primary", "esc")),
                              touched_zones={1, 5})
        controller_found(c)
        seq = ["ok", "ok", "not_seen"]

        async def handler(args):
            from fake_helper import bindings_reply
            return bindings_reply(seq.pop(0) if len(seq) > 1 else seq[0], args)
        c.handlers["set_bindings"] = handler
        assert (await wait(p.reset_all_buttons())) == {"ok": False, "message": PAD_NOT_SEEN}
        assert [z for z, _ in binding_writes(c)] == [1, 2, 3]
        assert s.touched_zones == {5}                               # zones 1 and 2 got their factory slots
        # M3: only the zones that landed are stored (both sets), and the next tick writes the rest again
        assert s.bindings == with_choices(("gamepad", "a", "secondary", "tab"))
        assert Settings.load(s.path).bindings == s.bindings
        assert p.reapplier.rerun is True
    run(go())


def test_reset_reply_reports_a_failed_save(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=dict(M2_AS_A))
        controller_found(c)
        c.bindings_reply = "reset"

        def broken():
            raise OSError("disk full")
        s.save = broken
        r = await wait(p.set_button("gamepad", "x", "secondary", "esc"))
        assert r["ok"] is False and r["message"].startswith(RESET_MESSAGE) and "disk full" in r["message"]
        assert s.bindings == FACTORY
    run(go())


# ---------- buttons: final review fixes ----------

def test_reset_reply_reruns_the_mode_and_vibration_next_tick(tmp_path):
    # I3: the helper's factory set wrote Gamepad and vibration 100; the next tick writes the owner's again.
    async def go():
        p, c, s = plugin_with(tmp_path, grip_vibration=False, user_set=True, bindings=dict(M2_AS_A))
        controller_found(c)
        c.bindings_reply = "reset"
        assert (await wait(p.set_button("gamepad", "x", "secondary", "esc"))) == {"ok": False,
                                                                                 "message": RESET_MESSAGE}
        assert p.reapplier.rerun is True
        c.calls.clear()
        c.bindings_reply = "ok"
        assert await wait(p.reapplier.tick())
        assert ("set_vibration", {"strength": 0}) in c.writes()
        assert binding_writes(c) == []                                 # nothing custom is left
        assert p.reapplier.rerun is False
    run(go())


def test_mode_change_reset_reply_reruns_next_tick(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, grip_vibration=False, user_set=True, bindings=dict(M2_AS_A))
        controller_found(c)
        c.bindings_reply = "reset"
        r = await wait(p.set_controller_mode("gamepad"))
        assert r == {"ok": True, "message": RESET_MESSAGE}
        assert p.reapplier.rerun is True and s.bindings == FACTORY
        c.calls.clear()
        c.bindings_reply = "ok"
        assert await wait(p.reapplier.tick())
        assert ("set_vibration", {"strength": 0}) in c.writes()
    run(go())


def test_reset_all_reset_reply_reruns(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=dict(M2_AS_A))
        controller_found(c)
        c.bindings_reply = "reset"
        assert (await wait(p.reset_all_buttons()))["ok"] is False
        assert p.reapplier.rerun is True and s.bindings == FACTORY and s.touched_zones == set()
    run(go())


def test_transport_failure_in_a_setter_marks_the_zone_touched(tmp_path):
    # M7: the choice may have landed though the reply was lost: the zone is put right at the next reapply.
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        c.handlers["set_bindings"] = reply(fail("Traction helper restarted, try again"))
        r = await wait(p.set_button("gamepad", "a", "secondary", "esc"))
        assert r["ok"] is False
        assert s.bindings == FACTORY                                  # not stored
        assert s.touched_zones == {5} and Settings.load(s.path).touched_zones == {5}
        c.handlers.pop("set_bindings")
        c.calls.clear()
        await wait(p.reapplier.apply_all())
        assert binding_writes(c) == [(5, Z5_FACTORY)]
        assert s.touched_zones == set()
    run(go())


def test_get_state_does_not_read_while_a_binding_write_runs(tmp_path):
    # M2: a read queued behind set_bindings could time out twice and get the helper killed mid-reset.
    async def go():
        p, c, s = plugin_with(tmp_path)
        controller_found(c)
        first = await wait(p.get_state())
        assert first["controller"]["found"] is True
        entered, release = held_bindings(c, ["ok"])
        setter = asyncio.ensure_future(p.set_button("gamepad", "a", "secondary", "esc"))
        await wait(entered.wait())
        c.calls.clear()
        state = await wait(p.get_state())
        assert [x for x in c.calls if x[0] in ("controller_info", "get_touchscreen", "armoury_state")] == []
        assert state["controller"]["found"] is True                  # the last reading
        assert state["touchscreen"] == first["touchscreen"]
        release.set()
        assert (await wait(setter))["ok"]
        c.calls.clear()
        await wait(p.get_state())
        assert any(x[0] == "controller_info" for x in c.calls)       # read again once the write is done
    run(go())


def test_auto_after_a_reapply_edits_go_to_the_gamepad_set(tmp_path):
    # Final review 2: Auto's loop wrote Desktop, then a reapply (it writes Gamepad under Auto) ran: until the loop
    # writes Desktop again, Gamepad is on the pad.
    async def go():
        p, c, s = plugin_with(tmp_path, controller_mode="auto")
        controller_found(c)
        p.controller_auto._written = "desktop"
        assert (await wait(p.get_state()))["buttons"]["live"] == "desktop"
        p.reapplier.applies += 1
        assert (await wait(p.get_state()))["buttons"]["live"] == "gamepad"
        c.calls.clear()
        assert (await wait(p.set_button("desktop", "a", "primary", "esc"))) == {"ok": True, "message": SAVED_DESKTOP}
        assert binding_writes(c) == []                                  # stored only
        assert s.bindings["desktop"] == {"a": {"primary": "esc"}}
        assert (await wait(p.set_button("gamepad", "a", "secondary", "win"))) == {"ok": True, "message": ""}
        assert binding_writes(c) == [(5, ["01-01", "02-82", "01-02", "00-00"])]
        assert set(binding_args(c)[0]) == {"zone", "slots"}            # watched: Gamepad
        p.reapplier.applies -= 1
        p.reapplier.applying = 1                                       # a reapply running: Gamepad as well
        assert (await wait(p.get_state()))["buttons"]["live"] == "gamepad"
        p.reapplier.applying = 0
    run(go())


def test_reset_button_on_a_back_button_turns_the_switch_on_and_writes_zone_8(tmp_path):
    # Final review 1/5: factory for M1 is the Shift key; zone 8 is live whatever set is edited (the switch is shared).
    chosen = with_choices(("gamepad", "back_right", "primary", "b"), ("desktop", "back_right", "primary", "a"),
                          m1_secondary=False)
    async def go():
        p, c, s = plugin_with(tmp_path, bindings=chosen, touched_zones={8})
        controller_found(c)
        assert (await wait(p.reset_button("desktop", "back_right"))) == {"ok": True, "message": ""}
        assert binding_writes(c) == [(8, Z8_FACTORY)]                   # the Gamepad set is live: written, watched
        assert set(binding_args(c)[0]) == {"zone", "slots"}
        saved = Settings.load(s.path)
        assert saved.bindings == with_choices(("gamepad", "back_right", "primary", "b"))
        assert saved.bindings["m1_secondary"] is True
        assert s.touched_zones == set()                                 # zone 8 holds the factory set again
        c.calls.clear()
        s.controller_mode = "desktop"
        s.bindings = chosen
        assert (await wait(p.reset_button("gamepad", "back_right")))["ok"]
        assert binding_writes(c) == [(8, Z8_FACTORY)] and binding_args(c)[0]["watch"] is False
        assert s.bindings == with_choices(("desktop", "back_right", "primary", "a"))
    run(go())


# ---------- the Library button ----------

LIBRARY_NOTE = ("Armoury Crate is running, so its Library setting applies. Turn on Use Traction instead of Armoury "
                "Crate to change it here.")
DEFAULT_PRESS = {"single": ["05-00-27-00-00-00-00-00-00", "05-00-17-00-00-00-00-00-00"],
                 "long": ["05-00-16-00-00-00-00-00-00", "05-00-04-00-00-00-00-00-00"]}


def press_calls(c):
    return [x for x in c.calls if x[0] == "set_press_bindings"]


def test_set_library_press_writes_and_stores(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, armoury_replaced=True)
        controller_found(c)
        assert (await wait(p.set_library_press("single", "asus_show_desktop"))) == {"ok": True, "message": ""}
        assert press_calls(c) == [("set_press_bindings", {
            "single": ["05-00-1C-00-00-00-00-00-00", "05-00-17-00-00-00-00-00-00"],
            "long": DEFAULT_PRESS["long"]})]
        saved = Settings.load(s.path)
        assert saved.library == {"single": "asus_show_desktop", "long": "armoury"} and saved.library_written
        assert saved.user_set is True
        state = await wait(p.get_state())
        assert state["library"] == {"single": "asus_show_desktop", "long": "armoury", "allowed": True, "note": ""}
        # bad input: refused, nothing sent or stored
        c.calls.clear()
        for press, choice in (("double", "esc"), ("single", "nothing"), ("long", ""), (None, "esc"), ("long", 5)):
            r = await wait(p.set_library_press(press, choice))
            assert r["ok"] is False and r["message"], (press, choice)
        assert press_calls(c) == [] and s.library["long"] == "armoury"
        # a refused write keeps the old choice
        c.handlers["set_press_bindings"] = reply(fail("Refused: unknown press binding 'x'."))
        r = await wait(p.set_library_press("long", "esc"))
        assert r == {"ok": False, "message": "Refused: unknown press binding 'x'."}
        assert s.library == {"single": "asus_show_desktop", "long": "armoury"}
        assert Settings.load(s.path).library["long"] == "armoury"
        # no controller: stored, written by the next reapply
        del c.handlers["set_press_bindings"]
        c.handlers["controller_info"] = reply(ok({"found": False}))
        c.calls.clear()
        r = await wait(p.set_library_press("long", "esc"))
        assert r == {"ok": True, "message": main.NO_CONTROLLER} and press_calls(c) == []
        assert Settings.load(s.path).library == {"single": "asus_show_desktop", "long": "esc"}
    run(go())


def test_no_write_while_armoury_runs(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)   # Armoury Crate installed (FakeClient) and not replaced
        controller_found(c)
        assert (await wait(p.set_library_press("single", "esc"))) == {"ok": True, "message": ""}
        assert press_calls(c) == []
        assert Settings.load(s.path).library == {"single": "esc", "long": "armoury"}
        state = await wait(p.get_state())
        assert state["library"] == {"single": "esc", "long": "armoury", "allowed": False, "note": LIBRARY_NOTE}
        assert (await wait(p.reset_library()))["ok"] and press_calls(c) == []
        assert (await wait(p.set_library_press("long", "win")))["ok"]
        # a reapply writes the controller, never the Library button
        c.calls.clear()
        assert await wait(p.reapplier.apply_all()) is True
        assert controller_writes(c) != [] and press_calls(c) == []
        # Armoury Crate replaced: the next reapply writes it
        rec = saved_record(tmp_path)
        rec.replaced = True
        rec.save()
        await wait(p.reapplier.apply_all())
        assert len(press_calls(c)) == 1
    run(go())


def test_library_allowed_needs_installed_known(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path)
        assert p._library_allowed() is False                  # Armoury Crate's install not read yet: not allowed
        c.handlers["armoury_state"] = reply(ok({"installed": False, "startTypes": {}, "running": []}))
        await p.armoury.check_installed()
        assert p._library_allowed() is True                   # not installed: allowed
        assert p.reapplier.library_allowed() is True
        p._old = True
        assert p._library_allowed() is False                  # an old Overdrive drives the controller
        state = await wait(p.get_state())
        assert state["library"]["allowed"] is False and state["library"]["note"] == ""
        assert (await wait(main.Plugin().get_state()))["library"] == {"single": "armoury", "long": "armoury",
                                                                       "allowed": False, "note": ""}
    run(go())


def test_library_refused_by_an_old_overdrive_and_while_busy(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, old=True, armoury_replaced=True)
        controller_found(c)
        assert (await wait(p.set_library_press("single", "esc"))) == {"ok": False, "message": UPDATE}
        assert (await wait(p.reset_library())) == {"ok": False, "message": UPDATE}
        assert press_calls(c) == [] and s.library["single"] == "armoury"
        p2, c2, s2 = plugin_with(tmp_path / "b", armoury_replaced=True)
        p2.armoury._busy = True
        assert (await wait(p2.set_library_press("single", "esc"))) == {"ok": False, "message": BUSY}
        p2.armoury._busy = False
        assert press_calls(c2) == [] and s2.library["single"] == "armoury"
    run(go())


def test_reset_library_writes_once_then_stops(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, armoury_replaced=True, user_set=True)
        controller_found(c)
        assert (await wait(p.set_library_press("long", "esc")))["ok"]
        c.calls.clear()
        assert (await wait(p.reset_library())) == {"ok": True, "message": ""}
        assert press_calls(c) == [("set_press_bindings", DEFAULT_PRESS)]
        saved = Settings.load(s.path)
        assert saved.library == {"single": "armoury", "long": "armoury"} and saved.library_written is False
        c.calls.clear()
        await wait(p.reapplier.apply_all())
        await wait(p.reapplier.apply_all())
        assert press_calls(c) == []
    run(go())


def test_reset_all_resets_library(tmp_path):
    async def go():
        p, c, s = plugin_with(tmp_path, armoury_replaced=True, library={"single": "esc", "long": "win"},
                              library_written=True)
        controller_found(c)
        assert (await wait(p.reset_all_buttons())) == {"ok": True, "message": ""}
        assert [z for z, _ in binding_writes(c)] == list(range(1, 10))
        assert press_calls(c) == [("set_press_bindings", DEFAULT_PRESS)]
        saved = Settings.load(s.path)
        assert saved.library == {"single": "armoury", "long": "armoury"} and saved.library_written is False
        # already reset: no Library call
        c.calls.clear()
        assert (await wait(p.reset_all_buttons()))["ok"]
        assert press_calls(c) == []
        # Armoury Crate running: the choices are reset, nothing is written
        p2, c2, s2 = plugin_with(tmp_path / "b", library={"single": "esc", "long": "armoury"})
        controller_found(c2)
        assert (await wait(p2.reset_all_buttons()))["ok"]
        assert press_calls(c2) == [] and s2.library == {"single": "armoury", "long": "armoury"}
    run(go())


def test_first_part_b_is_gone():
    p = main.Plugin()
    assert not hasattr(p, "set_armoury_button") and not hasattr(p, "armoury_button")
    assert not hasattr(main, "ArmouryButton")
