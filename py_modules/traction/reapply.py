"""Traction's reapply: the controller steps of Overdrive ba0307a's reapply (the controller forgets its mode and
vibration on sleep).

The loop itself (polling for resume, AC changes and the shared Armoury Crate record, the shared lock and generation,
retries) is ReapplierCore in reapply_core.py, shared with Overdrive.
"""
import logging
import time
from typing import Callable, Optional

from .controls import apply_controller, apply_press_bindings, transport_failure
from .reapply_core import POLL, Dropped, ReapplierCore, _StepClient
from .settings import Settings

# After wake the controller (or Windows' view of the pad) can take a while to come back. A reapply that finds no
# controller, or whose bindings write is refused because Windows does not see the pad, is tried again at the next
# poll, at most this often in a row per trigger (12 x 5 s, about a minute).
MISS_RETRIES = 12
PAD_NOT_SEEN = "Windows does not see the gamepad"   # the helper's refusal before a watched bindings write
NOT_FOUND = "The controller was not found, so its settings were not applied."


class _TimedStepClient(_StepClient):
    """The shared _StepClient (same lock, generation and Armoury-busy checks) that also passes the call's timeout on:
    set_bindings needs 20 s (pad polling plus the factory reset), the shared one would use the 10 s default."""

    async def call(self, cmd: str, args: Optional[dict] = None, timeout: float = 10.0) -> dict:
        r = self._r
        async with r.lock:
            if self._gen != r.generation or r._busy():
                raise Dropped()
            reply = await r.client.call(cmd, args or {}, timeout)
        self.transport |= r._is_transport_failure(reply)
        return reply


