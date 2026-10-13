'''
uv run python ./scripts/make_video_unlisted_bot_companion.py
This script helps you semi-manually set all videos to "unlisted" from "draft" in case the batch edit fails on YouTube Studio.  
You need to install vimium beforehand. 
"`" and "2" are intercepted. "`" quits the script immediately.
User loop:
    click "edit" (pen icon)
    Press "2" on keyboard
    wait for the bot
'''
# Reads the keyboard via evdev and injects keys via uinput, so it works on Wayland too.
# Assumes a US keyboard layout. Needs access to /dev/input/* and /dev/uinput
# (e.g. be in the `input` group, or run with sudo).
# uv run --extra youtube python -m scripts.make_video_unlisted_bot_companion [--device /dev/input/eventN]

from __future__ import annotations

import argparse
import queue
import random
import threading
import time

import evdev
from evdev import UInput, ecodes as e

CLICK_STEP = "document.getElementById('step-badge-3').click()"
CLICK_UNLISTED = "document.querySelector('tp-yt-paper-radio-button[name=\"UNLISTED\"]').click()"

_UNSHIFTED = {
    **{c: getattr(e, f'KEY_{c.upper()}') for c in 'abcdefghijklmnopqrstuvwxyz0123456789'},
    ' ': e.KEY_SPACE, '-': e.KEY_MINUS, '=': e.KEY_EQUAL, '[': e.KEY_LEFTBRACE,
    ']': e.KEY_RIGHTBRACE, ';': e.KEY_SEMICOLON, "'": e.KEY_APOSTROPHE, ',': e.KEY_COMMA,
    '.': e.KEY_DOT, '/': e.KEY_SLASH, '\\': e.KEY_BACKSLASH, '`': e.KEY_GRAVE,
}
_SHIFTED = {
    **{c.upper(): getattr(e, f'KEY_{c.upper()}') for c in 'abcdefghijklmnopqrstuvwxyz'},
    '!': e.KEY_1, '@': e.KEY_2, '#': e.KEY_3, '$': e.KEY_4, '%': e.KEY_5, '^': e.KEY_6,
    '&': e.KEY_7, '*': e.KEY_8, '(': e.KEY_9, ')': e.KEY_0, '_': e.KEY_MINUS, '+': e.KEY_EQUAL,
    '{': e.KEY_LEFTBRACE, '}': e.KEY_RIGHTBRACE, ':': e.KEY_SEMICOLON, '"': e.KEY_APOSTROPHE,
    '<': e.KEY_COMMA, '>': e.KEY_DOT, '?': e.KEY_SLASH, '|': e.KEY_BACKSLASH, '~': e.KEY_GRAVE,
}
KEY_HOLD = 0.001
debug_extra_wait = 0.0
stop = threading.Event()
uinput_lock = threading.Lock()


class Stopped(Exception):
    pass


def wait(at_least: float) -> None:
    if stop.wait(at_least + random.uniform(0, 0.6) + debug_extra_wait):
        raise Stopped


def find_keyboard() -> evdev.InputDevice:
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        keys = dev.capabilities().get(e.EV_KEY, [])
        if e.KEY_A in keys and e.KEY_GRAVE in keys and e.KEY_F12 in keys:
            return dev
    raise SystemExit('No keyboard found. Pass --device /dev/input/eventN.')


class Typist:
    def __init__(self, ui: UInput):
        self.ui = ui

    def _emit(self, code: int, value: int) -> None:
        if stop.is_set() and value == 1:
            raise Stopped
        with uinput_lock:
            self.ui.write(e.EV_KEY, code, value)
            self.ui.syn()
        time.sleep(KEY_HOLD)

    def tap(self, code: int, shift: bool = False) -> None:
        if shift:
            self._emit(e.KEY_LEFTSHIFT, 1)
        try:
            self._emit(code, 1)
            self._emit(code, 0)
        finally:
            if shift:
                self._emit(e.KEY_LEFTSHIFT, 0)

    def type(self, text: str) -> None:
        for c in text:
            if c in _UNSHIFTED:
                self.tap(_UNSHIFTED[c])
            else:
                self.tap(_SHIFTED[c], shift=True)

    def run_js(self, js: str) -> None:
        self.type(js)
        wait(0.0)
        self.tap(e.KEY_ENTER)

    def vimium_click(self) -> None:
        for c in 'fsw':
            self.tap(_UNSHIFTED[c])
            wait(0.08)


def make_unlisted(t: Typist) -> None:
    wait(0.1)
    t.tap(e.KEY_F12)
    print('Pressed F12')
    wait(0.8)
    t.run_js(CLICK_STEP)
    print('Clicked step badge')
    wait(0.3)
    t.run_js(CLICK_UNLISTED)
    print('Clicked unlisted option')
    wait(0.3)
    t.tap(e.KEY_F12)
    print('Pressed F12 again')
    wait(0.3)
    t.vimium_click()
    print('Performed first vimium click')
    wait(2.5)
    t.vimium_click()
    print('Performed second vimium click')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--device', help='keyboard evdev path; auto-detected if omitted')
    parser.add_argument('--debug', action='store_true', help='add 1 sec between actions (not between console keystrokes)')
    args = parser.parse_args()
    if args.debug:
        global debug_extra_wait
        debug_extra_wait = 1.0

    kbd = evdev.InputDevice(args.device) if args.device else find_keyboard()
    print(f'Using {kbd.path} ({kbd.name}). Press "2" in the edit dialog, "`" to quit.')
    with UInput.from_device(kbd, name='unlisted-bot-companion') as ui:
        t = Typist(ui)
        triggers: queue.Queue[None] = queue.Queue()
        kbd.grab()   # other keys are forwarded through `ui`
        # Listen in a thread so "`" is seen even while a sequence is running.
        threading.Thread(target=listen, args=(kbd, ui, triggers), daemon=True).start()
        try:
            while not stop.is_set():
                try:
                    triggers.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    make_unlisted(t)
                    print('done one video')
                except Stopped:
                    pass
        finally:
            kbd.ungrab()
        print('Stopped.')


def listen(kbd: evdev.InputDevice, ui: UInput, triggers: queue.Queue[None]) -> None:
    for event in kbd.read_loop():
        if event.type == e.EV_KEY and event.code == e.KEY_GRAVE:
            if event.value == 1:
                stop.set()
                return
        elif event.type == e.EV_KEY and event.code == e.KEY_2:
            if event.value == 1:
                triggers.put(None)
        else:
            with uinput_lock:
                ui.write_event(event)


if __name__ == '__main__':
    main()
