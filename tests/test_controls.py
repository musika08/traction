"""Ported from Overdrive ba0307a tests/test_controls.py (touchscreen and controller parts)."""
import asyncio

import pytest

from fake_helper import FakeClient, fail, ok
from traction import controls
from traction.settings import Settings

RESTARTED = "Traction helper restarted, try again"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def fresh_cache():
    controls.reset_cache()
    yield
    controls.reset_cache()


def settings(tmp_path, **fields):
    s = Settings.load(str(tmp_path / "settings.json"))
    for k, v in fields.items():
        setattr(s, k, v)
    return s


def handler(reply):
    async def h(args):
        return reply
    return h


def test_transport_failure_matches_traction_texts():
    assert controls.transport_failure(fail(RESTARTED))
    assert controls.transport_failure(fail("Traction helper did not answer in 10 s."))
    assert controls.transport_failure(fail("Traction helper is not running (starting)."))
    assert not controls.transport_failure(fail("Controller not found"))
    assert not controls.transport_failure(ok({}))


def test_touchscreen_toggle(tmp_path, monkeypatch):
    async def go():
        now = [1000.0]
        monkeypatch.setattr(controls, "clock", lambda: now[0])
        c = FakeClient()
        c.handlers["get_touchscreen"] = handler(ok({"found": True, "enabled": True, "instanceId": "x"}))
        count = lambda: len([x for x in c.calls if x[0] == "get_touchscreen"])
        assert (await controls.read_controls(c))["touchscreen"] == {"found": True, "enabled": True}
        assert (await controls.set_touchscreen(c, False))["ok"]
        assert c.writes() == [("set_touchscreen", {"enabled": False})]
        # C4: the cache is dropped, so the next read asks the real device (never shows the requested value)
        st = await controls.read_controls(c)
        assert st["touchscreen"] == {"found": True, "enabled": True} and count() == 2
        # the change has not landed yet: each read asks again (the panel polls for up to 15 s)
        now[0] += 1.5
        await controls.read_controls(c)
        assert count() == 3
        c.handlers["get_touchscreen"] = handler(ok({"found": True, "enabled": False, "instanceId": "x"}))
        now[0] += 1.5
        assert (await controls.read_controls(c))["touchscreen"] == {"found": True, "enabled": False}
        assert count() == 4
        now[0] += 1.5
        await controls.read_controls(c)                                # landed: cached again
        assert count() == 4
        c.handlers["set_touchscreen"] = handler(fail("no device"))
        assert not (await controls.set_touchscreen(c, True))["ok"]
        await controls.read_controls(c)                                # a refused write keeps the cache
        assert count() == 4
    run(go())


def test_touchscreen_rereads_stop_after_15_seconds(tmp_path, monkeypatch):
    async def go():
        now = [1000.0]
        monkeypatch.setattr(controls, "clock", lambda: now[0])
        c = FakeClient()
        c.handlers["get_touchscreen"] = handler(ok({"found": True, "enabled": True, "instanceId": "x"}))
        count = lambda: len([x for x in c.calls if x[0] == "get_touchscreen"])
        assert (await controls.set_touchscreen(c, False))["ok"]
        await controls.read_controls(c)
        now[0] += 16                                                   # never landed: back to the 30 s cache
        await controls.read_controls(c)
        await controls.read_controls(c)
        assert count() == 1
    run(go())


def test_failed_touchscreen_read_keeps_the_last_status(tmp_path, monkeypatch):
    async def go():
        now = [1000.0]
        monkeypatch.setattr(controls, "clock", lambda: now[0])
        c = FakeClient()
        good = handler(ok({"found": True, "enabled": True, "instanceId": "x"}))
        bad = handler(fail("PowerShell did not answer in 5 seconds."))
        count = lambda: len([x for x in c.calls if x[0] == "get_touchscreen"])
        # no good reading yet: a failure reports not found, and is not cached
        c.handlers["get_touchscreen"] = bad
        assert (await controls.read_controls(c))["touchscreen"] == {"found": False, "enabled": False}
        c.handlers["get_touchscreen"] = good
        assert (await controls.read_controls(c))["touchscreen"] == {"found": True, "enabled": True}
        assert count() == 2
        # cache expired, the read fails: the last status is shown (toggle stays), and the next read asks again
        now[0] += 31
        c.handlers["get_touchscreen"] = bad
        assert (await controls.read_controls(c))["touchscreen"] == {"found": True, "enabled": True}
        assert (await controls.read_controls(c))["touchscreen"] == {"found": True, "enabled": True}
        assert count() == 4
        c.handlers["get_touchscreen"] = good
        await controls.read_controls(c)
        await controls.read_controls(c)                                 # good again: cached
        assert count() == 5
        # settling on "off": a failed read reports the last real status (on), never the requested off
        assert (await controls.set_touchscreen(c, False))["ok"]
        c.handlers["get_touchscreen"] = bad
        now[0] += 1.5
        assert (await controls.read_controls(c))["touchscreen"] == {"found": True, "enabled": True}
        now[0] += 1.5
        await controls.read_controls(c)
        assert count() == 7                                             # still asking: not settled
    run(go())


