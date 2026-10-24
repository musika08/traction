// Run with: node --test tests/frontend/*.test.mjs
// Node 22.18+ / 23.6+ strip TypeScript types natively, so the pure modules are imported straight from src.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ARMOURY_BUSY,
  ARMOURY_LABEL,
  CONTROLLER_OPTIONS,
  armouryChecked,
  ACTIONS,
  COMBO_BUTTONS,
  armouryDisabled,
  backButtonOptions,
  changedLabel,
  comboOptions,
  combosNote,
  combosCollapsed,
  COMBOS_HELP,
  controllerBanner,
  controllerModeDescription,
  touchscreenCheck,
} from '../../src/controls.ts';
import { rowValue, pressRow, choose, pressCancel, focusIndex } from '../../src/picker.ts';

test('row labels and busy text', () => {
  assert.equal(ARMOURY_LABEL, 'Use Traction instead of Armoury Crate');
  assert.equal(ARMOURY_BUSY, 'Switching Armoury Crate services, this can take a few minutes');
});

test('controller mode options are Gamepad, Desktop, Auto in that order', () => {
  assert.deepEqual(CONTROLLER_OPTIONS.map((o) => o.label), ['Gamepad', 'Desktop', 'Auto']);
  assert.deepEqual(CONTROLLER_OPTIONS.map((o) => o.data), ['gamepad', 'desktop', 'auto']);
});

test('controllerModeDescription gives the three texts', () => {
  assert.equal(controllerModeDescription('gamepad'), 'The controller works as a gamepad (Steam and games).');
  assert.equal(controllerModeDescription('desktop'), 'Sticks and triggers work as a mouse; Steam menus cannot be steered.');
  assert.equal(controllerModeDescription('auto'), 'Gamepad in Steam and games, mouse on the desktop.');
});

test('touchscreenCheck waits for the device to match the target, then times out', () => {
  assert.equal(touchscreenCheck(true, true, 0), 'done');
  assert.equal(touchscreenCheck(true, false, 1500), 'wait');
  assert.equal(touchscreenCheck(undefined, false, 14999), 'wait');
  assert.equal(touchscreenCheck(true, false, 15000), 'timeout');
  assert.equal(touchscreenCheck(false, false, 20000), 'done');
});

test('blocked wins over note and disables the rows; note alone does not', () => {
  assert.deepEqual(controllerBanner('Update Overdrive', 'Armoury running'), { text: 'Update Overdrive', color: '#ff6b6b', disabled: true });
  assert.deepEqual(controllerBanner('', 'Armoury running'), { text: 'Armoury running', color: '#dcdedf', disabled: false });
  assert.deepEqual(controllerBanner(undefined, undefined), { text: '', color: '#dcdedf', disabled: false });
});

test('armoury toggle shows the stored state, or the target while switching', () => {
  assert.equal(armouryChecked(false, false), false);
  assert.equal(armouryChecked(true, false), true);
  assert.equal(armouryChecked(false, true), true);
  assert.equal(armouryChecked(true, true), false);
});

test('armoury toggle is disabled while an old Overdrive blocks Traction (the backend refuses it then)', () => {
  assert.equal(armouryDisabled(false, ''), false);
  assert.equal(armouryDisabled(false, undefined), false);
  assert.equal(armouryDisabled(true, ''), true);
  assert.equal(armouryDisabled(false, 'Update Overdrive to 0.2.0 or newer'), true);
});

test('inline picker rules', () => {
  assert.equal(rowValue(CONTROLLER_OPTIONS, 'auto', false), 'Auto ▾');
  assert.equal(rowValue(CONTROLLER_OPTIONS, 'auto', true), 'Auto ▴');
  assert.equal(pressRow(false), true);
  assert.equal(pressRow(false, true), false);
  assert.deepEqual(choose('auto', 'auto'), { open: false, apply: false });
  assert.deepEqual(choose('auto', 'desktop'), { open: false, apply: true });
  assert.deepEqual(pressCancel(true), { open: false, handled: true });
  assert.deepEqual(pressCancel(false), { open: false, handled: false });
  assert.equal(focusIndex(CONTROLLER_OPTIONS, 'desktop', true), 1);
  assert.equal(focusIndex(CONTROLLER_OPTIONS, 'desktop', false), -1);
});

test('action list keeps the plan order and labels', () => {
  assert.equal(ACTIONS.length, 43);
  assert.deepEqual(ACTIONS.slice(0, 3).map((a) => [a.data, a.label]), [['nothing', 'Nothing'], ['a', 'A'], ['b', 'B']]);
  assert.deepEqual(ACTIONS.slice(-3).map((a) => a.label), ['Volume up', 'Volume down', 'Show touch keyboard']);
  assert.equal(new Set(ACTIONS.map((a) => a.data)).size, ACTIONS.length);
});

test('combo buttons are the 16 non-back buttons in plan order', () => {
  assert.equal(COMBO_BUTTONS.length, 16);
  assert.deepEqual(COMBO_BUTTONS.slice(0, 2).map((b) => b.label), ['D-pad up', 'D-pad down']);
  assert.deepEqual(COMBO_BUTTONS.slice(-4).map((b) => b.data), ['view', 'menu', 'lt', 'rt']);
  assert.ok(!COMBO_BUTTONS.some((b) => b.data.startsWith('back_')));
});

test('back button options start with Shift (combos), combo options with Unchanged', () => {
  const back = backButtonOptions();
  assert.equal(back.length, ACTIONS.length + 1);
  assert.deepEqual(back[0], { data: 'shift', label: 'Shift (combos)' });
  assert.deepEqual(back[1], { data: 'nothing', label: 'Nothing' });
  const combo = comboOptions();
  assert.equal(combo.length, ACTIONS.length + 1);
  assert.deepEqual(combo[0], { data: 'unchanged', label: 'Unchanged' });
});

test('combosNote appears only when neither back button is Shift', () => {
  const text = 'Combos need a back button set to Shift.';
  assert.equal(combosNote({ back_left: 'a', back_right: 'b' }), text);
  assert.equal(combosNote({ back_left: 'shift', back_right: 'b' }), '');
  assert.equal(combosNote({ back_left: 'a', back_right: 'shift' }), '');
  assert.equal(combosNote({ back_left: 'shift', back_right: 'shift' }), '');
});

test('changedLabel', () => {
  assert.equal(changedLabel(0), 'None changed');
  assert.equal(changedLabel(3), '3 changed');
  assert.equal(changedLabel(undefined), 'None changed');
});

test('the combo list collapses only when blocked or unavailable, not while working', () => {
  assert.equal(combosCollapsed('', ''), false);
  assert.equal(combosCollapsed(undefined, undefined), false);
  assert.equal(combosCollapsed('Update Overdrive', ''), true);
  assert.equal(combosCollapsed('', 'helper not running'), true);
});

test('combos help line', () => {
  assert.equal(COMBOS_HELP, 'Changing one combo puts the others of the same button pair back to their factory action.');
});
