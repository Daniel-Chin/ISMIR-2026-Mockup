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
    let localStart = 7 // 07:00 local time
    let startOffsets = [0,0]

    const eventTitle = schedule => {
        const className = schedule.raw && schedule.raw.endTimeTbd
            ? 'calendar-end-tbd' : '';
        return `<span class="${className}">${schedule.title}</span>`;
    };

    const setupTZSelector = () => {
        const tzOptons = d3.select('#tzOptions')
        tzOptons.selectAll('option').data(tzNames)
          .join('option')
          .attr('data-tokens', d => d.split("/").join(" "))
          .text(d => d)
        $('.selectpicker')
          .selectpicker('val', current_tz)
          .on('changed.bs.select',
            function (e, clickedIndex, isSelected, previousValue) {
                new_tz = tzNames[clickedIndex]
                window.open(window.location.pathname+'?tz='+new_tz, '_self');
            })

    }

    setupTZSelector();

    // requires moments.js
    const enumerateDaysBetweenDates = function (startDate, endDate) {
        const dates = [];

        // console.log(startDate, endDate, "--- startDate, endDate");

        const currDate = moment(startDate);
        const lastDate = moment(endDate);

        dates.push(currDate.clone());
        while (currDate.add(1, 'days').diff(lastDate) < 0) {
            // console.log(currDate, "--- currDate");
            dates.push(currDate.clone());
        }

        dates.push(lastDate);
        return dates;
    };


    $.get('serve_config.json').then(config => {
        $.get(name).then(events => {
            const scroll_ref1 = config.opening_ref_title_1;
            const scroll_ref2 = config.opening_ref_title_2;

            const all_cals = [];
            const timezoneName = current_tz;

            const min_date = d3.min(events.map(e => e.start));
            var min_hours = d3.min(events.map(e => moment(e.start).tz(timezoneName).hours())) -1;
            var max_hours = d3.max(events.map(e => moment(e.end).tz(timezoneName).hours())) +1;
            if(min_hours < 0 || max_hours > 24) {
                min_hours = 0;
                max_hours = 24;
            }
            // console.log(min_hours, max_hours);
            const Calendar = tui.Calendar;
            // tui.Calendar v1 weeks are always 7 days; show only the conference days.
            const [firstDay, lastDay] = config.calendar_days.map(d => moment(d).toDate());
            const numDays = moment(lastDay).diff(moment(firstDay), 'days') + 1;
            const weekDayRange = Calendar.prototype._getWeekDayRange;
            Calendar.prototype._getWeekDayRange = function () {
                const [start] = weekDayRange.call(this, firstDay, firstDay.getDay(), false);
                return [start, new start.constructor(start).addDate(numDays - 1)];
            };
            const calendar = new Calendar('#calendar', {
                defaultView: 'week',
                isReadOnly: true,
                // useDetailPopup: true,
                taskView: false,
                scheduleView: ['time'],
                usageStatistics: false,
                // useDetailPopup: true,
                week: {
                    // workweek: !config.calendar["sunday_friday"],
                    daynames: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
                    startDayOfWeek: firstDay.getDay(),
                    // hourStart: min_hours,
                    // hourEnd: max_hours,
                    // narrowWeekend: true,
                },
                timezones: [{
                    timezoneOffset: -moment.tz.zone(timezoneName)
                      .utcOffset(moment(min_date)),
                    displayLabel: timezoneName,
                    tooltip: timezoneName
                }],
                theme: {
                  'week.dayname.height': '42px',
                  'week.timegridOneHour.height': '68px',
                  // 'week.dayGridSchedule.height': '100px',
                },
                // timezones: [{
                //     getTimezoneOffset: 540,
                //     displayLabel: 'a',
                //     tooltip: timezoneName
                // }],
                template: {
                    monthDayname: function (dayname) {
                        return '<span class="calendar-week-dayname-name">' + dayname.label + '</span>';
                    },
                    timegridDisplayPrimaryTime: function (time) {
                      // var meridiem = time.hour < 12 ? 'am' : 'pm';
                      var hour = time.hour < 10 ? `0${time.hour}` : time.hour;
                      var min = time.minutes === 0 ? '00' : time.minutes;
                      return hour + ':' + min;
                    },
                    time: function (schedule) {
                        var class_name=""
                        if (schedule.title == scroll_ref1) {
                          startOffsets[0] = parseInt(moment(schedule.start.getTime())
                            .tz(timezoneName)
                            .format('HH')) + parseInt(moment(schedule.start.getTime())
                            .tz(timezoneName)
                            .format('mm')) / 60 - localStart;
                          class_name = 'openingA';
                          // console.log(startOffsets);
                        } else if (schedule.title == scroll_ref2) {
                          startOffsets[1] = parseInt(
                            moment(schedule.start.getTime())
                            .tz(timezoneName)
                            .format('HH')) + parseInt(
                            moment(schedule.start.getTime())
                            .tz(timezoneName)
                            .format('mm')) / 60 - localStart;
                          class_name = 'openingB';
                          // console.log(startOffsets);
                        }
                        return `<strong class=${class_name}>` + moment(schedule.start.getTime())
                          .tz(timezoneName)
                          .format('HH:mm') + '</strong> ' + eventTitle(schedule);
                    },
                    milestone: function (schedule) {
                        return '<span class="calendar-font-icon ic-milestone-b"></span> <span style="background-color: ' + schedule.bgColor + '"> M: ' + schedule.title + '</span>';
                    },
                    weekDayname: function (model) {
                        const date = moment(model.renderDate, 'YYYY-MM-DD').format('MMM D');
                        return '<span class="tui-full-calendar-dayname-name">' + date + ' (' + model.dayName + ')</span>';
                    },
                },
            });
            calendar.setDate(firstDay);
            calendar.createSchedules(events);
            calendar.on({
                'clickSchedule': function (e) {
                    const s = e.schedule;
                    if (s.location.length > 0) {
                        window.open(s.location, '_self');
                    }
                },
            })

            all_cals.push(calendar);

            const cols = config.calendar.colors;
            if (cols) {
                const cals = [];
                Object.keys(cols).forEach(k => cals.push(calendarStyle(k, cols[k])))

                calendar.setCalendars(cals);

            }


            const week_dates = enumerateDaysBetweenDates(
              calendar.getDateRangeStart().toDate(),
              calendar.getDateRangeEnd().toDate())

            // Re-rendering rebuilds the time grids, so keep the user's scroll position.
            let isResizing = false;
            const c_sm = d3.select('#calendar_small')
            let i = 0
            for (const day of week_dates) {
                c_sm.append('div').attr('id', 'cal__' + i);
                const cal = new Calendar('#cal__' + i, {
                    defaultView: 'day',
                    template: {
                        time: function (schedule) {
                            return '<strong>' + moment(schedule.start.getTime())
                                .tz(timezoneName).format('HH:mm')
                                + '</strong> ' + eventTitle(schedule);
                        },
                    },
                    isReadOnly: true,
                    // useDetailPopup: true,
                    taskView: false,
                    scheduleView: ['time'],
                    usageStatistics: false,

                    timezones: [{
                        timezoneOffset: -moment.tz.zone(timezoneName)
                          .utcOffset(moment(min_date)),
                        displayLabel: timezoneName,
                        tooltip: timezoneName
                    }],
                })

                cal.setDate(day.toDate());
                cal.createSchedules(events);
                cal.on({
                    'clickSchedule': function (e) {
                        const s = e.schedule;
                        if (s.location.length > 0) {

                            if (s.location.split("-")[0] === 'tab') {
                              var location = s.location.split("|");
                              $('.nav-pills .nav-item .nav-link').eq(location[1]).trigger('click');
                              $(`#tab-${location[1]} #day .${location[location.length - 1]}`)[0].scrollIntoView();
                              $('html')[0].scrollTop -= 150;
                            } else {
                              window.open(s.location, '_blanket');
                            }
                        }
                    },
                })

                const dayContainer = '#cal__' + i;
                cal.on('afterRenderSchedule', function () {
                    if (isResizing) return;
                    const grid = $(dayContainer + ' .tui-full-calendar-timegrid-container')[0];
                    const blocks = $(dayContainer + ' .tui-full-calendar-time-date-schedule-block').get();
                    if (!grid || !blocks.length) return;
                    const firstTop = Math.min(...blocks.map(b => b.offsetTop));
                    grid.scrollTop = Math.max(firstTop - 20, 0);
                });

                all_cals.push(cal);
                const cols = config.calendar.colors;
                if (cols) {
                    const cals = [];
                    Object.keys(cols).forEach(k => cals.push(calendarStyle(k, cols[k])))

                    cal.setCalendars(cals);

                }

                i++;

                // console.log(day.format(), "--- day");
            }

            // console.log(week_dates.map(d => d.format()), "--- week_dates ");


            $(window).on('resize', _.debounce(function () {
                isResizing = true;
                const pageScroll = window.scrollY;
                const gridScrolls = $('.tui-full-calendar-timegrid-container')
                  .map((_i, el) => el.scrollTop).get();
                all_cals.forEach(c => c.render(true));
                setTimeout(function () {
                    $('.tui-full-calendar-timegrid-container').each(function (i, el) {
                        if (i < gridScrolls.length) el.scrollTop = gridScrolls[i];
                    });
                    window.scrollTo(window.scrollX, pageScroll);
                    isResizing = false;
                }, 0);
            }, 100));
            calendar.on('afterRenderSchedule', function() {
              if (isResizing) {
                return;
              }
              // console.log(startOffsets);
              const contain = $('#calendar .tui-full-calendar-timegrid-container');
              if (!contain.length) {
                return;
              }

              const openingABlocks = $('#calendar .openingA').parents('.tui-full-calendar-time-date-schedule-block');
              const openingBBlocks = $('#calendar .openingB').parents('.tui-full-calendar-time-date-schedule-block');
              const fallbackBlocks = $('#calendar .tui-full-calendar-time-date-schedule-block');

              let targetBlock = null;

              if (startOffsets[0] < -3 || startOffsets[0] >= 11) {
                targetBlock = openingBBlocks[0] || openingABlocks[0] || fallbackBlocks[0];
              }
              else {
                targetBlock = openingABlocks[0] || openingBBlocks[0] || fallbackBlocks[0];
              }

              if (!targetBlock || typeof targetBlock.offsetTop !== 'number') {
                return;
              }

              contain.scrollTop(Math.max(targetBlock.offsetTop - 20, 0));
            });
            // d3.selectAll('.tui-full-calendar-vlayout-area').attr('style',null);
        })

    })
}

$(window).ready(function() {

})