def test_read_controls_values_and_unsupported(tmp_path):
    async def go():
        c = FakeClient()
        c.handlers["controller_info"] = handler(ok({"found": True, "pid": "0x1B4C", "xbox": False}))
        c.handlers["get_touchscreen"] = handler(ok({"found": True, "enabled": True, "instanceId": "HID\\x"}))
        st = await controls.read_controls(c)
        assert st["controller"] == {"found": True}
        assert st["touchscreen"] == {"found": True, "enabled": True}
        for cmd in ("controller_info", "get_touchscreen"):
            c.handlers[cmd] = handler(fail("not supported"))
        controls.reset_cache()
        st = await controls.read_controls(c)
        assert st["controller"] == {"found": False}
        assert st["touchscreen"] == {"found": False, "enabled": False}
    run(go())


def test_touchscreen_status_is_cached_for_30_seconds(tmp_path, monkeypatch):
    async def go():
        now = [1000.0]
        monkeypatch.setattr(controls, "clock", lambda: now[0])
        c = FakeClient()
        c.handlers["get_touchscreen"] = handler(ok({"found": True, "enabled": True, "instanceId": "x"}))
        count = lambda: len([x for x in c.calls if x[0] == "get_touchscreen"])
        await controls.read_controls(c)
        now[0] += 29
        await controls.read_controls(c)
        assert count() == 1
        now[0] += 2
        await controls.read_controls(c)
        assert count() == 2
        assert c.timeouts["get_touchscreen"] == [15.0, 15.0]           # PowerShell in the helper: a long read
    run(go())


def test_apply_controller_writes_mode_and_vibration(tmp_path):
    async def go():
        c = FakeClient()
        s = settings(tmp_path, controller_mode="desktop", grip_vibration=False)
        r = await controls.apply_controller(c, s)
        assert r["ok"]
        assert c.writes() == [("set_controller_mode", {"mode": "desktop"}), ("set_vibration", {"strength": 0})]
        c.calls.clear()
        s.grip_vibration = True
        await controls.apply_controller(c, s, "gamepad")
        assert c.writes() == [("set_controller_mode", {"mode": "gamepad"}), ("set_vibration", {"strength": 100})]
        c.calls.clear()
        s.controller_mode = "auto"      # auto starts in gamepad
        await controls.apply_controller(c, s)
        assert c.writes()[0] == ("set_controller_mode", {"mode": "gamepad"})
        c.calls.clear()
        assert not (await controls.apply_controller(c, s, "bogus"))["ok"]
        assert c.calls == []
    run(go())


def test_apply_controller_reports_each_failure(tmp_path):
    async def go():
        c = FakeClient()
        c.handlers["set_controller_mode"] = handler(fail("mode refused"))
        r = await controls.apply_controller(c, settings(tmp_path))
        assert not r["ok"] and "mode refused" in r["message"]
        assert ("set_vibration", {"strength": 100}) in c.writes()   # still tried
    run(go())


def test_apply_controller_stops_after_transport_failure(tmp_path):
    async def go():
        c = FakeClient()
        c.handlers["set_controller_mode"] = handler(fail(RESTARTED))
        r = await controls.apply_controller(c, settings(tmp_path))
        assert not r["ok"] and r["message"] == RESTARTED
        assert [x[0] for x in c.calls] == ["set_controller_mode"]
    run(go())


# ---------- button bindings ----------

from fake_helper import PAD_NOT_SEEN, RESET_FAILED, RESET_MESSAGE  # noqa: E402

CHOSEN = {"back_left": "shift", "back_right": "b", "combos": {"a": "screenshot"}}
FACTORY = {"back_left": "shift", "back_right": "shift", "combos": {}}
Z5_GAMEPAD = ["01-01", "04-03-82-88-1B", "01-02", "00-00"]
Z5_DESKTOP = ["02-5A", "00-00", "02-76", "00-00"]
Z8_GAMEPAD = ["02-8E", "02-8E", "01-02", "01-02"]
Z8_DESKTOP = ["02-8E", "02-8E", "02-8F", "02-8F"]


