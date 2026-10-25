# Traction Part B: Armoury Crate button (single press) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A press of the Armoury Crate button (right side, below Menu) runs one action the owner picks in Traction's panel.

**Architecture:** The helper gets a background reader on the controller's 0x5A collection (shared read, read only). On the report `5A EC` it sends the chosen action with SendInput. main.py stores the choice and keeps the helper told (on change, and every 5 s while an action is set, so a restarted helper picks it up again). The panel gets one inline picker row.

**Tech Stack:** C# 5 / .NET Framework 4.8 via in-box csc (helper, house test runner), Python 3 (pytest), TypeScript/React with `@decky/ui`.

**Spec:** `X:\Projects\Decky Loader\plugins\traction\docs\specs\2026-10-24-traction-button-mapping-design.md` section 6 (Part B). Probe: `docs/notes/2026-10-24-remap-probe.md`, "Part B probe".

## Global Constraints

- Repo `X:\Projects\Decky Loader\plugins\traction`, branch main. Commit as musika08 / `225994527+musika08@users.noreply.github.com` (check `git config user.email`); **no Co-Authored-By or any Claude attribution**. Never push.
- Do not edit the files shared with Overdrive: `helper/src/shared/*` (AsusHid.cs, SharedHardware.cs, ProtocolKit.cs, ...), `py_modules/traction/helper_client.py`, `reapply_core.py`, `settings_file.py`, `armoury_record.py`, `armoury_switch.py`, `device.py`. Use their public members only (`Win32HidBus.List()`, `AsusHid.Select(...)`, `ProtocolKit.Reply/GetString`).
- Trigger: input report byte 0 = `0x5A`, byte 1 = `0xEC` (236), on the collection `AsusHid.Select` returns. Nothing else triggers. A trigger within 0.5 s of the last one that fired is ignored.
- Action ids (exactly these, in this order, labels from `bindings.ACTIONS`): `nothing, mouse_left, mouse_right, mouse_middle, scroll_up, scroll_down, esc, enter, tab, backspace, space, up, down, left, right, page_up, page_down, win, show_desktop, screenshot, task_manager, close_window, alt_tab, win_tab, volume_up, volume_down`. No gamepad buttons, no `touch_keyboard`.
- Input per action (virtual keys; arrows and Page Up/Down are extended keys): Esc 0x1B, Enter 0x0D, Tab 0x09, Backspace 0x08, Space 0x20, Up 0x26, Down 0x28, Left 0x25, Right 0x27, Page Up 0x21, Page Down 0x22, Windows 0x5B; Show desktop = Win+D (0x5B, 0x44); Screenshot = Win+Shift+S (0x5B, 0x10, 0x53); Task Manager = Ctrl+Shift+Esc (0x11, 0x10, 0x1B); Close window = Alt+F4 (0x12, 0x73); Alt+Tab (0x12, 0x09); Win+Tab (0x5B, 0x09); Volume up 0xAF, Volume down 0xAE; mouse left/right/middle = down then up; scroll up/down = one wheel step of +120 / -120. Keys of a combo go down in the listed order and up in reverse.
- Setting: `settings.json` key `armoury_button`, default `"nothing"`; one setting for both controller modes.
- Copy: row label `Armoury Crate button`; note (shown only when an action is set): `If Armoury Crate also has an action for this button, both run. Set it to nothing in Armoury Crate's Shortcuts & Key Binding.`
- Helper: reopen the collection every 2 s after a failed open or read (sleep, unplug), until the action is set to `nothing`.

## Rulings made while planning

- Ruling: the Armoury Crate button works while an Overdrive older than 0.2.0 blocks Traction's controller writes (it writes nothing to the controller) — cost if wrong: one `if self._old` check.
- Owner decision (2026-10-25): "Reset all buttons" also sets the Armoury Crate button back to `nothing` (its original behaviour: Traction stops handling it). Traction never changes Armoury Crate's own settings.
- Ruling: main.py resends the action every 5 s while it is not `nothing` (the helper treats the same action as a no-op), instead of a restart hook in the shared HelperClient — cost if wrong: one cheap pipe call per 5 s.

## Review Focus

