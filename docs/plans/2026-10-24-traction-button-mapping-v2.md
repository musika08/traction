# Traction Button Mapping v2 (Armoury Crate model) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the built v1 button mapping (back button Shift/normal + combo list) to Armoury Crate's model: per button a Primary and a Secondary, a "Use as secondary function" switch on M1/M2, and separate Gamepad and Desktop mapping sets.

**Architecture:** The helper (`set_bindings`, allow-list, gamepad check, `watch`) and the write path (`write_zones`, `touched_zones`, writes under the lock, reapply, rerun after reset) stay. `bindings.py` gets the v2 settings shape and slot rules; `main.py` gets v2 setters; the panel is rebuilt around a button list with inline Primary/Secondary pickers.

**Tech Stack:** Python 3 (pytest), TypeScript/React with `@decky/ui`. No C# change.

**Spec:** `X:\Projects\Decky Loader\plugins\traction\docs\specs\2026-10-24-traction-button-mapping-design.md` (v2). v1 plan: `docs/plans/2026-10-24-traction-button-mapping.md` (its Global Constraints for codes, zones and G-Helper defaults still hold).

## Global Constraints

- Repo `X:\Projects\Decky Loader\plugins\traction`, branch main. Commit as musika08 / `225994527+musika08@users.noreply.github.com` (check `git config user.email`); **no Co-Authored-By or any Claude attribution**. Never push.
- Do not edit shared copies (shared/SOURCE) or the helper.
- Codes, zones, slot order, the action list and G-Helper's gamepad/desktop defaults: exactly as the v1 plan's Global Constraints and `bindings.py` today.
- Button ids stay: `du dd dl dr ls rs lb rb a b x y view menu back_left back_right lt rt`. Labels in the panel: `back_right` = "M1 (right back button)", `back_left` = "M2 (left back button)".
- Back button slots: switch on (default) -> factory Shift code in both its slots (`02-8F` M1 / `02-8E` M2). Switch off -> its Primary in its button slot (Nothing `00-00` when no Primary chosen) and the factory Shift code in its secondary slot (proven bytes: M1 off with Primary B -> zone 8 = `02-8E, 02-8E, 01-02, 02-8F`).
- Other buttons: Primary = owner's choice for that set, else the set's factory button code (G-Helper gamepad or desktop default); Secondary = owner's choice for that set, else G-Helper's factory secondary (same for both sets).
- Copy: "Secondary functions need a back button set to Use as secondary function."

## Rulings made while planning

- Ruling: the M1/M2 switches are shared by both sets (Armoury Crate has one per profile, not per mode) — cost if wrong: add a per-set switch later.
- Ruling: one `touched_zones` set for the pad. On every mode write Traction writes the zones changed in EITHER set plus touched zones, so the pad always matches the active set whatever the firmware does on a mode switch; a zone leaves touched only when neither set has a choice in it and a Gamepad factory write landed — cost if wrong: a few extra zone writes per mode switch.
- Ruling: editing the set of the mode that is not live stores the choice only (no write); editing the live set writes that zone (watched in Gamepad, `watch:false` in Desktop). Supersedes v1's "Desktop setters never write", since Desktop now has an owner set — cost if wrong: none (Desktop writes are unwatched).
- Ruling: v1 setters `set_back_button`, `set_combo`, `reset_buttons` are removed with the v1 panel.

## Review Focus

1. v1 settings on disk (`back_right: "b"`, `combos: {...}`, `touched_zones`) load as v2 without losing the owner's mapping. Task 1.
2. M1 switch off with no Primary chosen: M1 does nothing (not Shift). Task 1.
3. Editing the Desktop set while in Gamepad writes nothing; switching to Desktop then writes it. Task 2.
4. Both switches off: Secondary pickers stay editable, the note shows, the stored Secondaries are kept. Task 3.
5. A reset reply while editing clears both sets and the switches go back on. Task 2.

---

### Task 1: v2 model in `bindings.py`

**Files:** Modify `py_modules/traction/bindings.py`, `tests/test_bindings.py`; update `tests/test_action_codes_match.py` only if a name it imports changes.

**Interfaces (produces):**
- `SETS = ("gamepad", "desktop")`; `FACTORY = "factory"`.
- `clean(raw) -> dict` returning `{"gamepad": {bid: {"primary"?: aid, "secondary"?: aid}}, "desktop": {...}, "m1_secondary": bool, "m2_secondary": bool}` (defaults True; only known ids; empty entries dropped). It also accepts the v1 shape and converts it: v1 `back_right`/`back_left` action -> that button's gamepad primary with its switch False ("shift" -> switch True); v1 `combos[b]` -> gamepad secondary of b.
- `zone_slots(zone: int, bindings: dict, set_name: str) -> list[str]` (4 codes, rules in Global Constraints).
- `zones_with_choices(bindings: dict) -> list[int]` (zones with a choice in either set, or a back-button switch off).
- `set_choice(bindings, set_name, button, slot, action) -> dict` (action FACTORY removes it), `set_back_secondary(bindings, side, on) -> dict`, `reset_button(bindings, set_name, button) -> dict`; all return a new cleaned dict.
- `all_zones()`, `keep_zones(old, new, zones)` kept (adapted to v2).