def binding_writes(c):
    return [(a["zone"], a["slots"]) for cmd, a in c.calls if cmd == "set_bindings"]


def test_apply_bindings_writes_only_changed_zones(tmp_path):
    async def go():
        c = FakeClient()
        s = settings(tmp_path)
        assert (await controls.apply_bindings(c, s, "gamepad"))["ok"]
        assert binding_writes(c) == []                         # factory set: nothing written
        s.bindings = dict(CHOSEN)
        r = await controls.apply_bindings(c, s, "gamepad")
        assert r["ok"] and r["message"] == ""
        assert binding_writes(c) == [(5, Z5_GAMEPAD), (8, Z8_GAMEPAD)]
        assert c.timeouts["set_bindings"] == [20.0, 20.0]      # 5 s pad polling plus the factory reset writes
        c.calls.clear()
        await controls.apply_bindings(c, s, "desktop")
        assert binding_writes(c) == [(5, Z5_DESKTOP), (8, Z8_DESKTOP)]   # G-Helper's desktop defaults
        c.calls.clear()
        await controls.apply_bindings(c, s, "auto")
        assert binding_writes(c) == [(5, Z5_GAMEPAD), (8, Z8_GAMEPAD)]   # auto starts in Gamepad
    run(go())


def test_apply_controller_writes_bindings_right_after_the_mode(tmp_path):
    async def go():
        c = FakeClient()
        s = settings(tmp_path, bindings=dict(CHOSEN))
        seq = []
        for mode in ("gamepad", "desktop", "gamepad"):        # Review Focus 3
            c.calls.clear()
            r = await controls.apply_controller(c, s, mode)
            assert r["ok"] and r["warning"] == ""
            assert [x[0] for x in c.writes()] == ["set_controller_mode", "set_bindings", "set_bindings",
                                                  "set_vibration"]
            seq.append(binding_writes(c))
        assert seq == [[(5, Z5_GAMEPAD), (8, Z8_GAMEPAD)], [(5, Z5_DESKTOP), (8, Z8_DESKTOP)],
                       [(5, Z5_GAMEPAD), (8, Z8_GAMEPAD)]]
        assert s.bindings == CHOSEN
    run(go())


def test_apply_controller_skips_bindings_when_the_mode_failed(tmp_path):
    async def go():
        c = FakeClient()
        c.handlers["set_controller_mode"] = handler(fail("mode refused"))
        r = await controls.apply_controller(c, settings(tmp_path, bindings=dict(CHOSEN)), "desktop")
        assert not r["ok"]
        assert binding_writes(c) == []                         # desktop slots on a gamepad-mode pad: never
    run(go())


def test_reset_reply_clears_and_saves_bindings(tmp_path):
    for outcome, message in (("reset", RESET_MESSAGE), ("reset_failed", RESET_FAILED)):   # Review Focus 4
        async def go():
            c = FakeClient()
            c.bindings_reply = outcome
            s = settings(tmp_path, bindings=dict(CHOSEN), user_set=True)
            s.save()
            r = await controls.apply_controller(c, s, "gamepad")
            assert r["ok"] and r["warning"] == message          # the mode and the vibration landed
            assert binding_writes(c) == [(5, Z5_GAMEPAD)]       # stopped at the zone that lost the pad
            assert s.bindings == FACTORY
            assert Settings.load(s.path).bindings == FACTORY
            assert ("set_vibration", {"strength": 100}) in c.writes()
            c.calls.clear()
            c.bindings_reply = "ok"
            await controls.apply_controller(c, s, "gamepad")    # the next reapply writes nothing custom
            assert binding_writes(c) == []
        run(go())


def test_pad_not_seen_keeps_bindings_and_logs_once(tmp_path, caplog):
    async def go():
        c = FakeClient()
        c.bindings_reply = "not_seen"
        s = settings(tmp_path, bindings=dict(CHOSEN))
        for _ in range(3):
            r = await controls.apply_controller(c, s, "desktop")
            assert r["ok"] and r["warning"] == PAD_NOT_SEEN
            assert not controls.transport_failure(r)
        assert s.bindings == CHOSEN                            # not written, not a reset
        assert binding_writes(c) == [(5, Z5_DESKTOP)] * 3
        assert ("set_vibration", {"strength": 100}) in c.writes()
    caplog.set_level("INFO")
    run(go())
    assert sum(PAD_NOT_SEEN in rec.getMessage() for rec in caplog.records) == 1
