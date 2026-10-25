"""The Armoury Crate button setting's action list and the loop that keeps the helper told (armoury_button.py)."""
import asyncio
import logging

from fake_helper import FakeClient, fail, ok
from traction import armoury_button, bindings, controls
from traction.armoury_button import ArmouryButton

TRANSPORT = "The helper did not answer in time."


def test_actions_are_the_non_gamepad_list():
    expected = tuple(a[0] for a in bindings.ACTIONS if not a[2].startswith("01-") and a[0] != "touch_keyboard")
    assert armoury_button.ACTIONS == expected
    assert armoury_button.ACTIONS[0] == "nothing" and armoury_button.ACTIONS[-1] == "volume_down"
    assert len(armoury_button.ACTIONS) == 26


class FakeHelper:
    """A helper whose listener holds an action and forgets it at a restart."""

    def __init__(self, client):
        self.action = "nothing"
        client.handlers["set_button_action"] = self.set

    async def set(self, args):
        self.action = args["action"]
        return ok({"action": self.action, "running": self.action != "nothing"})

    def restart(self):
        self.action = "nothing"


class Steps:
    """A sleep the test releases one tick at a time."""

    def __init__(self):
        self.waiting = asyncio.Event()
        self.go = asyncio.Event()
        self.slept = []

    async def sleep(self, secs):
        self.slept.append(secs)
        self.waiting.set()
        await self.go.wait()
        self.go.clear()

    async def next_tick(self):
        """Lets the loop run one more tick and waits until it sleeps again."""
        self.waiting.clear()
        self.go.set()
        await asyncio.wait_for(self.waiting.wait(), 2.0)

    async def first_tick(self):
        await asyncio.wait_for(self.waiting.wait(), 2.0)


def button_calls(c):
    return [x for x in c.calls if x[0] == "set_button_action"]


def test_loop_resends_after_helper_restart():
    async def go():
        c = FakeClient()
        helper = FakeHelper(c)
        steps = Steps()
        chosen = ["screenshot"]
        b = ArmouryButton(c, lambda: chosen[0], poll=5.0, sleep=steps.sleep)
        b.start()
        await steps.first_tick()                                    # tick 1
        assert button_calls(c) == [("set_button_action", {"action": "screenshot"})]
        assert helper.action == "screenshot" and steps.slept == [5.0]
        helper.restart()                                            # the listener forgets
        await steps.next_tick()                                     # tick 2: told again
        assert button_calls(c) == [("set_button_action", {"action": "screenshot"})] * 2
        assert helper.action == "screenshot"
        await b.stop()
        assert b._task is None
    asyncio.run(go())


def test_loop_sends_nothing_when_nothing_is_chosen():
    async def go():
        c = FakeClient()
        FakeHelper(c)
        steps = Steps()
        b = ArmouryButton(c, lambda: "nothing", sleep=steps.sleep)
        b.start()
        await steps.first_tick()
        await steps.next_tick()
        await steps.next_tick()
        assert c.calls == []
        await b.stop()
    asyncio.run(go())


def test_a_failed_nothing_is_sent_again_until_it_lands():
    async def go():
        c = FakeClient()
        replies = [fail(TRANSPORT), ok({"action": "nothing", "running": False})]

        async def h(_args):
            return replies.pop(0) if len(replies) > 1 else replies[0]
        c.handlers["set_button_action"] = h
        steps = Steps()
        b = ArmouryButton(c, lambda: "nothing", sleep=steps.sleep)
        assert (await b.sync())["ok"] is False                     # the change to nothing failed on the way
        b.start()
        await steps.first_tick()                                    # the loop sends it again, it lands
        await steps.next_tick()                                     # then nothing more
        assert button_calls(c) == [("set_button_action", {"action": "nothing"})] * 2
        await b.stop()
    asyncio.run(go())


def test_failures_are_logged_once_per_message(caplog):
    async def go():
        c = FakeClient()
        replies = [fail(TRANSPORT), fail(TRANSPORT), fail("Refused: unknown button action 'x'."),
                   ok({"action": "esc", "running": True}), fail(TRANSPORT)]

        async def h(_args):
            return replies.pop(0)
        c.handlers["set_button_action"] = h
        b = ArmouryButton(c, lambda: "esc", logger=logging.getLogger("traction-test"))
        for _ in range(5):
            await b.sync()
    with caplog.at_level(logging.WARNING, logger="traction-test"):
        asyncio.run(go())
    logged = [r.getMessage() for r in caplog.records if "Armoury Crate button" in r.getMessage()]
    assert len(logged) == 3        # transport, the refusal, transport again after a success
    assert TRANSPORT in logged[0] and "unknown button action" in logged[1] and TRANSPORT in logged[2]


def test_no_call_while_an_armoury_switch_runs():
    async def go():
        c = FakeClient()
        FakeHelper(c)
        c.armoury_inflight = 1
        b = ArmouryButton(c, lambda: "esc")
        await b.tick()
        assert c.calls == []
        c.armoury_inflight = 0
        await b.tick()
        assert button_calls(c) == [("set_button_action", {"action": "esc"})]
    asyncio.run(go())


def test_no_call_while_a_bindings_write_runs():
    async def go():
        c = FakeClient()
        FakeHelper(c)
        b = ArmouryButton(c, lambda: "esc")
        controls._bindings_calls[0] += 1
        try:
            await b.tick()
            assert c.calls == []
        finally:
            controls._bindings_calls[0] -= 1
        await b.tick()
        assert button_calls(c) == [("set_button_action", {"action": "esc"})]
    asyncio.run(go())


def test_loop_call_waits_longer_than_the_panel_call():
    async def go():
        c = FakeClient()
        FakeHelper(c)
        b = ArmouryButton(c, lambda: "esc")
        await b.tick()                     # the loop: above the longest helper call (set_bindings, 20 s)
        await b.sync()                     # the panel: the default
        assert c.timeouts["set_button_action"] == [armoury_button.LOOP_TIMEOUT, 10.0]
        assert armoury_button.LOOP_TIMEOUT == 25.0 and armoury_button.LOOP_TIMEOUT > controls.BINDINGS_TIMEOUT
    asyncio.run(go())


def test_listener_status_is_logged_once_per_change(caplog):
    async def go():
        c = FakeClient()
        replies = [
            ok({"action": "esc", "running": True, "open": False, "last_error": ""}),
            ok({"action": "esc", "running": True, "open": False, "last_error": ""}),
            ok({"action": "esc", "running": True, "open": True, "last_error": ""}),
            ok({"action": "esc", "running": True, "open": True, "last_error": ""}),
            ok({"action": "esc", "running": True, "open": False, "last_error": "read failed: gone"}),
            ok({"action": "esc", "running": True, "open": False, "last_error": "read failed: gone"}),
            fail(TRANSPORT),
            ok({"action": "esc", "running": True, "open": False, "last_error": "read failed: gone"}),
        ]

        async def h(_args):
            return replies.pop(0)
        c.handlers["set_button_action"] = h
        b = ArmouryButton(c, lambda: "esc", logger=logging.getLogger("traction-test"))
        for _ in range(8):
            await b.tick()
    with caplog.at_level(logging.INFO, logger="traction-test"):
        asyncio.run(go())
    status = [r for r in caplog.records if r.levelno == logging.INFO and "Armoury Crate button" in r.getMessage()]
    assert len(status) == 3        # first reply, opened, read error; a failed reply in between does not re-log
    assert "open False" in status[0].getMessage() and "open True" in status[1].getMessage()
    assert "read failed: gone" in status[2].getMessage()
