// node --test onsite-kit/test_timeline.cjs
const assert = require('node:assert');
const test = require('node:test');
const Timeline = require('./web/lbd-timeline.js');

const plan = {
  plays: ['a', 'b', 'c'], timetable_s: 8, poster_s: 20, start_ms: 1000000,
  seconds: { a: 100, b: 200, c: 300 },
};
const at = (seconds) => plan.start_ms + seconds * 1000;

test('a play runs timetable, poster, video', () => {
  const timeline = Timeline.build(plan);
  assert.strictEqual(timeline.total, 684);
  const expected = [
    [-5, 'before', 'a'], [0, 'timetable', 'a'], [8, 'poster', 'a'], [28, 'video', 'a'], [127, 'video', 'a'],
    [128, 'timetable', 'b'], [683, 'video', 'c'], [684, 'done', null],
  ];
  for (const [elapsed, phase, uid] of expected) {
    const position = Timeline.locate(timeline, elapsed);
    assert.strictEqual(position.phase, phase);
    assert.strictEqual(position.item && position.item.uid, uid);
  }
  assert.strictEqual(Timeline.locate(timeline, 158).offset, 2);
});

test('no poster goes straight to the video', () => {
  const timeline = Timeline.build({ ...plan, poster_s: 0 });
  assert.strictEqual(Timeline.locate(timeline, 8).phase, 'video');
});

test('edits leave the screen where it is', () => {
  const inVideo = at(170);  // 14 s into b's video
  const start = Timeline.reanchor(plan, { ...plan, poster_s: 30 }, inVideo);
  const edited = { ...plan, poster_s: 30, start_ms: start };
  const position = Timeline.locate(Timeline.build(edited), (inVideo - start) / 1000);
  assert.deepStrictEqual([position.phase, position.item.uid, position.offset], ['video', 'b', 14]);

  const later = Timeline.reanchor(plan, { ...plan, plays: ['a', 'b'] }, inVideo);
  assert.strictEqual(later, plan.start_ms);
  assert.strictEqual(Timeline.reanchor(plan, { ...plan, poster_s: 30 }, at(-10)), plan.start_ms);
  assert.strictEqual(Timeline.reanchor(plan, { ...plan, poster_s: 30 }, at(9999)), plan.start_ms);
});

test('posters fit the slot', () => {
  assert.strictEqual(Timeline.fitPoster(plan, 900, at(-1)), 92);  // (900 - 600 - 24) / 3
  assert.strictEqual(Timeline.fitPoster(plan, 900, at(170)), 236);  // c alone: (900 - 356 - 300 - 8)
  assert.strictEqual(Timeline.fitPoster(plan, 100, at(-1)), 0);
});
