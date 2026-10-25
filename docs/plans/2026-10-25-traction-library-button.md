# Traction Part B (revised): Library button single and long press Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner picks what the Library button (top right, three vertical lines) does on a single press and on a long press; Traction stores it in the controller like Armoury Crate does.

**Architecture:** Two controller feature reports (`5A D1 1D` single, `5A D1 23` long) each carry a Library slot and a Command Center slot. The helper gets one allow-listed command that writes both. The Python side turns the owner's choices (or Armoury Crate's saved choice, read from its registry key) into slots, always adds Command Center's own Armoury Crate setting, and writes on change and on every reapply while Armoury Crate is not running. The first Part B (the `5A EC` reader) is removed.

**Tech Stack:** C# 5 / .NET Framework 4.8 helper (in-box csc, house test runner), Python 3 (pytest, `winreg`), TypeScript/React with `@decky/ui`.

**Spec:** `X:\Projects\Decky Loader\plugins\traction\docs\specs\2026-10-24-traction-button-mapping-design.md` section 6 (revised). Evidence: `docs/notes/2026-10-24-remap-probe.md`, "Library and Command Center press bindings".

## Global Constraints

- Repo `X:\Projects\Decky Loader\plugins\traction`, branch main. Commit as musika08 / `225994527+musika08@users.noreply.github.com` (check `git config user.email`); **no Co-Authored-By or any Claude attribution**. Never push.
- Do not edit the files shared with Overdrive: `helper/src/shared/*`, `py_modules/traction/helper_client.py`, `reapply_core.py`, `settings_file.py`, `armoury_record.py`, `armoury_switch.py`, `device.py`.
- Name in all copy: **Library button**. Row label `Library button`; pickers `Single press`, `Long press`; default choice label `Armoury Crate setting`.
- Reports (64 bytes, zero padded, sent with the existing feature-report path): single = `5A D1 1D 01 12` + Library slot (9 bytes) + Command Center slot (9 bytes); long = `5A D1 23 01 12` + Library slot + Command Center slot.
- Slots (9 bytes): ASUS action `05 00 <code> 00 00 00 00 00 00`; key `04 00 00 01 <key> 00 00 00 00`; shortcut `04 00 00 <n> k1 k2 k3 00 00` (n = 2 or 3, PS/2 set-2 codes as in `bindings.ACTIONS`).
- Choice ids and slots (in this order in the picker, after `armoury`):
  - ASUS actions: `asus_show_desktop` 0x1C "Show desktop", `asus_task_manager` 0x1A "Task Manager", `asus_screen_capture` 0x16 "Screen capture", `asus_volume_up` 0x03 "Volume up", `asus_volume_down` 0x02 "Volume down", `asus_mic_mute` 0x01 "Mic mute", `asus_touch_keyboard` 0x19 "Touch keyboard", `asus_game_bar` 0x26 "Game Bar", `asus_xbox_library` 0x27 "Xbox Library", `asus_controller_overview` 0x28 "Controller Overview", `asus_launch_armoury` 0x04 "Launch Armoury Crate".
  - Keys/shortcuts, labels and codes from `bindings.ACTIONS`: `esc, enter, tab, backspace, space, up, down, left, right, page_up, page_down, win, close_window, alt_tab, win_tab` (`02-xx` -> key slot; `04-n-k..` -> shortcut slot).
