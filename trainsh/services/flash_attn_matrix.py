"""Explicit FlashAttention compatibility matrix helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .flash_attn_matrix_data import FLASH_ATTN_COMPAT_RULES, FlashAttnCompatRule

_COMPARATOR_CHARS = "<>=!~,"


def version_tuple(value: Any, *, limit: int = 3) -> tuple[int, ...]:
    """Extract a numeric version tuple from arbitrary text."""
    parts = re.findall(r"\d+", str(value or ""))
    if not parts:
        return ()
    return tuple(int(part) for part in parts[:limit])


def at_least(value: Any, minimum: tuple[int, ...]) -> bool:
    """Compare a parsed version against a minimum tuple."""
    current = version_tuple(value, limit=len(minimum))
    if not current:
        return False
    padded = current + (0,) * max(0, len(minimum) - len(current))
    return padded[: len(minimum)] >= minimum


def major_minor_text(value: Any) -> str:
    """Normalize a version into MAJOR.MINOR text."""
    version = version_tuple(value, limit=2)
    if len(version) < 2:
        return ""
    return f"{version[0]}.{version[1]}"


def normalize_version_pin(value: Any) -> str:
    """Normalize explicit version text, dropping common prefixes."""
    text = str(value or "").strip()
    if text.lower() in {"", "auto", "latest"}:
        return ""
    if text.startswith("=="):
        text = text[2:].strip()
    if text.startswith("v") and re.match(r"^v\d", text):
        text = text[1:]
    return text


def platform_tag(system: str, machine: str, mac_version: str = "") -> str:
    """Render one wheel platform tag from platform fields."""
    sys_text = str(system or "").strip().lower()
    machine_text = str(machine or "").strip().lower() or "x86_64"
    if sys_text == "linux":
        return f"linux_{machine_text}"
    if sys_text == "darwin":
        version = ".".join(str(mac_version or "").split(".")[:2]).strip(".") or "11.0"
        return f"macosx_{version}_{machine_text}"
    if sys_text == "windows":
        return "win_amd64"
    return ""


def family_from_capability(value: str) -> str:
    """Map one CUDA compute capability to a coarse GPU family."""
    nums = version_tuple(value, limit=2)
    if len(nums) < 2:
        return ""
    major, minor = nums
    if major in {10, 12}:
        return "blackwell"
    if (major, minor) == (7, 5):
        return "turing"
    if major == 8 and minor == 9:
        return "ada"
    if major == 8:
        return "ampere"
    if major == 9:
        return "hopper"
    return ""


def family_from_name(value: str) -> str:
    """Map one GPU product string to a coarse family."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if any(
        token in text
        for token in (
            "b200",
            "b100",
            "blackwell",
            "rtx 5090",
            "rtx 5080",
            "rtx 5070",
            "rtx 5060",
            "rtx pro 6000 blackwell",
            "rtx pro 5000 blackwell",
        )
    ):
        return "blackwell"
    if any(token in text for token in ("mi300", "mi250", "mi210", "mi200", "gfx90a", "gfx942", "gfx950")):
        return "cdna"
    if any(token in text for token in ("h100", "h800", "h200", "h20", "hopper")):
        return "hopper"
    if any(
        token in text
        for token in (
            "rtx 4090",
            "rtx 4080",
            "rtx 4070",
            "rtx 4060",
            "rtx 4000",
            "rtx 4500",
            "rtx 5000 ada",
            "rtx 6000 ada",
            "l4",
            "l40",
            "l40s",
            "ada",
        )
    ):
        return "ada"
    if any(
        token in text
        for token in (
            "a100",
            "a800",
            "a40",
            "a30",
            "a10",
            "rtx 3090",
            "rtx 3080",
            "rtx 3070",
            "rtx 3060",
            "rtx 30",
            "ampere",
        )
    ):
        return "ampere"
    if any(
        token in text
        for token in ("t4", "rtx 2080", "rtx 2070", "rtx 2060", "rtx 20", "titan rtx", "quadro rtx")
    ):
        return "turing"
    return ""


def infer_gpu_families(capabilities: tuple[str, ...], names: tuple[str, ...]) -> tuple[str, ...]:
    """Infer the coarse GPU family set from capability and product names."""
    families: list[str] = []
    for capability in capabilities:
        family = family_from_capability(capability)
        if family and family not in families:
            families.append(family)
    if not families:
        for name in names:
            family = family_from_name(name)
            if family and family not in families:
                families.append(family)
    if len(families) > 1:
        return ("mixed",)
    return tuple(families)


