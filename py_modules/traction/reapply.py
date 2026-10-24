"""Traction's reapply: the controller steps of Overdrive ba0307a's reapply (the controller forgets its mode and
vibration on sleep).

The loop itself (polling for resume, AC changes and the shared Armoury Crate record, the shared lock and generation,
retries) is ReapplierCore in reapply_core.py, shared with Overdrive.
"""
import logging
import time
from typing import Callable, Optional

from .controls import apply_controller, transport_failure
from .reapply_core import POLL, Dropped, ReapplierCore, _StepClient
from .settings import Settings


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
                 poll: float = POLL, logger: Optional[logging.Logger] = None, record=None):
        super().__init__(client, clock=clock, power_source=power_source, logger=logger, poll=poll, record=record)
        self.settings = settings
        # main.py: True while an Overdrive older than 0.2.0 drives the controller (nothing is written then)
        self.blocked: Optional[Callable[[], bool]] = None

    def _blocked(self) -> bool:
        return bool(self.blocked is not None and self.blocked())

    def _should_apply(self) -> bool:
        return self.settings.user_set and not self._blocked()

    def _is_transport_failure(self, reply: dict) -> bool:
        return transport_failure(reply)

    async def _apply_steps(self, gen: int) -> "tuple[list[str], bool, bool]":
        problems = []
        # No controller found means nothing to write.
        info = await self._step(gen, "controller_info", {})
        transport = transport_failure(info)
        data = info.get("data") if info.get("ok") else None
        written = False
        if isinstance(data, dict) and data.get("found"):
            step_client = _TimedStepClient(self, gen)
            r = await apply_controller(step_client, self.settings, logger=self.log)
            transport |= step_client.transport
            if r.get("ok"):
                written = True
                if r.get("warning"):   # the buttons were not written (pad not seen) or were reset
                    problems.append(r["warning"])
            else:
                problems.append(r.get("message") or "The controller settings were not applied.")
        return problems, transport, written
