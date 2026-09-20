import time

from lib.rpi_drivers import GPIO

from lib.functions import fastColorWipe


class GPIOHandler:
    def __init__(self, args, midiports, menu, ledstrip, ledsettings, usersettings, state_manager=None):
        self.args = args
        self.midiports = midiports
        self.menu = menu
        self.ledstrip = ledstrip
        self.ledsettings = ledsettings
        self.usersettings = usersettings
        self.state_manager = state_manager

        # Non-blocking acceleration and debounce tracking
        self._key_pressed_time = {}         # pin -> float (initial press timestamp)
        self._last_trigger_time = {}        # pin -> float (last repeat timestamp)
        self._handled_single_press = set()  # set of pins currently held for single-action buttons

        self.setup_gpio()

    def setup_gpio(self):
        if self.args.rotatescreen != "true":
            self.KEYRIGHT = 26
            self.KEYLEFT = 5
            self.KEYUP = 6
            self.KEYDOWN = 19
            self.KEY1 = 21
            self.KEY3 = 16
        else:
            self.KEYRIGHT = 5
            self.KEYLEFT = 26
            self.KEYUP = 19
            self.KEYDOWN = 6
            self.KEY1 = 16
            self.KEY3 = 21

        self.KEY2 = 20
        self.JPRESS = 13
        self.BACKLIGHT = 24

        GPIO.setmode(GPIO.BCM)
        for pin in (self.KEYRIGHT, self.KEYLEFT, self.KEYUP, self.KEYDOWN,
                    self.KEY1, self.KEY2, self.KEY3, self.JPRESS):
            GPIO.setup(pin, GPIO.IN, GPIO.PUD_UP)

    def _notify_activity(self, now=None):
        if now is None:
            now = time.time()
        self.midiports.last_activity = now
        if self.state_manager:
            self.state_manager.update_user_activity()

    def process_gpio_keys(self):
        now = time.time()

        # -------------------------------------------------------------
        # 1. Continuous navigation keys (KEYUP / KEYDOWN) - Smooth Scroll
        # -------------------------------------------------------------
        for pin, pointer_dir in ((self.KEYUP, 0), (self.KEYDOWN, 1)):
            if GPIO.input(pin) == 0:
                if pin not in self._key_pressed_time:
                    self._key_pressed_time[pin] = now
                    self._last_trigger_time[pin] = now
                    self._notify_activity(now)
                    self.menu.change_pointer(pointer_dir)
                else:
                    held = now - self._key_pressed_time[pin]
                    if held >= 0.35:
                        # Smooth scroll interval: 120ms initially, 70ms after 1.5s
                        interval = 0.07 if held > 1.5 else 0.12
                        if now - self._last_trigger_time[pin] >= interval:
                            self._last_trigger_time[pin] = now
                            self._notify_activity(now)
                            self.menu.change_pointer(pointer_dir)
            else:
                self._key_pressed_time.pop(pin, None)
                self._last_trigger_time.pop(pin, None)

        # -------------------------------------------------------------
        # 2. Continuous value adjustment (KEYLEFT / KEYRIGHT) - Smooth Scrubbing
        # -------------------------------------------------------------
        for pin, is_right in ((self.KEYLEFT, False), (self.KEYRIGHT, True)):
            if GPIO.input(pin) == 0:
                if pin not in self._key_pressed_time:
                    self._key_pressed_time[pin] = now
                    self._last_trigger_time[pin] = now
                    self._notify_activity(now)
                    self.menu.change_value("RIGHT" if is_right else "LEFT")
                else:
                    held = now - self._key_pressed_time[pin]
                    # Dynamic Acceleration Ramp:
                    # - < 0.35s: initial tap (wait before repeat)
                    # - 0.35s..1.2s: step 1 (10 Hz)
                    # - 1.2s..2.5s: step 2 (14 Hz)
                    # - 2.5s..4.0s: step 5 (20 Hz)
                    # - > 4.0s: step 10 (25 Hz)
                    if held >= 0.35:
                        if held < 1.2:
                            interval = 0.10
                            step = 1
                        elif held < 2.5:
                            interval = 0.07
                            step = 2
                        elif held < 4.0:
                            interval = 0.05
                            step = 5
                        else:
                            interval = 0.04
                            step = 10

                        if now - self._last_trigger_time[pin] >= interval:
                            self._last_trigger_time[pin] = now
                            self._notify_activity(now)
                            signed_step = step if is_right else -step
                            self.menu.change_value(signed_step)
            else:
                self._key_pressed_time.pop(pin, None)
                self._last_trigger_time.pop(pin, None)

        # -------------------------------------------------------------
        # 3. Single action buttons (KEY1, KEY2, KEY3, JPRESS) - Edge triggered
        # -------------------------------------------------------------
        # KEY1: Enter menu
        if GPIO.input(self.KEY1) == 0:
            if self.KEY1 not in self._handled_single_press:
                self._handled_single_press.add(self.KEY1)
                self._notify_activity(now)
                self.menu.enter_menu()
        else:
            self._handled_single_press.discard(self.KEY1)

        # KEY2: Go back
        if GPIO.input(self.KEY2) == 0:
            if self.KEY2 not in self._handled_single_press:
                self._handled_single_press.add(self.KEY2)
                self._notify_activity(now)
                self.menu.go_back()
                if not self.menu.screensaver_is_running:
                    fastColorWipe(self.ledstrip.strip, True, self.ledsettings)
        else:
            self._handled_single_press.discard(self.KEY2)

        # KEY3: Toggle sequence / Switch MIDI port
        if GPIO.input(self.KEY3) == 0:
            if self.KEY3 not in self._handled_single_press:
                self._handled_single_press.add(self.KEY3)
                self._notify_activity(now)
                if self.ledsettings.sequence_active:
                    self.ledsettings.set_sequence(0, 1)
                else:
                    active_input = self.usersettings.get_setting_value("input_port")
                    secondary_input = self.usersettings.get_setting_value("secondary_input_port")
                    self.midiports.change_port("inport", secondary_input)
                    self.usersettings.change_setting_value("secondary_input_port", active_input)
                    self.usersettings.change_setting_value("input_port", secondary_input)
                    fastColorWipe(self.ledstrip.strip, True, self.ledsettings)
        else:
            self._handled_single_press.discard(self.KEY3)

        # JPRESS: Speed multiplier change (x1 / x10)
        if GPIO.input(self.JPRESS) == 0:
            if self.JPRESS not in self._handled_single_press:
                self._handled_single_press.add(self.JPRESS)
                self._notify_activity(now)
                self.menu.speed_change()
        else:
            self._handled_single_press.discard(self.JPRESS)