1. The helper restarts (crash, hang kill): the button works again within about 5 s without touching the panel. Task 2.
2. Sleep and wake: the read fails, the reader reopens and the next press works. Task 1.
3. Choosing Nothing: the reader thread ends and no further presses act. Task 1.
4. A settings file with an unknown or non-string `armoury_button`: loads as `nothing`, never fails. Task 2.
5. A long hold (press `5A EC`, then `5A EC` again 6 s later at the release): two actions (the spec's known limit), but two reports 0.2 s apart give one. Task 1.

---

### Task 1: helper reader, actions and `set_button_action`

**Files:**
- Create: `helper/src/ButtonActions.cs`, `helper/src/ButtonListener.cs`
- Modify: `helper/src/TractionCore.cs` (command table, dispatch, `ButtonListener` property), `helper/src/HelperMain.cs` (wire the real listener)
- Test: `helper/tests/HelperTests.cs`, `helper/tests/FakeHardware.cs`

**Interfaces (produces):**
- `public struct InputStep { public bool Mouse; public ushort Vk; public bool Up; public bool Extended; public uint MouseFlags; public int Wheel; }`
- `public static class ButtonActions { public static readonly string[] Ids; public static IList<InputStep> Steps(string id); public static IList<string> Describe(string id); }`. `Describe` gives one string per step for tests: `"down 0x5B"`, `"up 0x5B"`, `"mouse left down"`, `"mouse left up"`, `"wheel 120"`. `Steps("nothing")` is empty; unknown id -> null.
- `public interface IInputSender { void Send(IList<InputStep> steps); }`; `Win32InputSender` (SendInput, KEYEVENTF_EXTENDEDKEY for extended keys).
- `public interface IReportSource { bool Open(); byte[] Read(); void Close(); }`; `HidReportSource` opens `AsusHid.Select(new Win32HidBus().List()).Path` with GENERIC_READ and FILE_SHARE_READ|FILE_SHARE_WRITE, reads `InputReportByteLength` bytes (HidP_GetCaps); `Read` throws `IOException` when the device is gone; `Close` cancels a pending read (CancelIoEx) and closes the handle.
- `public sealed class ButtonListener` with ctor `(IReportSource source, IInputSender sender, Func<DateTime> clock, Action<int> wait)`; `string Action { get; }`; `void SetAction(string id)` (starts the reader thread for an action, stops it for `nothing`, same id = no-op); `bool Handle(byte[] report)` (true when it fired; used by the thread and by tests); `bool Running { get; }`; `int Opens { get; }`.
- Helper command `set_button_action {action: string}` -> reply data `{"action": id, "running": bool}`; unknown id -> `Refused: unknown button action '<id>'.`; `ButtonListener` null -> `ControllerUnavailable`. Not in `ReadCommands`.

- [ ] **Step 1: tests in `HelperTests.cs`** (house runner, fakes in `FakeHardware.cs`: `FakeReportSource` with a queue of reports and exceptions, `FakeInputSender` recording `Describe`-style strings, a settable clock, `wait` that records the ms):
  - `ButtonActions_IdsMatchPlan`: `Ids` equals the Global Constraints list in order.
  - `ButtonActions_Screenshot`: `Describe("screenshot")` = `down 0x5B, down 0x10, down 0x53, up 0x53, up 0x10, up 0x5B`.
  - `ButtonActions_ArrowIsExtended`: `Steps("up")` = down/up of 0x26 with `Extended` true; `Steps("enter")` not extended.
  - `ButtonActions_ScrollDown`: `Describe("scroll_down")` = `wheel -120`; `Steps("nothing")` empty; `Steps("a")` null.
  - `Listener_OnlyEcFires`: `Handle({0x5A,0xEC})` true and one send; `{0x5A,0xA6}`, `{0x5A,0x00}`, `{0x5D,0xEC}`, `{0x5A}` false.
  - `Listener_Bounce`: EC at t, EC at t+0.2 s -> one send; EC at t+0.7 s -> second send; EC at t+6.0 s (release after a long hold) -> third send (Review Focus 5).
  - `Listener_NothingStops`: `SetAction("task_manager")` -> `Running` true; `SetAction("nothing")` -> `Running` false within 1 s, source closed; a later `Handle` sends nothing (Review Focus 3).
  - `Listener_ReopensAfterReadFailure`: source throws `IOException` on read, then `Open` fails once, then works and returns EC -> one send, `Opens` = 2, a 2000 ms wait recorded (Review Focus 2).
  - `SetButtonAction_RefusesUnknown`, `SetButtonAction_ReplyHasActionAndRunning`, `SetButtonAction_NotAllyRefused`.
- [ ] **Step 2:** `powershell -File helper\build.ps1 -Tests`: the new tests FAIL (compile errors count as failing).
- [ ] **Step 3:** implement the files above. The thread loop: open (on failure `wait(2000)` and retry) -> read -> `Handle` -> repeat; on `IOException` close, `wait(2000)`, reopen; exit when the action became `nothing`. `Handle` reads `Action` once, so a change mid-press runs either the old or the new action, never half. Sender exceptions are caught (logged to stderr) and never end the thread.
- [ ] **Step 4:** `powershell -File helper\build.ps1 -Tests` exits 0 (all tests, old and new, pass); `powershell -File helper\build.ps1` builds `bin\traction-helper.exe`.
- [ ] **Step 5:** commit `Armoury Crate button: helper reader and actions`.

### Task 2: settings and main.py

**Files:**
- Create: `py_modules/traction/armoury_button.py`
- Modify: `py_modules/traction/settings.py`, `main.py`
- Test: `tests/test_armoury_button.py`, `tests/test_settings.py`, `tests/test_main.py`, `tests/test_action_codes_match.py`

**Interfaces:**
- Consumes: helper command `set_button_action {action}` (Task 1), `ButtonActions.Ids` in `helper/src/ButtonActions.cs`.
- Produces:
  - `armoury_button.ACTIONS: tuple[str, ...]` (the Global Constraints ids, built from `bindings.ACTIONS` order).
  - `class ArmouryButton(client, get_action: Callable[[], str], poll: float = 5.0, sleep=asyncio.sleep, logger=None)` with `start()`, `async stop()`, `async sync() -> dict` (one `set_button_action` call with the current action; returns the reply). The loop calls `sync()` every `poll` while the action is not `nothing`; a refusal or transport failure is logged once per distinct message.
  - `Settings.armoury_button: str` (default `"nothing"`, saved in `to_dict`, `load` keeps it only when it is a str in `ACTIONS`).
  - Plugin method `set_armoury_button(action) -> {"ok", "message"}` (validate, store, save, `await sync()`; a transport failure is reported as is, the choice stays stored and the loop sends it later).
  - `get_state()["armoury_button"] = <action id>`.

- [ ] **Step 1: tests**
  - `test_actions_match_helper`: parse the `Ids` array in `ButtonActions.cs` (same regex style as `test_action_codes_match.py`) and assert it equals `armoury_button.ACTIONS`.
  - `test_actions_are_the_non_gamepad_list`: `ACTIONS` = ids of `bindings.ACTIONS` whose code does not start `01-`, minus `touch_keyboard`, in that order.
  - `test_settings_armoury_button`: default `"nothing"`; `"task_manager"` round-trips; `"a"`, `5`, `None` load as `"nothing"` (Review Focus 4).
  - `test_loop_resends_after_helper_restart`: fake client; action `screenshot`; tick 1 -> one call; the fake helper "restarts" (its listener forgets); tick 2 -> the call is sent again (Review Focus 1). Action `nothing` -> no calls from the loop.
  - `test_set_armoury_button`: valid id stores, saves and calls `set_button_action {"action": id}` once; unknown id -> `{"ok": False}` and nothing stored or sent; works while `_old` is True (ruling).
  - `test_state_has_armoury_button`; `test_reset_all_clears_armoury_button`: with `task_manager` stored, `reset_all_buttons()` stores and saves `nothing` and sends `set_button_action {"action": "nothing"}` (owner decision); it does so even when the controller writes are refused (old Overdrive).
- [ ] **Step 2:** `X:\Projects\Decky Loader\decky-loader\backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=<new dir>`: the new tests FAIL.
- [ ] **Step 3:** implement. main.py: create `ArmouryButton(self.client, lambda: self.settings.armoury_button, logger=decky.logger)` in `_main` and `start()` it right after `client.start()` (not in `_start_writes`); `stop()` it in `_unload` before the helper stops.
- [ ] **Step 4:** full suite passes (baseline 198 plus the new tests).
- [ ] **Step 5:** commit `Armoury Crate button: setting and plugin method`.

### Task 3: panel row

**Files:**
- Modify: `src/controls.ts`, `src/index.tsx`
- Test: `tests/frontend/controls.test.mjs`

- [ ] **Step 1: tests:** `ARMOURY_BUTTON_LABEL === 'Armoury Crate button'`; `armouryButtonOptions()` = Nothing first, then the Global Constraints ids with their `ACTIONS` labels, in order; `armouryButtonNote('nothing') === ''` and `armouryButtonNote('task_manager')` = the Global Constraints note.
- [ ] **Step 2:** `node --test tests/frontend/*.test.mjs`: the new tests FAIL.
- [ ] **Step 3:** add the helpers to `controls.ts`; in `index.tsx` an `InlinePicker` row labelled `ARMOURY_BUTTON_LABEL` after the button rows and before "Reset all buttons", value `state.armoury_button`, `onChange` -> `run('buttons', () => setArmouryButton(v))` (new `callable` `set_armoury_button`), then `<Note text={armouryButtonNote(...)} />`. Disabled only when the plugin has no helper (`unavailable`), not by the old-Overdrive block (ruling).
- [ ] **Step 4:** `npm run build`, `npm run typecheck`, `node --test tests/frontend/*.test.mjs` pass.
- [ ] **Step 5:** commit `Armoury Crate button: panel row`.

### Task 4 (controller with the owner): live test, Steam Big Picture in front

- [ ] Install (`tools/install-dev.ps1`, elevated). Set the row to Task Manager: one press opens it; a quick double press 1 s apart opens it twice (or focuses it).
- [ ] Screenshot, Volume up, Alt+Tab once each, from Big Picture and from the desktop.
- [ ] Sleep and wake, then one press works. Set Nothing: a press does nothing. Set Task Manager again, then Reset all buttons: the row shows Nothing and a press does nothing.
- [ ] Kill `traction-helper.exe` once: within about 10 s a press works again.
