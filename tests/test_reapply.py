"""Traction's reapply: the controller steps of Overdrive ba0307a's reapply (tests ported from its test_reapply.py)."""
import asyncio

from fake_helper import FakeClient, ok
from traction import bindings
from traction.armoury_record import ArmouryRecord
from traction.reapply import Reapplier
from traction.settings import Settings

RESTARTED = "Traction helper restarted, try again"


class Clock:
    def __init__(self):
        self.wall = 1_700_000_000.0
        self.mono = 5_000.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def step(self, wall, mono=None):
        self.wall += wall
        self.mono += wall if mono is None else mono


class Power:
    def __init__(self, value=True):
        self.value = value

    def __call__(self):
        return self.value


def make(tmp_path, user_set=True, **fields):
    s = Settings.load(str(tmp_path / "settings.json"))
    s.user_set = user_set
    for k, v in fields.items():
        setattr(s, k, v)
    return s


def run(coro):
    return asyncio.run(coro)


def _controller_client(found=True):
    c = FakeClient()

    async def info(args):
        return ok({"found": found, "pid": "0x1B4C", "xbox": False})
    c.handlers["controller_info"] = info
    return c


def test_reapply_includes_controller(tmp_path):
    async def go():
        c = _controller_client()
        s = make(tmp_path, controller_mode="desktop", grip_vibration=False)
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        assert await r.apply_all() is True
        assert c.calls == [("controller_info", {}), ("set_controller_mode", {"mode": "desktop"}),
                           ("set_vibration", {"strength": 0})]
        assert r.warning == ""
        c.calls.clear()
        s.controller_mode, s.grip_vibration = "auto", True     # Auto starts in Gamepad
        await r.apply_all()
        assert c.writes() == [("set_controller_mode", {"mode": "gamepad"}), ("set_vibration", {"strength": 100})]
    run(go())


def test_untouched_install_only_reads(tmp_path):
    async def go():
        c = _controller_client()
        await Reapplier(c, make(tmp_path, user_set=False), clock=Clock(), power_source=Power()).apply_all()
        assert c.writes() == [] and c.calls == []
    run(go())


def test_reapply_skips_controller_when_none_found(tmp_path):
    async def go():
        c = _controller_client(found=False)
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power())
        await r.apply_all()
        assert not any(cmd in ("set_controller_mode", "set_vibration") for cmd, _ in c.calls)
        assert r.warning == ""
    run(go())


def test_reapply_controller_failure_joins_warnings(tmp_path):
    async def go():
        c = _controller_client()

        async def refuse(args):
            return {"id": 1, "ok": False, "message": "The controller refused the mode.", "data": None}
        c.handlers["set_controller_mode"] = refuse
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power())
        await r.apply_all()
        assert "controller refused the mode" in r.warning
        assert ("set_vibration", {"strength": 100}) in c.writes()
        assert r.rerun is False                       # a device refusal is not retried
    run(go())


def test_user_change_drops_controller_step(tmp_path):
    async def go():
        c = _controller_client()
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power())
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_info(args):
            entered.set()
            await release.wait()
            return ok({"found": True, "pid": "0x1B4C", "xbox": False})
        c.handlers["controller_info"] = slow_info
        task = asyncio.ensure_future(r.apply_all())
        await entered.wait()
        r.generation += 1                      # a user change arrived meanwhile
        release.set()
        assert await task is False
        assert not any(cmd in ("set_controller_mode", "set_vibration") for cmd, _ in c.calls)
        assert r.rerun is True
    run(go())


def test_controller_restart_schedules_retry(tmp_path):
    async def go():
        c = _controller_client()

        async def restarted(args):
            return {"id": 1, "ok": False, "message": RESTARTED, "data": None}
        c.handlers["set_controller_mode"] = restarted
        c.handlers["set_vibration"] = restarted
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power())
        await r.apply_all()
        assert r.rerun is True
        assert r.warning.count(RESTARTED) == 1          # stopped after the first transport failure
        assert not any(cmd == "set_vibration" for cmd, _ in c.calls)
    run(go())


