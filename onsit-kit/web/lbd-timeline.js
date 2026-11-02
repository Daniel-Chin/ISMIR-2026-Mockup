// A screen's plan as a timeline. A play is [timetable][poster][video]; times are seconds from the start.
const Timeline = {
  build(plan) {
    let cursor = 0;
    const items = plan.plays.map((uid, index) => {
      const item = {
        index,
        uid,
        start: cursor,
        posterAt: cursor + plan.timetable_s,
        videoAt: cursor + plan.timetable_s + plan.poster_s,
      };
      cursor = item.end = item.videoAt + (plan.seconds[uid] || 0);
      return item;
    });
    return { items, total: cursor };
  },

  // What is on screen `elapsed` seconds after the start.
  locate(timeline, elapsed) {
    if (elapsed < 0) return { phase: 'before', item: timeline.items[0], offset: elapsed };
    const item = timeline.items.find((candidate) => elapsed < candidate.end);
    if (!item) return { phase: 'done', item: null, offset: elapsed - timeline.total };
    if (elapsed >= item.videoAt) return { phase: 'video', item, offset: elapsed - item.videoAt };
    if (elapsed >= item.posterAt) return { phase: 'poster', item, offset: elapsed - item.posterAt };
    return { phase: 'timetable', item, offset: elapsed - item.start };
  },

  // The index of the play on screen, or -1 outside the run. Plays up to it are history.
  currentIndex(plan, nowMs) {
    const position = Timeline.locate(Timeline.build(plan), (nowMs - plan.start_ms) / 1000);
    return position.item && position.phase !== 'before' ? position.item.index : -1;
  },

  // A start time that keeps what is on screen where it is when `edited` replaces `plan`, so
  // changing the poster time or anything earlier does not make the player jump.
  reanchor(plan, edited, nowMs) {
    const position = Timeline.locate(Timeline.build(plan), (nowMs - plan.start_ms) / 1000);
    if (!position.item || position.phase === 'before') return plan.start_ms;
    const mark = position.phase === 'video' ? 'videoAt' : 'start';
    const after = Timeline.build(edited).items[position.item.index];
    return plan.start_ms + (position.item[mark] - after[mark]) * 1000;
  },

  // The poster seconds that make the rest of the run end when the slot does, at most.
  fitPoster(plan, slotS, nowMs) {
    const timeline = Timeline.build(plan);
    const current = Timeline.currentIndex(plan, nowMs);
    const rest = timeline.items.slice(current + 1);
    if (!rest.length) return plan.poster_s;
    const used = current < 0 ? 0 : timeline.items[current].end;
    const videos = rest.reduce((sum, item) => sum + (plan.seconds[item.uid] || 0), 0);
    return Math.max(0, Math.floor((slotS - used - videos - rest.length * plan.timetable_s) / rest.length));
  },
};

if (typeof module !== 'undefined') module.exports = Timeline;
