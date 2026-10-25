// Pure text and rules for the Traction panel (no imports, only erasable TypeScript, so `node --test` loads it
// straight from src). Ported from Overdrive 0.1.0's curve.ts, trimmed to the rows Traction has.

export type ControllerMode = 'gamepad' | 'desktop' | 'auto';

export const ARMOURY_LABEL = 'Use Traction instead of Armoury Crate';
export const ARMOURY_DESCRIPTION =
  'Stops the Armoury Crate services so they do not undo these settings. Turning it off restores them.';
export const ARMOURY_BUSY = 'Switching Armoury Crate services, this can take a few minutes';
export const GRIP_VIBRATION_DESCRIPTION = 'Vibration motors in the grips.';
export const TOUCHSCREEN_DESCRIPTION = 'Turns the touch screen off, e.g. to avoid stray touches.';
export const CONTROLLER_NOT_FOUND = 'Controller not found';
export const NOT_ALLY = 'Traction supports the ROG Ally family only';

export const CONTROLLER_OPTIONS: { data: ControllerMode; label: string }[] = [
  { data: 'gamepad', label: 'Gamepad' },
  { data: 'desktop', label: 'Desktop' },
  { data: 'auto', label: 'Auto' },
];

export function controllerModeDescription(mode: string | null | undefined): string {
  if (mode === 'desktop') return 'Sticks and triggers work as a mouse; Steam menus cannot be steered.';
  if (mode === 'auto') return 'Gamepad in Steam and games, mouse on the desktop.';
  return 'The controller works as a gamepad (Steam and games).';
}

// Touchscreen change: the helper replies at once, so the panel polls the device status until it matches the target.
export const TOUCH_POLL_MS = 1500;
export const TOUCH_TIMEOUT_MS = 15000;
export const TOUCH_TIMEOUT_TEXT = 'Touch screen did not respond';

export function touchscreenCheck(enabled: boolean | undefined, target: boolean, elapsedMs: number): 'done' | 'wait' | 'timeout' {
  if (enabled === target) return 'done';
  return elapsedMs >= TOUCH_TIMEOUT_MS ? 'timeout' : 'wait';
}

// The line above the controller rows: `blocked` (rows disabled, shown red) wins over `note` (shown plain).
export function controllerBanner(
  blocked: string | undefined,
  note: string | undefined,
): { text: string; color: string; disabled: boolean } {
  if (blocked) return { text: blocked, color: '#ff6b6b', disabled: true };
  if (note) return { text: note, color: '#dcdedf', disabled: false };
  return { text: '', color: '#dcdedf', disabled: false };
}

// Steam's toggle flips itself on every press, so it is fed what it should show: while Armoury services switch, the
// target (the opposite of the stored state); else the stored state.
export function armouryChecked(replaced: boolean, busy: boolean): boolean {
  return busy ? !replaced : replaced;
}

// The Armoury toggle is also disabled while an old Overdrive blocks Traction: the backend refuses the switch then.
export function armouryDisabled(disabled: boolean, blocked: string | undefined): boolean {
  return disabled || !!blocked;
}

// ---------- Buttons ----------

export const MAPPING_SET_LABEL = 'Mapping set';
export const RESET_BUTTON_LABEL = 'Reset to factory';
export const RESET_ALL_LABEL = 'Reset all buttons';
export const BACK_SECONDARY_LABEL = 'Use as secondary function';
export const SECONDARY_NOTE = 'Secondary functions need a back button set to Use as secondary function.';
export const FACTORY_LABEL = 'Factory';

export const SET_OPTIONS: { data: string; label: string }[] = [
  { data: 'gamepad', label: 'Gamepad' },
  { data: 'desktop', label: 'Desktop' },
];

// The button list closes only when the rows cannot be used at all (blocked by an old Overdrive, helper unavailable);
// while a change is being written it stays open and only its pickers are disabled.
export function buttonsCollapsed(blocked: string | undefined, unavailable: string | undefined): boolean {
  return !!blocked || !!unavailable;
}

// Which button row is expanded after a press on `pressed`: nothing opens or changes while the list is collapsed.
export function nextOpen(current: string | null, pressed: string, collapsed: boolean): string | null {
  if (collapsed) return null;
  return current === pressed ? null : pressed;
}

export type ButtonEntry = { primary: string; secondary: string };

export type ButtonsState = {
  live: string;
  m1_secondary: boolean;
  m2_secondary: boolean;
  sets: Record<string, Record<string, ButtonEntry>>;
};