- Armoury Crate's saved choice: `HKCU\Software\ASUS\ARMOURY CRATE Service\GamepadCustomize`, DWORDs `LibBtnSFunctId`, `LibBtnLFunctId`, `CCBtnSFunctId`, `CCBtnLFunctId`. Id -> slot: 1..12 -> ASUS action with code `[0x19, 0x1C, 0x03, 0x02, 0x01, 0x16, 0x1E, 0x28, 0x17, 0x04, 0x26, 0x27][id-1]`; 0x21..0x2A -> shortcut by combo type `{0x21: 03 8C 88 76, 0x22: 02 82 0D, 0x23: 02 82 1C, 0x24: 02 8A 0C, 0x25: 02 82 1B, 0x26: 02 82 55, 0x27: 03 8C 8A C0, 0x28: 02 82 78, 0x29: 02 82 33, 0x2A: 03 82 88 57}`; anything else, a missing value or an unreadable key -> Armoury Crate's installed defaults: Library single `05 00 27`, Library long `05 00 16`, Command Center single `05 00 17`, Command Center long `05 00 04`.
- Writes happen on change, on every reapply and on every controller mode write (panel and Auto loop), only when (b) Armoury Crate is not running (`not installed or replaced`, the existing Armoury switch state) and (c) the controller is not blocked by an old Overdrive, and then: while Traction has replaced Armoury Crate (`replaced`), always, even with both presses `armoury` (they carry Armoury Crate's own setting from the registry, because nobody else rewrites them after sleep); when Armoury Crate is not installed, only when (a) at least one press is not `armoury`, and when (a) becomes false again ("Reset") the reports are written once with the Armoury Crate setting so the controller matches it, then no more. Writes go through the same lock and reapply rules as the button zones. Switching Armoury Crate back on first writes its own setting once when Traction wrote the reports (stored choices kept; a failed write does not block the switch).
- Copy when greyed: `Armoury Crate is running, so its Library setting applies. Turn on Use Traction instead of Armoury Crate to change it here.`

## Rulings made while planning

- Ruling: the device check (Task 1) runs before any code is built; if the controller refuses the reports or the Command Center button stops working, stop and report to the owner — cost if wrong: none (nothing built yet).
- Ruling: "Armoury Crate is running" = the Armoury switch's `installed and not replaced` (no new service query) — cost if wrong: a stale state for a few seconds after the owner starts Armoury Crate by hand.
- Ruling: the first Part B is removed in the same branch (helper reader, `set_button_action`, `armoury_button.py`, the `armoury_button` setting and panel row); a stored `armoury_button` key is dropped on load — cost if wrong: none (it was set to Nothing on the device).

## Review Focus

1. Armoury Crate's registry values missing, non-numeric or an unknown id: the defaults are used, never a crash or a zero slot. Task 3.
2. Command Center's slots are always the Armoury Crate setting (owner's: `05 00 17` / `05 00 04`), never zero, in both reports. Tasks 2 and 3.
3. Armoury Crate running: no press-binding report is ever sent, from the panel or a reapply. Task 3.
4. Reset (both presses back to `armoury`): one final write with the Armoury Crate setting, then none on later reapplies. Task 3.
5. A malformed slot from Python (wrong length, unknown code, n out of range): the helper refuses before any write. Task 2.

---

### Task 1 (controller with the owner): device check with the probe tool

**Files:** none in the repo. Tool: `C:\Users\Musika\AppData\Local\Temp\claude\X--Projects-Decky-Loader\c6bae604-5707-49a5-b21e-0001ba31d8d6\scratchpad\remap-probe\raw.exe` (sends one padded feature report). Watchers: `...\scratchpad\button-probe\rawkeys.exe`, `listen.exe`.

