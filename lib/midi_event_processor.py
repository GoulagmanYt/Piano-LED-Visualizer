import time
import inspect

from lib.rpi_drivers import Color

from lib.functions import get_note_position
from lib.log_setup import logger
from lib.learning_router import is_guide_channel, is_right_hand

# Import app_state to check practice_active flag
try:
    from webinterface import app_state
except ImportError:
    # If webinterface is not available, create a dummy app_state
    class DummyAppState:
        practice_active = False
    app_state = DummyAppState()

OFF_COLOR = Color(0, 0, 0)


class MIDIEventProcessor:
    """
    Processes MIDI events and translates them into LED strip visualizations.
    """
    def __init__(self, midiports, ledstrip, ledsettings, usersettings, saving, learning, menu, color_mode, state_manager=None):

        self.midiports = midiports
        self.ledstrip = ledstrip
        self.ledsettings = ledsettings
        self.usersettings = usersettings
        self.saving = saving
        self.learning = learning
        self.menu = menu
        self.color_mode = color_mode
        self.state_manager = state_manager
        self.last_sustain = 0  # Track sustain pedal state
        self._state_manager_accepts_midi_activity_time = None
        # Time tracking for sequence advancement to prevent rapid triggering
        self.last_sequence_advance = 0

    def process_midi_events(self):
        """
        Main method to process pending MIDI events from the queue.
        Handles different event types and routes them to appropriate handlers.
        Selects input source based on playback/learning state.
        """
        # Guides have their own source-aware queue and are never inferred from
        # channels on the normal live input.
        guides_processed = self.process_guide_events()
        piano_processed = self.process_learning_piano_events()
        # Determine which MIDI queue to process based on playback state and practice mode
        if not self.saving.is_playing_midi and not self.learning.is_started_midi:
            # Check if practice mode is active (websocket MIDI takes priority)
            if hasattr(app_state, 'practice_active') and app_state.practice_active:
                # Process websocket MIDI input (from practice tool)
                # Physical input still feeds forwarding, but its unused LED copy
                # must not accumulate and replay when practice mode ends.
                queues = getattr(self.midiports, "queues", None)
                if queues is not None:
                    queues.discard_inactive(learning_active=False, live_active=False)
                else:
                    self.midiports.midi_queue.clear()
                self.midiports.midipending = self.midiports.websocket_midi_queue
                queue_name = "websocket_input"
            else:
                # Process regular live MIDI input
                self.midiports.midipending = self.midiports.midi_queue
                queue_name = "live_input"
        else:
            # Process MIDI file playback
            self.midiports.midipending = self.midiports.midifile_queue
            queue_name = "midi_file"

        if not self.midiports.midipending:
            return guides_processed or piano_processed
        midi_logging_enabled = int(self.usersettings.get_setting_value("midi_logging")) == 1
        log_sink = self.learning.socket_send if midi_logging_enabled else None
        midiports = self.midiports
        ledstrip = self.ledstrip
        ledsettings = self.ledsettings
        color_mode = self.color_mode
        saving = self.saving
        handle_note_off = self.handle_note_off
        handle_note_on = self.handle_note_on
        handle_control_change = self.handle_control_change
        fallback_get_position = get_note_position
        ledstrip_get_position = getattr(ledstrip, "get_note_position", None)
        led_count = ledstrip.led_number

        # Process a bounded slice per frame to avoid jitter while preserving FIFO order.
        t0 = time.perf_counter()
        processed = 0

        def _process_one(msg, msg_timestamp):
            """Route one message exactly like before (LEDs/recording/color mode)."""
            if midi_logging_enabled and log_sink is not None and not getattr(msg, "is_meta", False):
                try:
                    log_sink.append("midi_event" + str(msg))
                except Exception as e:
                    logger.warning(f"[process midi events] Unexpected exception occurred: {e}")

            msg_type = getattr(msg, "type", None)
            velocity = getattr(msg, "velocity", 0)

            if ledsettings.mode != "Disabled" and msg_type in ("note_on", "note_off"):
                if callable(ledstrip_get_position):
                    note_position = ledstrip_get_position(msg.note, ledsettings)
                else:
                    note_position = fallback_get_position(msg.note, ledstrip, ledsettings)
                if 0 <= note_position < led_count:
                    if msg_type == "note_off" or velocity == 0:
                        handle_note_off(msg, msg_timestamp, note_position)
                    elif velocity > 0:
                        handle_note_on(msg, msg_timestamp, note_position)
            elif msg_type == "control_change":
                handle_control_change(msg, msg_timestamp)

            color_mode.MidiEvent(msg, None, ledstrip)
            saving.restart_time()

        midipending = midiports.midipending
        queues = getattr(midiports, "queues", None)
        if queues is not None:
            queue_depth = queues.queue_depth(midipending)
        else:
            queue_depth = len(midipending)
        diagnostics = midiports._ensure_runtime_diagnostics()
        diagnostics.set_metadata("selected_midi_queue", queue_name)
        diagnostics.set_gauge("midi_queue_depth_before", queue_depth)
        is_active_use = bool(self.state_manager and self.state_manager.is_active_use())
        max_messages = 1536 if is_active_use else 512
        max_duration = 0.003

        if queue_depth > 768:
            max_messages = min(max(max_messages, queue_depth * 2), 8192)
            max_duration = max(max_duration, 0.02 if is_active_use else 0.01)
        elif queue_depth > 512:
            max_messages = min(max(max_messages, queue_depth * 2), 4096)
            max_duration = max(max_duration, 0.015 if is_active_use else 0.008)
        elif queue_depth > 256:
            max_messages = min(max(max_messages, queue_depth), 2048)
            max_duration = max(max_duration, 0.01 if is_active_use else 0.006)

        while processed < max_messages and (time.perf_counter() - t0) < max_duration:
            if queues is not None:
                batch = queues.drain_queue(
                    midipending,
                    max_messages=min(16, max_messages - processed),
                )
            else:
                batch = []
                while midipending and len(batch) < min(16, max_messages - processed):
                    batch.append(midipending.popleft())
            if not batch:
                break
            now_perf = time.perf_counter()
            cur_time = time.time()
            midiports.last_activity = cur_time
            if self.state_manager:
                self._update_midi_activity(cur_time)
            saving.restart_time()
            for msg, msg_timestamp in batch:
                diagnostics.record_duration("midi_receive_to_process", time.perf_counter() - msg_timestamp)
                _process_one(msg, msg_timestamp)
                processed += 1
        diagnostics.increment_counter("midi_events_processed_total", processed)
        diagnostics.set_gauge("midi_events_processed_last", processed)
        if queues is not None:
            diagnostics.set_gauge("midi_queue_depth_after", queues.queue_depth(midipending))
        else:
            diagnostics.set_gauge("midi_queue_depth_after", len(midipending))
        self.midiports.refresh_queue_diagnostics()
        return processed > 0 or guides_processed or piano_processed

    def process_learning_piano_events(self):
        queues = getattr(self.midiports, "queues", None)
        lane = getattr(queues, "learning_piano_queue", None)
        if lane is None:
            return False
        events = queues.drain_queue(lane, max_messages=512)
        if not events:
            return False
        self._mark_learning_activity()
        # Local playback and practice own the display. Physical notes still
        # reach recording and the learning input, but must not overwrite them.
        render_live = not (self.saving.is_playing_midi or self.learning.is_started_midi or
                           getattr(app_state, "practice_active", False))
        position_fn = getattr(self.ledstrip, "get_note_position", None)
        for msg, timestamp in events:
            kind = getattr(msg, "type", None)
            if self.saving.is_recording:
                if kind == "note_on" and msg.velocity > 0:
                    self.saving.add_track("note_on", msg.note, msg.velocity, timestamp)
                elif kind == "note_off" or (kind == "note_on" and msg.velocity == 0):
                    self.saving.add_track("note_off", msg.note, 0, timestamp)
            if not render_live:
                continue
            if kind == "control_change":
                self.handle_control_change(msg, timestamp)
                continue
            if kind not in ("note_on", "note_off") or self.ledsettings.mode == "Disabled":
                continue
            position = (position_fn(msg.note, self.ledsettings) if callable(position_fn)
                        else get_note_position(msg.note, self.ledstrip, self.ledsettings))
            if not 0 <= position < self.ledstrip.led_number:
                continue
            guides = getattr(self.ledstrip, "keylist_guide", None)
            if guides is not None and guides[position]:
                # Guide state belongs to the computer stream; a piano release
                # must not extinguish a partially completed chord.
                continue
            if kind == "note_off" or msg.velocity == 0:
                self.handle_note_off(msg, timestamp, position, record=False)
            else:
                self.handle_note_on(msg, timestamp, position, record=False)
        return True

    def clear_guide_lights(self):
        """Clear only explicitly marked guides, preserving unrelated live notes."""
        guides = getattr(self.ledstrip, "keylist_guide", None)
        if not guides or not any(guides):
            return False
        idle_color, use_backlight = self._resolve_idle_color()
        for position, active in enumerate(guides):
            if not active:
                continue
            guides[position] = 0
            self.ledstrip.keylist[position] = 0
            self.ledstrip.keylist_status[position] = 0
            self.ledstrip.keylist_sustained[position] = 0
            self.ledstrip.keylist_external_software[position] = 0
            self._apply_idle_color(position, idle_color, use_backlight)
        return True

    def process_guide_events(self):
        """Render source-tagged computer guides without forwarding or recording.

        Local song/practice modes own the LEDs. Discard guides during those
        modes rather than replaying old lights when they end.
        """
        queues = getattr(self.midiports, "queues", None)
        if queues is None or not hasattr(queues, "guide_queue"):
            return False
        if (self.saving.is_playing_midi or self.learning.is_started_midi or
                getattr(app_state, "practice_active", False)):
            queues.clear_guides()
            return self.clear_guide_lights()
        events = queues.drain_guides(max_messages=512)
        if not events:
            return False
        if any(msg is not None for msg, _ in events):
            self._mark_learning_activity()
        ledstrip = self.ledstrip
        position_fn = getattr(ledstrip, "get_note_position", None)
        for msg, timestamp in events:
            if msg is None or (getattr(msg, "type", None) == "control_change" and
                               getattr(msg, "control", None) in (120, 123)):
                self.clear_guide_lights()
                continue
            if getattr(msg, "type", None) not in ("note_on", "note_off"):
                continue
            position = (position_fn(msg.note, self.ledsettings) if callable(position_fn)
                        else get_note_position(msg.note, ledstrip, self.ledsettings))
            if not 0 <= position < ledstrip.led_number:
                continue
            if msg.type == "note_off" or getattr(msg, "velocity", 0) == 0:
                # A guide-off must not extinguish an ordinary note occupying the
                # same LED (for example after switching source).
                guides = getattr(ledstrip, "keylist_guide", None)
                if guides is not None and guides[position]:
                    self.handle_note_off(msg, timestamp, position)
            elif self.ledsettings.mode != "Disabled":
                self.handle_note_on(msg, timestamp, position, is_guide=True)
        return True

    def _mark_learning_activity(self):
        now = time.time()
        self.midiports.last_activity = now
        if self.state_manager:
            self._update_midi_activity(now)
        restart = getattr(self.saving, 'restart_time', None)
        if callable(restart):
            restart()

    def _update_midi_activity(self, current_time):
        accepts_current_time = self._state_manager_accepts_midi_activity_time
        if accepts_current_time is None:
            accepts_current_time = self._state_manager_update_accepts_current_time()
            self._state_manager_accepts_midi_activity_time = accepts_current_time

        if accepts_current_time:
            self.state_manager.update_midi_activity(current_time)
        else:
            self.state_manager.update_midi_activity()

    def _state_manager_update_accepts_current_time(self):
        try:
            signature = inspect.signature(self.state_manager.update_midi_activity)
        except (AttributeError, TypeError, ValueError):
            return False

        for parameter in signature.parameters.values():
            if parameter.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            ):
                return True
        return False

    @staticmethod
    def _is_external_software_channel(msg, is_guide=False):
        if is_guide:
            channel = getattr(msg, "channel", msg)
            try:
                channel = int(channel)
            except (TypeError, ValueError):
                return False
            return is_guide_channel(channel)
        channel = getattr(msg, "channel", None)
        return channel in (11, 12, "11", "12")

    @staticmethod
    def _is_right_hand_channel(msg, is_guide=False):
        channel = getattr(msg, "channel", msg)
        try:
            channel = int(channel)
        except (TypeError, ValueError):
            return False
        if is_guide:
            return is_right_hand(channel)
        return channel in (12, "12")
    
    def handle_note_off(self, msg, msg_timestamp, note_position, record=True):
        """
        Handle note-off MIDI events.
        
        Turns off the corresponding LED or applies fading effects based on the current mode.
        
        Args:
            msg: The MIDI message object
            msg_timestamp: Timestamp when the message was received
            note_position: Position on the LED strip corresponding to the note
        """
        # Clear external software tracking flag if external software turns off the LED
        # Allow local piano input to also turn off LEDs even if they were lit by external software
        # This is essential for learning mode where Synthesia lights the LED (channels 11/12)
        # but the user's piano (channel 0) should be able to turn it off
        channel = getattr(msg, "channel", None)
        if self.ledstrip.keylist_external_software[note_position] == 1:
            if self._is_external_software_channel(msg) or channel in (0, "0"):
                # External software is turning off the LED - clear tracking
                self.ledstrip.keylist_external_software[note_position] = 0
        
        velocity = 0
        self.ledstrip.keylist_status[note_position] = 0

        guides = getattr(self.ledstrip, "keylist_guide", None)
        was_guide = guides is not None and bool(guides[note_position])
        if was_guide:
            guides[note_position] = 0
            self.ledstrip.keylist_external_software[note_position] = 0
            self.ledstrip.keylist_sustained[note_position] = 0
            if self.ledsettings.mode != "Fading":
                self.ledstrip.keylist[note_position] = 0
                idle_color, use_backlight = self._resolve_idle_color()
                self._apply_idle_color(note_position, idle_color, use_backlight)
                return

        # Check if sustain pedal is active for Velocity and Pedal modes
        pedal_deadzone = 10  # Standard MIDI deadzone for sustain pedal
        sustain_active = (self.ledsettings.mode in ["Velocity", "Pedal"] and 
                         self.last_sustain >= pedal_deadzone)

        if sustain_active:
            # Mark note as sustained instead of turning off
            self.ledstrip.keylist_sustained[note_position] = 1
        else:
            # Apply different effects based on the current LED mode
            if self.ledsettings.mode == "Fading":
                # Set to fading state (1000+ indicates fading)
                self.ledstrip.keylist[note_position] = 1000
            elif self.ledsettings.mode == "Normal":
                # Standard mode - full brightness while key is pressed
                self.ledstrip.keylist[note_position] = 0
            elif self.ledsettings.mode == "Pulse":
                # Find the active pulse for this note and trigger release
                for pulse in self.ledstrip.active_pulses:
                    if pulse["position"] == note_position and pulse.get("state") != "release":
                        pulse["state"] = "release"
                        pulse["release_time"] = time.perf_counter()
                        # Keep the pulse active in the list so led_effects_processor handles the animation
                        # We don't set keylist to 0 because the pulse effect handles the LED status
            elif self.ledsettings.mode == "Pedal":
                # Gradually reduce brightness based on pedal settings
                self.ledstrip.keylist[note_position] *= (100 - self.ledsettings.fadepedal_notedrop) / 100

        # If LED is completely off, set appropriate color
        if self.ledstrip.keylist[note_position] <= 0:
            idle_color, use_backlight = self._resolve_idle_color()
            self._apply_idle_color(note_position, idle_color, use_backlight)

        # Record the note-off event if recording is active
        if record and self.saving.is_recording and not was_guide:
            self.saving.add_track("note_off", msg.note, velocity, msg_timestamp)

    def handle_note_on(self, msg, msg_timestamp, note_position, is_guide=False, record=True):
        """
        Handle note-on MIDI events.
        
        Illuminates the corresponding LED with appropriate color based on current settings,
        velocity sensitivity, and various modes.
        
        Args:
            msg: The MIDI message object
            msg_timestamp: Timestamp when the message was received
            note_position: Position on the LED strip corresponding to the note
        """
        velocity = msg.velocity
        guides = getattr(self.ledstrip, "keylist_guide", None)
        if guides is not None:
            guides[note_position] = int(is_guide)
        mode = self.ledsettings.mode
        if is_guide and mode != "Fading":
            mode = "Normal"

        # Get color from color mode handler
        color = self.color_mode.NoteOn(msg, msg_timestamp, None, note_position)
        if color is not None:
            red, green, blue = color
        else:
            red, green, blue = (0, 0, 0)

        # Keep the assigned hand color in the state used by effects as well as
        # the immediate LED write, so Rainbow cannot replace it next frame.
        channel = getattr(msg, "channel", None)
        is_external = self._is_external_software_channel(msg, is_guide=is_guide)
        use_hand_color = is_external and self.ledsettings.skipped_notes != "Finger-based"
        if use_hand_color:
            right_hand = self._is_right_hand_channel(msg, is_guide=is_guide)
            hand_color = self.learning.hand_colorR if right_hand else self.learning.hand_colorL
            red, green, blue = map(int, self.learning.hand_colorList[hand_color])

        # Store the note color
        self.ledstrip.keylist_color[note_position] = (red, green, blue)

        # Set this key as active and clear sustained status
        self.ledstrip.keylist_status[note_position] = 1
        self.ledstrip.keylist_sustained[note_position] = 0
        
        # Calculate brightness based on velocity if in velocity mode
        if mode == "Velocity":
            brightness = velocity / 127.0  # Linear mapping: 0-127 velocity -> 0-1 brightness
        else:
            brightness = 1

        # Apply different effects based on the current LED mode
        if mode == "Fading":
            # 1001 indicates the key is active and will start fading when released
            self.ledstrip.keylist[note_position] = 1001
        elif mode == "Velocity":
            # Brightness varies with velocity (999 * brightness for linear scaling)
            self.ledstrip.keylist[note_position] = 999 * brightness
        elif mode == "Normal":
            # Standard mode - full brightness while key is pressed
            self.ledstrip.keylist[note_position] = 1000
        elif mode == "Pedal":
            # For pedal mode, start at 999 (will be affected by pedal status)
            self.ledstrip.keylist[note_position] = 999
        elif mode == "Pulse":
            # Create a new pulse effect
            self.ledstrip.active_pulses.append({
                "position": note_position,
                "color": (red, green, blue),
                "start_time": time.perf_counter(),
                "velocity": velocity / 127.0,
                "state": "attack",
                "release_time": None
            })
            self.ledstrip.keylist[note_position] = 0  # Pulse handles lighting

        # Handle special channels for hand coloring (channels 11 and 12)
        if is_external:
            # Mark this LED as externally controlled by external software
            self.ledstrip.keylist_external_software[note_position] = 1
            if use_hand_color:
                s_color = Color(red, green, blue)
                self.ledstrip.strip.setPixelColor(note_position, s_color)
                self.ledstrip.set_adjacent_colors(note_position, s_color, False)
        else:
            # Normal channel is taking control - clear external software flag
            if self.ledstrip.keylist_external_software[note_position] == 1:
                self.ledstrip.keylist_external_software[note_position] = 0
            
            if self.ledsettings.skipped_notes != "Normal":
                # Apply standard note color with velocity-based brightness
                s_color = Color(int(int(red) * brightness), int(int(green) * brightness),
                                int(int(blue) * brightness))
                self.ledstrip.strip.setPixelColor(note_position, s_color)
                self.ledstrip.set_adjacent_colors(note_position, s_color, False)

        if is_guide:
            # Guides are binary LEDs even in Velocity, Pedal or Pulse mode.
            guide_color = Color(red, green, blue)
            self.ledstrip.strip.setPixelColor(note_position, guide_color)
            self.ledstrip.set_adjacent_colors(note_position, guide_color, False)

        # Record the note-on event if recording is active
        if record and self.saving.is_recording and not is_guide:
            if self.ledsettings.color_mode == "Multicolor":
                import webcolors as wc
                # Include color information in multicolor mode
                self.saving.add_track("note_on", msg.note, velocity, msg_timestamp,
                                      wc.rgb_to_hex((red, green, blue)))
            else:
                self.saving.add_track("note_on", msg.note, velocity, msg_timestamp)

    def handle_control_change(self, msg, msg_timestamp):
        """
        Handle control change MIDI events.
        
        Processes pedal events, sequence advancement triggers, and other control messages.
        
        Args:
            msg: The MIDI message object
            msg_timestamp: Timestamp when the message was received
        """
        control = msg.control
        value = msg.value

        # Track sustain pedal state (MIDI CC 64)
        if control == 64:  # Sustain pedal
            self.last_sustain = value
            self.ledstrip.sustain_value = value
            
            # Handle sustain pedal release - clear all sustained notes
            pedal_deadzone = 10  # Standard MIDI deadzone for sustain pedal
            if value < pedal_deadzone and self.ledsettings.mode in ["Velocity", "Pedal"]:
                idle_color, use_backlight = self._resolve_idle_color()
                for i, sustained in enumerate(self.ledstrip.keylist_sustained):
                    if sustained == 1:
                        # Clear sustained status
                        self.ledstrip.keylist_sustained[i] = 0
                        # If key is not currently pressed, turn it off
                        if self.ledstrip.keylist_status[i] == 0:
                            self.ledstrip.keylist[i] = 0  # Turn off immediately
                            self._apply_idle_color(i, idle_color, use_backlight)

        current_time = time.time()
        # Handle sequence advancement based on control values
        if self.ledsettings.sequence_active and self.ledsettings.next_step is not None:
            try:
                # Check if the incoming control matches the configured control for sequence advancement
                if int(control) == int(self.ledsettings.control_number):
                    # Sequence advancement logic:
                    # - If next_step > 0: advance when control value exceeds threshold
                    # - If next_step = -1: advance when control value = 0 (released)
                    if (int(self.ledsettings.next_step) > 0 and int(value) > int(self.ledsettings.next_step)) or \
                       (int(self.ledsettings.next_step) == -1 and int(value) == 0):
                        # Limit advancement frequency to prevent rapid triggering
                        if (current_time - self.last_sequence_advance) > 1:
                            self.ledsettings.set_sequence(0, 1)
                            self.last_sequence_advance = current_time
            except TypeError:
                logger.warning("TypeError encountered in sequence logic")
            except Exception as e:
                logger.warning(f"[handle control change] Unexpected exception occurred: {e}")

        # Record the control change if recording is active
        if self.saving.is_recording:
            self.saving.add_control_change("control_change", 0, control, value, msg_timestamp)

    def _resolve_idle_color(self):
        """Compute the color to apply when a key returns to its idle state."""
        if self.ledsettings.backlight_brightness > 0 and not self.menu.screensaver_is_running:
            scale = self.ledsettings.backlight_brightness_percent / 100.0
            return Color(
                int(self.ledsettings.backlight_red * scale),
                int(self.ledsettings.backlight_green * scale),
                int(self.ledsettings.backlight_blue * scale),
            ), True
        return OFF_COLOR, False

    def _apply_idle_color(self, note_position, color_value, is_backlight):
        """Apply either the backlight color or switch LEDs off for a key."""
        self.ledstrip.strip.setPixelColor(note_position, color_value)
        self.ledstrip.set_adjacent_colors(note_position, color_value, True if is_backlight else False)
