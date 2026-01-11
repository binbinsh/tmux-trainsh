# kitten-trainsh recipe progress view
# Visual progress display for recipe execution

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Callable
from enum import Enum
from datetime import datetime


class StepStatus(Enum):
    """Status of a recipe step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class StepProgress:
    """Progress information for a single step."""
    step_id: str
    step_name: str
    status: StepStatus = StepStatus.PENDING
    output_lines: List[str] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        """Get duration in seconds."""
        if not self.started_at:
            return 0
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def duration_str(self) -> str:
        """Get formatted duration string."""
        secs = self.duration_seconds
        if secs < 60:
            return f"{secs:.1f}s"
        elif secs < 3600:
            return f"{int(secs // 60)}m {int(secs % 60)}s"
        else:
            return f"{int(secs // 3600)}h {int((secs % 3600) // 60)}m"


@dataclass
class RecipeProgress:
    """Overall progress of a recipe execution."""
    recipe_name: str
    total_steps: int
    steps: Dict[str, StepProgress] = field(default_factory=dict)
    current_step_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed

    @property
    def completed_steps(self) -> int:
        """Count of completed steps."""
        return sum(1 for s in self.steps.values() if s.status == StepStatus.COMPLETED)

    @property
    def failed_steps(self) -> int:
        """Count of failed steps."""
        return sum(1 for s in self.steps.values() if s.status == StepStatus.FAILED)

    @property
    def progress_percent(self) -> float:
        """Overall progress percentage."""
        if self.total_steps == 0:
            return 0
        return (self.completed_steps / self.total_steps) * 100


class RecipeProgressHandler:
    """
    Handles recipe execution progress callbacks.

    Can be used with recipe_executor to track and display progress.
    """

    def __init__(
        self,
        recipe_name: str,
        step_ids: List[str],
        step_names: Optional[Dict[str, str]] = None,
        on_update: Optional[Callable[["RecipeProgress"], None]] = None,
    ):
        """
        Initialize the progress handler.

        Args:
            recipe_name: Name of the recipe
            step_ids: List of step IDs in execution order
            step_names: Optional mapping of step ID to display name
            on_update: Callback when progress changes
        """
        self.progress = RecipeProgress(
            recipe_name=recipe_name,
            total_steps=len(step_ids),
        )
        self.step_order = step_ids
        self.step_names = step_names or {}
        self.on_update = on_update

        # Initialize step progress entries
        for step_id in step_ids:
            self.progress.steps[step_id] = StepProgress(
                step_id=step_id,
                step_name=self.step_names.get(step_id, step_id),
            )

    def on_recipe_start(self) -> None:
        """Called when recipe execution starts."""
        self.progress.started_at = datetime.now()
        self.progress.status = "running"
        self._notify()

    def on_recipe_complete(self, success: bool) -> None:
        """Called when recipe execution completes."""
        self.progress.completed_at = datetime.now()
        self.progress.status = "completed" if success else "failed"
        self.progress.current_step_id = None
        self._notify()

    def on_step_start(self, step_id: str) -> None:
        """Called when a step starts executing."""
        if step_id in self.progress.steps:
            step = self.progress.steps[step_id]
            step.status = StepStatus.RUNNING
            step.started_at = datetime.now()
            self.progress.current_step_id = step_id
            self._notify()

    def on_step_output(self, step_id: str, line: str) -> None:
        """Called when a step produces output."""
        if step_id in self.progress.steps:
            step = self.progress.steps[step_id]
            step.output_lines.append(line)
            # Keep only last 100 lines to save memory
            if len(step.output_lines) > 100:
                step.output_lines = step.output_lines[-100:]
            self._notify()

    def on_step_complete(self, step_id: str, success: bool, error: Optional[str] = None) -> None:
        """Called when a step completes."""
        if step_id in self.progress.steps:
            step = self.progress.steps[step_id]
            step.status = StepStatus.COMPLETED if success else StepStatus.FAILED
            step.completed_at = datetime.now()
            step.error = error
            self._notify()

    def on_step_skip(self, step_id: str, reason: str = "") -> None:
        """Called when a step is skipped."""
        if step_id in self.progress.steps:
            step = self.progress.steps[step_id]
            step.status = StepStatus.SKIPPED
            step.error = reason
            self._notify()

    def _notify(self) -> None:
        """Notify listeners of progress update."""
        if self.on_update:
            self.on_update(self.progress)


def format_progress_text(progress: RecipeProgress, width: int = 60) -> str:
    """
    Format progress as text for display.

    Args:
        progress: RecipeProgress to format
        width: Terminal width

    Returns:
        Formatted text string
    """
    lines = []

    # Header
    lines.append(f"Recipe: {progress.recipe_name}")
    lines.append("=" * min(width, 60))

    # Overall progress bar
    pct = progress.progress_percent
    bar_width = min(width - 10, 40)
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    lines.append(f"[{bar}] {pct:.0f}%")
    lines.append("")

    # Step list
    for step_id in progress.steps:
        step = progress.steps[step_id]
        icon = _get_status_icon(step.status)
        is_current = step_id == progress.current_step_id
        prefix = "→ " if is_current else "  "

        line = f"{prefix}{icon} {step.step_name}"

        # Add duration for completed/running steps
        if step.status in (StepStatus.RUNNING, StepStatus.COMPLETED, StepStatus.FAILED):
            line += f" ({step.duration_str})"

        lines.append(line)

        # Show error if failed
        if step.error:
            lines.append(f"      Error: {step.error[:50]}...")

    lines.append("")

    # Current step output
    if progress.current_step_id:
        current_step = progress.steps.get(progress.current_step_id)
        if current_step and current_step.output_lines:
            lines.append("--- Output ---")
            for line in current_step.output_lines[-10:]:
                # Truncate long lines
                if len(line) > width:
                    line = line[:width - 3] + "..."
                lines.append(f"  {line}")

    return "\n".join(lines)


def _get_status_icon(status: StepStatus) -> str:
    """Get icon for step status."""
    icons = {
        StepStatus.PENDING: "○",
        StepStatus.RUNNING: "◐",
        StepStatus.COMPLETED: "●",
        StepStatus.FAILED: "✗",
        StepStatus.SKIPPED: "◌",
        StepStatus.CANCELLED: "⊘",
    }
    return icons.get(status, "?")


def get_status_color(status: StepStatus) -> str:
    """Get ANSI color for step status."""
    colors = {
        StepStatus.PENDING: "\033[90m",    # Gray
        StepStatus.RUNNING: "\033[33m",    # Yellow
        StepStatus.COMPLETED: "\033[32m",  # Green
        StepStatus.FAILED: "\033[31m",     # Red
        StepStatus.SKIPPED: "\033[90m",    # Gray
        StepStatus.CANCELLED: "\033[90m",  # Gray
    }
    return colors.get(status, "")