def test_controller_info_timeout_is_retried(tmp_path):
    async def go():
        c = FakeClient()

        async def timeout(args):
            return {"id": None, "ok": False, "message": "Traction helper did not answer in 10 s.", "data": None}
        c.handlers["controller_info"] = timeout
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power())
        await r.apply_all()
        assert r.rerun is True and c.writes() == []
    run(go())


def test_reapply_on_ac_change_and_resume(tmp_path):
    async def go():
        c = _controller_client()
        power, clock = Power(True), Clock()
        r = Reapplier(c, make(tmp_path), clock=clock, power_source=power)
        r.prime()
        assert await r.tick() is False
        power.value = False
        assert await r.tick() is True
        assert [cmd for cmd, _ in c.writes()] == ["set_controller_mode", "set_vibration"]
        clock.step(5)
        assert await r.tick() is False
        clock.step(3600, mono=5)       # the PC slept: the controller forgot its mode and vibration
        assert await r.tick() is True
        assert len(c.writes()) == 4
    run(go())


def test_no_reapply_while_armoury_call_runs(tmp_path, caplog):
    async def go():
        c = _controller_client()
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power())
        c.armoury_inflight = 1
        with caplog.at_level("INFO", logger="traction"):
            assert await r.apply_all() is False
        assert c.calls == [] and r.rerun is True
        assert "Reapply deferred while Armoury Crate services are being switched" in caplog.text
        c.armoury_inflight = 0
        assert await r.tick() is True
        assert c.writes() and r.rerun is False
    run(go())


def test_reapply_on_record_flip(tmp_path, caplog):
    async def go():
        folder = str(tmp_path / "armoury")
        c = _controller_client()
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power(), record=ArmouryRecord(folder))
        r.prime()
        assert await r.tick() is False
        other = ArmouryRecord(folder)              # Overdrive (or Traction's own switch) stops Armoury Crate
        other.replaced, other.recorded = True, {"ArmouryCrateService": "Automatic"}
        other.save()
        with caplog.at_level("INFO", logger="traction"):
            assert await r.tick() is True
        assert "Reapplying (Armoury switched" in caplog.text
        assert [cmd for cmd, _ in c.writes()] == ["set_controller_mode", "set_vibration"]
        assert await r.tick() is False
    run(go())


def test_skip_message_names_traction(tmp_path, caplog):
    async def go():
        r = Reapplier(FakeClient(), make(tmp_path, user_set=False), clock=Clock(), power_source=Power())
        with caplog.at_level("INFO", logger="traction"):
            await r.apply_all()
        assert "Reapply skipped: no Traction settings chosen yet" in caplog.text
    run(go())


# ---------- button bindings ----------

from fake_helper import PAD_NOT_SEEN, RESET_MESSAGE  # noqa: E402

# The v1 mapping (M1 as B, Shift+A = Screenshot) as v2 loads it: M1's switch off, B its Primary in both sets.
CHOSEN = bindings.clean({"back_left": "shift", "back_right": "b", "combos": {"a": "screenshot"}})


def test_reapply_writes_bindings_with_the_long_timeout(tmp_path):
    async def go():
        c = _controller_client()
        s = make(tmp_path, bindings=bindings.clean(CHOSEN))
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        assert await r.apply_all() is True
        assert [x[0] for x in c.writes()] == ["set_controller_mode", "set_bindings", "set_bindings",
                                              "set_vibration"]
        assert c.timeouts["set_bindings"] == [20.0, 20.0]      # the step client keeps the timeout
        assert r.warning == ""
    run(go())