def recommend_max_jobs(memory_gb: float, cpu_count: int) -> int:
    """Choose a conservative MAX_JOBS cap for source builds."""
    try:
        mem_total = int(float(memory_gb or 0))
    except (TypeError, ValueError):
        mem_total = 0
    try:
        cpus = int(cpu_count or 0)
    except (TypeError, ValueError):
        cpus = 0
    if mem_total <= 0 or cpus <= 0 or mem_total >= 96:
        return 0
    budget = max(1, mem_total // 8)
    return budget if budget < cpus else 0


def compose_install_spec(package_name: str, version_or_spec: Any, *, default: str = "") -> str:
    """Build an install spec from package name plus optional version/spec text."""
    package = str(package_name or "").strip()
    if not package:
        return str(default or "").strip()
    text = str(version_or_spec or "").strip()
    if text.lower() in {"", "auto", "latest"}:
        return str(default or package).strip()
    lowered = text.lower()
    if lowered.startswith(package.lower()):
        return text
    if any(char in text for char in _COMPARATOR_CHARS):
        if text.startswith(("==", "!=", ">=", "<=", "~=", ">", "<")):
            return f"{package}{text}"
        return text
    return f"{package}=={text}"


def exact_version_from_spec(package_name: str, install_spec: str) -> str:
    """Extract an exact pinned version from a package spec when present."""
    package = str(package_name or "").strip()
    spec = str(install_spec or "").strip()
    if not package or not spec.lower().startswith(package.lower()):
        return ""
    remain = spec[len(package) :].strip()
    if not remain.startswith("=="):
        return ""
    return normalize_version_pin(remain[2:])


def flash_attn_probe_score(probe: Any) -> tuple[int, int, int, int, int]:
    """Score one probe candidate so env auto-discovery can pick the best Python."""
    path = str(getattr(probe, "python_executable", "") or "").lower()
    return (
        1 if getattr(probe, "installed", False) else 0,
        1 if (getattr(probe, "torch_available", False) and getattr(probe, "backend", "")) else 0,
        1 if getattr(probe, "torch_available", False) else 0,
        1 if getattr(probe, "gpu_names", ()) else 0,
        1 if any(token in path for token in ("/venv/", ".venv/", "/conda/", "miniconda", "anaconda")) else 0,
    )


def resolve_cuda_arch_list(capabilities: tuple[str, ...]) -> str:
    """Convert CUDA capability tuples into FLASH_ATTN_CUDA_ARCHS text."""
    seen: list[str] = []
    for capability in capabilities:
        version = version_tuple(capability, limit=2)
        if len(version) < 2:
            continue
        arch = f"{version[0]}{version[1]}"
        if arch not in seen:
            seen.append(arch)
    return ";".join(seen)


def installed_matches_strategy(installed_version: str, strategy: str, pinned: str) -> bool:
    """Decide whether one installed version satisfies the selected strategy."""
    version = normalize_version_pin(installed_version)
    if not version:
        return False
    if pinned:
        return version == pinned
    major = version_tuple(version, limit=1)
    major_value = major[0] if major else 0
    if strategy == "fa4":
        return major_value >= 4
    if strategy in {"fa2", "fa2-rocm"}:
        return major_value == 2
    return True


def package_hint_from_version_spec(version_or_spec: Any) -> str:
    """Infer a likely package family from the user's version/spec text."""
    text = str(version_or_spec or "").strip().lower()
    if text in {"", "auto", "latest"}:
        return ""
    exact = normalize_version_pin(text)
    major = version_tuple(exact, limit=1)
    if major:
        if major[0] >= 4:
            return "flash-attn-4"
        return "flash-attn"
    if text.startswith("flash-attn-4"):
        return "flash-attn-4"
    if text.startswith("flash-attn"):
        return "flash-attn"
    if ">=4" in text or text.startswith("==4") or text.startswith("~=4"):
        return "flash-attn-4"
    return ""


@dataclass(frozen=True)
class FlashAttnMatrixDecision:
    """Resolved matrix decision before probe-specific validation is applied."""

    rule_id: str
    package_name: str
    strategy: str
    target: str
    default_install_spec: str
    unsupported_reason: str = ""


def select_compat_rule(
    *,
    backend: str,
    family: str,
    requested_package: str,
    version_spec: Any,
) -> FlashAttnMatrixDecision:
    """Resolve the explicit compatibility matrix row for one environment."""
    request = str(requested_package or "").strip().lower()
    version_hint = package_hint_from_version_spec(version_spec)
    if backend == "cuda" and family == "turing":
        rule = FLASH_ATTN_COMPAT_RULES[0]
        return FlashAttnMatrixDecision(
            rule_id=rule.rule_id,
            package_name=request if request not in {"", "auto"} else rule.package_name,
            strategy=rule.strategy,
            target=rule.target,
            default_install_spec=rule.default_install_spec,
            unsupported_reason=rule.unsupported_reason,
        )
    if backend == "cuda":
        if request == "flash-attn-4" or (request in {"", "auto"} and version_hint == "flash-attn-4"):
            rule = FLASH_ATTN_COMPAT_RULES[1]
            if family not in rule.families:
                return FlashAttnMatrixDecision(
                    rule_id="cuda_fa4_unsupported_family",
                    package_name="flash-attn-4",
                    strategy="unsupported",
                    target="unsupported",
                    default_install_spec="flash-attn-4",
                    unsupported_reason="flash-attn-4 targets Hopper and Blackwell GPUs only.",
                )
            return FlashAttnMatrixDecision(
                rule_id=rule.rule_id,
                package_name=rule.package_name,
                strategy=rule.strategy,
                target=rule.target,
                default_install_spec=rule.default_install_spec,
            )
        if request in {"", "auto"} and not version_hint and family in {"hopper", "blackwell"}:
            rule = FLASH_ATTN_COMPAT_RULES[1]
            return FlashAttnMatrixDecision(
                rule_id=rule.rule_id,
                package_name=rule.package_name,
                strategy=rule.strategy,
                target=rule.target,
                default_install_spec=rule.default_install_spec,
            )
        rule = FLASH_ATTN_COMPAT_RULES[2]
        return FlashAttnMatrixDecision(
            rule_id=rule.rule_id,
            package_name="flash-attn",
            strategy=rule.strategy,
            target=rule.target,
            default_install_spec=rule.default_install_spec,
        )
    if backend == "rocm":
        if request == "flash-attn-4" or version_hint == "flash-attn-4":
            return FlashAttnMatrixDecision(
                rule_id="rocm_fa4_unsupported",
                package_name="flash-attn-4",
                strategy="unsupported",
                target="unsupported",
                default_install_spec="flash-attn-4",
                unsupported_reason="flash-attn-4 is not the tmux-trainsh default path for ROCm environments.",
            )
        rule = FLASH_ATTN_COMPAT_RULES[3]
        return FlashAttnMatrixDecision(
            rule_id=rule.rule_id,
            package_name=rule.package_name,
            strategy=rule.strategy,
            target=rule.target,
            default_install_spec=rule.default_install_spec,
        )
    return FlashAttnMatrixDecision(
        rule_id="missing_backend",
        package_name=request or "flash-attn",
        strategy="unsupported",
        target="unsupported",
        default_install_spec=request or "flash-attn",
        unsupported_reason="Neither a CUDA nor a ROCm backend was detected in the target Python environment.",
    )


def compatibility_matrix_lines() -> tuple[str, ...]:
    """Render a concise user-facing compatibility matrix summary."""
    return (
        "CUDA Ampere / Ada: `flash-attn` 2.x",
        "CUDA Hopper / Blackwell: auto -> `flash-attn-4`, explicit `flash-attn` 2.x still allowed",
        "ROCm CDNA: `flash-attn` 2.x",
        "Turing: unsupported",
    )


def render_compatibility_matrix() -> str:
    """Render the compatibility matrix as stable human-readable text."""
    lines = ["FlashAttention Compatibility Matrix"]
    for line in compatibility_matrix_lines():
        lines.append(f"- {line}")
    lines.append("")
    lines.append("Rule IDs")
    for rule in FLASH_ATTN_COMPAT_RULES:
        family_text = "/".join(item or "default" for item in rule.families)
        lines.append(
            f"- {rule.rule_id}: backend={rule.backend} families={family_text} "
            f"package={rule.package_name} strategy={rule.strategy}"
        )
    return "\n".join(lines)


__all__ = [
    "FLASH_ATTN_COMPAT_RULES",
    "FlashAttnCompatRule",
    "FlashAttnMatrixDecision",
    "at_least",
    "compatibility_matrix_lines",
    "compose_install_spec",
    "exact_version_from_spec",
    "flash_attn_probe_score",
    "infer_gpu_families",
    "installed_matches_strategy",
    "major_minor_text",
    "normalize_version_pin",
    "package_hint_from_version_spec",
    "platform_tag",
    "render_compatibility_matrix",
    "recommend_max_jobs",
    "resolve_cuda_arch_list",
    "select_compat_rule",
    "version_tuple",
]
