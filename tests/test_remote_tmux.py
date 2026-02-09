import unittest
from unittest.mock import patch

from trainsh.core.remote_tmux import RemoteTmuxClient


class _Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RemoteTmuxClientTests(unittest.TestCase):
    def test_send_keys_literal_uses_tmux_send_keys(self):
        seen = []

        def fake_builder(host, command=None, tty=False, set_term=False):
            seen.append((host, command, tty, set_term))
            return ["ssh", host, command or ""]

        client = RemoteTmuxClient("gpu-host", fake_builder)
        with patch("subprocess.run", side_effect=[_Completed(), _Completed()]):
            result = client.send_keys("train_session", "echo hello", enter=True, literal=True)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(seen), 2)
        self.assertIn("tmux send-keys -t train_session -l 'echo hello'", seen[0][1])
        self.assertIn("tmux send-keys -t train_session Enter", seen[1][1])

    def test_list_panes_parses_lines(self):
        def fake_builder(host, command=None, tty=False, set_term=False):
            return ["ssh", host, command or ""]

        client = RemoteTmuxClient("gpu-host", fake_builder)
        with patch("subprocess.run", return_value=_Completed(stdout="%1\n%2\n")):
            panes = client.list_panes("train_session", "#{pane_id}")

        self.assertEqual(panes, ["%1", "%2"])

    def test_write_text_uses_heredoc(self):
        seen = []

        def fake_builder(host, command=None, tty=False, set_term=False):
            seen.append((host, command, tty, set_term))
            return ["ssh", host, command or ""]

        client = RemoteTmuxClient("gpu-host", fake_builder)
        with patch("subprocess.run", return_value=_Completed(returncode=0)):
            result = client.write_text("~/.tmux.conf", "set -g mouse on\n")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(seen), 1)
        self.assertIn('cat > "$HOME/.tmux.conf" <<', seen[0][1])
        self.assertIn("set -g mouse on", seen[0][1])

    def test_build_attach_command_uses_status_mode_and_tty(self):
        seen = []

        def fake_builder(host, command=None, tty=False, set_term=False):
            seen.append((host, command, tty, set_term))
            return ["ssh", host, command or ""]

        client = RemoteTmuxClient("gpu-host", fake_builder)
        cmd = client.build_attach_command("train_session", status_mode="off")

        self.assertIn("ssh", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("tmux set-option -gq status off", cmd)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0][2])  # tty
        self.assertTrue(seen[0][3])  # set_term


if __name__ == "__main__":
    unittest.main()
