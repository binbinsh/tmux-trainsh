import unittest
from unittest.mock import patch

from trainsh.core.tmux_bridge import TmuxBridgeManager


class FakeLocalTmux:
    def __init__(self):
        self.available = True
        self.sessions = set()
        self.window_names = ["bridges"]
        self.panes = ["%0"]
        self.pane_titles = {}
        self.split_result = ("%1", 0)
        self.killed = []

    def display_message(self, target, fmt):
        if fmt == "#{session_name}:#{window_name}":
            return type("R", (), {"returncode": 0, "stdout": "sess:win\n"})()
        if fmt == "#{pane_title}":
            title = self.pane_titles.get(target, "")
            return type("R", (), {"returncode": 0, "stdout": title})()
        return type("R", (), {"returncode": 0, "stdout": ""})()

    def new_session(self, name, detached=True, window_name=None, command=None):
        self.sessions.add(name)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def has_session(self, name):
        return name in self.sessions

    def list_windows(self, target, fmt="#{window_name}"):
        return list(self.window_names)

    def list_panes(self, target, fmt="#{pane_id}"):
        return list(self.panes)

    def split_window(self, target, command, horizontal=True):
        pane_id, code = self.split_result
        return type("R", (), {"returncode": code, "stdout": pane_id, "stderr": ""})()

    def set_pane_title(self, pane_id, title):
        self.pane_titles[pane_id] = title
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def select_layout(self, target, layout):
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    def kill_pane(self, pane_id):
        self.killed.append(pane_id)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()


class TmuxBridgeManagerTests(unittest.TestCase):
    def test_ensure_ready_and_connect_inside_tmux(self):
        fake = FakeLocalTmux()
        with patch("trainsh.core.tmux_bridge.LocalTmuxClient", return_value=fake), patch.dict(
            "os.environ", {"TMUX_PANE": "%9"}, clear=False
        ):
            bridge = TmuxBridgeManager("job1", "demo", enabled=True, allow_outside_tmux=True)
            ok, reason = bridge._ensure_ready()
            self.assertTrue(ok)
            self.assertEqual(bridge.mode, "current_window")
            self.assertEqual(bridge.window_target, "sess:win")

            ok, msg = bridge.connect("main", "attach-cmd")
            self.assertTrue(ok)
            self.assertIn("created", msg)
            pane_id = bridge.get_pane("main")
            self.assertEqual(pane_id, "%1")

            ok, msg = bridge.connect("main", "attach-cmd")
            self.assertTrue(ok)
            self.assertIn("ready", msg)

            bridge.disconnect("main")
            self.assertEqual(fake.killed, ["%1"])

    def test_detached_session_ready_and_failure_paths(self):
        fake = FakeLocalTmux()
        with patch("trainsh.core.tmux_bridge.LocalTmuxClient", return_value=fake), patch.dict("os.environ", {}, clear=True):
            bridge = TmuxBridgeManager("job1", "demo", enabled=False)
            ok, reason = bridge._ensure_ready()
            self.assertFalse(ok)
            self.assertIn("disabled", reason)

            bridge = TmuxBridgeManager("job1", "demo", enabled=True, allow_outside_tmux=False)
            ok, reason = bridge._ensure_ready()
            self.assertFalse(ok)
            self.assertIn("detached bridge is disabled", reason)

            fake.available = False
            bridge = TmuxBridgeManager("job1", "demo")
            ok, reason = bridge._ensure_ready()
            self.assertFalse(ok)
            self.assertIn("tmux binary not found", reason)

        fake = FakeLocalTmux()
        fake.window_names = []
        with patch("trainsh.core.tmux_bridge.LocalTmuxClient", return_value=fake), patch.dict("os.environ", {}, clear=True):
            bridge = TmuxBridgeManager("job1", "demo")
            ok, reason = bridge._ensure_ready()
            self.assertFalse(ok)
            self.assertIn("failed to resolve bridge tmux window", reason)

        fake = FakeLocalTmux()
        fake.panes = []
        with patch("trainsh.core.tmux_bridge.LocalTmuxClient", return_value=fake), patch.dict("os.environ", {}, clear=True):
            bridge = TmuxBridgeManager("job1", "demo")
            ok, reason = bridge._ensure_ready()
            self.assertFalse(ok)
            self.assertIn("failed to resolve bridge tmux pane", reason)

        fake = FakeLocalTmux()
        fake.split_result = ("%1", 1)
        with patch("trainsh.core.tmux_bridge.LocalTmuxClient", return_value=fake), patch.dict("os.environ", {}, clear=True):
            bridge = TmuxBridgeManager("job1", "demo")
            ok, reason = bridge.connect("main", "attach-cmd")
            self.assertFalse(ok)
            self.assertIn("failed to create tmux split", reason)

    def test_find_existing_reuse_and_state_session(self):
        fake = FakeLocalTmux()
        fake.sessions.add("bridge-sess")
        fake.panes = ["%0", "%2"]
        fake.pane_titles["%2"] = "train:main"
        with patch("trainsh.core.tmux_bridge.LocalTmuxClient", return_value=fake), patch.dict("os.environ", {}, clear=True):
            bridge = TmuxBridgeManager("job1", "demo", session_name="bridge-sess")
            ok, reason = bridge._ensure_ready()
            self.assertTrue(ok)
            self.assertEqual(bridge.mode, "detached_session")
            self.assertEqual(bridge.get_state_session(), "bridge-sess")

            ok, msg = bridge.connect("main", "attach-cmd")
            self.assertTrue(ok)
            self.assertIn("reused", msg)
            self.assertEqual(bridge.get_pane("main"), "%2")

            bridge.disconnect("missing")
            self.assertEqual(fake.killed, [])

            fake.pane_titles["%3"] = "train:other"
            fake.panes.append("%3")
            self.assertEqual(bridge.get_pane("other"), "%3")


if __name__ == "__main__":
    unittest.main()
