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
  BUTTON_ROWS,
  actionOptions,
  actionLabels,
  rowSummary,
  buttonSummary,
  secondaryNote,
  primaryEnabled,
  buttonsCollapsed,
  nextOpen,
  SET_OPTIONS,
  armouryDisabled,
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

test('button rows follow the plan order with M1 then M2 last', () => {
  assert.equal(BUTTON_ROWS.length, 18);
  assert.deepEqual(BUTTON_ROWS.slice(0, 2).map((b) => b.label), ['D-pad up', 'D-pad down']);
  assert.deepEqual(BUTTON_ROWS.slice(-4).map((b) => b.data), ['lt', 'rt', 'back_right', 'back_left']);
  assert.deepEqual(BUTTON_ROWS.slice(-2).map((b) => b.label), ['M1 (right back button)', 'M2 (left back button)']);
  assert.equal(new Set(BUTTON_ROWS.map((b) => b.data)).size, 18);
});

test('mapping sets and picker options', () => {
  assert.deepEqual(SET_OPTIONS.map((o) => o.label), ['Gamepad', 'Desktop']);
  const o = actionOptions();
  assert.equal(o.length, ACTIONS.length + 1);
  assert.deepEqual(o[0], { data: 'factory', label: 'Factory' });
  assert.deepEqual(o[1], { data: 'nothing', label: 'Nothing' });
});

test('rowSummary shows Primary / Secondary with Factory for factory', () => {
  const labels = actionLabels();
  assert.equal(rowSummary({ primary: 'factory', secondary: 'factory' }, labels), 'Factory / Factory');
  assert.equal(rowSummary({ primary: 'a', secondary: 'screenshot' }, labels), 'A / Screenshot');
  assert.equal(rowSummary({ primary: 'b', secondary: 'factory' }, labels, true), 'B');
  assert.equal(rowSummary(undefined, labels), 'Factory / Factory');
});

test('buttonSummary: back buttons show the switch while on, else the Primary only', () => {
  const labels = actionLabels();
  const st = { m1_secondary: true, m2_secondary: false };
  const e = { primary: 'b', secondary: 'factory' };
  assert.equal(buttonSummary('back_right', e, st, labels), 'Use as secondary function');
  assert.equal(buttonSummary('back_left', e, st, labels), 'B');
  assert.equal(buttonSummary('a', e, st, labels), 'B / Factory');
});

test('primaryEnabled is false only for a back button whose switch is on', () => {
  const st = { m1_secondary: true, m2_secondary: false };
  assert.equal(primaryEnabled('back_right', st), false);
  assert.equal(primaryEnabled('back_left', st), true);
  assert.equal(primaryEnabled('a', st), true);
});

test('secondaryNote appears only when both switches are off', () => {
  const text = 'Secondary functions need a back button set to Use as secondary function.';
  assert.equal(secondaryNote({ m1_secondary: false, m2_secondary: false }), text);
  assert.equal(secondaryNote({ m1_secondary: true, m2_secondary: false }), '');
  assert.equal(secondaryNote({ m1_secondary: false, m2_secondary: true }), '');
  assert.equal(secondaryNote(undefined), '');
});

test('the button list collapses only when blocked or unavailable, not while working', () => {
  assert.equal(buttonsCollapsed('', ''), false);
  assert.equal(buttonsCollapsed(undefined, undefined), false);
  assert.equal(buttonsCollapsed('Update Overdrive', ''), true);
  assert.equal(buttonsCollapsed('', 'helper not running'), true);
});

test('nextOpen toggles a row, and never opens one while collapsed', () => {
  assert.equal(nextOpen(null, 'a', false), 'a');
  assert.equal(nextOpen('a', 'a', false), null);
  assert.equal(nextOpen('a', 'b', false), 'b');
  assert.equal(nextOpen(null, 'a', true), null);
  assert.equal(nextOpen('a', 'a', true), null);
});
