#!/usr/bin/env python3

import sys
import threading
import unittest
from collections import deque
from unittest.mock import patch

sys.path.append("./")
sys.path.append("../")

from lib.midi_queues import MidiQueues
from lib.midiports import MidiPorts


class FakePlayPort:
    def __init__(self, fail_times=0):
        self.sent = []
        self.fail_times = fail_times

    def send(self, msg):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("temporary RTP send failure")
        self.sent.append(msg)


class FakeInputBackend:
    def __init__(self):
        self.calls = []

    def ignore_types(self, sysex=True, timing=True, active_sense=True):
        self.calls.append(
            {
                "sysex": sysex,
                "timing": timing,
                "active_sense": active_sense,
            }
        )


class FakeInputPort:
    def __init__(self):
        self._rt = FakeInputBackend()


class FakeMidiMessage:
    def __init__(
        self,
        msg_type="note_on",
        channel=0,
        note=60,
        velocity=100,
        time=0,
        control=64,
        value=127,
    ):
        self.type = msg_type
        self.channel = channel
        self.note = note
        self.velocity = velocity
        self.time = time
        self.control = control
        self.value = value

    def __str__(self):
        if self.type == "control_change":
            return (
                f"{self.type} channel={self.channel} control={self.control} "
                f"value={self.value} time={self.time}"
            )
        return (
            f"{self.type} channel={self.channel} note={self.note} "
            f"velocity={self.velocity} time={self.time}"
        )


