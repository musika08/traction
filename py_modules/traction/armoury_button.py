"""The Armoury Crate button (spec section 6, Part B): the action a single press runs, kept in the helper.

The helper's reader (helper/src/ButtonListener.cs) starts with "nothing" and forgets the action when it restarts
(crash, hang kill). So the action is sent when it changes (set_armoury_button) and again every POLL seconds while it is
not "nothing" (the helper treats the same action again as a no-op): a restarted helper is told within about POLL
seconds without touching the panel. A "nothing" that did not land (transport failure) is sent again by the loop until
it does. No call is made while an Armoury Crate switch runs (the single-threaded helper is busy for minutes; a call
sent then would time out). A refusal or transport failure is logged once per distinct message.
"""
import asyncio
import logging
from typing import Callable, Optional

from . import bindings

NOTHING = "nothing"
POLL = 5.0
# The actions a press can run: bindings.ACTIONS order, no gamepad buttons (codes 01-..) and no touch keyboard. The same
# ids, in this order, as ButtonActions.Ids in helper/src/ButtonActions.cs.
ACTIONS = tuple(a[0] for a in bindings.ACTIONS if not a[2].startswith("01-") and a[0] != "touch_keyboard")


class ArmouryButton:
    def __init__(self, client, get_action: Callable[[], str], poll: float = POLL, sleep=asyncio.sleep,
                 logger: Optional[logging.Logger] = None):
        self.client = client
        self.get_action = get_action
        self.poll = poll
        self.sleep = sleep
        self.log = logger or logging.getLogger("traction")
        self._task: Optional[asyncio.Task] = None
        self._told: Optional[str] = NOTHING   # the action the helper last accepted; None = unknown (a send failed)
        self._logged: Optional[str] = None    # the last failure logged (each distinct message once)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def sync(self) -> dict:
        """One set_button_action with the current action; returns the helper's reply."""
        action = self.get_action()
        r = await self.client.call("set_button_action", {"action": action})
        if r.get("ok"):
            self._told, self._logged = action, None
            return r
        self._told = None
        message = str(r.get("message") or "no reply")
        if message != self._logged:
            self._logged = message
            self.log.warning(f"Traction: the Armoury Crate button action '{action}' was not set: {message}")
        return r

    async def tick(self) -> None:
        """One loop step: sync while an action is set, or while a "nothing" has not landed yet."""
        if getattr(self.client, "busy", False):
            return
        if self.get_action() != NOTHING or self._told != NOTHING:
            await self.sync()

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:   # never ends the loop
                message = f"error: {e}"
                if message != self._logged:
                    self._logged = message
                    self.log.warning(f"Traction: the Armoury Crate button loop failed: {e}")
            await self.sleep(self.poll)
