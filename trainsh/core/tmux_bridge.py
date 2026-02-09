# tmux-trainsh local tmux bridge
# Auto-creates local tmux splits that attach to recipe windows

import os
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from .tmux_naming import get_bridge_session_name
from .local_tmux import LocalTmuxClient


@dataclass
class BridgePane:
    """A local tmux pane used as a bridge to a recipe window."""

    window_name: str
    pane_id: str
    attach_command: str


class TmuxBridgeManager:
    """Manage local tmux split panes that auto-attach recipe windows."""

    def __init__(
        self,
        job_id: str,
        recipe_name: str,
        enabled: bool = True,
        allow_outside_tmux: bool = True,
        session_name: Optional[str] = None,
        allocate_session_name: Optional[Callable[[], str]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.job_id = job_id
        self.recipe_name = recipe_name
        self.enabled = enabled
        self.allow_outside_tmux = allow_outside_tmux
        self.log_callback = log_callback or (lambda _msg: None)
        self._allocate_session_name = allocate_session_name

        self.session_name = session_name or ""
        self.mode = "disabled"  # disabled | current_window | detached_session
        self.window_target = ""
        self._split_target = ""
        self._anchor_pane = os.environ.get("TMUX_PANE", "")
        self._ready = False
        self._detached_notice_emitted = False
        self._tmux = LocalTmuxClient()
        self._tmux_available = self._tmux.available

        self.panes: Dict[str, BridgePane] = {}

    @property
    def tmux(self) -> LocalTmuxClient:
        """Access shared local tmux client."""
        return self._tmux

    def _pane_title(self, window_name: str) -> str:
        """Stable pane title for finding panes across resume."""
        return f"train:{window_name}"

    def _ensure_ready(self) -> Tuple[bool, str]:
        """Initialize bridge mode and targets on first use."""
        if self._ready:
            return True, ""

        if not self.enabled:
            return False, "tmux auto bridge disabled by config"
        if not self._tmux_available:
            return False, "tmux binary not found for auto bridge"

        if self._anchor_pane:
            # Running inside tmux: split the current window.
            target_info = self._tmux.display_message(
                self._anchor_pane,
                "#{session_name}:#{window_name}",
            )
            if target_info.returncode != 0:
                return False, "failed to resolve current tmux window for auto bridge"

            self.mode = "current_window"
            self.window_target = target_info.stdout.strip()
            self._split_target = self._anchor_pane
            self._ready = True
            return True, ""

        if not self.allow_outside_tmux:
            return False, "not running inside tmux and detached bridge is disabled"

        if not self.session_name:
            if self._allocate_session_name:
                self.session_name = self._allocate_session_name()
            else:
                self.session_name = get_bridge_session_name(self.recipe_name, self.job_id, 0)

        # Outside tmux: create/reuse a detached local session for bridge panes.
        created = not self._tmux.has_session(self.session_name)
        if created:
            result = self._tmux.new_session(
                self.session_name,
                detached=True,
                window_name="bridges",
            )
            if result.returncode != 0:
                return False, "failed to create detached tmux bridge session"

        window_names = self._tmux.list_windows(self.session_name, "#{window_name}")
        if not window_names:
            return False, "failed to resolve bridge tmux window"

        if "bridges" in window_names:
            window_name = "bridges"
        else:
            window_name = window_names[0]

        self.mode = "detached_session"
        self.window_target = f"{self.session_name}:{window_name}"

        pane_ids = self._tmux.list_panes(self.window_target, "#{pane_id}")
        if not pane_ids:
            return False, "failed to resolve bridge tmux pane"

        self._split_target = pane_ids[0]
        self._ready = True
        self._detached_notice_emitted = not created
        return True, ""

    def _find_existing_pane(self, window_name: str) -> Optional[str]:
        """Find pane by stable title in the bridge window."""
        if not self.window_target:
            return None

        expected_title = self._pane_title(window_name)
        pane_ids = self._tmux.list_panes(self.window_target, "#{pane_id}")
        for pane_id in pane_ids:
            if not pane_id:
                continue
            title_result = self._tmux.display_message(pane_id, "#{pane_title}")
            if title_result.returncode != 0:
                continue
            if title_result.stdout.strip() == expected_title:
                return pane_id
        return None

    def _set_pane_title(self, pane_id: str, window_name: str) -> None:
        """Set pane title to make resume idempotent."""
        self._tmux.set_pane_title(pane_id, self._pane_title(window_name))

    def _normalize_layout(self) -> None:
        """Keep all bridge panes visible and easy to monitor."""
        if self.window_target:
            self._tmux.select_layout(self.window_target, "tiled")

    def connect(self, window_name: str, attach_command: str) -> Tuple[bool, str]:
        """Create or reuse a split pane for a window attach command."""
        ready, reason = self._ensure_ready()
        if not ready:
            return False, reason

        existing = self.panes.get(window_name)
        if existing:
            self._split_target = existing.pane_id
            return True, f"bridge pane ready: {existing.pane_id}"

        pane_id = self._find_existing_pane(window_name)
        if pane_id:
            self.panes[window_name] = BridgePane(
                window_name=window_name,
                pane_id=pane_id,
                attach_command=attach_command,
            )
            self._split_target = pane_id
            return True, f"bridge pane reused: {pane_id}"

        split_target = self._split_target or self._anchor_pane or self.window_target
        horizontal = len(self.panes) % 2 == 0

        result = self._tmux.split_window(
            split_target,
            attach_command,
            horizontal=horizontal,
        )
        if result.returncode != 0 and self.window_target and split_target != self.window_target:
            result = self._tmux.split_window(
                self.window_target,
                attach_command,
                horizontal=horizontal,
            )
        if result.returncode != 0:
            return False, "failed to create tmux split for auto bridge"

        pane_id = result.stdout.strip()
        self.panes[window_name] = BridgePane(
            window_name=window_name,
            pane_id=pane_id,
            attach_command=attach_command,
        )
        self._split_target = pane_id
        self._set_pane_title(pane_id, window_name)
        self._normalize_layout()

        if self.mode == "detached_session" and not self._detached_notice_emitted:
            self._detached_notice_emitted = True
            return True, f"bridge pane created: {pane_id} (attach: tmux attach -t {self.session_name})"

        return True, f"bridge pane created: {pane_id}"

    def disconnect(self, window_name: str) -> None:
        """Close the bridge pane for a recipe window."""
        if not self._ready:
            return

        pane = self.panes.pop(window_name, None)
        pane_id = pane.pane_id if pane else self._find_existing_pane(window_name)
        if not pane_id:
            return

        self._tmux.kill_pane(pane_id)

    def get_state_session(self) -> str:
        """Session name to persist for resume (detached mode only)."""
        if self.mode == "detached_session" and self.session_name:
            return self.session_name
        return ""

    def get_pane(self, window_name: str) -> Optional[str]:
        """Get existing bridge pane id for a recipe window."""
        pane = self.panes.get(window_name)
        if pane:
            return pane.pane_id

        if not self._ready:
            return None

        pane_id = self._find_existing_pane(window_name)
        if pane_id:
            self.panes[window_name] = BridgePane(
                window_name=window_name,
                pane_id=pane_id,
                attach_command="",
            )
            return pane_id

        return None