// What a button can do (ids and order as in the backend's bindings table).
export const ACTIONS: { data: string; label: string }[] = [
  { data: 'nothing', label: 'Nothing' },
  { data: 'a', label: 'A' },
  { data: 'b', label: 'B' },
  { data: 'x', label: 'X' },
  { data: 'y', label: 'Y' },
  { data: 'lb', label: 'LB' },
  { data: 'rb', label: 'RB' },
  { data: 'ls', label: 'Left stick click' },
  { data: 'rs', label: 'Right stick click' },
  { data: 'du', label: 'D-pad up' },
  { data: 'dd', label: 'D-pad down' },
  { data: 'dl', label: 'D-pad left' },
  { data: 'dr', label: 'D-pad right' },
  { data: 'lt', label: 'LT' },
  { data: 'rt', label: 'RT' },
  { data: 'view', label: 'View' },
  { data: 'menu', label: 'Menu' },
  { data: 'mouse_left', label: 'Left click' },
  { data: 'mouse_right', label: 'Right click' },
  { data: 'mouse_middle', label: 'Middle click' },
  { data: 'scroll_up', label: 'Scroll up' },
  { data: 'scroll_down', label: 'Scroll down' },
  { data: 'esc', label: 'Esc' },
  { data: 'enter', label: 'Enter' },
  { data: 'tab', label: 'Tab' },
  { data: 'backspace', label: 'Backspace' },
  { data: 'space', label: 'Space' },
  { data: 'up', label: 'Up arrow' },
  { data: 'down', label: 'Down arrow' },
  { data: 'left', label: 'Left arrow' },
  { data: 'right', label: 'Right arrow' },
  { data: 'page_up', label: 'Page Up' },
  { data: 'page_down', label: 'Page Down' },
  { data: 'win', label: 'Windows key' },
  { data: 'show_desktop', label: 'Show desktop' },
  { data: 'screenshot', label: 'Screenshot' },
  { data: 'task_manager', label: 'Task Manager' },
  { data: 'close_window', label: 'Close window' },
  { data: 'alt_tab', label: 'Alt+Tab' },
  { data: 'win_tab', label: 'Win+Tab' },
  { data: 'volume_up', label: 'Volume up' },
  { data: 'volume_down', label: 'Volume down' },
  { data: 'touch_keyboard', label: 'Show touch keyboard' },
];

// One row per button, in the order of the panel (M1 and M2 last).
export const BUTTON_ROWS: { data: string; label: string }[] = [
  { data: 'du', label: 'D-pad up' },
  { data: 'dd', label: 'D-pad down' },
  { data: 'dl', label: 'D-pad left' },
  { data: 'dr', label: 'D-pad right' },
  { data: 'ls', label: 'Left stick click' },
  { data: 'rs', label: 'Right stick click' },
  { data: 'lb', label: 'LB' },
  { data: 'rb', label: 'RB' },
  { data: 'a', label: 'A' },
  { data: 'b', label: 'B' },
  { data: 'x', label: 'X' },
  { data: 'y', label: 'Y' },
  { data: 'view', label: 'View' },
  { data: 'menu', label: 'Menu' },
  { data: 'lt', label: 'LT' },
  { data: 'rt', label: 'RT' },
  { data: 'back_right', label: 'M1 (right back button)' },
  { data: 'back_left', label: 'M2 (left back button)' },
];

export function isBackButton(button: string): boolean {
  return button === 'back_left' || button === 'back_right';
}

// Picker options for a Primary or Secondary: Factory first, then the actions. M1 and M2 (`back`) have no Factory
// choice (their factory binding is the "Use as secondary function" switch): Nothing, then the actions.
export function actionOptions(back = false): { data: string; label: string }[] {
  return back ? [...ACTIONS] : [{ data: 'factory', label: FACTORY_LABEL }, ...ACTIONS];
}

function actionLabel(id: string | undefined, labels: Record<string, string>): string {
  if (!id || id === 'factory') return FACTORY_LABEL;
  return labels[id] ?? id;
}

// "Primary / Secondary" with "Factory" where the owner has no choice; `single` (M1, M2) shows only the Primary.
export function rowSummary(
  entry: { primary?: string; secondary?: string } | undefined,
  labels: Record<string, string>,
  single = false,
): string {
  const p = actionLabel(entry?.primary, labels);
  return single ? p : p + ' / ' + actionLabel(entry?.secondary, labels);
}

export function actionLabels(): Record<string, string> {
  const m: Record<string, string> = {};
  for (const a of ACTIONS) m[a.data] = a.label;
  return m;
}