- [ ] **Step 1: tests** (exact values): factory gamepad zone 5 `["01-01","00-00","01-02","00-00"]`; factory desktop zone 5 `["02-5A","00-00","02-76","00-00"]`; gamepad `a` primary `mouse_left` + secondary `screenshot` -> zone 5 `["03-01","04-03-82-88-1B","01-02","00-00"]`; desktop set unaffected by a gamepad choice; M1 switch off + primary `b` -> zone 8 `["02-8E","02-8E","01-02","02-8F"]` (Review Focus 2: switch off, no primary -> `["02-8E","02-8E","00-00","02-8F"]`); v1 `{"back_right":"b","combos":{"a":"screenshot"}}` -> v2 gamepad back_right primary b, m1_secondary False, a secondary screenshot (Review Focus 1); junk dropped; `zones_with_choices` covers both sets and switches.
- [ ] **Step 2:** run, FAIL. **Step 3:** implement. **Step 4:** run full suite (some v1 tests will need updating in Task 2; keep test_bindings green). **Step 5:** commit `Button mapping v2: model`.

### Task 2: backend v2

**Files:** Modify `py_modules/traction/settings.py`, `py_modules/traction/controls.py`, `py_modules/traction/controller_auto.py` (only if it calls v1 names), `main.py`, `tests/test_settings.py`, `tests/test_controls.py`, `tests/test_main.py`, `tests/test_controller_auto.py`, `tests/test_reapply.py`, `tests/fake_helper.py`.

**Interfaces (produces):**
- `apply_bindings(client, settings, mode)` writes `zones_with_choices ∪ touched_zones` with `zone_slots(zone, b, "desktop" if mode == "desktop" else "gamepad")`, watched unless Desktop (existing rules for touched, reset, uncertain kept).
- Plugin methods (same refusal/lock rules as now, choice computed inside the lock): `set_button(set_name, button, slot, action)` (action may be "factory"), `set_back_secondary(side, on)` ("left"|"right"), `reset_button(set_name, button)`, `reset_all_buttons()` (clears both sets and switches on; writes all 9 zones with the live set's factory slots; Desktop unwatched). A change to the live set writes its zone; a change to the other set only stores (Review Focus 3).
- `get_state()["buttons"] = {"live": "gamepad"|"desktop", "m1_secondary": bool, "m2_secondary": bool, "sets": {"gamepad": {bid: {"primary": aid|"factory", "secondary": aid|"factory"}}, "desktop": {...}}}` (every button present).
- v1 methods removed; a reset reply clears both sets and sets both switches True (Review Focus 5).

- [ ] **Step 1: tests:** v1 file on disk loads as v2 and the first reapply writes the same zone 8 bytes as v1 did; set_button live vs other set; switch off/on writes zone 8; reset_button and reset_all_buttons; Gamepad->Desktop->Gamepad writes both sets' zones; reset reply; old Overdrive -> no set_bindings.
- [ ] **Step 2:** FAIL. **Step 3:** implement; remove or rewrite v1 tests that assert removed methods. **Step 4:** full suite PASS. **Step 5:** commit `Button mapping v2: backend`.

### Task 3: panel v2

**Files:** Modify `src/index.tsx`, `src/controls.ts`, `tests/frontend/controls.test.mjs`.

- [ ] **Step 1:** pure helpers with tests: `BUTTON_ROWS` (ids + labels in the button order above, M1/M2 last); `rowSummary(entry, labels)` -> "Primary / Secondary" with "Factory" for factory; `secondaryNote(state)` (copy above when both switches are off, Review Focus 4); `primaryEnabled(button, state)` (false for M1/M2 while their switch is on).
- [ ] **Step 2:** replace the v1 Buttons rows: "Mapping set" picker (Gamepad / Desktop, opens on `live`), one row per button with `rowSummary`, pressing it expands inline: Primary picker ("Factory" first, then actions), Secondary picker (same), "Reset to factory"; for M1/M2 also the "Use as secondary function" toggle; then "Reset all buttons"; the note; same disabled/blocked rules and list-stays-open behaviour as now.
- [ ] **Step 3:** build, typecheck, frontend tests pass. **Step 4:** commit `Button mapping v2: panel`.

### Task 4 (controller with the owner): live test, Steam Big Picture in front

- [ ] Install; check the carried-over M1 = B still works; A Primary = B; M1 switch on again, then M1 + A Secondary = Screenshot; Desktop set: A Primary = Enter in Desktop mode only; sleep and wake; Reset all buttons; XInput pad present after each Gamepad write.
- [ ] Then Part B probe (Command Center / Armoury Crate buttons) as its own design step.
