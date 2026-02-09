import unittest

from trainsh.core.local_tmux import LocalTmuxClient


class LocalTmuxClientTests(unittest.TestCase):
    def test_backend_is_known_value(self):
        client = LocalTmuxClient()
        self.assertIn(client.backend, {"subprocess", "unavailable"})

    def test_has_session_returns_bool(self):
        client = LocalTmuxClient()
        exists = client.has_session("definitely_missing_session_name_for_test")
        self.assertIsInstance(exists, bool)

    def test_build_attach_command_nested(self):
        client = LocalTmuxClient()
        cmd = client.build_attach_command("train_test", nested=True)
        self.assertIn("TMUX= tmux attach -t train_test", cmd)
        self.assertIn("TMUX= tmux new-session -A -s train_test", cmd)


if __name__ == "__main__":
    unittest.main()
