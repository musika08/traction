# Traction: button mapping design (v2, Armoury Crate model)

Date: 2026-10-24. Status: v2 for owner review. v1 (back button "Shift or normal" plus a combo list) was built and
the right-back-button = B step passed live; the owner then asked for Armoury Crate SE's model. Research on ASUS's
guides (FAQ 1050220, 1050046, the ROG Ally remap guide, the Armoury Crate SE v3 article) and the device probe
(`docs/notes/2026-10-24-remap-probe.md`) are the basis.

## 1. What the owner gets (Armoury Crate model)

- **Pick a button, then set its two jobs:**
  - **Primary**: what the button does when pressed.
  - **Secondary function**: what it does while a back button (M1 or M2) is held.
  Example: A: Primary = Left click, Secondary = Screenshot. A clicks; holding M1 + A takes a screenshot.
- **Buttons:** A, B, X, Y, D-pad up/down/left/right, LB, RB, LT, RT, left stick click, right stick click, View, Menu,
  and the back buttons M1 (right) and M2 (left).
- **Back buttons:** each has a **"Use as secondary function"** switch (on by default). On: holding it fires the other
  buttons' secondary functions (factory behaviour). Off: it becomes a normal button with its own Primary (e.g. B).
  When both are off, secondary functions can't be reached; the panel says so.
- **Two mapping sets: Gamepad and Desktop.** Each controller mode has its own primaries and secondaries; the panel
  edits the set of the mode chosen at the top of the Buttons screen (default: the current mode). Factory set =
  G-Helper's gamepad and desktop defaults.
- **Per button "Reset to factory"** and **"Reset all buttons"** (both sets).
- The **Xbox button** is not touched (Steam uses it as its own menu button, which the owner wants to keep).
- **Command Center and Armoury Crate buttons:** Part B, see section 6.

## 2. Panel

Section **Buttons** under the existing rows:
- "Mapping set": Gamepad / Desktop (opens on the current mode).
- One row per button showing "Primary / Secondary" (e.g. "Left click / Screenshot"); pressing it expands that button
  inline with two pickers (Primary, Secondary) and "Reset to factory". For M1/M2 the expanded part also has the
  "Use as secondary function" switch, and Primary is only enabled when that switch is off.
- "Reset all buttons".
- Note when both back buttons are off: "Secondary functions need a back button set to Use as secondary function."
- Inline pickers only (the panel avoids Decky's popup windows). Same Armoury Crate note and old-Overdrive block as
  the other controller rows.

## 3. The action list

Unchanged from v1 (only actions that work with nothing else running): Nothing; gamepad buttons A, B, X, Y, LB, RB,
LT, RT, L/R stick click, D-pad, View, Menu; mouse left/right/middle click, scroll up/down; keys Esc, Enter, Tab,
Backspace, Space, arrows, Page Up/Down, Windows key; Windows actions Show desktop, Screenshot, Task Manager, Close
window, Alt+Tab, Win+Tab, Volume up/down, Show touch keyboard. Codes from G-Helper `AllyControl.cs` at
c09017453d9ed0c52261b67a48d02bd55232e6ac. Later additions (Armoury Crate has them, not in v2): numpad keys, any
key, custom key combinations, hold to repeat.

## 4. How it reaches the controller

Same as v1, already built and reviewed: the binding report `5A D1 02 <zone> 2C` + four 11-byte slots per zone
(button primary, button secondary, partner primary, partner secondary), allow-listed `set_bindings`, the gamepad
check with factory reset in Gamepad, `watch: false` in Desktop, `touched_zones`, writes under the lock, reapply after
sleep / Decky start / Armoury switch / mode switch. A back button with "Use as secondary function" off sends its
Primary in its button slot and keeps the factory code in its secondary slot (the report proven on the device).

## 5. Stored settings

`bindings = {"gamepad": {<button>: {"primary": <action>, "secondary": <action>}}, "desktop": {...},
"m1_secondary": bool, "m2_secondary": bool}`; missing entries mean factory. v1 settings are migrated: v1 back-button
actions become that button's Gamepad Primary with its switch off; v1 combos become Gamepad Secondaries.
The mode write is followed by the zones of that mode's set (changed or touched), as now.

## 6. Part B (after a device probe): Command Center and Armoury Crate buttons

Not firmware-bindable; they send vendor events on the controller's 0x5A input report that a program must catch
(on the Xbox Ally X the Armoury Crate/Library button sends code 147; codes for Command Center to be found by the
probe). Traction's helper would read those reports and run the action itself: **Single press** and **Long press**,
keyboard/mouse/Windows actions only (no gamepad buttons: Windows cannot fake one without an extra driver).
First a probe: with Armoury Crate stopped, log what each press sends, and check what the device legend's defaults
(Gaming Copilot, Push to Talk, Voice typing, Game Bar) come from.

## 7. Tests

Unit: the v2 settings shape and v1 migration; per-mode slots; switch off/on for M1/M2; per-button and full reset;
panel helpers. Live on the Ally (Steam Big Picture in front): A Primary = B; M1 + A Secondary = Screenshot; M1 switch
off and M1 Primary = B; Desktop set differs from Gamepad; sleep and wake keeps both; reset all.

## 8. Out of scope

Per-game profiles, import/export, hold to repeat, the mappings overlay (M1/M2 + B), the Xbox button.
