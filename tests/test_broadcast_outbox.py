import threading
import unittest

from lib.broadcast_outbox import BroadcastOutbox


class TestBroadcastOutbox(unittest.TestCase):
    def test_drain_preserves_order_and_clears_queue(self):
        outbox = BroadcastOutbox(maxlen=4)
        outbox.append("first")
        outbox.append("second")

        self.assertEqual(outbox.drain(), ["first", "second"])
        self.assertEqual(outbox.drain(), [])

    def test_bounded_queue_retains_newest_messages_and_counts_drops(self):
        outbox = BroadcastOutbox(maxlen=2)
        outbox.append("first")
        outbox.append("second")
        outbox.append("third")

        self.assertEqual(outbox.drain(), ["second", "third"])
        self.assertEqual(outbox.dropped, 1)

    def test_concurrent_producers_do_not_lose_messages_below_capacity(self):
        outbox = BroadcastOutbox(maxlen=1000)

        threads = [
            threading.Thread(
                target=lambda start=start: [outbox.append(value) for value in range(start, start + 100)]
            )
            for start in range(0, 400, 100)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(outbox.drain()), 400)
        self.assertEqual(outbox.dropped, 0)


if __name__ == "__main__":
    unittest.main()