class TestMidiPorts(unittest.TestCase):
    def test_disconnection_clears_pending_notes_and_reenable_does_not_replay(self):
        ports = self.make_ports()
        ports.msg_callback(FakeMidiMessage())
        ports.playport = None
        self.assertFalse(ports._flush_live_forward_queue_once())
        for _ in range(1000):
            ports.msg_callback(FakeMidiMessage())
        self.assertEqual(len(ports.live_forward_queue), 0)
        ports.playport = FakePlayPort()
        ports.queues.set_forwarding_enabled(True)
        self.assertFalse(ports._flush_live_forward_queue_once())
        self.assertEqual(ports.playport.sent, [])

    def test_prolonged_send_failure_ends_session_and_clears_backlog(self):
        ports = self.make_ports()
        ports.playport = FakePlayPort(fail_times=100)
        ports.msg_callback(FakeMidiMessage())
        ports._send_failure_since = 1.0
        with patch('lib.midiports.time.perf_counter', return_value=3.0):
            self.assertFalse(ports._flush_live_forward_queue_once())
        self.assertIsNone(ports.playport)
        self.assertFalse(ports.live_forward_queue)
        self.assertFalse(ports.queues.forwarding_enabled)

    def test_output_silence_releases_sustain_and_notes_on_every_channel(self):
        port = FakePlayPort()
        MidiPorts._silence_output(port)
        self.assertEqual(len(port.sent), 48)
        self.assertEqual({(m.channel, m.control, m.value) for m in port.sent},
                         {(ch, cc, 0) for ch in range(16) for cc in (64, 120, 123)})

    def run_forward_wait_boundary(self, produce, *, backoff_until=0.0):
        """Queue work exactly after the empty check and before condition.wait."""
        ports = self.make_ports()
        ports.worker_running = True
        ports.forward_backoff_until = backoff_until
        waits = []

        class BoundaryCondition(threading.Condition):
            entered = False

            def __enter__(self):
                if not self.entered:
                    self.entered = True
                    produce(ports)
                return super().__enter__()

            def wait(self, timeout=None):
                waits.append(timeout)
                ports.worker_running = False

        ports.forward_condition = BoundaryCondition()
        original_flush = ports._flush_live_forward_queue_once
        attempts = 0

        def flush():
            nonlocal attempts
            attempts += 1
            self.assertLessEqual(attempts, 8, "forward worker spun instead of waiting")
            sent = original_flush()
            if sent:
                ports.worker_running = False
            return sent

        ports._flush_live_forward_queue_once = flush
        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            ports._live_forward_loop()
        return ports, waits

    def test_live_forward_notification_before_wait_is_not_lost(self):
        msg = FakeMidiMessage()
        ports, waits = self.run_forward_wait_boundary(
            lambda ports: ports.enqueue_rtp_message(msg, msg_timestamp=100.0)
        )
        self.assertEqual(waits, [])
        self.assertEqual(ports.playport.sent, [msg])

    def test_due_scheduled_forward_notification_before_wait_is_not_lost(self):
        msg = FakeMidiMessage()
        ports, waits = self.run_forward_wait_boundary(
            lambda ports: ports.schedule_rtp_message(msg, due_time=99.0, enqueued_at=99.0)
        )
        self.assertEqual(waits, [])
        self.assertEqual(ports.playport.sent, [msg])

    def test_new_scheduled_deadline_replaces_idle_wait(self):
        ports, waits = self.run_forward_wait_boundary(
            lambda ports: ports.schedule_rtp_message(
                FakeMidiMessage(), due_time=100.005, enqueued_at=100.0
            )
        )
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 0.005)
        self.assertEqual(ports.playport.sent, [])

    def test_live_forward_backoff_waits_until_retry_without_spinning(self):
        ports, waits = self.run_forward_wait_boundary(
            lambda ports: ports.enqueue_rtp_message(FakeMidiMessage(), msg_timestamp=100.0),
            backoff_until=100.02,
        )
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 0.02)
        self.assertEqual(len(ports.live_forward_queue), 1)
        self.assertEqual(ports.playport.sent, [])

    def test_due_scheduled_backoff_waits_until_retry_without_spinning(self):
        ports, waits = self.run_forward_wait_boundary(
            lambda ports: ports.schedule_rtp_message(
                FakeMidiMessage(), due_time=99.0, enqueued_at=99.0
            ),
            backoff_until=100.02,
        )
        self.assertEqual(len(waits), 1)
        self.assertAlmostEqual(waits[0], 0.02)
        self.assertEqual(ports.playport.sent, [])

    def test_live_forward_idle_worker_keeps_bounded_wait(self):
        _, waits = self.run_forward_wait_boundary(lambda ports: None)
        self.assertEqual(waits, [0.05])

    def test_live_forward_without_output_waits_instead_of_spinning(self):
        def disconnect_and_enqueue(ports):
            ports.playport = None
            ports.enqueue_rtp_message(FakeMidiMessage(), msg_timestamp=100.0)

        ports, waits = self.run_forward_wait_boundary(disconnect_and_enqueue)
        self.assertEqual(waits, [0.05])
        self.assertEqual(len(ports.live_forward_queue), 1)

    def test_scheduled_forward_without_output_keeps_bounded_wait(self):
        for due_time in (99.0, 100.005):
            with self.subTest(due_time=due_time):
                def disconnect_and_schedule(ports):
                    ports.playport = None
                    ports.schedule_rtp_message(
                        FakeMidiMessage(), due_time=due_time, enqueued_at=99.0
                    )

                ports, waits = self.run_forward_wait_boundary(disconnect_and_schedule)
                self.assertEqual(waits, [0.05])
                self.assertEqual(len(ports.scheduled_forward_queue), 1)

    def test_live_forward_shutdown_before_wait_does_not_sleep(self):
        _, waits = self.run_forward_wait_boundary(
            lambda ports: setattr(ports, "worker_running", False)
        )
        self.assertEqual(waits, [])

    def make_ports(self, *, midi_maxlen=4, websocket_maxlen=4, forward_maxlen=4):
        ports = MidiPorts.__new__(MidiPorts)
        ports.queues = MidiQueues(
            live_maxlen=midi_maxlen,
            file_maxlen=500,
            websocket_maxlen=websocket_maxlen,
            forward_maxlen=forward_maxlen,
            scheduled_forward_maxlen=forward_maxlen,
            websocket_publish_maxlen=forward_maxlen,
            reserved_noteoff_slots=1,
        )
        ports.midifile_queue = ports.queues.file_queue
        ports.midi_queue = ports.queues.live_visualizer_queue
        ports.websocket_midi_queue = ports.queues.websocket_queue
        ports.learning_midi_queue = ports.queues.live_learning_queue
        ports.live_forward_queue = ports.queues.live_forward_queue
        ports.scheduled_forward_queue = ports.queues.scheduled_forward_queue
        ports.websocket_publish_queue = ports.queues.websocket_publish_queue
        ports.drop_counter = 0
        ports.drop_counts = {}
        ports.ignored_counts = {}
        ports.forward_stats = {
            "live_sent": 0,
            "live_send_errors": 0,
            "websocket_sent": 0,
            "websocket_dropped": 0,
            "send_time_total_ms": 0.0,
            "send_time_max_ms": 0.0,
            "scheduled_sent": 0,
            "scheduled_late_messages": 0,
            "scheduled_late_max_ms": 0.0,
            "scheduled_late_last_ms": 0.0,
        }
        ports.last_activity = 0
        ports.inport = None
        ports.playport = FakePlayPort()
        ports.midipending = None
        ports.midi_monitor_thread = None
        ports.monitor_running = False
        ports.on_input_connected = None
        ports.queue_reserved_noteoff_slots = 1
        ports.last_reconnect_time = None
        ports.reconnect_count = 0
        ports.actual_input_port = None
        ports.actual_play_port = None
        ports.last_resolved_input_port = None
        ports.last_resolved_play_port = None
        ports.last_resolution_reason = {}
        ports.port_runtime_reconnects = 0
        ports.ignored_message_types = {"clock", "active_sensing"}
        ports.forward_backoff_until = 0.0
        return ports

    def test_live_latency_includes_time_waiting_before_native_send(self):
        ports = self.make_ports()
        ports.queues.enqueue_live_forward(FakeMidiMessage(), timestamp=100.0)
        with patch('lib.midiports.time.perf_counter', return_value=100.250):
            self.assertTrue(ports._flush_live_forward_queue_once())
        timing = ports._ensure_runtime_diagnostics().snapshot()['timings']
        self.assertEqual(timing['rtp_live_queue_wait']['max_ms'], 250.0)
        self.assertEqual(timing['rtp_send']['max_ms'], 0.0)

    def test_callback_count_distinguishes_ingress_from_processing_and_resets(self):
        ports = self.make_ports()
        ports.msg_callback(FakeMidiMessage())
        ports.msg_callback(FakeMidiMessage('clock'))
        ports.msg_callback(FakeMidiMessage('note_off'))
        self.assertEqual(ports.get_runtime_diagnostics()['counters']['midi_callback_calls'], 2)
        ports.reset_runtime_diagnostics()
        ports.msg_callback(FakeMidiMessage())
        self.assertEqual(ports.get_runtime_diagnostics()['counters']['midi_callback_calls'], 1)

    def test_callback_does_not_wait_to_notify_an_already_busy_forwarder(self):
        ports = self.make_ports()
        ports.forward_condition = threading.Condition()
        first, second = FakeMidiMessage(note=60), FakeMidiMessage(note=64)
        ports.queues.enqueue_live_forward(first)
        finished = threading.Event()

        def receive():
            ports.msg_callback(second)
            finished.set()

        worker = threading.Thread(target=receive)
        try:
            with ports.forward_condition:
                worker.start()
                self.assertTrue(finished.wait(.25), 'callback blocked on redundant forward notification')
        finally:
            worker.join(2)
        self.assertEqual([item[0] for item in ports.live_forward_queue], [first, second])

    def test_overlapping_input_callbacks_wake_sleeping_forwarder(self):
        ports = self.make_ports()
        admitted = threading.Barrier(2)
        sleeping, forwarded = threading.Event(), threading.Event()

        class OverlappingInputs(MidiQueues):
            def enqueue_all_live(self, *args, **kwargs):
                wake = super().enqueue_all_live(*args, **kwargs)
                admitted.wait(2)
                return wake

        class SleepingCondition(threading.Condition):
            def wait(self, timeout=None):
                sleeping.set()
                return super().wait(2)  # Expose a lost notify without watchdog rescue.

        class ObservedPort(FakePlayPort):
            def send(self, message):
                super().send(message)
                if len(self.sent) == 2:
                    forwarded.set()

        ports.queues = OverlappingInputs()
        ports.live_forward_queue = ports.queues.live_forward_queue
        ports.scheduled_forward_queue = ports.queues.scheduled_forward_queue
        ports.forward_condition = SleepingCondition()
        ports.playport = ObservedPort()
        ports.worker_running = True
        worker = threading.Thread(target=ports._live_forward_loop)
        callbacks = [threading.Thread(target=ports.msg_callback, args=(FakeMidiMessage(note=n),))
                     for n in (60, 64)]
        try:
            worker.start()
            self.assertTrue(sleeping.wait(1))
            for callback in callbacks:
                callback.start()
            self.assertTrue(forwarded.wait(.25), 'overlapping callbacks lost their forwarding wakeup')
        finally:
            ports.worker_running = False
            ports._notify_forward_worker()
            for callback in callbacks:
                callback.join(2)
            worker.join(2)

    def test_live_input_is_not_forwarded_synchronously(self):
        ports = self.make_ports()
        msg = FakeMidiMessage()

        ports.msg_callback(msg)

        self.assertEqual(len(ports.midi_queue), 1)
        self.assertEqual(len(ports.learning_midi_queue), 1)
        self.assertEqual(
            len(ports.playport.sent),
            0,
            "Live MIDI input should not block inside the callback by sending immediately",
        )
        self.assertEqual(len(ports.live_forward_queue), 1)

        ports._flush_live_forward_queue_once()

        self.assertEqual(len(ports.playport.sent), 1)
        self.assertIs(ports.playport.sent[0], msg)

    def test_diagnostics_queue_drained_during_snapshot_does_not_retry_sent_note(self):
        ports = self.make_ports()
        msg = FakeMidiMessage()
        ports.enqueue_rtp_message(msg, msg_timestamp=99.0)

        class DrainingDeque(deque):
            def __getitem__(self, index):
                # The consumer removes the final entry after the nonempty
                # check, before diagnostics reads the head of the queue.
                self.clear()
                return super().__getitem__(index)

        ports.midi_queue = DrainingDeque([(msg, 99.0)])
        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            self.assertTrue(ports._flush_live_forward_queue_once())
            self.assertFalse(ports._flush_live_forward_queue_once())

        self.assertEqual(ports.playport.sent, [msg])
        self.assertEqual(ports.forward_stats["live_send_errors"], 0)
        self.assertEqual(len(ports.live_forward_queue), 0)

    def test_overdue_scheduled_release_is_not_starved_by_continuous_live_input(self):
        ports = self.make_ports()
        release = FakeMidiMessage(msg_type="note_off", note=61, velocity=0)
        ports.schedule_rtp_message(release, due_time=98.0, enqueued_at=97.0)
        live = FakeMidiMessage(note=60)
        ports.enqueue_rtp_message(live, msg_timestamp=99.0)

        def send_and_keep_live_busy(msg):
            ports.playport.sent.append(msg)
            ports.enqueue_rtp_message(FakeMidiMessage(note=62), msg_timestamp=100.0)

        ports.playport.send = send_and_keep_live_busy
        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            for _ in range(4):
                ports._flush_live_forward_queue_once()

        self.assertIs(ports.playport.sent[0], release)
        self.assertIn(live, ports.playport.sent)

    def test_older_live_message_precedes_due_scheduled_message(self):
        ports = self.make_ports()
        live = FakeMidiMessage(note=60)
        scheduled = FakeMidiMessage(note=61)
        ports.enqueue_rtp_message(live, msg_timestamp=97.0)
        ports.schedule_rtp_message(scheduled, due_time=98.0, enqueued_at=96.0)
        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            ports._flush_live_forward_queue_once()
            ports._flush_live_forward_queue_once()
        self.assertEqual(ports.playport.sent, [live, scheduled])

    def test_future_scheduled_message_does_not_delay_live_input(self):
        ports = self.make_ports()
        live = FakeMidiMessage(note=60)
        ports.enqueue_rtp_message(live, msg_timestamp=99.0)
        ports.schedule_rtp_message(FakeMidiMessage(note=61), due_time=101.0, enqueued_at=98.0)
        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            self.assertTrue(ports._flush_live_forward_queue_once())
            self.assertFalse(ports._flush_live_forward_queue_once())
        self.assertEqual(ports.playport.sent, [live])

    def test_panic_follows_a_note_already_selected_by_the_forward_worker(self):
        ports = self.make_ports()
        note = FakeMidiMessage(note=60)
        ports.enqueue_rtp_message(note)
        selected = threading.Event()
        release = threading.Event()
        panic_started = threading.Event()
        panic_done = threading.Event()
        errors = []
        original_peek = ports.queues.peek_live_forward

        def select_then_pause():
            item = original_peek()
            selected.set()
            if not release.wait(2):
                raise TimeoutError("test did not release the selected note")
            return item

        ports.queues.peek_live_forward = select_then_pause

        def forward():
            try:
                ports._flush_live_forward_queue_once()
            except Exception as error:
                errors.append(error)

        def panic():
            panic_started.set()
            try:
                ports.send_all_notes_off()
            except Exception as error:
                errors.append(error)
            finally:
                panic_done.set()

        worker = threading.Thread(target=forward)
        reset = threading.Thread(target=panic)
        worker.start()
        try:
            self.assertTrue(selected.wait(2))
            reset.start()
            self.assertTrue(panic_started.wait(2))
            # The old implementation completes the reset before the selected
            # note is sent. A serialized reset waits for the in-flight note.
            panic_done.wait(0.1)
        finally:
            release.set()
            worker.join(2)
            if reset.ident is not None:
                reset.join(2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(reset.is_alive())
        self.assertEqual(errors, [])
        self.assertIs(ports.playport.sent[0], note)
        self.assertEqual(len(ports.playport.sent), 49)
        self.assertEqual(ports.playport.sent[-1].type, "control_change")

    def test_learning_queue_does_not_steal_live_visualizer_input(self):
        ports = self.make_ports()
        msg = FakeMidiMessage(note=67)

        ports.msg_callback(msg)

        learning_msg, _ = ports.learning_midi_queue.popleft()
        visualizer_msg, _ = ports.midi_queue.popleft()

        self.assertIs(learning_msg, msg)
        self.assertIs(visualizer_msg, msg)

    def test_live_and_forward_critical_queues_do_not_drop_when_capacity_hint_is_small(self):
        ports = self.make_ports(midi_maxlen=4, forward_maxlen=16)
        first = FakeMidiMessage(note=60)
        second = FakeMidiMessage(note=61)
        third = FakeMidiMessage(note=62)
        fourth = FakeMidiMessage(note=63)
        note_off = FakeMidiMessage(msg_type="note_off", note=60, velocity=0)

        ports.msg_callback(first)
        ports.msg_callback(second)
        ports.msg_callback(third)
        ports.msg_callback(fourth)
        ports.msg_callback(note_off)

        queued = [msg.note for msg, _ in ports.midi_queue]
        queued_types = [msg.type for msg, _ in ports.midi_queue]

        self.assertEqual(queued, [60, 61, 62, 63, 60])
        self.assertEqual(queued_types, ["note_on", "note_on", "note_on", "note_on", "note_off"])
        self.assertEqual(ports.drop_counter, 0)
        self.assertEqual(ports.drop_counts, {})

    def test_websocket_input_queues_playback_instead_of_sending_synchronously(self):
        ports = self.make_ports()

        ports.add_websocket_midi_message("midi_eventnote_on channel=0 note=64 velocity=90 time=0")

        self.assertEqual(len(ports.websocket_midi_queue), 1)
        self.assertEqual(len(ports.live_forward_queue), 1)
        self.assertEqual(len(ports.playport.sent), 0)

        ports._flush_live_forward_queue_once()

        self.assertEqual(len(ports.playport.sent), 1)
        self.assertEqual(ports.playport.sent[0].note, 64)

    def test_websocket_control_change_routes_sustain_to_forward_queue(self):
        ports = self.make_ports()

        ports.add_websocket_midi_message(
            "midi_eventcontrol_change channel=0 control=64 value=127 time=0"
        )

        self.assertEqual(len(ports.websocket_midi_queue), 1)
        self.assertEqual(len(ports.live_forward_queue), 1)

        ports._flush_live_forward_queue_once()

        self.assertEqual(len(ports.playport.sent), 1)
        self.assertEqual(ports.playport.sent[0].type, "control_change")
        self.assertEqual(ports.playport.sent[0].control, 64)
        self.assertEqual(ports.playport.sent[0].value, 127)

    def test_failed_playport_send_keeps_live_forward_message_for_retry(self):
        ports = self.make_ports()
        ports.playport = FakePlayPort(fail_times=1)
        msg = FakeMidiMessage(note=65)

        ports.enqueue_rtp_message(msg)

        with patch("lib.midiports.time.perf_counter", side_effect=[100.0, 100.1, 100.2]):
            self.assertFalse(ports._flush_live_forward_queue_once())

        self.assertEqual(len(ports.playport.sent), 0)
        self.assertEqual(len(ports.live_forward_queue), 1)

        with patch("lib.midiports.time.perf_counter", side_effect=[101.0, 101.1]):
            self.assertTrue(ports._flush_live_forward_queue_once())

        self.assertEqual(len(ports.live_forward_queue), 0)
        self.assertEqual(ports.playport.sent, [msg])

    def test_realtime_clock_is_ignored_before_entering_live_queues(self):
        ports = self.make_ports()

        ports.msg_callback(FakeMidiMessage(msg_type="clock"))

        self.assertEqual(len(ports.midi_queue), 0)
        self.assertEqual(len(ports.live_forward_queue), 0)
        self.assertEqual(len(ports.websocket_publish_queue), 0)
        self.assertEqual(ports.ignored_counts["clock"], 1)

    def test_enqueue_rtp_message_routes_software_notes_through_forward_queue(self):
        ports = self.make_ports()
        msg = FakeMidiMessage(note=72)

        queued = ports.enqueue_rtp_message(msg)

        self.assertTrue(queued)
        self.assertEqual(len(ports.playport.sent), 0)
        self.assertEqual(len(ports.live_forward_queue), 1)

        ports._flush_live_forward_queue_once()

        self.assertEqual(len(ports.playport.sent), 1)
        self.assertIs(ports.playport.sent[0], msg)

    def test_enqueue_rtp_message_ignores_transport_messages_before_rtp_queue(self):
        ports = self.make_ports()

        clock_queued = ports.enqueue_rtp_message(FakeMidiMessage(msg_type="clock"))
        start_queued = ports.enqueue_rtp_message(FakeMidiMessage(msg_type="start"))

        self.assertFalse(clock_queued)
        self.assertFalse(start_queued)
        self.assertEqual(len(ports.live_forward_queue), 0)
        self.assertEqual(ports.ignored_counts["clock"], 1)
        self.assertEqual(ports.ignored_counts["start"], 1)

    def test_schedule_rtp_message_waits_until_due_time(self):
        ports = self.make_ports(forward_maxlen=16)
        msg = FakeMidiMessage(note=74)

        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            queued = ports.schedule_rtp_message(msg, due_time=100.5)

        self.assertTrue(queued)
        self.assertEqual(len(ports.playport.sent), 0)
        self.assertEqual(len(ports.scheduled_forward_queue), 1)

        with patch("lib.midiports.time.perf_counter", return_value=100.1):
            self.assertFalse(ports._flush_live_forward_queue_once())
        self.assertEqual(len(ports.playport.sent), 0)

        with patch("lib.midiports.time.perf_counter", side_effect=[100.6, 100.7]):
            self.assertTrue(ports._flush_live_forward_queue_once())

        self.assertEqual(len(ports.playport.sent), 1)
        self.assertIs(ports.playport.sent[0], msg)

    def test_immediate_rtp_messages_are_not_blocked_by_future_scheduled_messages(self):
        ports = self.make_ports(forward_maxlen=16)
        scheduled = FakeMidiMessage(note=80)
        immediate = FakeMidiMessage(note=81)

        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            ports.schedule_rtp_message(scheduled, due_time=101.0)
            ports.enqueue_rtp_message(immediate)

        with patch("lib.midiports.time.perf_counter", side_effect=[100.1, 100.2]):
            self.assertTrue(ports._flush_live_forward_queue_once())

        self.assertEqual([msg.note for msg in ports.playport.sent], [81])
        self.assertEqual(len(ports.scheduled_forward_queue), 1)

    def test_scheduled_rtp_lateness_is_tracked_in_diagnostics(self):
        ports = self.make_ports(forward_maxlen=16)
        msg = FakeMidiMessage(note=82)

        with patch("lib.midiports.time.perf_counter", return_value=100.0):
            ports.schedule_rtp_message(msg, due_time=100.0)

        with patch("lib.midiports.time.perf_counter", side_effect=[100.25, 100.30, 100.30]), patch(
            "lib.midiports._get_cached_input_names", return_value=[]
        ), patch("lib.midiports._get_cached_output_names", return_value=[]):
            ports._flush_live_forward_queue_once()
            diagnostics = ports.get_rtp_diagnostics()

        self.assertEqual(diagnostics["scheduled_late_messages"], 1)
        self.assertGreaterEqual(diagnostics["scheduled_late_max_ms"], 200.0)

    def test_due_scheduled_note_is_not_starved_by_new_live_messages(self):
        ports = self.make_ports()
        scheduled = FakeMidiMessage(note=99)
        ports.queues.enqueue_scheduled_forward(scheduled, enqueued_at=90, due_time=100)
        older_live = FakeMidiMessage(note=60)
        ports.queues.enqueue_live_forward(older_live, timestamp=99)

        with patch("lib.midiports.time.perf_counter", return_value=101):
            for _ in range(3):
                ports.queues.enqueue_live_forward(FakeMidiMessage(note=61), timestamp=101)
                ports.queues.enqueue_live_forward(FakeMidiMessage(note=62), timestamp=101)
                ports._flush_live_forward_queue_once()

        self.assertEqual(ports.playport.sent[:2], [older_live, scheduled])
        self.assertEqual(len(ports.scheduled_forward_queue), 0)
        self.assertGreater(len(ports.live_forward_queue), 0)

    def test_configure_input_backend_filters_enables_rtmidi_timing_filter(self):
        ports = self.make_ports()
        input_port = FakeInputPort()

        ports._configure_input_backend_filters(input_port)

        self.assertEqual(
            input_port._rt.calls,
            [
                {
                    "sysex": False,
                    "timing": True,
                    "active_sense": True,
                }
            ],
        )

    def test_diagnostics_refresh_runtime_play_port_label_from_current_alsa_slot(self):
        ports = self.make_ports()
        ports.actual_play_port = "rtpmidid:PC_Robin 128:3"

        with patch("lib.midiports._get_cached_input_names", return_value=[]), patch(
            "lib.midiports._get_cached_output_names",
            return_value=[
                "rtpmidid:OSCMidi 128:3",
                "rtpmidid:PC_Robin 128:4",
            ],
        ):
            diagnostics = ports.get_rtp_diagnostics()

        self.assertEqual(diagnostics["actual_play_port"], "rtpmidid:OSCMidi 128:3")

    def test_input_reconnect_reopens_port_when_saved_device_returns_with_new_alsa_id(self):
        ports = self.make_ports()
        ports.usersettings = type(
            "FakeSettings",
            (),
            {"get_setting_value": lambda self, name: "mio:mio MIDI 1 16:0"},
        )()
        ports.inport = FakeInputPort()
        ports.actual_input_port = "mio:mio MIDI 1 16:0"
        opened = []

        def fake_open_input(port_name, callback=None):
            opened.append(port_name)
            return FakeInputPort()

        with patch("lib.midiports._get_cached_input_names", return_value=["mio:mio MIDI 1 24:0"]), patch(
            "lib.midiports._get_cached_output_names", return_value=[]
        ), patch("lib.midiports.mido.open_input", side_effect=fake_open_input):
            changed = ports._reconnect_input(force=False)

        self.assertTrue(changed)
        self.assertEqual(opened, ["mio:mio MIDI 1 24:0"])
        self.assertEqual(ports.actual_input_port, "mio:mio MIDI 1 24:0")
        self.assertEqual(ports.port_runtime_reconnects, 1)

    def test_input_connected_callback_fires_once_when_usb_input_is_opened(self):
        ports = self.make_ports()
        ports.usersettings = type(
            "FakeSettings",
            (),
            {"get_setting_value": lambda self, name: "default"},
        )()
        connected = []
        ports.on_input_connected = connected.append

        def fake_open_input(port_name, callback=None):
            return FakeInputPort()

        with patch(
            "lib.midiports._get_cached_input_names",
            return_value=["USB AudioDevice:USB AudioDevice MIDI 1 16:0"],
        ), patch("lib.midiports._get_cached_output_names", return_value=[]), patch(
            "lib.midiports.mido.open_input",
            side_effect=fake_open_input,
        ):
            self.assertTrue(ports._reconnect_input(force=True))
            self.assertFalse(ports._reconnect_input(force=False))

        self.assertEqual(connected, ["USB AudioDevice:USB AudioDevice MIDI 1 16:0"])

    def test_auto_reconnect_iteration_retries_when_input_is_missing_until_usb_appears(self):
        ports = self.make_ports()
        ports.usersettings = type(
            "FakeSettings",
            (),
            {"get_setting_value": lambda self, name: "default"},
        )()
        reconnects = []
        ports.reconnect_ports = lambda force=False: reconnects.append(force)

        with patch(
            "lib.midiports._get_cached_input_names",
            return_value=["USB AudioDevice:USB AudioDevice MIDI 1 16:0"],
        ), patch(
            "lib.midiports._get_cached_output_names",
            return_value=[],
        ), patch(
            "lib.midiports._refresh_port_cache",
            return_value=None,
        ):
            state = ports._auto_reconnect_once(False, False, False)

        self.assertEqual(reconnects, [False])
        self.assertEqual(state, (True, False, False))

    def test_output_reconnect_reopens_port_when_saved_device_returns_with_new_alsa_id(self):
        ports = self.make_ports()
        ports.usersettings = type(
            "FakeSettings",
            (),
            {
                "get_setting_value": lambda self, name: "rtpmidid:OSCMidi 128:3",
                "change_setting_value": lambda self, name, value: None,
            },
        )()
        ports.playport = FakePlayPort()
        ports.actual_play_port = "rtpmidid:OSCMidi 128:3"
        opened = []

        def fake_open_output(port_name):
            opened.append(port_name)
            return FakePlayPort()

        with patch("lib.midiports._get_cached_input_names", return_value=[]), patch(
            "lib.midiports._get_cached_output_names", return_value=["rtpmidid:OSCMidi 130:3"]
        ), patch("lib.midiports.mido.open_output", side_effect=fake_open_output):
            changed = ports._reconnect_output(force=False)

        self.assertTrue(changed)
        self.assertEqual(opened, ["rtpmidid:OSCMidi 130:3"])
        self.assertEqual(ports.actual_play_port, "rtpmidid:OSCMidi 130:3")
        self.assertEqual(ports.port_runtime_reconnects, 1)

    def test_explicit_missing_play_port_does_not_fallback_or_rewrite_setting(self):
        ports = self.make_ports()
        changed_settings = []
        ports.usersettings = type(
            "FakeSettings",
            (),
            {
                "get_setting_value": lambda self, name: "rtpmidid:SavedSession 128:3",
                "change_setting_value": lambda self, name, value: changed_settings.append((name, value)),
            },
        )()
        ports.playport = None
        ports.actual_play_port = None

        with patch("lib.midiports._get_cached_input_names", return_value=[]), patch(
            "lib.midiports._get_cached_output_names", return_value=["rtpmidid:OtherSession 130:3"]
        ), patch("lib.midiports.mido.open_output") as open_output:
            changed = ports._reconnect_output(force=False)

        self.assertFalse(changed)
        open_output.assert_not_called()
        self.assertEqual(changed_settings, [])
        self.assertIsNone(ports.actual_play_port)

    def test_runtime_diagnostics_include_queue_depth_and_age_peaks(self):
        ports = self.make_ports()

        with patch("lib.midiports.time.perf_counter", side_effect=[100.0, 100.0, 103.0]), patch(
            "lib.midiports._get_cached_input_names", return_value=[]
        ), patch("lib.midiports._get_cached_output_names", return_value=[]):
            ports.msg_callback(FakeMidiMessage())
            diagnostics = ports.get_runtime_diagnostics()

        live_input = diagnostics["queues"]["live_input"]
        live_forward = diagnostics["queues"]["live_forward"]

        self.assertEqual(live_input["current_depth"], 1)
        self.assertEqual(live_input["max_depth"], 1)
        self.assertEqual(live_input["current_oldest_age_ms"], 3000.0)
        self.assertEqual(live_input["max_oldest_age_ms"], 3000.0)
        self.assertEqual(live_forward["current_depth"], 1)

    def test_websocket_publish_loop_does_not_back_off_while_queue_still_has_backlog(self):
        ports = self.make_ports()
        ports.worker_running = True
        ports.websocket_publish_queue.extend([(FakeMidiMessage(), 0.0), (FakeMidiMessage(), 0.0)])

        def fake_flush():
            ports.websocket_publish_queue.popleft()
            ports.worker_running = False
            return False

        ports._flush_websocket_publish_queue_once = fake_flush

        with patch("lib.midiports.time.sleep") as sleep_mock:
            ports._websocket_publish_loop()

        sleep_mock.assert_not_called()

    def test_live_forward_loop_does_not_sleep_while_backlog_remains(self):
        ports = self.make_ports(forward_maxlen=4)
        ports.worker_running = True
        ports.live_forward_queue.extend(
            [
                (FakeMidiMessage(note=60), 0.0, "stress"),
                (FakeMidiMessage(note=61), 0.0, "stress"),
            ]
        )

        def fake_flush():
            if ports.live_forward_queue:
                ports.live_forward_queue.popleft()
                if not ports.live_forward_queue:
                    ports.worker_running = False
                return True
            ports.worker_running = False
            return False

        ports._flush_live_forward_queue_once = fake_flush

        with patch("lib.midiports.time.sleep") as sleep_mock:
            ports._live_forward_loop()

        sleep_mock.assert_not_called()

    def test_stress_live_and_scheduled_forward_paths_are_lossless(self):
        total = 50_000
        ports = self.make_ports(midi_maxlen=4, forward_maxlen=4)
        ports.playport = FakePlayPort()

        for index in range(total):
            ports.msg_callback(FakeMidiMessage(note=index % 128))
            ports.schedule_rtp_message(
                FakeMidiMessage(note=(index + 1) % 128),
                due_time=float(index),
                enqueued_at=0.0,
                source="stress_scheduled",
            )

        self.assertEqual(len(ports.midi_queue), total)
        self.assertEqual(len(ports.live_forward_queue), total)
        self.assertEqual(len(ports.scheduled_forward_queue), total)
        self.assertEqual(ports.drop_counter, 0)

        with patch("lib.midiports.time.perf_counter", return_value=float(total)):
            while ports.live_forward_queue or ports.scheduled_forward_queue:
                ports._flush_live_forward_queue_once()

        self.assertEqual(len(ports.playport.sent), total * 2)
        self.assertEqual(len(ports.live_forward_queue), 0)
        self.assertEqual(len(ports.scheduled_forward_queue), 0)
        self.assertEqual(ports.drop_counter, 0)


if __name__ == "__main__":
    unittest.main()
