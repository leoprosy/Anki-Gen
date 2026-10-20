// Fonctions pures de la page frise (static/timeline-core.js).
// Lancer avec : node --test tests/test_timeline_ui.js
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const core = require(path.join(__dirname, '../static/timeline-core.js'));

function fakeTimers() {
  let now = 0;
  let next = 1;
  const pending = new Map();
  return {
    setTimeout(fn, ms) { const id = next++; pending.set(id, { fn, at: now + ms }); return id; },
    clearTimeout(id) { pending.delete(id); },
    advance(ms) {
      now += ms;
      for (const [id, entry] of [...pending].sort((a, b) => a[1].at - b[1].at)) {
        if (entry.at <= now) { pending.delete(id); entry.fn(); }
      }
    },
  };
}

test('debounce fires once, after the last call', () => {
  const timers = fakeTimers();
  const calls = [];
  const debounced = core.debounce((value) => calls.push(value), 250, timers);
  debounced('a');
  timers.advance(200);
  debounced('b');
  timers.advance(200);
  assert.deepEqual(calls, []);
  timers.advance(60);
  assert.deepEqual(calls, ['b']);
});

test('debounce can be cancelled or flushed', () => {
  const timers = fakeTimers();
  const calls = [];
  const debounced = core.debounce((value) => calls.push(value), 250, timers);
  debounced('a');
  debounced.cancel();
  timers.advance(500);
  assert.deepEqual(calls, []);
  debounced('b');
  debounced.flush('c');
  timers.advance(500);
  assert.deepEqual(calls, ['c']);
});

test('singleFlight runs at once, then merges the calls made while running', async () => {
  const releases = [];
  let calls = 0;
  const run = core.singleFlight(() => {
    calls += 1;
    return new Promise((resolve) => releases.push(resolve));
  });
  const first = run();
  assert.equal(calls, 1);                 // aucun délai pour une modification isolée
  run(); run(); run();                     // trois modifications pendant le rendu
  assert.equal(calls, 1);
  releases.shift()();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(calls, 2);                 // regroupées en un seul rendu suivant
  releases.shift()();
  await first;
  assert.equal(calls, 2);
  run();
  assert.equal(calls, 3);                 // de nouveau libre
  releases.shift()();
});

test('singleFlight survives a failing call', async () => {
  let calls = 0;
  const run = core.singleFlight(async () => {
    calls += 1;
    if (calls === 1) throw new Error('network');
  });
  await run();
  await run();
  assert.equal(calls, 2);
});

test('serialize writes keys in the canonical order of the schema', () => {
  const doc = {
    events: [{ label: 'Traité', date: '1860', id: 'e1', importance: 2, track: 't' }],
    title: 'Frise', schema: 'ankigen.timeline/1', lang: 'fr', tracks: [{ label: 'T', id: 't' }],
  };
  const text = core.serialize(doc);
  const parsed = JSON.parse(text);
  assert.deepEqual(Object.keys(parsed), ['schema', 'title', 'lang', 'tracks', 'events']);
  assert.deepEqual(Object.keys(parsed.events[0]), ['id', 'track', 'label', 'date', 'importance']);
  assert.deepEqual(Object.keys(parsed.tracks[0]), ['id', 'label']);
  assert.ok(text.includes('\n  "title": "Frise"'));
});

test('serialize keeps unknown keys, after the known ones', () => {
  const parsed = JSON.parse(core.serialize({ zzz: 1, schema: 's', title: 't' }));
  assert.deepEqual(Object.keys(parsed), ['schema', 'title', 'zzz']);
});

test('parsePointer and elementAt', () => {
  assert.deepEqual(core.parsePointer('/events/3/date'), ['events', '3', 'date']);
  assert.deepEqual(core.parsePointer('/a~1b/c~0d'), ['a/b', 'c~d']);
  assert.deepEqual(core.parsePointer(''), []);
  assert.deepEqual(core.elementAt('/periods/2/end'), { kind: 'periods', index: 2 });
  assert.equal(core.elementAt('/title'), null);
  assert.equal(core.elementAt('/events/x'), null);
});

const TEXT = `{
  "schema": "ankigen.timeline/1",
  "title": "Frise",
  "events": [
    {"id": "e1", "date": "1860", "label": "Traité"},
    {"id": "e2", "date": "vers 1450", "lable": "x"}
  ]
}`;

test('pointerRange selects the value at a path', () => {
  const range = core.pointerRange(TEXT, '/events/1/date');
  assert.equal(range.found, true);
  assert.equal(TEXT.slice(range.start, range.end), '"date": "vers 1450"');
});

