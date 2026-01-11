# kitten-trainsh session registry
# Tracks active recipe sessions for terminal<->status mapping

import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List
from datetime import datetime
import uuid


@dataclass
class RecipeSession:
    """Represents an active recipe execution session."""
    session_id: str
    recipe_name: str
    recipe_path: Optional[str]
    host_id: Optional[str]
    tmux_session: str
    kitty_window_id: Optional[int]
    started_at: str
    status: str  # running, completed, failed, cancelled

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RecipeSession":
        """Create from dictionary."""
        return cls(
            session_id=data.get("session_id", ""),
            recipe_name=data.get("recipe_name", ""),
            recipe_path=data.get("recipe_path"),
            host_id=data.get("host_id"),
            tmux_session=data.get("tmux_session", ""),
            kitty_window_id=data.get("kitty_window_id"),
            started_at=data.get("started_at", ""),
            status=data.get("status", "running"),
        )

    @classmethod
    def create(
        cls,
        recipe_name: str,
        recipe_path: Optional[str] = None,
        host_id: Optional[str] = None,
        kitty_window_id: Optional[int] = None,
    ) -> "RecipeSession":
        """Create a new session with auto-generated IDs."""
        session_id = uuid.uuid4().hex[:12]
        return cls(
            session_id=session_id,
            recipe_name=recipe_name,
            recipe_path=recipe_path,
            host_id=host_id,
            tmux_session=f"trainsh-{session_id}",
            kitty_window_id=kitty_window_id,
            started_at=datetime.now().isoformat(),
            status="running",
        )


class SessionRegistry:
    """
    Registry for tracking active recipe sessions.

    Allows mapping between:
    - Kitty terminal windows
    - Remote tmux sessions
    - Recipe execution status

    This enables opening a terminal in one window and viewing
    the recipe status in another, with both linked to the same session.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize the session registry.

        Args:
            state_dir: Directory to store session state file.
                      Defaults to ~/.config/kitten-trainsh/
        """
        if state_dir is None:
            state_dir = Path.home() / ".config" / "kitten-trainsh"
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "active_sessions.json"
        self.sessions: dict[str, RecipeSession] = {}
        self._load()

    def _load(self) -> None:
        """Load sessions from state file."""
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text())
                self.sessions = {
                    k: RecipeSession.from_dict(v)
                    for k, v in data.items()
                }
            except (json.JSONDecodeError, KeyError):
                self.sessions = {}

    def _save(self) -> None:
        """Save sessions to state file."""
        data = {k: v.to_dict() for k, v in self.sessions.items()}
        self.state_file.write_text(json.dumps(data, indent=2))

    def register(self, session: RecipeSession) -> None:
        """
        Register a new session.

        Args:
            session: Session to register
        """
        self.sessions[session.session_id] = session
        self._save()

    def unregister(self, session_id: str) -> None:
        """
        Remove a session from the registry.

        Args:
            session_id: ID of session to remove
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            self._save()

    def update_status(self, session_id: str, status: str) -> None:
        """
        Update the status of a session.

        Args:
            session_id: Session ID
            status: New status (running, completed, failed, cancelled)
        """
        if session_id in self.sessions:
            self.sessions[session_id].status = status
            self._save()

    def get(self, session_id: str) -> Optional[RecipeSession]:
        """
        Get a session by ID.

        Args:
            session_id: Session ID

        Returns:
            RecipeSession or None
        """
        return self.sessions.get(session_id)

    def get_by_kitty_window(self, window_id: int) -> Optional[RecipeSession]:
        """
        Find session by kitty window ID.

        Args:
            window_id: Kitty window ID

        Returns:
            RecipeSession or None
        """
        for session in self.sessions.values():
            if session.kitty_window_id == window_id:
                return session
        return None

    def get_by_tmux_session(self, tmux_name: str) -> Optional[RecipeSession]:
        """
        Find session by tmux session name.

        Args:
            tmux_name: Tmux session name

        Returns:
            RecipeSession or None
        """
        for session in self.sessions.values():
            if session.tmux_session == tmux_name:
                return session
        return None

    def list_running(self) -> List[RecipeSession]:
        """
        List all running sessions.

        Returns:
            List of running sessions
        """
        return [s for s in self.sessions.values() if s.status == "running"]

    def list_all(self) -> List[RecipeSession]:
        """
        List all sessions.

        Returns:
            List of all sessions
        """
        return list(self.sessions.values())

    def cleanup_stale(self) -> int:
        """
        Remove sessions that are no longer running.

        Checks if the tmux session still exists and removes
        sessions where it doesn't.

        Returns:
            Number of sessions cleaned up
        """
        from .tmux import TmuxManager

        removed = 0
        for session_id in list(self.sessions.keys()):
            session = self.sessions[session_id]

            # Only check running sessions
            if session.status != "running":
                # Remove completed/failed sessions older than 1 hour
                try:
                    started = datetime.fromisoformat(session.started_at)
                    if (datetime.now() - started).total_seconds() > 3600:
                        del self.sessions[session_id]
                        removed += 1
                except ValueError:
                    pass
                continue

            # Check if tmux session still exists
            # Note: This only works for local sessions, not remote
            tmux = TmuxManager()
            if not tmux.session_exists(session.tmux_session):
                # Mark as completed if tmux session is gone
                session.status = "completed"
                removed += 1

        if removed > 0:
            self._save()

        return removed


def get_current_kitty_window_id() -> Optional[int]:
    """
    Get the current kitty window ID using remote control.

    Returns:
        Window ID or None if not running in kitty
    """
    import subprocess
    import os

    # Check if we're in kitty
    if "KITTY_WINDOW_ID" in os.environ:
        try:
            return int(os.environ["KITTY_WINDOW_ID"])
        except ValueError:
            pass

    # Try using kitty @ ls
    try:
        result = subprocess.run(
            ["kitten", "@", "ls", "--match", "state:focused"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data and len(data) > 0:
                tabs = data[0].get("tabs", [])
                if tabs:
                    windows = tabs[0].get("windows", [])
                    if windows:
                        return windows[0].get("id")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    return None
