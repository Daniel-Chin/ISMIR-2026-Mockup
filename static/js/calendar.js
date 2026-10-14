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
            // Grow the container until the time grid fits, so only the page scrolls.
            // Skips hidden calendars (desktop on mobile and vice versa); resize refits.
            const fitHeight = (cal, container) => {
                cal.render(true);
                const grid = $(container + ' .tui-full-calendar-timegrid-container')[0];
                if (!grid || !grid.clientHeight) return;
                const overflow = grid.scrollHeight - grid.clientHeight;
                if (overflow <= 0) return;
                const el = $(container)[0];
                el.style.height = (el.offsetHeight + overflow) + 'px';
                cal.render(true);
            };
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
                    hourStart: min_hours,
                    hourEnd: max_hours,
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
                        return '<strong>' + moment(schedule.start.getTime())
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

            all_cals.push([calendar, '#calendar']);

            const cols = config.calendar.colors;
            if (cols) {
                const cals = [];
                Object.keys(cols).forEach(k => cals.push(calendarStyle(k, cols[k])))

                calendar.setCalendars(cals);

            }


            const week_dates = enumerateDaysBetweenDates(
              calendar.getDateRangeStart().toDate(),
              calendar.getDateRangeEnd().toDate())

            const c_sm = d3.select('#calendar_small')
            let i = 0
            for (const day of week_dates) {
                c_sm.append('div').attr('id', 'cal__' + i);
                const cal = new Calendar('#cal__' + i, {
                    defaultView: 'day',
                    week: { hourStart: min_hours, hourEnd: max_hours },
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

                all_cals.push([cal, '#cal__' + i]);
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


            const fitAll = () => all_cals.forEach(([c, container]) => fitHeight(c, container));
            fitAll();
            $(window).on('resize', _.debounce(function () {
                const pageScroll = window.scrollY;
                fitAll();
                window.scrollTo(window.scrollX, pageScroll);
            }, 100));
            // d3.selectAll('.tui-full-calendar-vlayout-area').attr('style',null);
        })

    })
}

$(window).ready(function() {

})
