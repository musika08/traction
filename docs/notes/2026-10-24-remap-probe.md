# Button remap probe on the ROG Xbox Ally X (2026-10-24)

First live probe of G-Helper's binding report (AllyControl.BindZone at c09017453d9ed0c52261b67a48d02bd55232e6ac):
`[5A D1 02 <zone> 2C]` + four 10-byte bindings (left, left layer 2, right, right layer 2), sent as one 64-byte
feature report to the controller collection (PID 0x1B4C). No admin rights are needed for the write.

What happened, in order:
1. Zone 8 (M1/M2), M1 -> gamepad B (`01-02`), layer 2 kept at the defaults. Write ok. Owner: pressing the right back
   button did nothing in Steam.
2. Mode write `[5A D1 01 01 01]`, then zone 8 with both back buttons -> B. Write ok. Nothing happened.
3. Mode write, then zone 5 (A/B) with A -> B. Write ok. Owner: A on a game tile did nothing (read at the time as
   "A now acts as B"; see 5).
4. Zone 5 restored, zone 8 -> Enter (`02-5A`). Owner: no button, stick or D-pad worked any more.
5. XInput showed no controller at all (XInputGetState 1167 on all four pads), although the PnP devices
   "ROG Xbox Ally Device Gamepad" and "HID-compliant game controller" were present and OK. Rewriting every zone
   with G-Helper's defaults, `[5A D1 0B 01 01]` (controller on) and G-Helper's InitInput
   (`5A` + "ASUS Tech.Inc.") did not bring it back. The power button did not sleep the device either.
6. A Windows restart brought the gamepad back (XInput pad 0 sending packets).

Open questions before any further write:
- Which step dropped the gamepad: possibly already step 1, so "A did nothing" in step 3 may mean the controller was
  already gone, not that the remap worked.
- Whether the Xbox Ally X accepts BindZone at all, and whether its back buttons go through zone 8.

Rules for the next probe:
- Run the XInput watcher between every single write; if the gamepad disappears, stop and restore.
- Keep the touchscreen on as a fallback input.
- Read G-Helper's issues/changelog for Xbox Ally X remapping first.

## Retest the same day (after research), Steam Big Picture in front: both work

Tool: a probe that checks XInput pad 0 after every write and rewrites G-Helper's full default set if the pad is gone for 5 s.
Single-zone writes, no commit reports, no mode write needed. The pad stayed present after every write.
1. Zone 5 with A's layer-2 slot = B (`5A D1 02 05 2C | 01 01 | 01 02 | 01 02 | 00`): plain A still A; back button held + A acted as B. Combos work.
2. Zone 8 with the right back button (M1) = B, left (M2) and both layer-2 slots at the defaults: the right back button acted as B (went back from a game page); A and the sticks kept working; the left one still worked as the layer-2 key.
3. Zone 5 and zone 8 restored to the defaults; pad present.

Findings:
- On this device the back buttons are the layer-2 ("secondary function") key by default (codes 02-8E / 02-8F). Holding one makes other buttons use their layer-2 binding.
- The first probe's "nothing happened" was most likely tested on Steam's home screen, where B does nothing. The pad loss earlier is still unexplained (it happened around the time Steam was closed and reopened).
- While another window is in front, Steam's desktop layout turns the controller into keyboard keys (A = Enter) and XInput shows no buttons, so on-device tests must run with Steam Big Picture in front.

Owner decision: each back button can be either the Shift (layer-2) key for combos, or a normal button; and Traction lets the owner set what the combos (layer-2 bindings of other buttons) do.

## Part B probe: Command Center and Armoury Crate buttons (2026-10-25)

Read-only listener on every ASUS 0x0B05 HID collection of PID 0x1B4C (the keyboard and mouse collections can't be
opened: access denied, Windows owns them) plus a low-level keyboard hook. Armoury Crate SE and all ASUS services were
running; nothing opened on any press.

- **Command Center** (left side, above View): before the InitInput hello, input report `5A A6` (166, G-Helper's "cc")
  then `5A 00` 1 ms later. After one InitInput (`5A` + "ASUS Tech.Inc."), the same press came as the key **F21**
  (vk 0x84, scan 0x6C) down and up 4 ms apart, and no `5A A6`.
- **Armoury Crate** (right side, below Menu): `5A EC` (236) only, no release report; the same before and after
  InitInput. G-Helper ignores 236 (it expects 56 or 147 on the older Ally).
- **Holds**: a 3 s and a 5 s hold each gave exactly one event at the press, the same as a quick tap. The firmware
  sends no release timing, so a long press can't be told apart from a single press.
- Back button + Command Center: not tested (the press only showed the plain code earlier).