test('pointerRange selects an unknown key with its value', () => {
  const range = core.pointerRange(TEXT, '/events/1/lable');
  assert.equal(TEXT.slice(range.start, range.end), '"lable": "x"');
});

test('pointerRange falls back inside the parent of a missing member', () => {
  const range = core.pointerRange(TEXT, '/events/1/label');
  assert.equal(range.found, false);
  assert.equal(range.start, range.end);
  assert.equal(TEXT[range.start - 1], '{');
  assert.ok(TEXT.slice(range.start).startsWith('"id": "e2"'));
});

test('pointerRange copes with prose around the JSON and with broken JSON', () => {
  const pasted = 'Voici :\n```json\n' + TEXT + '\n```';
  const range = core.pointerRange(pasted, '/title');
  assert.equal(pasted.slice(range.start, range.end), '"title": "Frise"');
  const broken = '{"title": "Frise", "events": [{"id": "e1", "date": 1860,,]}';
  const partial = core.pointerRange(broken, '/events/0/date');
  assert.equal(broken.slice(partial.start, partial.end), '"date": 1860');
  assert.deepEqual(core.pointerRange('', '/title'), { start: 0, end: 0, found: false });
});

test('lineColumnOffset follows the 1-indexed report of the server', () => {
  assert.equal(core.lineColumnOffset('ab\ncd\nef', 2, 2), 4);
  assert.equal(core.lineColumnOffset('ab\ncd', 9, 1), 5);
});

test('dates sort chronologically, BC included', () => {
  const values = ['1971-08-15', '-44-03-15', '1971', '-753', 'present', '1971-08', 'nope'];
  assert.deepEqual([...values].sort(core.compareDates),
                   ['-753', '-44-03-15', '1971', '1971-08', '1971-08-15', 'present', 'nope']);
});

test('uniqueId avoids every id of the document', () => {
  const doc = { tracks: [{ id: 'evenement' }], events: [{ id: 'evenement-2' }] };
  assert.equal(core.uniqueId(doc, 'Évènement'), 'evenement-3');
  assert.equal(core.uniqueId(doc, 'Traité de Rome'), 'traite_de_rome');
  assert.equal(core.uniqueId({}, '!!'), 'element');
});

test('renameId updates every reference', () => {
  const doc = { tracks: [{ id: 't' }], events: [{ id: 'e', track: 't' }], periods: [{ id: 'p', track: 't' }],
                links: [{ from: 'e', to: 'p' }] };
  core.renameId(doc, 't', 'commerce');
  assert.equal(doc.events[0].track, 'commerce');
  assert.equal(doc.periods[0].track, 'commerce');
  core.renameId(doc, 'e', 'traite');
  assert.equal(doc.links[0].from, 'traite');
  assert.equal(core.trackUsage(doc, 'commerce'), 2);
});

test('nextPendingChunk prefers the next paragraph that cites dates, and wraps around', () => {
  const chunks = [
    { id: 1, status: 'ok', mentions: 3 },
    { id: 2, status: 'pending', mentions: 0 },
    { id: 3, status: 'pending', mentions: 4 },
    { id: 4, status: 'error', mentions: 2 },
  ];
  assert.equal(core.nextPendingChunk(chunks, 1).id, 3);
  assert.equal(core.nextPendingChunk(chunks, 3).id, 4);
  // Après le dernier, on repart du début ; un paragraphe sans date reste un recours.
  assert.equal(core.nextPendingChunk(chunks, 4).id, 3);
  const onlyDateless = [{ id: 1, status: 'ok', mentions: 1 }, { id: 2, status: 'pending', mentions: 0 }];
  assert.equal(core.nextPendingChunk(onlyDateless, 1).id, 2);
  assert.equal(core.nextPendingChunk([{ id: 1, status: 'ok', mentions: 1 }], 1), null);
});

test('partialItems : seuls les éléments datés au libellé complet', () => {
  const text = '{"tracks":[{"id":"pol","label":"Politique"}],"eras":[{"id":"era_rev","label":"Révolution","start":"1789",'
    + '"end":"1799"}],"events":[{"id":"bastille","track":"pol","date":"1789-07-14","label":"Prise de la \\"Bastille\\""},'
    + '{"id":"varennes","track":"pol","date":"1791-06","label":"Fuite à Vare';
  assert.deepEqual(core.partialItems(text), [
    { date: '1789', label: 'Révolution' },
    { date: '1789-07-14', label: 'Prise de la "Bastille"' },
  ]);
  assert.deepEqual(core.partialItems(''), []);
});

test('clock : minutes et secondes', () => {
  assert.equal(core.clock(0), '0:00');
  assert.equal(core.clock(65.9), '1:05');
});
