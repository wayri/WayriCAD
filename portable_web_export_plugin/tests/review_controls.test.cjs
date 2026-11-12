const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../resources/review_controls.js'), 'utf8'), context);
const review = context.WayriCADPortableReview;
const component = {id:'board-id',boardUuid:'board-id',schematicUuids:['symbol-id'],reference:'U1'};

test('cross-probe never chooses the first duplicate UUID or conflicting reference', () => {
  const part = {id:'board#board-id',uuid:'board-id',reference:'U1'};
  assert.equal(review.findPart(component,[part]),part);
  assert.equal(review.findPart(component,[part,{...part}]),null);
  assert.equal(review.findPart(component,[{...part,uuid:'unrelated'}]),null);
  assert.equal(review.findPart(component,[{id:'symbol',uuid:'symbol-id',reference:'OTHER'}]).id,'symbol');
  const noIdentity = {reference:'U1',schematicUuids:[]};
  assert.equal(review.findPart(noIdentity,[{reference:'U1'},{reference:'U1'}]),null);
  assert.equal(review.componentForItem({uuid:'board-id'},[component,{...component}]),null);
  assert.equal(review.componentForItem({uuid:'different',reference:'U1'},[component]),null);
  assert.equal(review.componentForItem({ownerUuid:'board-id',uuid:'pad'},[component]),component);
});

test('exact part and net lookup rejects substrings, case changes and duplicate names', () => {
  const parts = [{id:'a',uuid:'uuid-a',reference:'R1'},{id:'b',uuid:'uuid-b',reference:'R10'}];
  assert.equal(review.exactMatch(parts,'R1',['id','uuid'],'reference').item.id,'a');
  assert.equal(review.exactMatch(parts,'R',['id','uuid'],'reference').count,0);
  assert.equal(review.exactMatch(parts,'r1',['id','uuid'],'reference').count,0);
  assert.equal(review.exactMatch([...parts,{id:'c',reference:'R1'}],'R1',['id'],'reference').item,null);
  const nets = [{id:'board/net:1',name:'GND'},{id:'board/net:2',name:'GND'}];
  assert.equal(review.exactMatch(nets,'GND',['id'],'name').item,null);
  assert.equal(review.exactMatch(nets,'board/net:2',['id'],'name').item.id,'board/net:2');
});

test('malicious saved labels are text nodes, never HTML', () => {
  const labels = ['<img src=x onerror=alert(1)>','</script><script>bad()</script>','A & B'];
  const children = [], node = {replaceChildren(){children.length=0;},append(child){children.push(child);},
    ownerDocument:{createElement(){return {set innerHTML(value){throw Error('Unsafe HTML');}};}}};
  review.showSelection(node,labels);
  assert.deepEqual(children.map(child=>child.textContent),labels);
});

test('progress rows keep known stable keys and reject executable/coercible state', () => {
  const rows = review.trackingRows({'board-id':{notes:'<img onerror=bad()>',orderedQty:2},unknown:{notes:'ignore'}},[component]);
  assert.equal(Object.keys(rows).join(','),'board-id');
  assert.equal(rows['board-id'].orderedQty,2);
  assert.equal(rows['board-id'].notes,'<img onerror=bad()>');
  for(const value of [{orderedQty:-1},{receivedQty:'<img>'},{assembly:'<script>'},{dnp:'yes'},{notes:{}}]) {
    assert.throws(()=>review.trackingRows({'board-id':value},[component]));
  }
});
