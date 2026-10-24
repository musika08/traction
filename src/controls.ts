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

export const BACK_LEFT_LABEL = 'Left back button';
export const BACK_RIGHT_LABEL = 'Right back button';
export const COMBOS_LABEL = 'Combos';
export const RESET_BUTTONS_LABEL = 'Reset buttons';
export const COMBOS_NEED_SHIFT = 'Combos need a back button set to Shift.';

export type ButtonsState = {
  back_left: string;
  back_right: string;
  combos: Record<string, string>;
  changed: number;
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

// The buttons that have a combo (every button except the two back buttons), in the backend's order.
export const COMBO_BUTTONS: { data: string; label: string }[] = [
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
];

export function backButtonOptions(): { data: string; label: string }[] {
  return [{ data: 'shift', label: 'Shift (combos)' }, ...ACTIONS];
}

export function comboOptions(): { data: string; label: string }[] {
  return [{ data: 'unchanged', label: 'Unchanged' }, ...ACTIONS];
}

// Combos are reached through a back button set to Shift; with neither set, the stored combos stay but do nothing.
export function combosNote(b: { back_left?: string; back_right?: string } | undefined): string {
  if (!b) return '';
  return b.back_left === 'shift' || b.back_right === 'shift' ? '' : COMBOS_NEED_SHIFT;
}

export function changedLabel(n: number | undefined): string {
  return n && n > 0 ? n + ' changed' : 'None changed';
}
