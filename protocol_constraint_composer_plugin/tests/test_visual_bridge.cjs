/* Run with node: bounded message waits and focus refresh concurrency. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function main() {
  const elements = new Map(), handlers = {}, timers = new Map(), messages = [];
  let timerId = 0;
  const context = vm.createContext({
    console,
    document: {querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {classList: {add(){}, remove(){}}, textContent: ''});
      return elements.get(selector);
    }, addEventListener() {}},
    window: {wayricad: {postMessage(value) {messages.push(JSON.parse(value));}},
      addEventListener(name, callback) {handlers[name] = callback;}},
    setTimeout(callback) {const id = ++timerId; timers.set(id, callback); return id;},
    clearTimeout(id) {timers.delete(id);},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/studio.js'), 'utf8'), context);
  const read = vm.runInContext("call('snapshot')", context);
  context.window.studio.receive(messages[0].id, {ok: true, value: 'ready'});
  assert.equal(await read, 'ready');
  assert.equal(timers.size, 0);

  const lost = vm.runInContext("call('save_rule')", context);
  const rejected = assert.rejects(lost, /native worksheet.*staged changes/);
  for (const [id, callback] of timers) {timers.delete(id); callback();}
  await rejected;
  assert.equal(vm.runInContext('pending.size', context), 0);
  context.window.studio.receive(messages[1].id, {ok: true, value: 'late'});
  assert.equal(messages.length, 2); // A timed-out mutation is never replayed.

  context.window.wayricad.postMessage = () => {throw new Error('broken transport');};
  await assert.rejects(vm.runInContext("call('snapshot')", context), /broken transport/);
  assert.equal(timers.size, 0);
  assert.equal(vm.runInContext('pending.size', context), 0);

  vm.runInContext('state={}; let refreshCount=0, finishRefresh; refresh=()=>{refreshCount++; return new Promise(resolve=>{finishRefresh=resolve;});};', context);
  const first = handlers.focus();
  await handlers.focus();
  assert.equal(vm.runInContext('refreshCount', context), 1);
  vm.runInContext('finishRefresh()', context);
  await first;
  const next = handlers.focus();
  assert.equal(vm.runInContext('refreshCount', context), 2);
  vm.runInContext('finishRefresh()', context);
  await next;
  console.log('Constraint visual bridge: response, timeout, transport failure, late response and focus concurrency passed.');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