// The back button's own switch (shared by both sets): on means it works as the secondary function (Shift).
export function backSwitchOn(button: string, state: { m1_secondary?: boolean; m2_secondary?: boolean }): boolean {
  if (button === 'back_right') return !!state.m1_secondary;
  if (button === 'back_left') return !!state.m2_secondary;
  return false;
}

// M1 and M2 keep their Primary for when the switch is off; while it is on they are the Shift key. `pending` is the
// switch's target while its change is being written (the picker follows the toggle), else undefined.
export function primaryEnabled(
  button: string,
  state: { m1_secondary?: boolean; m2_secondary?: boolean },
  pending?: boolean,
): boolean {
  if (!isBackButton(button)) return true;
  return !(pending ?? backSwitchOn(button, state));
}

// The list line of a button: M1 and M2 show the switch while it is on, else their Primary only ("Nothing" when none:
// with the switch off and no Primary the button does nothing).
export function buttonSummary(
  button: string,
  entry: { primary?: string; secondary?: string } | undefined,
  state: { m1_secondary?: boolean; m2_secondary?: boolean },
  labels: Record<string, string>,
): string {
  if (!isBackButton(button)) return rowSummary(entry, labels);
  if (backSwitchOn(button, state)) return BACK_SECONDARY_LABEL;
  const p = entry?.primary;
  return !p || p === 'factory' ? labels.nothing ?? 'Nothing' : rowSummary(entry, labels, true);
}

// The mapping set being edited: fixed from the first state that names the live set, so it does not flip while the
// owner edits when Auto changes the mode on the pad. Only the Mapping set picker changes it afterwards.
export function keepPickedSet(current: string | null, live: string | undefined): string | null {
  return current ?? live ?? null;
}

// Secondary functions are reached through a back button used as the secondary function; with neither, the stored
// Secondaries stay (and stay editable) but do nothing.
export function secondaryNote(state: { m1_secondary?: boolean; m2_secondary?: boolean } | undefined): string {
  if (!state) return '';
  return state.m1_secondary || state.m2_secondary ? '' : SECONDARY_NOTE;
}

// ---------- Library button ----------

export const LIBRARY_LABEL = 'Library button';
export const LIBRARY_ARMOURY_LABEL = 'Armoury Crate setting';
export const LIBRARY_NOTE =
  'Armoury Crate is running, so its Library setting applies. Turn on Use Traction instead of Armoury Crate to change it here.';

// Ids as in the backend's library.CHOICES: the Armoury Crate setting first, then the ASUS actions, then keys and
// shortcuts (labels of the keys from ACTIONS).
const LIBRARY_ASUS: { data: string; label: string }[] = [
  { data: 'asus_show_desktop', label: 'Show desktop' },
  { data: 'asus_task_manager', label: 'Task Manager' },
  { data: 'asus_screen_capture', label: 'Screen capture' },
  { data: 'asus_volume_up', label: 'Volume up' },
  { data: 'asus_volume_down', label: 'Volume down' },
  { data: 'asus_mic_mute', label: 'Mic mute' },
  { data: 'asus_touch_keyboard', label: 'Touch keyboard' },
  { data: 'asus_game_bar', label: 'Game Bar' },
  { data: 'asus_xbox_library', label: 'Xbox Library' },
  { data: 'asus_controller_overview', label: 'Controller Overview' },
  { data: 'asus_launch_armoury', label: 'Launch Armoury Crate' },
];
const LIBRARY_KEY_IDS = [
  'esc', 'enter', 'tab', 'backspace', 'space', 'up', 'down', 'left', 'right', 'page_up', 'page_down', 'win',
  'close_window', 'alt_tab', 'win_tab',
];

export function libraryOptions(): { data: string; label: string }[] {
  const labels = actionLabels();
  return [
    { data: 'armoury', label: LIBRARY_ARMOURY_LABEL },
    ...LIBRARY_ASUS,
    ...LIBRARY_KEY_IDS.map((id) => ({ data: id, label: labels[id] ?? id })),
  ];
}

export type LibraryState = { single: string; long: string; allowed: boolean; note?: string };

// "Single press / Long press" choices, each by its label.
export function librarySummary(
  lib: { single?: string; long?: string } | undefined,
  labels: Record<string, string>,
): string {
  const one = (id: string | undefined) => labels[id ?? 'armoury'] ?? id ?? LIBRARY_ARMOURY_LABEL;
  return one(lib?.single) + ' / ' + one(lib?.long);
}

// Shown under the row only while Armoury Crate is running (the row is greyed then).
export function libraryNote(lib: { allowed?: boolean } | undefined): string {
  return lib && lib.allowed === false ? LIBRARY_NOTE : '';
}
