/* Dependency-free contract check for the visual rule overview. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
  const elements = new Map(), bridgeCalls = [];
  const context = vm.createContext({
    document: {
      querySelector(selector) {
        if (!elements.has(selector)) elements.set(selector, {classList: {add(){}, remove(){}}, textContent: ''});
        return elements.get(selector);
      },
      addEventListener(){},
    },
    window: {wayricad: {postMessage(value) {bridgeCalls.push(JSON.parse(value));}}, addEventListener(){}},
    setTimeout(){return 1;}, clearTimeout(){},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/studio.js'), 'utf8'), context);
  context.fixture = {
    rules: [{index: 0, name: 'USB pair', enabled: true, layer: 'F.Cu', condition: '', constraints: [{kind: 'track_width', values: {min: '0.15mm'}}]}],
    specs: [{key: 'track_width', label: 'Track width', category: 'Routing', fields: ['min', 'opt', 'max']}],
    summary: {enabled: 1, rules: 1, errors: 0, warnings: 0, changed: []},
    classes: [], components: [], nets: [], regions: [], layers: ['F.Cu'], dirty: false,
  };
  vm.runInContext('state=fixture', context);
  const overview = vm.runInContext('workspacePage()', context);
  assert.match(overview, /Edit rules in KiCad/);
  assert.match(overview, /Tools &gt; Design Rule Editor/);
  assert.match(overview, /0\.15mm/);
  assert.doesNotMatch(overview, /data-(?:action="(?:new-rule|edit-rule|delete|duplicate|move-up|move-down|scope-builder)"|toggle|value|class|setting)/);
  assert.equal(vm.runInContext('typeof netclassesPage', context), 'undefined');
  assert.equal(vm.runInContext('typeof ruleForm', context), 'undefined');
  assert.equal(vm.runInContext('availableViews.has("netclasses")', context), false);
  await assert.rejects(vm.runInContext('action("edit-rule")', context), /Design Rule Editor/);
  assert.deepEqual(bridgeCalls, []);
  console.log('Read-only rule overview and stale generic editor guard passed.');
}

main().catch(error => {console.error(error); process.exitCode = 1;});
