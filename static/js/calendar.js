// config.yml calendar.colors: {bg, border} per category (a plain colour string also works).
function calendarStyle(id, v) {
    const bg = typeof v === 'string' ? v : v.bg;
    const border = typeof v === 'string' ? v : (v.border || v.bg);
    return { id: id, name: id, bgColor: bg, dragBgColor: bg, borderColor: border, color: '#1f2933' };
}

function make_cal(name) {

    // console.log(location.search, "--- location.search");

    const current_tz = getUrlParameter('tz') || moment.tz.guess();
    const tzNames = [...moment.tz.names()];
    // console.log(current_tz);

    const eventTitle = schedule => {
        const className = schedule.raw && schedule.raw.endTimeTbd
            ? 'calendar-end-tbd' : '';
        return `<span class="${className}">${schedule.title}</span>`;
    };

    // POSIX inverts the sign: Etc/GMT+1 is UTC-1.
    const tzLabel = name => {
        const m = name.match(/^Etc\/GMT([+-]\d+)$/);
        if (!m) return name;
        const offset = -Number(m[1]);
        return `UTC${offset > 0 ? '+' : '-'}${Math.abs(offset)} (${name})`;
    };

    const setupTZSelector = () => {
        const tzOptons = d3.select('#tzOptions')
        tzOptons.selectAll('option').data(tzNames)
          .join('option')
          .attr('value', d => d)
          .attr('data-tokens', d => tzLabel(d).split("/").join(" "))
          .text(tzLabel)
        $('.selectpicker')
          .selectpicker('val', current_tz)
          .on('changed.bs.select',
            function (e, clickedIndex, isSelected, previousValue) {
                new_tz = tzNames[clickedIndex]
                window.open(window.location.pathname+'?tz='+encodeURIComponent(new_tz), '_self');
            })

    }

    setupTZSelector();

    $.get('serve_config.json').then(config => {
        $.get(name).then(utcEvents => {
            const all_cals = [];
            const timezoneName = current_tz;

            // tui.Calendar lays out days and hours in the browser's timezone, so hand it
            // display-tz wall-clock times disguised as browser-local times.
            const toWallClock = t => moment(moment(t).tz(timezoneName).format('YYYY-MM-DDTHH:mm:ss')).toDate();
            // Split events at midnight so each piece sits in one day column.
            const events = [];
            utcEvents.forEach(e => {
                const start = toWallClock(e.start);
                const end = toWallClock(e.end);
                const raw = {...e.raw, wallStart: start};
                let pieceStart = start;
                let i = 0;
                while (pieceStart < end) {
                    const midnight = moment(pieceStart).startOf('day').add(1, 'day').toDate();
                    const pieceEnd = end < midnight ? end : midnight;
                    events.push({...e, id: i ? `${e.id}-${i}` : e.id, start: pieceStart, end: pieceEnd, raw});
                    pieceStart = pieceEnd;
                    i++;
                }
            });
            // Label the axis with the display tz without tui shifting it.
            const timezones = [{
                timezoneOffset: -d3.min(events, e => e.start).getTimezoneOffset(),
                displayLabel: tzLabel(timezoneName),
                tooltip: timezoneName,
            }];

            // Hour ranges of the y axis: one range, or two around the largest empty stretch.
            const hourRangesOf = evs => {
                const covered = new Array(24).fill(false);
                evs.forEach(e => {
                    const from = e.start.getHours();
                    const to = moment(e.end).diff(moment(e.start).startOf('day'), 'minutes') / 60;
                    for (let h = from; h < to; h++) covered[h] = true;
                });
                if (!covered.some(c => c)) return [[0, 24]];
                let gapStart = 0, gapLen = 0;
                for (let s = 0; s < 24; s++) {
                    if (covered[s] || !covered[(s + 23) % 24]) continue;
                    let len = 0;
                    while (!covered[(s + len) % 24]) len++;
                    if (len > gapLen) [gapStart, gapLen] = [s, len];
                }
                const pad = 1;
                if (gapLen <= 2 * pad + 1) return [[0, 24]];
                const gapEnd = gapStart + gapLen;
                if (gapStart === 0 || gapEnd >= 24) {
                    const from = gapEnd % 24, to = gapStart || 24;
                    return [[Math.max(0, from - pad), Math.min(24, to + pad)]];
                }
                return [[0, gapStart + pad], [gapEnd - pad, 24]];
            };

            // In each day with SIDE_LANE events, they get a column of their own on the right, instead of
            // halving whatever they overlap. The rest are laid out again in what is left: side by side
            // only where they overlap one another (tui.Calendar counted the lane's events too).
            const SIDE_LANE = 'Majlis', SIDE_LANE_WIDTH = 30;   // a calendarId (category); percent
            const layOutSideLane = container => {
                $(container + ' .tui-full-calendar-time-date').each((_, day) => {
                    const blocks = [...day.querySelectorAll('.tui-full-calendar-time-date-schedule-block')];
                    const inLane = b => b.querySelector(`[data-calendar-id="${SIDE_LANE}"]`);
                    if (!blocks.some(inLane)) return;
                    const rest = 100 - SIDE_LANE_WIDTH;
                    const place = (b, left, width) => { b.style.left = left + '%'; b.style.width = width + '%'; };
                    blocks.filter(inLane).forEach(b => place(b, rest, SIDE_LANE_WIDTH));
                    const others = blocks.filter(b => !inLane(b)).map(b => ({ b, top: parseFloat(b.style.top), bottom: parseFloat(b.style.top) + parseFloat(b.style.height) }))
                        .sort((x, y) => x.top - y.top);
                    // Clusters of overlapping events; in each, every event takes the first free column.
                    for (let i = 0; i < others.length;) {
                        const cluster = [], columnEnds = [];
                        let end = -Infinity;
                        for (; i < others.length && (!cluster.length || others[i].top < end); i++) {
                            const o = others[i];
                            o.column = columnEnds.findIndex(e => e <= o.top);
                            if (o.column < 0) o.column = columnEnds.length;
                            columnEnds[o.column] = o.bottom;
                            end = Math.max(end, o.bottom);
                            cluster.push(o);
                        }
                        cluster.forEach(o => place(o.b, o.column * rest / columnEnds.length, rest / columnEnds.length));
                    }
                });
            };
            const render = (cal, container) => {
                cal.render(true);
                layOutSideLane(container);
            };

            // Grow the container until the time grid fits, so only the page scrolls.
            // Skips hidden calendars (desktop on mobile and vice versa); resize refits.
            const fitHeight = (cal, container) => {
                render(cal, container);
                const grid = $(container + ' .tui-full-calendar-timegrid-container')[0];
                if (!grid || !grid.clientHeight) return;
                const overflow = grid.scrollHeight - grid.clientHeight;
                if (overflow <= 0) return;
                const el = $(container)[0];
                el.style.height = (el.offsetHeight + overflow) + 'px';
                render(cal, container);
            };
            // tui.Calendar pins a current-time line outside the hour range to the grid's edge, and
            // rewrites the line's top on every render and minute tick.
            const hideOutOfRangeHourMarkers = container => {
                new MutationObserver(() => {
                    $(container + ' .tui-full-calendar-timegrid-hourmarker').each((_, marker) => {
                        const display = ['0%', '100%'].includes(marker.style.top) ? 'none' : '';
                        if (marker.style.display !== display) marker.style.display = display;
                    });
                }).observe($(container)[0], { subtree: true, childList: true, attributes: true, attributeFilter: ['style'] });
            };
            const Calendar = tui.Calendar;
            // tui.Calendar v1 weeks are always 7 days; show only the days with events.
            const firstDay = moment(d3.min(events, e => e.start)).startOf('day').toDate();
            const lastDay = moment(d3.max(events, e => e.end)).subtract(1, 'ms').startOf('day').toDate();
            const numDays = moment(lastDay).diff(moment(firstDay), 'days') + 1;
            const weekDayRange = Calendar.prototype._getWeekDayRange;
            Calendar.prototype._getWeekDayRange = function () {
                const [start] = weekDayRange.call(this, firstDay, firstDay.getDay(), false);
                return [start, new start.constructor(start).addDate(numDays - 1)];
            };

            const timeTemplate = schedule => '<strong>'
                + moment(schedule.raw.wallStart).format('HH:mm') + '</strong> ' + eventTitle(schedule);

            // One calendar instance per hour range, stacked with a zig-zag break between.
            const addCalendars = (parent, id, evs, options, setup) => {
                hourRangesOf(evs).forEach(([hourStart, hourEnd], i) => {
                    if (i > 0) parent.append('div').attr('class', 'calendar-break');
                    const container = `${id}-${i}`;
                    const opts = {...options, week: {...options.week, hourStart, hourEnd}};
                    if (i > 0) opts.theme = {...opts.theme, 'week.dayname.height': '0px'};
                    // Start at the grid's own height; fitHeight only grows, and skips a grid squeezed to 0.
                    const theme = opts.theme || {};
                    const px = (key, fallback) => parseInt(theme[key] || fallback);
                    const height = px('week.dayname.height', '42px')
                        + (hourEnd - hourStart) * px('week.timegridOneHour.height', '52px');
                    parent.append('div').attr('id', container.slice(1))
                        .attr('class', i > 0 ? 'calendar-continued' : null)
                        .style('height', height + 'px');
                    const cal = new Calendar(container, opts);
                    setup(cal);
                    cal.createSchedules(events);
                    const cols = config.calendar.colors;
                    if (cols) cal.setCalendars(Object.keys(cols).map(k => calendarStyle(k, cols[k])));
                    hideOutOfRangeHourMarkers(container);
                    all_cals.push([cal, container]);
                });
            };

            addCalendars(d3.select('#calendar'), '#calendar', events, {
                defaultView: 'week',
                isReadOnly: true,
                taskView: false,
                scheduleView: ['time'],
                usageStatistics: false,
                week: {
                    daynames: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
                    startDayOfWeek: firstDay.getDay(),
                },
                timezones,
                theme: {
                  'week.dayname.height': '42px',
                  'week.timegridOneHour.height': '68px',
                },
                template: {
                    timegridDisplayPrimaryTime: function (time) {
                      var hour = time.hour < 10 ? `0${time.hour}` : time.hour;
                      var min = time.minutes === 0 ? '00' : time.minutes;
                      return hour + ':' + min;
                    },
                    time: timeTemplate,
                    weekDayname: function (model) {
                        const date = moment(model.renderDate, 'YYYY-MM-DD').format('MMM D');
                        return '<span class="tui-full-calendar-dayname-name">' + date + ' (' + model.dayName + ')</span>';
                    },
                },
            }, cal => {
                cal.setDate(firstDay);
                cal.on('clickSchedule', e => {
                    const s = e.schedule;
                    const newTab = e.event.ctrlKey || e.event.metaKey;
                    if (s.location.length > 0) window.open(s.location, newTab ? '_blank' : '_self');
                });
            });

            const c_sm = d3.select('#calendar_small');
            for (let i = 0; i < numDays; i++) {
                const day = moment(firstDay).add(i, 'days').toDate();
                const dayEvents = events.filter(e => moment(e.start).isSame(day, 'day'));
                addCalendars(c_sm.append('div').attr('class', 'calendar-day'), '#cal__' + i, dayEvents, {
                    defaultView: 'day',
                    template: { time: timeTemplate },
                    isReadOnly: true,
                    taskView: false,
                    scheduleView: ['time'],
                    usageStatistics: false,
                    timezones,
                }, cal => {
                    cal.setDate(day);
                    cal.on('clickSchedule', e => {
                        const s = e.schedule;
                        if (s.location.length > 0) {
                            if (s.location.split("-")[0] === 'tab') {
                              var location = s.location.split("|");
                              $('.nav-pills .nav-item .nav-link').eq(location[1]).trigger('click');
                              $(`#tab-${location[1]} #day .${location[location.length - 1]}`)[0].scrollIntoView();
                              $('html')[0].scrollTop -= 150;
                            } else {
                              window.open(s.location, '_blank');
                            }
                        }
                    });
                });
            }

            const fitAll = () => all_cals.forEach(([c, container]) => fitHeight(c, container));
            fitAll();
            $(window).on('resize', _.debounce(function () {
                const pageScroll = window.scrollY;
                fitAll();
                window.scrollTo(window.scrollX, pageScroll);
            }, 100));
        })

    })
}

$(window).ready(function() {

})
