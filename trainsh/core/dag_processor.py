"""Recipe DAG discovery and metadata extraction."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..constants import CONFIG_DIR
from ..pyrecipe.loader import load_python_recipe


_METADATA_KEYS = {
    "name",
    "schedule",
    "schedule_interval",
    "cron",
    "is_paused",
    "paused",
    "pause",
    "owner",
    "tags",
    "catchup",
    "max_active_runs",
    "max_active_runs_per_dag",
    "executor",
    "executor_kwargs",
    "callbacks",
}

_INTERVAL_PRESETS = {
    "@hourly": 3600,
    "@daily": 24 * 3600,
    "@weekly": 7 * 24 * 3600,
    "@monthly": 30 * 24 * 3600,
    "@yearly": 365 * 24 * 3600,
}

_RE_METADATA = re.compile(r"^\s*#\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$")
_RE_EVERY = re.compile(r"^@?every\s+([0-9]+)\s*([smhd])$", re.IGNORECASE)
_RE_SECONDS = re.compile(r"^([0-9]+)\s*([smhd])$")


def _to_seconds(value: int, unit: str) -> int:
    if unit == "s":
        return int(value)
    if unit == "m":
        return int(value) * 60
    if unit == "h":
        return int(value) * 3600
    if unit == "d":
        return int(value) * 24 * 3600
    return int(value)


def parse_schedule(raw: Optional[str]) -> "DagSchedule":
    """Parse a schedule string into an internal representation."""
    if raw is None:
        return DagSchedule(raw=None, kind="manual", interval_seconds=None)

    text = str(raw).strip()
    if not text:
        return DagSchedule(raw="", kind="manual", interval_seconds=None)

    lower = text.lower()
    if lower in {"", "none", "off", "manual", "disabled", "pause", "paused", "false", "no"}:
        return DagSchedule(raw=text, kind="disabled", interval_seconds=None)
    if lower in _INTERVAL_PRESETS:
        return DagSchedule(raw=text, kind="interval", interval_seconds=_INTERVAL_PRESETS[lower])

    m = _RE_EVERY.match(lower)
    if m:
        return DagSchedule(
            raw=text,
            kind="interval",
            interval_seconds=_to_seconds(int(m.group(1)), m.group(2)),
        )

    m = _RE_SECONDS.match(lower)
    if m:
        return DagSchedule(
            raw=text,
            kind="interval",
            interval_seconds=_to_seconds(int(m.group(1)), m.group(2)),
        )

    if lower.startswith("@"):
        return DagSchedule(raw=text, kind="manual", interval_seconds=None)
    if re.search(r"\s", text):
        return DagSchedule(raw=text, kind="cron", interval_seconds=None)
    return DagSchedule(raw=text, kind="manual", interval_seconds=None)


@dataclass
class DagSchedule:
    """Normalized schedule metadata."""

    raw: Optional[str]
    kind: str
    interval_seconds: Optional[int] = None

    @property
    def is_due_capable(self) -> bool:
        return self.kind == "interval" and bool(self.interval_seconds)

    @property
    def is_supported(self) -> bool:
        return self.kind in {"interval", "manual", "disabled"}


@dataclass
class ParsedDag:
    """One discovered DAG with runtime-ready metadata."""

    dag_id: str
    path: Path
    recipe_name: str
    is_python: bool
    schedule: Optional[str]
    schedule_meta: DagSchedule
    is_paused: bool = False
    tags: List[str] = field(default_factory=list)
    owner: str = "trainsh"
    catchup: bool = False
    callbacks: List[str] = field(default_factory=lambda: ["console", "sqlite"])
    max_active_runs: int = 1
    max_active_runs_per_dag: Optional[int] = None
    executor: Optional[str] = None
    executor_kwargs: Dict[str, Any] = field(default_factory=dict)
    load_error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_modified: float = 0.0
    parsed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_valid(self) -> bool:
        return self.load_error is None

    @property
    def is_enabled(self) -> bool:
        return not self.is_paused

    @property
    def normalized_max_active_runs(self) -> int:
        return max(1, int(self.max_active_runs or 1))

    @property
    def normalized_max_active_runs_per_dag(self) -> int:
        if self.max_active_runs_per_dag is None:
            return self.normalized_max_active_runs
        return max(1, int(self.max_active_runs_per_dag))

    @property
    def is_interval_schedulable(self) -> bool:
        return self.schedule_meta.is_due_capable

    def load_recipe(self) -> Any:
        return load_python_recipe(str(self.path))


class DagProcessor:
    """Discover and parse recipe DAG metadata."""

    def __init__(
        self,
        dag_roots: Optional[Sequence[str]] = None,
        *,
        include_patterns: Optional[Sequence[str]] = None,
        recursive: bool = True,
    ):
        self.dag_roots = [Path(p) for p in (dag_roots or [str(CONFIG_DIR / "recipes")])]
        self.include_patterns = list(include_patterns or ["**/*.py"])
        self.recursive = recursive

    def discover_dags(self) -> List[ParsedDag]:
        dags: List[ParsedDag] = []
        for path in self.discover_files():
            dags.append(self.process_dag_file(path))
        dags.sort(key=lambda item: item.dag_id)
        return dags

    def discover_files(self) -> List[Path]:
        files: List[Path] = []
        for root in self.dag_roots:
            if not root:
                continue
            path = Path(root).expanduser().resolve()
            if not path.exists():
                continue

            if path.is_file():
                if path.suffix.lower() == ".py":
                    files.append(path)
                continue

            if not path.is_dir():
                continue

            if self.recursive:
                for pattern in self.include_patterns:
                    files.extend(path.glob(pattern))
            else:
                patterns = [p.split("**/")[-1] for p in self.include_patterns]
                for pattern in patterns:
                    files.extend(path.glob(pattern))

        return sorted(set(p for p in files if p.is_file()))

    def process_dag_file(self, path: Path) -> ParsedDag:
        path = path.expanduser().resolve()
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta = self._parse_metadata(path, text)
        stats = path.stat()
        schedule_raw = meta.get("schedule")
        if schedule_raw is None:
            schedule_raw = meta.get("schedule_interval")

        load_error: Optional[str] = None
        try:
            ast.parse(text)
        except Exception as exc:  # noqa: BLE001
            load_error = str(exc)

        recipe_name = str(meta.get("name", path.stem))
        callbacks = self._coerce_list(meta.get("callbacks", ["console", "sqlite"]))
        return ParsedDag(
            dag_id=str(path),
            path=path,
            recipe_name=recipe_name,
            is_python=True,
            schedule=str(schedule_raw) if schedule_raw is not None else None,
            schedule_meta=parse_schedule(schedule_raw),
            is_paused=self._coerce_bool(meta.get("is_paused", meta.get("paused", meta.get("pause", False)))),
            tags=self._coerce_list(meta.get("tags", [])),
            owner=str(meta.get("owner", "trainsh")),
            catchup=self._coerce_bool(meta.get("catchup", False)),
            callbacks=callbacks,
            max_active_runs=int(meta.get("max_active_runs", 1)),
            max_active_runs_per_dag=meta.get("max_active_runs_per_dag"),
            executor=self._coerce_scalar(meta.get("executor")),
            executor_kwargs=self._coerce_dict(meta.get("executor_kwargs", {})),
            load_error=load_error,
            metadata=meta,
            last_modified=stats.st_mtime,
            parsed_at=datetime.now(timezone.utc),
        )

    def _parse_metadata(self, path: Path, text: str) -> Dict[str, Any]:
        metadata = self._parse_comment_metadata(text)
        metadata.update(self._parse_python_assignments(text))
        return metadata

    def _parse_comment_metadata(self, text: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {}
        for raw_line in text.splitlines():
            match = _RE_METADATA.match(raw_line)
            if not match:
                continue
            key = match.group(1).lower()
            if key not in _METADATA_KEYS:
                continue
            raw_value = match.group(2).strip().strip("`\"'")
            value = self._safe_literal(raw_value)
            if value is None:
                value = raw_value
            meta[key] = value
        return meta

    def _parse_python_assignments(self, text: str) -> Dict[str, Any]:
        parsed: Dict[str, Any] = {}
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return parsed

        recipe_call = self._find_recipe_call(tree)
        recipe_name = self._parse_recipe_name_call(tree)
        if recipe_name:
            parsed["name"] = recipe_name
        if recipe_call is not None:
            parsed.update(self._parse_recipe_call_keywords(recipe_call))

        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target] if node.target else []
                value = node.value
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    key = target.id
                    if key not in _METADATA_KEYS:
                        continue
                    parsed_value = self._safe_literal(value)
                    if parsed_value is not None:
                        parsed[key] = parsed_value
        return parsed

    def _find_recipe_call(self, tree: ast.AST) -> Optional[ast.Call]:
        for node in getattr(tree, "body", []):
            value = getattr(node, "value", None)
            if isinstance(node, ast.Assign):
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                value = node.value
            if not isinstance(value, ast.Call):
                continue
            if self._is_recipe_factory_call(value):
                return value
        return None

    def _parse_recipe_name_call(self, tree: ast.AST) -> Optional[str]:
        value = self._find_recipe_call(tree)
        if value is None:
            return None

        if value.args:
            parsed = self._safe_literal(value.args[0])
            if isinstance(parsed, str) and parsed.strip():
                return parsed.strip()

        for keyword in value.keywords:
            if keyword.arg != "name":
                continue
            parsed = self._safe_literal(keyword.value)
            if isinstance(parsed, str) and parsed.strip():
                return parsed.strip()
        return None

    def _parse_recipe_call_keywords(self, node: ast.Call) -> Dict[str, Any]:
        parsed: Dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg not in _METADATA_KEYS:
                continue
            value = self._safe_literal(keyword.value)
            if value is not None:
                parsed[keyword.arg] = value
        return parsed

    @staticmethod
    def _is_recipe_factory_call(node: ast.Call) -> bool:
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "recipe"
        if isinstance(func, ast.Attribute):
            return func.attr == "recipe"
        return False

    @staticmethod
    def _safe_literal(node_or_text: Any) -> Any:
        if not isinstance(node_or_text, (ast.AST, str)):
            return None
        if isinstance(node_or_text, str):
            try:
                return ast.literal_eval(node_or_text)
            except Exception:
                return None
        try:
            return ast.literal_eval(node_or_text)
        except Exception:
            return None

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return bool(value)
        text = str(value).strip().lower()
        return text in {"1", "true", "yes", "on", "y"}

    @staticmethod
    def _coerce_scalar(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip() or None

    @staticmethod
    def _coerce_list(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip().strip("'\"") for item in value.split(",") if item.strip()]
        return []

    @staticmethod
    def _coerce_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        return {}


def dag_id_from_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


__all__ = [
    "DagProcessor",
    "ParsedDag",
    "DagSchedule",
    "parse_schedule",
    "dag_id_from_path",
]
