// Run with node --test tests/test_update_ui.js.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const template = fs.readFileSync(path.join(__dirname, '../templates/base.html'), 'utf8');
const script = template.slice(template.indexOf('    const updBanner'), template.lastIndexOf('  </script>'));

function ui(check, apply, failRestart = false) {
  const elements = {};
  for (const id of ['update-banner', 'update-btn', 'update-message', 'update-dismiss']) {
    elements[id] = { style: {}, addEventListener(event, fn) { this[event] = fn; } };
  }
  const requests = [];
  const commands = [];
  const context = vm.createContext({
    document: { getElementById: id => elements[id] },
    window: {
      T: key => key,
      addEventListener() {},
      __TAURI__: { core: { invoke: async command => {
        commands.push(command);
        if (failRestart) throw new Error('restart failed');
      } } },
    },
    fetch: async url => {
      requests.push(url);
      return { json: async () => url.endsWith('/check') ? check : apply };
    },
  });
  vm.runInContext(script, context);
  return { elements, requests, commands, check: () => vm.runInContext('checkUpdate()', context) };
}

test('download changes the button to a native restart, without downloading twice', async () => {
  const state = ui({ update_available: true }, { status: 'staged', message: 'Ready' });
  await state.check();
  await state.elements['update-btn'].click();
  assert.equal(state.elements['update-btn'].textContent, 'js.restart_app');
  assert.equal(state.elements['update-btn'].disabled, false);
  await state.elements['update-btn'].click();
  assert.deepEqual(state.commands, ['restart_app']);
  assert.deepEqual(state.requests, ['/api/update/check', '/api/update/apply']);
});

test('page navigation restores restart and a failed restart can be retried', async () => {
  const state = ui({ restart_required: true, message: 'Ready' }, null, true);
  await state.check();
  await state.elements['update-btn'].click();
  assert.equal(state.elements['update-btn'].disabled, false);
  assert.equal(state.elements['update-message'].textContent, 'js.restart_failed');
  assert.deepEqual(state.requests, ['/api/update/check']);
});

test('an up-to-date check leaves the update banner hidden', async () => {
  const state = ui({ update_available: false });
  await state.check();
  assert.notEqual(state.elements['update-banner'].style.display, 'flex');
});

test('an update needing a new installer opens the installer page instead of downloading', async () => {
  const state = ui({ installer_required: true, message: 'Needs installer' });
  await state.check();
  assert.equal(state.elements['update-banner'].style.display, 'flex');
  assert.equal(state.elements['update-message'].textContent, 'Needs installer');
  assert.equal(state.elements['update-btn'].textContent, 'js.get_installer');
  await state.elements['update-btn'].click();
  assert.deepEqual(state.requests, ['/api/update/check', '/api/update/open-installer']);
  assert.deepEqual(state.commands, []);
});

test('apply answering installer_required switches the banner to the installer', async () => {
  const state = ui({ update_available: true }, { status: 'installer_required', message: 'Needs installer' });
  await state.check();
  await state.elements['update-btn'].click();
  assert.equal(state.elements['update-btn'].textContent, 'js.get_installer');
  await state.elements['update-btn'].click();
  assert.deepEqual(state.requests,
    ['/api/update/check', '/api/update/apply', '/api/update/open-installer']);
});
