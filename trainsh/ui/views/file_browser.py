# kitten-trainsh TUI file browser component
# Remote file browsing in kitty TUI

from dataclasses import dataclass
from typing import Optional, List, Callable, Any
from datetime import datetime

from ...services.sftp_browser import RemoteFileBrowser, FileEntry
from ...services.ssh import SSHClient


@dataclass
class FileBrowserState:
    """State for the file browser view."""
    host_id: str
    host_name: str
    current_path: str
    entries: List[FileEntry]
    selected_index: int = 0
    scroll_offset: int = 0
    marked_files: List[str] = None
    search_query: str = ""
    show_hidden: bool = True
    sort_by: str = "name"  # name, size, modified
    loading: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        if self.marked_files is None:
            self.marked_files = []

    @property
    def selected_entry(self) -> Optional[FileEntry]:
        """Get the currently selected entry."""
        if 0 <= self.selected_index < len(self.entries):
            return self.entries[self.selected_index]
        return None


class FileBrowserView:
    """
    TUI file browser component for remote hosts.

    Provides file listing, navigation, and selection
    functionality that can be integrated into the main TUI handler.
    """

    def __init__(
        self,
        ssh_client: SSHClient,
        host_id: str,
        host_name: str,
        initial_path: str = "~",
        on_select: Optional[Callable[[FileEntry], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize the file browser.

        Args:
            ssh_client: SSH client for the remote host
            host_id: Host identifier
            host_name: Display name for the host
            initial_path: Starting directory path
            on_select: Callback when a file is selected (Enter pressed)
            on_exit: Callback when browser is closed (Esc pressed)
        """
        self.browser = RemoteFileBrowser(ssh_client)
        self.on_select = on_select
        self.on_exit = on_exit

        self.state = FileBrowserState(
            host_id=host_id,
            host_name=host_name,
            current_path=initial_path,
            entries=[],
        )

        # Load initial directory
        self.refresh()

    def refresh(self) -> None:
        """Refresh the current directory listing."""
        self.state.loading = True
        self.state.error = None

        try:
            entries = self.browser.navigate(self.state.current_path)

            # Apply hidden file filter
            if not self.state.show_hidden:
                entries = [e for e in entries if not e.name.startswith(".")]

            # Apply search filter
            if self.state.search_query:
                query = self.state.search_query.lower()
                entries = [e for e in entries if query in e.name.lower()]

            # Apply sorting
            entries = self._sort_entries(entries)

            self.state.entries = entries
            self.state.selected_index = min(
                self.state.selected_index,
                len(entries) - 1 if entries else 0
            )
        except Exception as e:
            self.state.error = str(e)
            self.state.entries = []
        finally:
            self.state.loading = False

    def _sort_entries(self, entries: List[FileEntry]) -> List[FileEntry]:
        """Sort entries according to current sort setting."""
        # Always put directories first
        dirs = [e for e in entries if e.is_dir]
        files = [e for e in entries if not e.is_dir]

        if self.state.sort_by == "name":
            dirs.sort(key=lambda e: e.name.lower())
            files.sort(key=lambda e: e.name.lower())
        elif self.state.sort_by == "size":
            dirs.sort(key=lambda e: e.name.lower())
            files.sort(key=lambda e: -e.size)
        elif self.state.sort_by == "modified":
            dirs.sort(key=lambda e: e.modified or datetime.min, reverse=True)
            files.sort(key=lambda e: e.modified or datetime.min, reverse=True)

        return dirs + files

    def navigate_up(self) -> None:
        """Navigate to parent directory."""
        if self.state.current_path in ("/", "~"):
            return

        parent = "/".join(self.state.current_path.rstrip("/").split("/")[:-1])
        if not parent:
            parent = "/"

        self.state.current_path = parent
        self.state.selected_index = 0
        self.state.scroll_offset = 0
        self.refresh()

    def navigate_into(self) -> None:
        """Navigate into selected directory."""
        entry = self.state.selected_entry
        if entry and entry.is_dir:
            self.state.current_path = entry.path
            self.state.selected_index = 0
            self.state.scroll_offset = 0
            self.refresh()

    def select_entry(self) -> None:
        """Select the current entry (call callback)."""
        entry = self.state.selected_entry
        if entry and self.on_select:
            self.on_select(entry)

    def move_up(self) -> None:
        """Move selection up."""
        if self.state.selected_index > 0:
            self.state.selected_index -= 1
            self._adjust_scroll()

    def move_down(self) -> None:
        """Move selection down."""
        if self.state.selected_index < len(self.state.entries) - 1:
            self.state.selected_index += 1
            self._adjust_scroll()

    def move_page_up(self, page_size: int = 10) -> None:
        """Move selection up by a page."""
        self.state.selected_index = max(0, self.state.selected_index - page_size)
        self._adjust_scroll()

    def move_page_down(self, page_size: int = 10) -> None:
        """Move selection down by a page."""
        self.state.selected_index = min(
            len(self.state.entries) - 1,
            self.state.selected_index + page_size
        )
        self._adjust_scroll()

    def move_to_top(self) -> None:
        """Move selection to first entry."""
        self.state.selected_index = 0
        self.state.scroll_offset = 0

    def move_to_bottom(self) -> None:
        """Move selection to last entry."""
        self.state.selected_index = len(self.state.entries) - 1
        self._adjust_scroll()

    def _adjust_scroll(self, visible_rows: int = 20) -> None:
        """Adjust scroll offset to keep selection visible."""
        if self.state.selected_index < self.state.scroll_offset:
            self.state.scroll_offset = self.state.selected_index
        elif self.state.selected_index >= self.state.scroll_offset + visible_rows:
            self.state.scroll_offset = self.state.selected_index - visible_rows + 1

    def toggle_mark(self) -> None:
        """Toggle mark on current entry."""
        entry = self.state.selected_entry
        if entry:
            if entry.path in self.state.marked_files:
                self.state.marked_files.remove(entry.path)
            else:
                self.state.marked_files.append(entry.path)
            self.move_down()

    def toggle_hidden(self) -> None:
        """Toggle showing hidden files."""
        self.state.show_hidden = not self.state.show_hidden
        self.refresh()

    def cycle_sort(self) -> None:
        """Cycle through sort options."""
        options = ["name", "size", "modified"]
        idx = options.index(self.state.sort_by)
        self.state.sort_by = options[(idx + 1) % len(options)]
        self.state.entries = self._sort_entries(self.state.entries)

    def set_search(self, query: str) -> None:
        """Set search filter."""
        self.state.search_query = query
        self.refresh()

    def go_home(self) -> None:
        """Navigate to home directory."""
        home = self.browser.get_home_directory()
        self.state.current_path = home
        self.state.selected_index = 0
        self.state.scroll_offset = 0
        self.refresh()

    def get_selected_path(self) -> Optional[str]:
        """Get the path of the selected entry."""
        entry = self.state.selected_entry
        return entry.path if entry else None

    def get_marked_paths(self) -> List[str]:
        """Get list of marked file paths."""
        return list(self.state.marked_files)


def format_file_entry(
    entry: FileEntry,
    width: int = 60,
    is_selected: bool = False,
    is_marked: bool = False,
) -> str:
    """
    Format a file entry for display.

    Args:
        entry: FileEntry to format
        width: Terminal width
        is_selected: Whether entry is currently selected
        is_marked: Whether entry is marked

    Returns:
        Formatted string for display
    """
    # Mark indicator
    mark = "*" if is_marked else " "

    # Selection indicator
    select = ">" if is_selected else " "

    # Icon and name
    icon = entry.icon
    name = entry.name

    # Size or directory indicator
    size = entry.display_size

    # Truncate name if needed
    name_width = width - 25  # Leave room for size, icon, markers
    if len(name) > name_width:
        name = name[:name_width - 3] + "..."

    # Modified time
    mod_time = ""
    if entry.modified:
        mod_time = entry.modified.strftime("%Y-%m-%d")

    return f"{select}{mark} {icon} {name:<{name_width}} {size:>10} {mod_time}"


def format_browser_header(state: FileBrowserState, width: int = 60) -> str:
    """Format the browser header line."""
    path = state.current_path
    if len(path) > width - 20:
        path = "..." + path[-(width - 23):]

    return f"[{state.host_name}] {path}"


def format_browser_footer(state: FileBrowserState, width: int = 60) -> str:
    """Format the browser footer with stats and help."""
    total = len(state.entries)
    marked = len(state.marked_files)
    pos = state.selected_index + 1

    stats = f"{pos}/{total}"
    if marked > 0:
        stats += f" ({marked} marked)"

    help_text = "↑↓:nav  Enter:open  Space:mark  h:hidden  s:sort  q:quit"

    # Truncate help if needed
    avail = width - len(stats) - 3
    if len(help_text) > avail:
        help_text = help_text[:avail - 3] + "..."

    return f"{stats}  {help_text}"
