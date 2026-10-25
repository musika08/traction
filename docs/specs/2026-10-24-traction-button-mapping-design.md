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
- **Library button** (top right, three vertical lines): single and long press, Part B, see section 6. The Command Center button is not Traction's.

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

## 6. Part B: the Library button (single and long press)

Revised 2026-10-25 after the live test and REA. The first Part B (listening for `5A EC`) was wrong: those tests
pressed the Menu button, and `5A EC` comes from Menu presses now and then. Evidence and report layout:
`docs/notes/2026-10-24-remap-probe.md` ("Library and Command Center press bindings"). The owner calls the top-right
button (three vertical lines) the **Library button**.

**What the owner gets:** a **Library button** row in the Buttons section. Pressing it expands two inline pickers,
**Single press** and **Long press**, plus "Reset to factory". The controller does the timing, so both work on every
press with no delay.

- **Choices** (one list for both pickers):
  - **Armoury Crate setting** (the default): the action chosen in Armoury Crate's Shortcuts & Key Binding page,
    read from its saved settings (today: single = Task Manager, long = Controller Overview).
  - ASUS actions the controller runs itself: Show desktop, Task Manager, Screen capture, Volume up, Volume down,
    Mic mute, Touch keyboard, Game Bar, Xbox Library, Controller Overview, Launch Armoury Crate.
  - The keys and shortcuts from Traction's action list (Esc, Enter, Tab, Backspace, Space, arrows, Page Up/Down,
    Windows key, Close window, Alt+Tab, Win+Tab). Not gamepad buttons or mouse clicks: the Library slot only takes keys
    and ASUS actions.
- **One setting for both controller modes** (Armoury Crate keeps one too).
- **"Reset to factory" and "Reset all buttons"** set both back to **Armoury Crate setting**.
- **The Command Center button is not changed.** Both buttons share the controller's two reports, so Traction always
  sends Command Center's own Armoury Crate setting with them (today: quick press = Command Center, which Overdrive
  and the Bar rely on; long press = Launch Armoury Crate).
- **While Armoury Crate is running, its setting applies:** Armoury Crate rewrites these reports after sleep and mode
  changes, so Traction does not write them then. The row is greyed with the note "Armoury Crate is running, so its
  Library setting applies. Turn on Use Traction instead of Armoury Crate to change it here."
- The Xbox button is still not touched.

**How it reaches the controller:**
- Two feature reports on the controller collection Traction already writes, 64 bytes, zero padded:
  - single: `5A D1 1D 01 12` + Library slot (9 bytes) + Command Center slot (9 bytes)
  - long: `5A D1 23 01 12` + Library slot + Command Center slot
- Slot: an ASUS action `05 00 <code> 00 00 00 00 00 00`, a key `04 00 00 01 <key> 00 00 00 00`, or a shortcut
  `04 00 00 <n> k1 k2 k3 00 00` (PS/2 set-2 codes, the same scheme as the other buttons).
- "Armoury Crate setting" is read from `HKCU\Software\ASUS\ARMOURY CRATE Service\GamepadCustomize`
  (`LibBtnSFunctId`, `LibBtnLFunctId`, `CCBtnSFunctId`, `CCBtnLFunctId`) and turned into a slot the way Armoury Crate
  does (ids 1-12 ASUS actions, 0x21-0x2A shortcuts). Ids above 0x60 (single keys in Armoury Crate) fall back to the
  defaults for now, since their key encoding is not known yet. An id Traction can't translate, or a missing value,
  falls back to Armoury Crate's installed defaults (single: Xbox Library / Command Center; long: Screen capture /
  Launch Armoury Crate).
- Written when the owner changes it and on every reapply (start, wake, Armoury switched) and every controller mode
  write (panel or Auto), never while Armoury Crate is running:
  - While Traction has replaced Armoury Crate (Use Traction instead of Armoury Crate is on), on every one of those
    writes, even with both presses on Armoury Crate setting: the reports then carry Armoury Crate's own setting from
    the registry, because nobody else rewrites them after sleep or a mode switch.
  - When Armoury Crate is not installed, only once the owner has chosen something other than Armoury Crate setting
    for either press; after a Reset back to Armoury Crate setting it is written once more, then no more (otherwise
    Traction never sends these reports).
  - Handing back to Armoury Crate (the switch turned off): when Traction wrote the reports, it writes Armoury Crate's
    own setting once before Armoury Crate is switched back on (the stored choices are kept). A failed write is logged
    and does not stop the switch.
  New helper command `set_press_bindings {short, long}` (two 18-byte slot pairs, allow-listed codes only).
- Before the build relies on it, a device check: send the owner's own Armoury Crate values back and confirm the
  Library button still opens Task Manager and Command Center still works; then one changed value.
- **Replaces the first Part B:** the `5A EC` reader, `set_button_action`, the 5 s loop and the `armoury_button`
  setting are removed (a stored `armoury_button` is ignored).

## 7. Tests

Unit: the v2 settings shape and v1 migration; per-mode slots; switch off/on for M1/M2; per-button and full reset;
panel helpers; Part B: slot encoding per choice, the Armoury Crate id translation and fallback, Command Center slots
always sent, no write while Armoury Crate runs. Live (Part B): device check first, then single and long press, after
sleep, Command Center unchanged. Live on the Ally (Steam Big Picture in front): A Primary = B; M1 + A Secondary = Screenshot; M1 switch
off and M1 Primary = B; Desktop set differs from Gamepad; sleep and wake keeps both; reset all.

## 8. Out of scope

Per-game profiles, import/export, hold to repeat, the mappings overlay (M1/M2 + B), the Xbox button.
