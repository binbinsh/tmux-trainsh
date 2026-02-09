import unittest

from trainsh.core.tmux_naming import (
    get_bridge_session_name,
    get_job_name,
    get_live_session_name,
    get_session_name,
    get_window_session_name,
    get_window_session_prefix,
    parse_window_session_index,
)


class TmuxNamingTests(unittest.TestCase):
    def test_live_session_name(self):
        self.assertEqual(
            get_live_session_name("Hello", "abcdef123456", 0),
            "train_hello_abcdef12_0",
        )

    def test_bridge_session_name(self):
        self.assertEqual(
            get_bridge_session_name("Hello", "abcdef123456", 1),
            "train_hello_abcdef12_1",
        )

    def test_job_name_contains_recipe_and_job_token(self):
        self.assertEqual(get_job_name("Brew Up", "abcdef123456"), "brew_up_abcdef12")

    def test_session_name(self):
        self.assertEqual(
            get_session_name("Brew Up", "abcdef123456", 3),
            "train_brew_up_abcdef12_3",
        )

    def test_window_session_name(self):
        self.assertEqual(
            get_window_session_name("brewup", "abcdef123456", 2),
            "train_brewup_abcdef12_2",
        )

    def test_window_session_prefix(self):
        self.assertEqual(
            get_window_session_prefix("Brew Up", "abcdef123456"),
            "train_brew_up_abcdef12_",
        )

    def test_parse_window_session_index(self):
        self.assertEqual(
            parse_window_session_index("train_brew_up_abcdef12_9", "brew up", "abcdef123456"),
            9,
        )
        self.assertIsNone(
            parse_window_session_index("train_other_abcdef12_9", "brew up", "abcdef123456"),
        )


if __name__ == "__main__":
    unittest.main()