def test_reapply_warns_when_the_pad_is_not_seen_or_reset(tmp_path):
    async def go():
        c = _controller_client()
        c.bindings_reply = "not_seen"
        s = make(tmp_path, bindings=bindings.clean(CHOSEN))
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        await r.apply_all()
        assert r.warning == PAD_NOT_SEEN and r.rerun is True    # nothing written: tried again at the next poll
        assert s.bindings == CHOSEN
        c.bindings_reply = "reset"
        await r.apply_all()
        assert r.warning == RESET_MESSAGE
        assert s.bindings == bindings.clean(None)               # both sets cleared, both switches on
        c.calls.clear()
        c.bindings_reply = "ok"
        await r.apply_all()
        assert [x[0] for x in c.writes()] == ["set_controller_mode", "set_vibration"]
        assert r.warning == ""
    run(go())


def test_reapply_reset_reply_reruns_with_the_owners_vibration(tmp_path):
    # I3: the factory set wrote vibration 100; the next tick writes the owner's 0 (and nothing custom).
    async def go():
        c = _controller_client()
        c.bindings_reply = "reset"
        s = make(tmp_path, bindings=bindings.clean(CHOSEN), grip_vibration=False)
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        assert await r.apply_all() is True
        assert r.rerun is True
        c.calls.clear()
        c.bindings_reply = "ok"
        assert await r.tick() is True
        assert ("set_vibration", {"strength": 0}) in c.writes()
        assert [x for x in c.writes() if x[0] == "set_bindings"] == []
        assert r.rerun is False
    run(go())


# ---------- after wake: the controller (or the pad) is not back yet ----------

def _waking_client(found):
    """controller_info answers found=found[0], then found[1], ... (the last one from then on)."""
    c = FakeClient()
    answers = list(found)

    async def info(args):
        value = answers.pop(0) if len(answers) > 1 else answers[0]
        return ok({"found": value, "pid": "0x1B4C", "xbox": False})
    c.handlers["controller_info"] = info
    return c


def _triggered(tmp_path, c, **fields):
    power = Power(True)
    r = Reapplier(c, make(tmp_path, **fields), clock=Clock(), power_source=power)
    r.prime()
    power.value = False                    # the wake's trigger (AC off)
    return r, power


def test_controller_not_found_after_wake_is_retried(tmp_path):
    async def go():
        c = _waking_client([False, True])
        r, _ = _triggered(tmp_path, c, bindings=bindings.clean(CHOSEN))
        assert await r.tick() is True
        assert c.writes() == [] and r.rerun is True
        assert await r.tick() is True      # the next poll tries again: the controller is back
        assert [x[0] for x in c.writes()] == ["set_controller_mode", "set_bindings", "set_bindings",
                                              "set_vibration"]
        assert r.rerun is False and r.warning == ""
        assert await r.tick() is False
    run(go())


def test_pad_not_seen_after_wake_is_retried(tmp_path):
    async def go():
        c = _controller_client()
        c.bindings_reply = "not_seen"
        r, _ = _triggered(tmp_path, c, bindings=bindings.clean(CHOSEN))
        assert await r.tick() is True
        assert r.rerun is True
        c.calls.clear()
        c.bindings_reply = "ok"
        assert await r.tick() is True
        assert [x[0] for x in c.writes()] == ["set_controller_mode", "set_bindings", "set_bindings",
                                              "set_vibration"]
        assert r.rerun is False and r.warning == ""
    run(go())


def test_retries_stop_after_twelve_misses(tmp_path, caplog):
    async def go():
        c = _waking_client([False])
        r, power = _triggered(tmp_path, c)
        with caplog.at_level("INFO", logger="traction"):
            runs = 0
            while await r.tick():
                runs += 1
                assert runs <= 12
        assert runs == 12 and r.rerun is False and c.writes() == []
        gave_up = [x for x in caplog.records if x.levelname == "WARNING"]
        assert len(gave_up) == 1 and "not found" in gave_up[0].getMessage()
        assert await r.tick() is False
        # A success resets the count; so does the next trigger.
        power.value = True
        assert await r.tick() is True and r.rerun is True
    run(go())


