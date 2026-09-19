import unittest
from unittest.mock import MagicMock, patch

from lib.gpio_handler import GPIOHandler


class TestGPIOHandler(unittest.TestCase):
    def setUp(self):
        self.args = MagicMock()
        self.args.rotatescreen = "false"
        self.midiports = MagicMock()
        self.menu = MagicMock()
        self.ledstrip = MagicMock()
        self.ledsettings = MagicMock()
        self.ledsettings.sequence_active = False
        self.usersettings = MagicMock()
        self.state_manager = MagicMock()

    def test_gpio_handler_single_tap(self):
        with patch("lib.gpio_handler.GPIO") as mock_gpio:
            handler = GPIOHandler(
                self.args, self.midiports, self.menu, self.ledstrip,
                self.ledsettings, self.usersettings, self.state_manager
            )

            # Simulate KEYLEFT pressed
            mock_gpio.input.side_effect = lambda pin: 0 if pin == handler.KEYLEFT else 1
            handler.process_gpio_keys()

            self.menu.change_value.assert_called_once_with("LEFT")
            assert self.midiports.last_activity > 0
            self.state_manager.update_user_activity.assert_called_once()

            # Release key
            mock_gpio.input.side_effect = lambda pin: 1
            handler.process_gpio_keys()
            self.assertNotIn(handler.KEYLEFT, handler._key_pressed_time)

    def test_gpio_handler_dynamic_acceleration(self):
        with patch("lib.gpio_handler.GPIO") as mock_gpio, patch("time.time") as mock_time:
            t0 = 1000.0
            mock_time.return_value = t0
            handler = GPIOHandler(
                self.args, self.midiports, self.menu, self.ledstrip,
                self.ledsettings, self.usersettings, self.state_manager
            )

            # 1. Initial press at t0
            mock_gpio.input.side_effect = lambda pin: 0 if pin == handler.KEYRIGHT else 1
            handler.process_gpio_keys()
            self.menu.change_value.assert_called_with("RIGHT")
            self.menu.change_value.reset_mock()

            # 2. Within debounce (< 0.35s): no repeat
            mock_time.return_value = t0 + 0.20
            handler.process_gpio_keys()
            self.menu.change_value.assert_not_called()

            # 3. Phase 1: 0.5s held (> 0.35s, < 1.2s) -> step 1
            mock_time.return_value = t0 + 0.50
            handler.process_gpio_keys()
            self.menu.change_value.assert_called_with(1)
            self.menu.change_value.reset_mock()

            # 4. Phase 2: 1.5s held (1.2s - 2.5s) -> step 2
            mock_time.return_value = t0 + 1.50
            handler.process_gpio_keys()
            self.menu.change_value.assert_called_with(2)
            self.menu.change_value.reset_mock()

            # 5. Phase 3: 3.0s held (2.5s - 4.0s) -> step 5
            mock_time.return_value = t0 + 3.00
            handler.process_gpio_keys()
            self.menu.change_value.assert_called_with(5)
            self.menu.change_value.reset_mock()

            # 6. Phase 4: 5.0s held (> 4.0s) -> step 10
            mock_time.return_value = t0 + 5.00
            handler.process_gpio_keys()
            self.menu.change_value.assert_called_with(10)

    def test_gpio_handler_single_action_edge_triggered(self):
        with patch("lib.gpio_handler.GPIO") as mock_gpio:
            handler = GPIOHandler(
                self.args, self.midiports, self.menu, self.ledstrip,
                self.ledsettings, self.usersettings, self.state_manager
            )

            # Press KEY1 (Enter)
            mock_gpio.input.side_effect = lambda pin: 0 if pin == handler.KEY1 else 1
            handler.process_gpio_keys()
            self.menu.enter_menu.assert_called_once()

            # Keep holding KEY1
            handler.process_gpio_keys()
            self.assertEqual(self.menu.enter_menu.call_count, 1)  # Not called again!

            # Release KEY1
            mock_gpio.input.side_effect = lambda pin: 1
            handler.process_gpio_keys()

            # Press KEY1 again
            mock_gpio.input.side_effect = lambda pin: 0 if pin == handler.KEY1 else 1
            handler.process_gpio_keys()
            self.assertEqual(self.menu.enter_menu.call_count, 2)


if __name__ == "__main__":
    unittest.main()
