class DisplayRefreshPolicy:
    def __init__(self):
        self._static_menu_restored = False

    def reset_static_menu(self):
        """Allow the static menu to refresh again (e.g. after wake-up, screensaver exit, or state change)."""
        self._static_menu_restored = False

    def should_show_static_menu(self, elapsed_time, hold_time, scroll_needed, should_refresh):
        if elapsed_time <= hold_time:
            self._static_menu_restored = False
            return False
        if not should_refresh:
            return False
        if scroll_needed:
            return True
        if self._static_menu_restored:
            return False
        self._static_menu_restored = True
        return True
