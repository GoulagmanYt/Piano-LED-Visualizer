import ast
import json
import logging
import math
import os
import subprocess
import threading
import time
from logging.handlers import RotatingFileHandler

import mido
import numpy as np

from lib.broadcast_outbox import BroadcastOutbox
from lib.functions import clamp, fastColorWipe, get_note_position
from lib.learning_cache import load_learning_cache, save_learning_cache
from lib.learning_input_adapter import LearningInputAdapter
from lib.learning_timeline import merge_learning_tracks
from lib.log_setup import logger
from lib.rpi_drivers import Color
from lib.score_manager import ScoreManager
from lib.song_file_security import resolve_song_path
from webinterface import app_state


def compute_notes_time(mid):
    """Return the absolute time in seconds of each non-meta MidiFile message.

    Meta messages such as markers and tempo changes also carry a time delta.
    Include it in the total to keep subsequent note timestamps accurate.
    """
    time_passed = 0
    notes_time = []
    for msg in mid:
        time_passed += msg.time
        if not msg.is_meta:
            notes_time.append(time_passed)
    return notes_time

# Create a score logger
score_logger = logging.getLogger("score_logger")
score_logger.setLevel(logging.INFO)
score_logger.propagate = False
file_handler = RotatingFileHandler("score_log.txt", maxBytes=5000000, backupCount=3)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
score_logger.addHandler(file_handler)
score_logger.info("Score logger initialized.")


def find_nearest(array, target):
    array = np.asarray(array)
    idx = (np.abs(array - target)).argmin()
    return idx


# Get midi song tempo
def get_tempo(mid):
    for msg in mid:  # Search for tempo
        if msg.type == 'set_tempo':
            return msg.tempo
    return 500000  # If not found return default tempo


def _extract_midi_note_velocity(msg):
    note = int(msg.note)
    if msg.type == 'note_off':
        return note, 0
    return note, int(msg.velocity)