def test_success_resets_the_miss_count(tmp_path):
    async def go():
        c = _waking_client([False] * 11 + [True, False])
        r, _ = _triggered(tmp_path, c)
        for _ in range(12):                # 11 misses, then a write
            assert await r.tick() is True
        assert c.writes() and r.rerun is False
        r.rerun = True                     # e.g. a later redo misses again: it is retried, not given up
        assert await r.tick() is True and r.rerun is True
    run(go())


def test_old_overdrive_gets_no_retries(tmp_path):
    async def go():
        c = _waking_client([False])
        r, _ = _triggered(tmp_path, c)
        r.blocked = lambda: True
        assert await r.tick() is True
        assert r.rerun is False and c.writes() == [] and c.calls == []
        assert await r.tick() is False
    run(go())


def test_reapply_on_standby_wake(tmp_path):
    """Modern Standby: the clocks keep running and the AC line stays the same, but Windows logs each wake; a new
    wake record is a trigger. An unreadable log (None) is no trigger and keeps the last record seen."""
    async def go():
        c = _controller_client()
        wake = Power(13034)
        r = Reapplier(c, make(tmp_path), clock=Clock(), power_source=Power(), wake_source=wake)
        r.prime()
        assert await r.tick() is False
        wake.value = 13050                 # the Ally woke from standby
        assert await r.tick() is True
        assert [cmd for cmd, _ in c.writes()] == ["set_controller_mode", "set_vibration"]
        assert await r.tick() is False
        wake.value = None
        assert await r.tick() is False
        wake.value = 13050
        assert await r.tick() is False
    run(go())


# ---------- the Library button ----------

def press_calls(c):
    return [x for x in c.calls if x[0] == "set_press_bindings"]


def test_reapply_writes_press_bindings_when_chosen(tmp_path):
    async def go():
        c = _controller_client()
        s = make(tmp_path, library={"single": "asus_task_manager", "long": "armoury"})
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        r.library_allowed = lambda: True
        assert await r.apply_all() is True
        # after the controller writes; the registry is unreadable in tests: Armoury Crate's defaults elsewhere
        assert c.writes() == [("set_controller_mode", {"mode": "gamepad"}), ("set_vibration", {"strength": 100}),
                              ("set_press_bindings", {
                                  "single": ["05-00-1A-00-00-00-00-00-00", "05-00-17-00-00-00-00-00-00"],
                                  "long": ["05-00-16-00-00-00-00-00-00", "05-00-04-00-00-00-00-00-00"]})]
        assert r.warning == ""
        c.calls.clear()
        await r.apply_all()   # every reapply while chosen
        assert len(press_calls(c)) == 1
        # no controller found: nothing
        c2 = _controller_client(found=False)
        await Reapplier(c2, s, clock=Clock(), power_source=Power()).apply_all()
        assert press_calls(c2) == []
    run(go())


def test_reapply_no_press_bindings_while_armoury_runs(tmp_path):
    async def go():
        c = _controller_client()
        s = make(tmp_path, library={"single": "esc", "long": "esc"}, library_written=True)
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        r.library_allowed = lambda: False
        await r.apply_all()
        assert press_calls(c) == [] and c.writes() != []
    run(go())


def test_reapply_reset_restores_once(tmp_path):
    async def go():
        c = _controller_client()
        s = make(tmp_path, library_written=True)
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        r.library_allowed = lambda: True
        await r.apply_all()
        assert len(press_calls(c)) == 1 and s.library_written is False
        await r.apply_all()
        await r.apply_all()
        assert len(press_calls(c)) == 1
    run(go())


def test_reapply_reports_a_press_bindings_refusal(tmp_path):
    async def go():
        c = _controller_client()

        async def refuse(args):
            return {"id": 1, "ok": False, "message": "Refused: unknown press binding 'x'.", "data": None}
        c.handlers["set_press_bindings"] = refuse
        s = make(tmp_path, library={"single": "esc", "long": "armoury"})
        r = Reapplier(c, s, clock=Clock(), power_source=Power())
        await r.apply_all()
        assert r.warning == "Refused: unknown press binding 'x'."
    run(go())