class Reapplier(ReapplierCore):
    """Writes the stored controller mode and grip vibration when a controller is found."""

    LOGGER_NAME = "traction"
    NOTHING_CHOSEN = "Reapply skipped: no Traction settings chosen yet"
    BLOCKED = "Reapply skipped: an Overdrive older than 0.2.0 drives the controller"

    @property
    def SKIP_MESSAGE(self) -> str:   # what ReapplierCore logs when _should_apply is False
        return self.BLOCKED if self._blocked() else self.NOTHING_CHOSEN

    def __init__(self, client, settings: Settings, clock=time, power_source: Optional[Callable] = None,
                 poll: float = POLL, logger: Optional[logging.Logger] = None, record=None,
                 wake_source: Optional[Callable[[], Optional[int]]] = None):
        super().__init__(client, clock=clock, power_source=power_source, logger=logger, poll=poll, record=record)
        self.settings = settings
        # main.py: wake_win32.last_wake_id. A new wake record is a trigger (Modern Standby fools the clock check).
        self.wake_source = wake_source
        self._wake: Optional[int] = None   # the newest wake record seen
        # main.py: True while an Overdrive older than 0.2.0 drives the controller (nothing is written then)
        self.blocked: Optional[Callable[[], bool]] = None
        # main.py: True while the Library button reports may be written (Armoury Crate is not running and no old
        # Overdrive drives the controller). None: allowed (no Armoury Crate switch to ask).
        self.library_allowed: Optional[Callable[[], bool]] = None
        self._reset_seen = False   # a reapply's bindings write ended in the helper's factory reset
        self._missed = ""          # this reapply's pad-not-seen refusal (added to `warning`), else ""
        self._retry_miss = False   # this reapply found no controller or the pad was not seen: retry at the next poll
        self._misses = 0           # consecutive reapplies that missed since the last trigger or controller write

    async def apply_all(self) -> bool:
        """ReapplierCore.apply_all; after a factory reset by the helper (it wrote Gamepad and vibration 100) the next
        tick reapplies once more, which writes the stored mode and vibration and nothing custom (the bindings are
        cleared by then). A reapply that missed the controller (_note_miss) is retried the same way. Both are set after
        the core's own rerun bookkeeping, which would clear them."""
        self._reset_seen = False
        self._missed = ""
        self._retry_miss = False
        try:
            return await super().apply_all()
        finally:
            if self._reset_seen:
                self._reset_seen = False
                self.rerun = True
            if self._retry_miss:
                self._retry_miss = False
                self.rerun = True
            if self._missed:   # shown in the panel (the pad-not-seen refusal was shown before the retries, too)
                self.warning = " ".join(w for w in (self.warning, self._missed) if w)
                self._missed = ""

    def prime(self) -> None:
        super().prime()
        if self.wake_source is not None:
            self._wake = self.wake_source()
            if self._wake is None:
                self.log.warning("Could not read Windows' wake events: wakes from standby are not noticed")
            else:
                self.log.info(f"Watching for wake events (last one: record {self._wake})")

    def _woke(self) -> bool:
        """A wake record newer than the last one seen (None, an unreadable log, keeps the last one)."""
        if self.wake_source is None:
            return False
        wake = self.wake_source()
        if wake is None:
            return False
        woke = self._wake is not None and wake != self._wake
        self._wake = wake
        return woke

    def _triggers(self) -> "list[str]":
        reasons = super()._triggers()
        if self._woke() and "resume" not in reasons:
            reasons.append("wake")
        if reasons:   # a new trigger (resume, AC change, Armoury switched) gets its own run of retries
            self._misses = 0
        return reasons

    def _note_miss(self, message: str, show: bool) -> None:
        """Counts a reapply that could not reach the controller. Below MISS_RETRIES it is retried at the next poll
        (logged as info); the last one logs one warning; after that nothing is retried until the next trigger.
        `show`: the message also goes into the panel warning."""
        self._misses += 1
        if show:
            self._missed = message
        if self._misses < MISS_RETRIES:
            self._retry_miss = True
            self.log.info(f"{message} Trying again at the next poll ({self._misses}/{MISS_RETRIES})")
        elif self._misses == MISS_RETRIES:
            self.log.warning(f"{message} Gave up after {MISS_RETRIES} tries, until the next sleep, wake or AC "
                             f"change.")

    def _blocked(self) -> bool:
        return bool(self.blocked is not None and self.blocked())

    def _library_allowed(self) -> bool:
        return bool(self.library_allowed is None or self.library_allowed())

    def _should_apply(self) -> bool:
        return self.settings.user_set and not self._blocked()

    def _is_transport_failure(self, reply: dict) -> bool:
        return transport_failure(reply)

    async def _apply_steps(self, gen: int) -> "tuple[list[str], bool, bool]":
        problems = []
        # No controller found means nothing to write (just after wake: tried again at the next poll, see _note_miss).
        info = await self._step(gen, "controller_info", {})
        transport = transport_failure(info)
        data = info.get("data") if info.get("ok") else None
        written = False
        if isinstance(data, dict) and data.get("found"):
            step_client = _TimedStepClient(self, gen)
            r = await apply_controller(step_client, self.settings, logger=self.log)
            transport |= step_client.transport
            if not step_client.transport:
                # The controller forgets the Library button's reports on sleep: rewritten every time while chosen.
                lib = await apply_press_bindings(step_client, self.settings, self._library_allowed(), logger=self.log)
                transport |= step_client.transport
                if not lib.get("ok"):
                    problems.append(lib.get("message") or "The Library button was not applied.")
            if r.get("reset"):
                self._reset_seen = True
            warning = r.get("warning") or ""
            if r.get("ok"):
                written = True
                if warning.startswith(PAD_NOT_SEEN) and not r.get("reset"):   # nothing written yet: try again
                    self._note_miss(warning, show=True)
                    return problems, transport, written
                if warning:   # the buttons were reset
                    problems.append(warning)
            else:
                problems.append(r.get("message") or "The controller settings were not applied.")
            self._misses = 0
        elif not transport:   # just after wake the controller may not be back yet
            self._note_miss(NOT_FOUND, show=False)
        return problems, transport, written