- [ ] Armoury Crate switched off by the owner (Traction's "Use Traction instead of Armoury Crate").
- [ ] Send the owner's own values: single `5A D1 1D 01 12 04 00 00 03 8C 88 76 00 00 05 00 17 00 00 00 00 00 00`, long `5A D1 23 01 12 05 00 28 00 00 00 00 00 00 05 00 04 00 00 00 00 00 00`. Expect `ok=True`. Owner: Library single opens Task Manager; Command Center quick press still acts (`5A A6` seen by `listen.exe`).
- [ ] Change one value: single with Library `05 00 1C 00 00 00 00 00 00` (Show desktop). Owner: Library single shows the desktop; Command Center unchanged.
- [ ] Long press check with Library long `04 00 00 01 76 00 00 00 00` (Esc): raw input shows Esc from `MI_03` on a long press only.
- [ ] Sleep and wake: does the changed value survive? (Decides whether the reapply must rewrite; it will rewrite either way.)
- [ ] Restore the owner's values (first step). Record results in `docs/notes/2026-10-24-remap-probe.md` and commit `Probe notes: Library press binding device check`.

### Task 2: helper: `set_press_bindings`, old reader removed

**Files:**
- Create: `helper/src/PressBindings.cs`
- Delete: `helper/src/ButtonActions.cs`, `helper/src/ButtonListener.cs`
- Modify: `helper/src/TractionCore.cs`, `helper/src/HelperMain.cs`, `helper/tests/HelperTests.cs`, `helper/tests/FakeHardware.cs`

**Interfaces (produces):**
- `public static class PressBindings { public static bool IsAllowedSlot(string slot); public static byte[] Report(byte command, string library, string commandCenter); }`. A slot string is 9 bytes `"05-00-1C-00-00-00-00-00-00"`. Allowed: type `05`, byte1 `00`, code in {0x01,0x02,0x03,0x04,0x16,0x17,0x19,0x1A,0x1C,0x1E,0x26,0x27,0x28}, rest zero; or type `04`, bytes1-2 `00`, n in 1..3, the n key bytes non-zero and each a PS/2 code or modifier already allowed in `Bindings` (the key bytes that appear in its allow-listed `02-xx`/`04-...` codes), rest zero. `Report(0x1D, ...)` = `5A D1 1D 01 12` + 9 + 9 bytes; `Report(0x23, ...)` for long.
- Helper command `set_press_bindings {single: [libSlot, ccSlot], long: [libSlot, ccSlot]}` -> writes the single report then the long report (unwatched; no pad check, these slots are not gamepad zones); reply data `{"written": ["single", "long"]}`; any disallowed slot -> `Refused: unknown press binding '<slot>'.` before any write; `Hid` null -> `ControllerUnavailable`. Not in `ReadCommands`.
- Remove `set_button_action`, the listener property and its wiring.

- [ ] **Step 1: tests:** `PressBindings_Report_Single` (bytes of `Report(0x1D, "04-00-00-03-8C-88-76-00-00", "05-00-17-00-00-00-00-00-00")` = the Task 1 single report, 64 bytes after padding by the send path); `PressBindings_AllowsFunctionAndKeys` (`05-00-1C...`, `04-00-00-01-76...`, `04-00-00-02-8A-0C...` true); `PressBindings_RefusesBad` (`05-00-99...`, `04-00-00-04-...`, `04-00-00-01-00...`, 8-byte slot, `01-02-...` false); `SetPressBindings_WritesSingleThenLong` (fake HID sees exactly the two reports in order); `SetPressBindings_RefusesBeforeWriting`; `SetButtonAction_Gone` (unknown command); not-Ally refusal count updated.
- [ ] **Step 2:** `powershell -NoProfile -ExecutionPolicy Bypass -File helper\build.ps1 -Tests`: new tests fail.
- [ ] **Step 3:** implement; delete the old reader files and their tests.
- [ ] **Step 4:** `build.ps1 -Tests` exit 0; `build.ps1` builds `bin\traction-helper.exe`.
- [ ] **Step 5:** commit `Library button: helper press bindings`.

### Task 3: Python model, settings, writes, main

**Files:**
- Create: `py_modules/traction/library.py`
- Delete: `py_modules/traction/armoury_button.py`, `tests/test_armoury_button.py`
- Modify: `py_modules/traction/settings.py`, `py_modules/traction/controls.py`, `py_modules/traction/reapply.py`, `main.py`, `tests/test_settings.py`, `tests/test_controls.py`, `tests/test_reapply.py`, `tests/test_main.py`, `tests/test_action_codes_match.py`, `tests/fake_helper.py`

**Interfaces:**
- Consumes: helper `set_press_bindings` (Task 2).
- Produces:
  - `library.CHOICES: tuple[(id, label)]` (`("armoury", "Armoury Crate setting")` first, then the Global Constraints order); `library.ARMOURY = "armoury"`.
  - `library.armoury_ids(read=None) -> dict` with keys `lib_single, lib_long, cc_single, cc_long` (ints or None; `read` injectable, default reads the registry with `winreg`, any error -> None values).
  - `library.slot_for_id(id: Optional[int], default: str) -> str`; `library.slot_for_choice(choice: str, armoury_slot: str) -> str`.
  - `library.slots(settings_library: dict, ids: dict) -> {"single": [lib, cc], "long": [lib, cc]}`.
  - `Settings.library: dict` = `{"single": id, "long": id}`, default both `armoury`; load keeps only ids in `CHOICES`; drops a stored `armoury_button`.
  - `controls.apply_press_bindings(client, settings, allowed: bool, read=None) -> dict` (no call when not allowed or nothing chosen and nothing to restore; tracks "needs one restore write" in `settings.library_written: bool`, saved).
  - Reapply: `Reapplier.library_allowed: Optional[Callable[[], bool]]` set by main (`not installed or replaced`, and not old Overdrive); `_apply_steps` calls `apply_press_bindings` after the controller writes when the controller was found.
  - Plugin methods `set_library_press(press, choice)` (`press` in `single`/`long`), `reset_library()`; `reset_all_buttons()` also resets the library choices; `get_state()["library"] = {"single": id, "long": id, "allowed": bool, "note": copy or ""}`. All via `_refuse_controller` and under the controller lock like the zone setters.
  - Remove `armoury_button`, `set_armoury_button`, the loop and its state key.

- [ ] **Step 1: tests:** `test_slot_for_id` (0x21 -> `04-00-00-03-8C-88-76-00-00`; 8 -> `05-00-28-...`; 9 -> `05-00-17-...`; 10 -> `05-00-04-...`; 0x60, None, 0 -> the default); `test_slots_keep_command_center` (owner ids 33/8/9/10 with choices single `asus_show_desktop`, long `esc` -> single `["05-00-1C-…", "05-00-17-…"]`, long `["04-00-00-01-76-…", "05-00-04-…"]`); `test_registry_unreadable_uses_defaults` (Review Focus 1); `test_settings_library_roundtrip_and_junk` (unknown ids -> `armoury`; `armoury_button` dropped); `test_no_write_while_armoury_runs` (panel setter stores, no helper call, note set; reapply no call) (Review Focus 3); `test_reset_writes_once_then_stops` (Review Focus 4); `test_reapply_writes_press_bindings_when_chosen`; `test_reset_all_resets_library`; `test_choices_codes_in_helper_allow_list` (every choice slot passes the C# allow-list: parse `PressBindings.cs` code sets, same style as `test_action_codes_match.py`).
- [ ] **Step 2:** pytest (`X:\Projects\Decky Loader\decky-loader\backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=<new dir>`): new tests fail.
- [ ] **Step 3:** implement; remove the old Part B Python code and tests.
- [ ] **Step 4:** full suite passes.
- [ ] **Step 5:** commit `Library button: settings, writes and plugin methods`.

### Task 4: panel

**Files:** Modify `src/controls.ts`, `src/index.tsx`, `tests/frontend/controls.test.mjs`.

- [ ] **Step 1: tests:** `LIBRARY_LABEL === 'Library button'`; `libraryOptions()` = Global Constraints ids and labels in order with `Armoury Crate setting` first; `librarySummary({single, long}, labels)` -> `"<single> / <long>"`; `libraryNote(state)` returns the greyed copy only when `allowed` is false. Remove the old Armoury Crate button helpers and tests.
- [ ] **Step 2:** `node --test tests/frontend/*.test.mjs`: new tests fail.
- [ ] **Step 3:** replace the old row with a `Library button` row after the button rows (same expand pattern as `ButtonRow`: Single press and Long press `InlinePicker`s and `Reset to factory`), disabled when `controllerDisabled` or `!state.library.allowed`, with the note under it.
- [ ] **Step 4:** `npm run build`, `npm run typecheck`, frontend tests pass.
- [ ] **Step 5:** commit `Library button: panel row`.

### Task 5 (controller with the owner): live test, Steam Big Picture in front

- [ ] Install. With Armoury Crate running: the row is greyed with the note. Switch Armoury Crate off.
- [ ] Single press = Show desktop, long press = Esc: both work on every press; Command Center quick press still acts.
- [ ] Sleep and wake: both still work. Reset to factory: Library opens Task Manager again (owner's Armoury Crate setting).
- [ ] Switch Armoury Crate back on: Library keeps the Armoury Crate setting.
- [ ] With Armoury Crate switched off and a choice set: Gamepad -> Desktop -> Gamepad, then press the Library button (the choice still acts after the mode switches).
- [ ] Reset to factory, sleep, wake, then a quick Library press: expect Task Manager (Armoury Crate's setting is written after the wake while Traction replaces Armoury Crate).
- [ ] After switching Armoury Crate back on, press the Library button before any sleep: expect Armoury Crate's setting (Task Manager), not Traction's choice.