class LearnMIDI:
    def __init__(self, usersettings, ledsettings, midiports, ledstrip):
        self.menu = None
        self.usersettings = usersettings
        self.ledsettings = ledsettings
        self.midiports = midiports
        self.input_adapter = LearningInputAdapter(midiports.queues)
        self.ledstrip = ledstrip
        self._learning_strip = None
        
        # Initialize the score manager

        self.loading = 0
        self.songs_per_page = int(usersettings.get_setting_value("songs_per_page"))
        self.sort_by = usersettings.get_setting_value("sort_by")
        self.practice = int(usersettings.get_setting_value("practice"))
        self.hands = int(usersettings.get_setting_value("hands"))
        self.mute_hand = int(usersettings.get_setting_value("mute_hand"))
        self.start_point = float(usersettings.get_setting_value("start_point"))
        self.end_point = float(usersettings.get_setting_value("end_point"))
        self.set_tempo = int(usersettings.get_setting_value("set_tempo"))
        self.hand_colorR = int(usersettings.get_setting_value("hand_colorR"))
        self.hand_colorL = int(usersettings.get_setting_value("hand_colorL"))
        self.prev_hand_colorR = int(usersettings.get_setting_value("prev_hand_colorR"))
        self.prev_hand_colorL = int(usersettings.get_setting_value("prev_hand_colorL"))

        self.show_wrong_notes = int(usersettings.get_setting_value("show_wrong_notes"))
        self.show_future_notes = int(usersettings.get_setting_value("show_future_notes"))

        self.notes_time = []
        self.socket_send = BroadcastOutbox()

        # Store software's notes that need to be played when user presses their key
        self.pending_software_notes = []
        # Store the next note's timing information
        self.next_note_time = None
        self.next_note_delay = None

        self.is_loop_active = int(usersettings.get_setting_value("is_loop_active"))
        
        self.is_led_activeL = int(usersettings.get_setting_value("is_led_activeL"))
        self.is_led_activeR = int(usersettings.get_setting_value("is_led_activeR"))

        self.loadingList = ['', 'Load..', 'Proces', 'Merge', 'Done', 'Error!']
        self.learningList = ['Start', 'Stop']
        self.practiceList = ['Melody', 'Rhythm', 'Listen']
        self.handsList = ['Both', 'Right', 'Left']
        self.mute_handList = ['Off', 'Right', 'Left']
        self.hand_colorList = ast.literal_eval(usersettings.get_setting_value("hand_colorList"))

        self.song_tempo = 500000
        self.song_tracks = []
        self.song_hands = []
        self.ticks_per_beat = 240
        self.is_loaded_midi = {}
        self.is_started_midi = False
        self.learning_state = "stopped"
        self._state_lock = threading.RLock()
        self._load_lock = threading.Lock()
        self._load_initializing = False
        self._learning_thread = None
        self.stop_event = threading.Event()
        self.t = None

        self.current_idx = 0

        self.mistakes_count = 0
        self.number_of_mistakes = int(usersettings.get_setting_value("number_of_mistakes"))
        self.delay_countR = 0
        self.delay_countL = 0
        self.awaiting_restart_loop = False
        self.score_manager = ScoreManager()
        self.right_hand_timing = []
        self.left_hand_timing = []
        self.right_hand_mistakes = []
        self.left_hand_mistakes = []


    @property
    def _output_strip(self):
        view = getattr(self, "_learning_strip", None)
        return self.ledstrip.strip if view is None else view

    def _hand_for(self, index, message):
        if len(self.song_hands) == len(self.song_tracks):
            return self.song_hands[index]
        # Compatibility for in-memory callers that provide an already prepared
        # score. Files loaded by load_midi always carry explicit hand roles.
        channel = getattr(message, "channel", 0)
        if channel in (1, 2):
            return channel
        return 1 if message.type in ("note_on", "note_off") else 0

    def add_instance(self, menu):
        self.menu = menu

    def change_practice(self, value):
        self.practice += value
        self.practice = clamp(self.practice, 0, len(self.practiceList) - 1)
        self.usersettings.change_setting_value("practice", self.practice)

    def change_hands(self, value):
        self.hands += value
        self.hands = clamp(self.hands, 0, len(self.handsList) - 1)
        self.usersettings.change_setting_value("hands", self.hands)

    def change_mute_hand(self, value):
        self.mute_hand += value
        self.mute_hand = clamp(self.mute_hand, 0, len(self.mute_handList) - 1)
        self.usersettings.change_setting_value("mute_hand", self.mute_hand)

    def restart_learning(self):
        if self.is_started_midi:
            self.stop_learning()
            worker = getattr(self, "_learning_thread", None) or self.t
            if worker and worker is not threading.current_thread():
                worker.join(timeout=2)
                if worker.is_alive():
                    logger.warning("Learning restart deferred: previous worker is still stopping")
                    return
            self.t = threading.Thread(target=self.learn_midi)
            self.t.start()

    def stop_learning(self):
        stop_event = getattr(self, "stop_event", None)
        if stop_event is None:
            stop_event = threading.Event()
            self.stop_event = stop_event
        with self._state_lock:
            self._stop_cleanups = getattr(self, "_stop_cleanups", 0) + 1
            self.learning_state = "stopping"
            self.is_started_midi = False
            stop_event.set()
            if hasattr(self, "pending_software_notes"):
                self.pending_software_notes.clear()
            self.next_note_time = None
            self.next_note_delay = None
        try:
            try:
                if hasattr(self.midiports, "clear_scheduled_rtp_messages"):
                    self.midiports.clear_scheduled_rtp_messages(source="learning")
                elif hasattr(self.midiports, "queues"):
                    self.midiports.queues.clear_scheduled_forward(source="learning")
            finally:
                request_panic = getattr(self.midiports, "request_all_notes_off", None)
                if callable(request_panic):
                    request_panic()
                elif hasattr(self.midiports, "send_all_notes_off"):
                    try:
                        self.midiports.send_all_notes_off()
                    except Exception as e:
                        logger.debug(f"Learning MIDI panic send failed: {e}")
        finally:
            with self._state_lock:
                self._stop_cleanups -= 1
        logger.info("learning_midi transition=stopping")

    def _wait_or_stopped(self, delay):
        stop_event = getattr(self, "stop_event", None)
        if stop_event is None:
            stop_event = threading.Event()
            self.stop_event = stop_event
        if stop_event.is_set() or not self.is_started_midi:
            return True
        if delay <= 0:
            return False
        return stop_event.wait(delay) or not self.is_started_midi

    def restart_loop(self):
        self.awaiting_restart_loop = True

    def change_start_point(self, value):
        self.start_point += 5 * value
        self.start_point = clamp(self.start_point, 0, self.end_point - 10)
        self.usersettings.change_setting_value("start_point", self.start_point)
        self.restart_learning()

    def change_end_point(self, value):
        self.end_point += 5 * value
        self.end_point = clamp(self.end_point, self.start_point + 10, 100)
        self.usersettings.change_setting_value("end_point", self.end_point)
        self.restart_learning()

    def change_set_tempo(self, value):
        self.set_tempo += 5 * value
        self.set_tempo = clamp(self.set_tempo, 10, 200)
        self.usersettings.change_setting_value("set_tempo", self.set_tempo)

    def change_show_wrong_notes(self, value):
        self.show_wrong_notes += value
        self.show_wrong_notes = clamp(self.show_wrong_notes, 0, 1)
        self.usersettings.change_setting_value("show_wrong_notes", self.show_wrong_notes)

    def change_show_future_notes(self, value):
        self.show_future_notes += value
        self.show_future_notes = clamp(self.show_future_notes, 0, 1)
        self.usersettings.change_setting_value("show_future_notes", self.show_future_notes)

    def change_number_of_mistakes(self, value):
        self.number_of_mistakes += value
        self.number_of_mistakes = clamp(self.number_of_mistakes, 0, 255)
        self.usersettings.change_setting_value("number_of_mistakes", self.number_of_mistakes)

    def change_hand_color(self, value, hand):
        if hand == 'RIGHT':
            self.hand_colorR += value
            self.hand_colorR = clamp(self.hand_colorR, 0, len(self.hand_colorList) - 1)
            self.usersettings.change_setting_value("hand_colorR", self.hand_colorR)
        elif hand == 'LEFT':
            self.hand_colorL += value
            self.hand_colorL = clamp(self.hand_colorL, 0, len(self.hand_colorList) - 1)
            self.usersettings.change_setting_value("hand_colorL", self.hand_colorL)

    def load_song_from_cache(self, song_path):
        try:
            source = resolve_song_path(song_path, must_exist=True, allowed_extensions={"mid"})
        except (ValueError, OSError):
            return False
        cache = load_learning_cache(song_path, source)
        if cache is None or "song_hands" not in cache:
            return False
        self.song_tempo = cache['song_tempo']
        self.ticks_per_beat = cache['ticks_per_beat']
        self.song_tracks = cache['song_tracks']
        self.song_hands = cache['song_hands']
        self.notes_time = cache['notes_time']
        self.loading = 4
        return True

    def load_midi(self, song_path):
        try:
            source = resolve_song_path(song_path, must_exist=True, allowed_extensions={"mid"})
        except (ValueError, OSError) as error:
            logger.warning("Cannot load learning song: %s", error)
            self.loading = 5
            return
        with self._load_lock:
            with self._state_lock:
                self._load_initializing = True
            try:
                self.stop_learning()
                owner = self._learning_thread
                if owner is threading.current_thread():
                    raise RuntimeError("Learning worker cannot replace its own song")
                if owner is not None:
                    owner.join(timeout=2)
                    if owner.is_alive():
                        raise RuntimeError("Previous learning worker is still stopping")
                with self._state_lock:
                    self.loading = 1
                    self._load_initializing = False
                self._load_midi(song_path, source)
            except (OSError, RuntimeError) as error:
                logger.warning("Cannot replace learning song: %s", error)
                self.loading = 5
            finally:
                with self._state_lock:
                    self._load_initializing = False

    def _load_midi(self, song_path, source):
        self.is_loaded_midi.clear()
        self.is_loaded_midi[song_path] = True
        # Remember currently loaded song for highscore tracking
        try:
            self.current_song_name = song_path
        except Exception:
            self.current_song_name = song_path
        self.loading = 1  # 1 = Load..
        # Update learning settings for current song
        try:
            profile_id = getattr(app_state, 'current_profile_id', None)
            # Only update if a profile is selected and we know the song name
            if profile_id:
                # Use ProfileManager directly if available
                pm = getattr(app_state, 'profile_manager', None)
                if pm:
                    section_list = pm.get_learning_settings(int(profile_id), self.current_song_name)
                    app_state.learning.is_loop_active = section_list["loop"]
                    app_state.learning.practice = section_list["practice"]
                    app_state.learning.hands = section_list["hands"]
                    app_state.learning.mute_hand = section_list["mute_hands"]
                    app_state.learning.show_wrong_notes = section_list["wrong_notes"]
                    app_state.learning.show_future_notes = section_list["future_notes"]
                    app_state.learning.number_of_mistakes = section_list["mistakes"]
                    app_state.learning.set_tempo = section_list["tempo"]
                    app_state.learning.start_point = section_list["start"]
                    app_state.learning.end_point = section_list["end"]
                    app_state.learning.hand_colorR = section_list["rh_color"]
                    app_state.learning.hand_colorL = section_list["lh_color"]
                    app_state.learning.prev_hand_colorR = section_list["prev_rh_color"]
                    app_state.learning.prev_hand_colorL = section_list["prev_lh_color"]
                    app_state.learning.is_led_activeL = section_list["lh_active"]
                    app_state.learning.is_led_activeR = section_list["rh_active"]
        except Exception as e:
            logger.warning(f"Failed to fetch learning section: {e}")
        # Load song from cache
        if self.load_song_from_cache(song_path):
            return
        logger.info("Cache not found")

        try:
            # Load the midi file
            source_stat = source.stat()
            mid = mido.MidiFile(source, clip=True)  # clip=True fixes some midi files

            # Get tempo and Ticks per beat
            self.song_tempo = get_tempo(mid)
            self.ticks_per_beat = mid.ticks_per_beat

            # Musical hand roles must not overwrite MIDI protocol channels.
            self.loading = 2  # 2 = Proces
            self.loading = 3  # 3 = Merge
            self.song_tracks, self.song_hands = merge_learning_tracks(mid)
            self.notes_time.clear()
            self.notes_time.extend(compute_notes_time(mid))

            fastColorWipe(self.ledstrip.strip, True, self.ledsettings)

            # Save to cache
            try:
                current_stat = source.stat()
                if ((source_stat.st_mtime_ns, source_stat.st_size)
                        == (current_stat.st_mtime_ns, current_stat.st_size)):
                    save_learning_cache(song_path, source, {
                        'song_tempo': self.song_tempo, 'ticks_per_beat': self.ticks_per_beat,
                        'notes_time': self.notes_time, 'song_tracks': self.song_tracks,
                        'song_hands': self.song_hands,
                    })
            except (OSError, ValueError) as error:
                logger.warning("Learning cache unavailable; song remains playable: %s", error)

            self.loading = 4  # 4 = Done
        except Exception as e:
            logger.warning(e)
            self.loading = 5  # 5 = Error!
            self.is_loaded_midi.clear()

    # predict future notes in MIDI messages
    def predict_future_notes(self, starting_note, ending_note, notes_to_press):

        if self.show_future_notes != 1:
            return

        predicted_future_notes = []
        current_note = starting_note
        for msg in self.song_tracks[starting_note:ending_note]:
            # Get time delay
            tDelay = mido.tick2second(msg.time, self.ticks_per_beat, self.song_tempo * 100 / self.set_tempo)

            if tDelay > 0 and predicted_future_notes and self.practice == 0:
                self.light_up_predicted_future_notes(predicted_future_notes)
                return

            hand = self._hand_for(current_note, msg)
            if (msg.type == 'note_on' and msg.velocity > 0 and hand in (1, 2)
                    and (self.hands == 0 or self.hands == hand)):
                # make sure msg.note is not in notes_to_press list
                if msg.note not in notes_to_press:
                    predicted_future_notes.append((msg, hand))

            current_note += 1
        self.light_up_predicted_future_notes(predicted_future_notes)

    def light_up_predicted_future_notes(self, notes):
        dim = 10
        for msg, hand in notes:
            # Light-up LEDs with the notes to press
            if not msg.is_meta:
                # Calculate note position on the strip and display
                if msg.type == 'note_on' or msg.type == 'note_off':
                    note_position = get_note_position(msg.note, self.ledstrip, self.ledsettings)

                    brightness = 0.5
                    brightness /= dim
                    red, green, blue = [0, 0, 0]
                    if hand == 1:
                        # red = int(self.hand_colorList[self.hand_colorR][0] * brightness)
                        # green = int(self.hand_colorList[self.hand_colorR][1] * brightness)
                        # blue = int(self.hand_colorList[self.hand_colorR][2] * brightness)
                        red, green, blue = [int(c * brightness) for c in self.hand_colorList[self.hand_colorR]]
                    if hand == 2:
                        # red = int(self.hand_colorList[self.hand_colorL][0] * brightness)
                        # green = int(self.hand_colorList[self.hand_colorL][1] * brightness)
                        # blue = int(self.hand_colorList[self.hand_colorL][2] * brightness)
                        red, green, blue = [int(c * brightness) for c in self.hand_colorList[self.hand_colorL]]

                    self._output_strip.setPixelColor(note_position, Color(red, green, blue))
        if notes:
            self._output_strip.show()

    def handle_wrong_notes(self, wrong_notes, hand_hint_notesL, hand_hint_notesR):

        brightness = 0.05
        # loop through wrong_notes and light them up
        for msg in wrong_notes:
            note, velocity = _extract_midi_note_velocity(msg)

            note_position = get_note_position(note, self.ledstrip, self.ledsettings)
            if velocity > 0:
                self.mistakes_count += 1
                if self.show_wrong_notes:
                    self._output_strip.setPixelColor(note_position, Color(255, 0, 0))
                if self.show_wrong_notes and self.is_led_activeL == 0:
                    for expected_note in hand_hint_notesL:
                        red, green, blue = [int(c * brightness) for c in self.hand_colorList[self.prev_hand_colorL]]
                        self._output_strip.setPixelColor(expected_note, Color(red, green, blue))
                if self.show_wrong_notes and self.is_led_activeR == 0:
                    for expected_note in hand_hint_notesR:
                        red, green, blue = [int(c * brightness) for c in self.hand_colorList[self.prev_hand_colorR]]
                        self._output_strip.setPixelColor(expected_note, Color(red, green, blue))
                 
                # Wrong note penalty
                self.score_manager.penalize_for_wrong_note()
                score_logger.debug("wrong note - score:" +str(self.score_manager.get_score()))
                score_logger.debug("panelty:" +str(self.score_manager.get_last_score_update()))

                # # Send score update to frontend
                self.socket_send.append(json.dumps({
                    "type": "score_update",
                    "score": self.score_manager.get_score(),
                    "combo": self.score_manager.get_combo(),
                    "multiplier": self.score_manager.get_multiplier(),
                    "last_update": self.score_manager.get_last_score_update()
                }))
            elif self.show_wrong_notes:
                if callable(getattr(type(self._output_strip), "clearPixel", None)):
                    self._output_strip.clearPixel(note_position)
                else:
                    self._output_strip.setPixelColor(note_position, Color(0, 0, 0))

        if self.mistakes_count > self.number_of_mistakes > 0:
            self.mistakes_count = 0
            self.restart_loop()

        if self.show_wrong_notes and wrong_notes:
            self._output_strip.show()

    def learn_midi(self):
        with self._state_lock:
            owner = getattr(self, "_learning_thread", None)
            silencing = getattr(self.midiports, "is_silencing_output", None)
            if callable(silencing) and silencing():
                logger.warning("Learning start deferred: previous output cleanup is still pending")
                return
            if (self.is_started_midi or self._load_initializing or getattr(self, "_stop_cleanups", 0)
                    or (owner is not None and owner.is_alive())):
                return
            if not hasattr(self, "stop_event"):
                self.stop_event = threading.Event()
            self.stop_event.clear()
            # Reserve the session before releasing the lock, including loading.
            self.is_started_midi = True
            self.t = threading.current_thread()
            self._learning_thread = self.t
            self.learning_state = "starting"
            logger.info("learning_midi transition=starting")
        try:
            strip = self.ledstrip.strip
            if callable(getattr(type(strip), "priority_view", None)):
                self._learning_strip = strip.priority_view()
            self._run_learning()
        except Exception:
            self.learning_state = "error"
            logger.exception("Learning session failed")
        finally:
            final_state = "error" if self.learning_state == "error" else "stopped"
            try:
                if self.learning_state != "stopping":
                    self.stop_learning()
            finally:
                view = self._learning_strip
                self._learning_strip = None
                try:
                    if view is not None:
                        view.close()
                finally:
                    with self._state_lock:
                        self.is_started_midi = False
                        self.learning_state = final_state
                        self._learning_thread = None
                logger.info("learning_midi transition=%s", final_state)

    def _publish_score(self):
        self.socket_send.append(json.dumps({
            "type": "score_update", "score": self.score_manager.get_score(),
            "combo": self.score_manager.get_combo(),
            "multiplier": self.score_manager.get_multiplier(),
            "last_update": self.score_manager.get_last_score_update(),
        }))

    def _await_learning_chord(self, targets, left_hints, right_hints, next_index, end_index):
        """Match pitches while keeping input-channel releases independent.

        Each physical pitch earns points once per expected chord. Timing uses
        the input's perf_counter timestamp, independent of queue delay or UTC.
        """
        pressed = set()
        scored = set()
        self.next_note_time = min(target["due"] for target in targets.values())
        self.next_note_delay = 0
        while self.is_started_midi and not self.awaiting_restart_loop:
            wrong = []
            for message, timestamp in self.input_adapter.drain_note_events():
                note, velocity = _extract_midi_note_velocity(message)
                event_time = (float(timestamp) if isinstance(timestamp, (int, float))
                              and math.isfinite(timestamp) else time.perf_counter())
                if event_time < self.next_note_time:
                    continue  # Input left over from before this chord was shown.
                key = (getattr(message, "channel", 0), note)
                if velocity == 0:
                    pressed.discard(key)
                    if note not in targets:
                        wrong.append(message)
                    continue
                if key in pressed:
                    continue
                pressed.add(key)
                if note not in targets:
                    wrong.append(message)
                    nearest = min(targets, key=lambda expected: abs(expected - note))
                    target = targets[nearest]
                    for hand in target["hands"]:
                        mistakes = self.right_hand_mistakes if hand == 1 else self.left_hand_mistakes
                        mistakes.append(target["position"])
                elif note not in scored:
                    scored.add(note)
                    target = targets[note]
                    delay = event_time - target["due"]
                    self.score_manager.add_score_for_correct_note(delay)
                    for hand in target["hands"]:
                        timing = self.right_hand_timing if hand == 1 else self.left_hand_timing
                        timing.append((target["position"], delay))
                        if abs(delay) >= self.score_manager.max_delay:
                            if hand == 1:
                                self.delay_countR += 1
                            else:
                                self.delay_countL += 1
                    self._publish_score()
            self.handle_wrong_notes(wrong, left_hints, right_hints)
            if self.awaiting_restart_loop:
                return False
            if set(targets).issubset(note for _channel, note in pressed):
                due = time.perf_counter()
                for message in self.pending_software_notes:
                    if self._wait_or_stopped(0):
                        return False
                    self.midiports.schedule_rtp_message(message, due_time=due, source="learning")
                self.pending_software_notes.clear()
                return True
            if self._wait_or_stopped(0.001):
                break
            self.predict_future_notes(next_index, end_index, targets)
        return False

    def _render_learning_note(self, message, hand, left_hints, right_hints, active):
        if message.type not in ("note_on", "note_off") or hand not in (1, 2):
            return
        key = (message.channel, message.note)
        if message.type == "note_on" and message.velocity > 0:
            active[key] = hand
        else:
            active.pop(key, None)
        remaining = next((role for (_channel, note), role in active.items()
                          if note == message.note), None)
        position = get_note_position(message.note, self.ledstrip, self.ledsettings)
        if remaining is None:
            release = getattr(type(self._output_strip), "clearPixel", None)
            if callable(release):
                self._output_strip.clearPixel(position)
            else:
                self._output_strip.setPixelColor(position, Color(0, 0, 0))
        else:
            color_index = self.hand_colorR if remaining == 1 else self.hand_colorL
            self._output_strip.setPixelColor(position, Color(*(int(c * 0.5)
                                             for c in self.hand_colorList[color_index])))
        hints = right_hints if hand == 1 else left_hints
        enabled = self.is_led_activeR if hand == 1 else self.is_led_activeL
        if enabled == 0:
            if remaining is not None and position not in hints:
                hints.append(position)
            elif remaining is None and position in hints:
                hints.remove(position)

    def _play_section(self):
        """Play same-tick groups, including meta events, on one musical clock."""
        start = int(self.start_point * len(self.song_tracks) / 100)
        end = int(self.end_point * len(self.song_tracks) / 100)
        self.current_idx = sum(not msg.is_meta for msg in self.song_tracks[:start])
        tempo, position = 500000, 0.0
        for message in self.song_tracks[:start]:
            position += mido.tick2second(message.time, self.ticks_per_beat, tempo)
            if message.type == "set_tempo":
                tempo = message.tempo
        groups, group = [], []
        for index in range(start, end):
            message = self.song_tracks[index]
            if message.time > 0 and group:
                groups.append(group)
                group = []
            group.append((index, message))
        if group:
            groups.append(group)

        fastColorWipe(self._output_strip, True, self.ledsettings)
        due = time.perf_counter()
        targets, active = {}, {}
        left_hints, right_hints = [], []
        for group in groups:
            if not self.is_started_midi:
                break
            delta = mido.tick2second(group[0][1].time, self.ticks_per_beat, tempo)
            delay = delta * 100 / self.set_tempo
            if targets:
                self._await_learning_chord(targets, left_hints, right_hints, group[0][0], end)
                targets.clear()
                fastColorWipe(self._output_strip, True, self.ledsettings)
                due = max(due, time.perf_counter() - delay)
                left_hints.clear()
                right_hints.clear()
            if self.awaiting_restart_loop:
                self.awaiting_restart_loop = False
                return True
            due += delay
            if self._wait_or_stopped(max(0, due - time.perf_counter())):
                break
            position += delta
            self.midiports.last_activity = time.time()
            software = []
            for index, message in group:
                if message.is_meta:
                    if message.type == "set_tempo":
                        tempo = message.tempo
                    continue
                if self.current_idx < len(self.notes_time):
                    self.socket_send.append(self.notes_time[self.current_idx])
                self.current_idx += 1
                hand = self._hand_for(index, message)
                self._render_learning_note(message, hand, left_hints, right_hints, active)
                selected = hand in (1, 2) and (self.hands == 0 or self.hands == hand)
                if (self.practice == 0 and selected and message.type == "note_on"
                        and message.velocity > 0):
                    target = targets.setdefault(message.note, {"hands": set(), "due": due,
                                                               "position": position})
                    target["hands"].add(hand)
                if (self.practice == 2 or hand == 0
                        or (self.hands == 1 and hand == 2 and self.mute_hand != 2)
                        or (self.hands == 2 and hand == 1 and self.mute_hand != 1)):
                    software.append(message)
            self._output_strip.show()
            if targets:
                self.pending_software_notes.extend(software)
            else:
                for message in software:
                    if self._wait_or_stopped(0):
                        break
                    self.midiports.schedule_rtp_message(message, due_time=due, source="learning")
        if targets and self.is_started_midi:
            self._await_learning_chord(targets, left_hints, right_hints, end, end)
        if self.awaiting_restart_loop:
            self.awaiting_restart_loop = False
            return True
        return False

    def _run_learning(self):
        if self.loading == 0:
            self.menu.render_message("Load song to start", "", 1500)
            self.is_started_midi = False
            self.learning_state = "stopped"
            return
        elif 0 < self.loading < 4:
            while 0 < self.loading < 4:
                if self._wait_or_stopped(0.1):
                    self.learning_state = "stopped"
                    return
        if self.loading == 4:
            self.learning_state = "running"
            logger.info("learning_midi transition=running")
            # Reset the score when starting a new learning session
            self.score_manager.reset()
            self.mistakes_count = 0
            self.right_hand_timing.clear()
            self.left_hand_timing.clear()
            self.right_hand_mistakes.clear()
            self.left_hand_mistakes.clear()
            midi_time = 0
            self.delay_countR = 0
            self.delay_countL = 0
            score_logger.debug("score reset" +str(self.score_manager.get_score()))
                  
            # Send score update to frontend
            self.socket_send.append(json.dumps({
                "type": "score_update",
                "score": self.score_manager.get_score(),
                "combo": self.score_manager.get_combo(),
                "multiplier": self.score_manager.get_multiplier(),
                "last_update": 0 # Reset last update as well
            }))
        elif self.loading == 5:
            self.is_started_midi = False  # Allow restarting the Thread
            self.learning_state = "error"
            logger.info("learning_midi transition=error")
            return

        self.t = threading.current_thread()
        keep_looping = True
        while keep_looping:
            if self._wait_or_stopped(1):
                break
            self.score_manager.reset()
            self.right_hand_timing.clear()
            self.left_hand_timing.clear()
            self.right_hand_mistakes.clear()
            self.left_hand_mistakes.clear()
            self.delay_countR = 0
            self.delay_countL = 0
            midi_time = 0
            score_logger.debug("midi_time  - reset" +str(midi_time))
            score_logger.debug("score reset keep looping" +str(self.score_manager.get_score()))
            self.socket_send.append(json.dumps({
                "type": "score_update",
                "score": self.score_manager.get_score(),
                "combo": self.score_manager.get_combo(),
                "multiplier": self.score_manager.get_multiplier(),
                "last_update": 0
            }))
            restart_requested = False
            try:
                restart_requested = self._play_section()


            except Exception as e:
                logger.warning(e)
                self.is_started_midi = False
                self.learning_state = "error"
                logger.info("learning_midi transition=error")

            if not (self.is_loop_active or restart_requested) or self.is_started_midi is False:
                keep_looping = False

            # Update profile highscore
            try:
                profile_id = getattr(app_state, 'current_profile_id', None)
                # Only update if a profile is selected and we know the song name
                if profile_id and hasattr(self, 'current_song_name') and self.current_song_name:
                    # new_score is the final session score
                    new_score = int(self.score_manager.get_score())
                    # Use ProfileManager directly if available
                    pm = getattr(app_state, 'profile_manager', None)
                    if pm:
                        updated = pm.update_highscore(int(profile_id), self.current_song_name, new_score)
                        if updated:
                            # Notify UI via websocket to update the highscore cell dynamically
                            self.socket_send.append(json.dumps({
                                "type": "highscore_update",
                                "song_name": self.current_song_name,
                                "score": new_score,
                                "profile_id": int(profile_id)
                            }))
            except Exception as e:
                logger.warning(f"Failed to update highscore: {e}")

            # Send session summary data
            if not keep_looping:
                try:
                    # Get actual RGB colors
                    color_r_rgb = self.hand_colorList[self.hand_colorR]
                    color_l_rgb = self.hand_colorList[self.hand_colorL]

                    summary_data = {
                        "type": "session_summary",
                        # Basic stats
                        "delay_r": self.delay_countR,
                        "delay_l": self.delay_countL,
                        "mistakes_r_count": len(self.right_hand_mistakes),
                        "mistakes_l_count": len(self.left_hand_mistakes),
                        # Data for graph
                        "timing_r": self.right_hand_timing,
                        "timing_l": self.left_hand_timing,
                        "mistakes_r_times": self.right_hand_mistakes,
                        "mistakes_l_times": self.left_hand_mistakes,
                        "max_delay": self.score_manager.max_delay,
                        "color_r": f'rgb({color_r_rgb[0]}, {color_r_rgb[1]}, {color_r_rgb[2]})',
                        "color_l": f'rgb({color_l_rgb[0]}, {color_l_rgb[1]}, {color_l_rgb[2]})'
                    }
                    self.socket_send.append(json.dumps(summary_data))
                    score_logger.info(f"Sent session summary (length: {len(json.dumps(summary_data))})") # Log length for debugging if needed
                except Exception as e:
                    score_logger.error(f"Error preparing/sending session summary: {e}")
    def convert_midi_to_abc(self, midi_file):
        if not os.path.isfile('Songs/' + midi_file.replace(".mid", ".abc")):
            # subprocess.call(['midi2abc',  'Songs/' + midi_file, '-o', 'Songs/' + midi_file.replace(".mid", ".abc")])
            try:
                subprocess.check_output(
                    ['midi2abc', 'Songs/' + midi_file, '-o', 'Songs/' + midi_file.replace(".mid", ".abc")])
            except Exception as e:
                # check if e contains the string 'No such file or directory'
                if 'No such file or directory' in str(e):
                    logger.info("midi2abc not found")
        else:
            logger.info("file already converted")
