"""FlashAttention environment probing and install planning helpers."""

from __future__ import annotations

import json
import shlex
from dataclasses import asdict, dataclass, field
from textwrap import dedent
from typing import Any

from .flash_attn_matrix import (
    at_least,
    compose_install_spec,
    exact_version_from_spec,
    flash_attn_probe_score,
    infer_gpu_families,
    installed_matches_strategy,
    major_minor_text,
    normalize_version_pin,
    package_hint_from_version_spec,
    platform_tag,
    recommend_max_jobs,
    resolve_cuda_arch_list,
    select_compat_rule,
    version_tuple,
)


_PROBE_MARKER = "__TRAINSH_FLASH_ATTN_PROBE__="
_WHEEL_BASE_URL = (
    "https://github.com/Dao-AILab/flash-attention/releases/download/v{version}/{wheel_name}"
)


def _string_list(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        text = values.strip()
        return (text,) if text else ()
    if not isinstance(values, (list, tuple, set)):
        text = str(values).strip()
        return (text,) if text else ()
    return tuple(str(value).strip() for value in values if str(value).strip())


@dataclass(frozen=True)
class FlashAttnProbe:
    """Normalized probe result for one Python environment."""

    python_executable: str = ""
    python_version: str = ""
    python_tag: str = ""
    platform_system: str = ""
    platform_machine: str = ""
    platform_tag: str = ""
    mac_version: str = ""
    torch_available: bool = False
    torch_version: str = ""
    torch_major_minor: str = ""
    torch_cuda_version: str = ""
    torch_hip_version: str = ""
    torch_cxx11_abi: str = ""
    torch_error: str = ""
    flash_attn_version: str = ""
    gpu_names: tuple[str, ...] = field(default_factory=tuple)
    gpu_capabilities: tuple[str, ...] = field(default_factory=tuple)
    gpu_families: tuple[str, ...] = field(default_factory=tuple)
    nvcc_version: str = ""
    hipcc_version: str = ""
    cpu_count: int = 0
    memory_gb: float = 0.0
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def backend(self) -> str:
        if self.torch_hip_version or self.hipcc_version or any("mi" in name.lower() for name in self.gpu_names):
            return "rocm"
        if self.torch_cuda_version or self.nvcc_version or self.gpu_names:
            return "cuda"
        return ""

    @property
    def primary_gpu_family(self) -> str:
        return self.gpu_families[0] if self.gpu_families else ""

    @property
    def installed(self) -> bool:
        return bool(self.flash_attn_version)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "FlashAttnProbe":
        data = dict(payload or {})
        python_version = str(data.get("python_version", "")).strip()
        python_tag = str(data.get("python_tag", "")).strip()
        if not python_tag:
            version = version_tuple(python_version, limit=2)
            if len(version) == 2:
                python_tag = f"cp{version[0]}{version[1]}"
        gpu_names = _string_list(data.get("gpu_names"))
        gpu_capabilities = _string_list(data.get("gpu_capabilities"))
        return cls(
            python_executable=str(data.get("python_executable", "")).strip(),
            python_version=python_version,
            python_tag=python_tag,
            platform_system=str(data.get("platform_system", "")).strip(),
            platform_machine=str(data.get("platform_machine", "")).strip(),
            platform_tag=str(data.get("platform_tag", "")).strip()
            or platform_tag(
                str(data.get("platform_system", "")).strip(),
                str(data.get("platform_machine", "")).strip(),
                str(data.get("mac_version", "")).strip(),
            ),
            mac_version=str(data.get("mac_version", "")).strip(),
            torch_available=bool(data.get("torch_available")),
            torch_version=str(data.get("torch_version", "")).strip(),
            torch_major_minor=str(data.get("torch_major_minor", "")).strip()
            or major_minor_text(data.get("torch_version", "")),
            torch_cuda_version=str(data.get("torch_cuda_version", "")).strip(),
            torch_hip_version=str(data.get("torch_hip_version", "")).strip(),
            torch_cxx11_abi=str(data.get("torch_cxx11_abi", "")).strip(),
            torch_error=str(data.get("torch_error", "")).strip(),
            flash_attn_version=str(data.get("flash_attn_version", "")).strip(),
            gpu_names=gpu_names,
            gpu_capabilities=gpu_capabilities,
            gpu_families=_string_list(data.get("gpu_families")) or infer_gpu_families(gpu_capabilities, gpu_names),
            nvcc_version=str(data.get("nvcc_version", "")).strip(),
            hipcc_version=str(data.get("hipcc_version", "")).strip(),
            cpu_count=int(data.get("cpu_count") or 0),
            memory_gb=float(data.get("memory_gb") or 0.0),
            errors=_string_list(data.get("errors")),
        )


@dataclass(frozen=True)
class FlashAttnPlan:
    """Planning result for one probed FlashAttention environment."""

    ok: bool
    status: str
    backend: str
    target: str
    summary: str
    package_name: str
    strategy: str
    install_spec: str
    rule_id: str = ""
    wheel_url: str = ""
    wheel_name: str = ""
    recommended_max_jobs: int = 0
    install_env: dict[str, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_flash_attn_probe_command(python_bin: str = "") -> str:
    """Build one remote shell command that prints one or more probe JSON payloads."""
    preferred_python = str(python_bin or "").strip()
    shell_script = dedent(
        f"""\
        set -e
        PREFERRED_PY={shlex.quote(preferred_python)}
        SEEN=""
        FOUND=0
        add_candidate() {{
          CANDIDATE="$1"
          [ -n "$CANDIDATE" ] || return 0
          [ -x "$CANDIDATE" ] || return 0
          case " $SEEN " in
            *" $CANDIDATE "*) return 0 ;;
          esac
          SEEN="$SEEN $CANDIDATE"
          FOUND=1
          TRAINSH_FLASH_ATTN_PY="$CANDIDATE" "$CANDIDATE" - <<'PY'
        import json
        import os
        import platform
        import re
        import subprocess
        import sys

        MARKER = {json.dumps(_PROBE_MARKER)}


        def run_text(argv):
            try:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            except Exception:
                return ""
            text = (result.stdout or result.stderr or "").strip()
            return text if result.returncode == 0 else ""


        def parse_nvcc(text):
            match = re.search(r"release\\s+([0-9]+(?:\\.[0-9]+)?)", text)
            return match.group(1) if match else ""


        def parse_hipcc(text):
            match = re.search(r"(?:HIP|hipcc)\\s+version[:\\s]+([0-9]+(?:\\.[0-9]+)+)", text, flags=re.I)
            return match.group(1) if match else ""


        def memory_gb():
            try:
                with open("/proc/meminfo", "r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return round(int(parts[1]) / 1024 / 1024, 2)
            except OSError:
                return 0.0
            return 0.0


        requested_python = os.environ.get("TRAINSH_FLASH_ATTN_PY", "").strip()
        gpu_names = []
        gpu_capabilities = []
        torch_available = False
        torch_version = ""
        torch_cuda_version = ""
        torch_hip_version = ""
        torch_cxx11_abi = ""
        torch_error = ""
        flash_attn_version = ""

        try:
            import torch  # type: ignore

            torch_available = True
            torch_version = str(getattr(torch, "__version__", "") or "")
            torch_cuda_version = str(getattr(torch.version, "cuda", "") or "")
            torch_hip_version = str(getattr(torch.version, "hip", "") or "")
            cxx11_abi = getattr(getattr(torch, "_C", None), "_GLIBCXX_USE_CXX11_ABI", None)
            if cxx11_abi is not None:
                torch_cxx11_abi = "TRUE" if bool(cxx11_abi) else "FALSE"
            if getattr(torch, "cuda", None) and torch.cuda.is_available():
                for index in range(int(torch.cuda.device_count())):
                    try:
                        gpu_names.append(str(torch.cuda.get_device_name(index)))
                    except Exception:
                        pass
                    try:
                        capability = torch.cuda.get_device_capability(index)
                    except Exception:
                        capability = None
                    if capability:
                        gpu_capabilities.append(f"{{capability[0]}}.{{capability[1]}}")
        except Exception as exc:
            torch_error = str(exc)

        if not gpu_names:
            text = run_text(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
            if text:
                gpu_names = [line.strip() for line in text.splitlines() if line.strip()]
        if not gpu_names:
            text = run_text(["rocminfo"])
            if text:
                gpu_names = sorted(
                    {{
                        line.split(":", 1)[1].strip()
                        for line in text.splitlines()
                        if "Name:" in line and "gfx" not in line
                    }}
                )

        try:
            import flash_attn  # type: ignore

            flash_attn_version = str(getattr(flash_attn, "__version__", "") or "")
        except Exception:
            flash_attn_version = ""

        payload = {{
            "python_executable": requested_python or sys.executable,
            "python_version": platform.python_version(),
            "python_tag": f"cp{{sys.version_info.major}}{{sys.version_info.minor}}",
            "platform_system": platform.system(),
            "platform_machine": platform.machine(),
            "platform_tag": (
                f"linux_{{platform.machine()}}" if sys.platform.startswith("linux")
                else "win_amd64" if sys.platform == "win32"
                else ""
            ),
            "mac_version": platform.mac_ver()[0],
            "torch_available": torch_available,
            "torch_version": torch_version,
            "torch_major_minor": ".".join(torch_version.split(".")[:2]) if torch_version else "",
            "torch_cuda_version": torch_cuda_version,
            "torch_hip_version": torch_hip_version,
            "torch_cxx11_abi": torch_cxx11_abi,
            "torch_error": torch_error,
            "flash_attn_version": flash_attn_version,
            "gpu_names": gpu_names,
            "gpu_capabilities": gpu_capabilities,
            "nvcc_version": parse_nvcc(run_text(["nvcc", "--version"])),
            "hipcc_version": parse_hipcc(run_text(["hipcc", "--version"])),
            "cpu_count": os.cpu_count() or 0,
            "memory_gb": memory_gb(),
            "errors": [],
        }}
        print(MARKER + json.dumps(payload, sort_keys=True))
        PY
        }}

        if [ -n "$PREFERRED_PY" ]; then
          add_candidate "$PREFERRED_PY"
        else
          if command -v python3 >/dev/null 2>&1; then add_candidate "$(command -v python3)"; fi
          if command -v python >/dev/null 2>&1; then add_candidate "$(command -v python)"; fi
          if [ -n "${{VIRTUAL_ENV:-}}" ]; then add_candidate "${{VIRTUAL_ENV}}/bin/python"; fi
          if [ -n "${{CONDA_PREFIX:-}}" ]; then add_candidate "${{CONDA_PREFIX}}/bin/python"; fi
          for candidate in \
            /venv/main/bin/python \
            /venv/bin/python \
            /opt/conda/bin/python \
            /root/miniconda3/bin/python \
            /root/anaconda3/bin/python \
            "$HOME/.venv/bin/python" \
            /workspace/.venv/bin/python \
            /workspace/*/.venv/bin/python \
            /workspace/*/*/.venv/bin/python \
            /opt/conda/envs/*/bin/python \
            /root/miniconda3/envs/*/bin/python \
            /root/anaconda3/envs/*/bin/python
          do
            add_candidate "$candidate"
          done
        fi

        if [ "$FOUND" -eq 0 ]; then
          printf '%s%s\\n' '{_PROBE_MARKER}' '{{"errors":["python-not-found"]}}'
        fi
        """
    ).strip()
    return f"sh -lc {shlex.quote(shell_script)}"


def parse_flash_attn_probe_output(output: str) -> FlashAttnProbe:
    """Extract the best probe payload from shell output."""
    candidates: list[FlashAttnProbe] = []
    for line in str(output or "").splitlines():
        if line.startswith(_PROBE_MARKER):
            try:
                payload = json.loads(line[len(_PROBE_MARKER) :].strip())
            except Exception as exc:
                return FlashAttnProbe.from_dict({"errors": [f"invalid-probe-payload: {exc}"]})
            if not isinstance(payload, dict):
                return FlashAttnProbe.from_dict({"errors": ["probe-payload-was-not-an-object"]})
            candidates.append(FlashAttnProbe.from_dict(payload))
    if candidates:
        return sorted(candidates, key=flash_attn_probe_score, reverse=True)[0]
    return FlashAttnProbe.from_dict({"errors": ["probe-output-missing"]})


def guess_flash_attn_wheel_url(probe: FlashAttnProbe | dict[str, Any], version: str) -> tuple[str, str]:
    """Mirror the upstream wheel naming convention when enough data is available."""
    normalized = probe if isinstance(probe, FlashAttnProbe) else FlashAttnProbe.from_dict(probe)
    pinned = normalize_version_pin(version)
    torch_tag = normalized.torch_major_minor
    python_tag = normalized.python_tag
    platform_text = normalized.platform_tag
    cxx11_abi = normalized.torch_cxx11_abi or "FALSE"
    if not pinned or not torch_tag or not python_tag or not platform_text:
        return "", ""
    if normalized.backend == "cuda":
        cuda_version = version_tuple(normalized.torch_cuda_version, limit=2)
        if not cuda_version:
            return "", ""
        cuda_tag = "11" if cuda_version[0] == 11 else "12"
        wheel_name = (
            f"flash_attn-{pinned}+cu{cuda_tag}torch{torch_tag}"
            f"cxx11abi{cxx11_abi}-{python_tag}-{python_tag}-{platform_text}.whl"
        )
    elif normalized.backend == "rocm":
        hip_version = version_tuple(normalized.torch_hip_version or normalized.hipcc_version, limit=2)
        if len(hip_version) < 2:
            return "", ""
        hip_tag = f"{hip_version[0]}{hip_version[1]}"
        wheel_name = (
            f"flash_attn-{pinned}+rocm{hip_tag}torch{torch_tag}"
            f"cxx11abi{cxx11_abi}-{python_tag}-{python_tag}-{platform_text}.whl"
        )
    else:
        return "", ""
    return _WHEEL_BASE_URL.format(version=pinned, wheel_name=wheel_name), wheel_name


def plan_flash_attn_install(
    probe: FlashAttnProbe | dict[str, Any],
    *,
    version: str = "",
    package_name: str = "",
    force_build: bool = False,
) -> FlashAttnPlan:
    """Analyze one probe and produce an install plan."""
    normalized = probe if isinstance(probe, FlashAttnProbe) else FlashAttnProbe.from_dict(probe)
    requested_package = str(package_name or "").strip().lower()
    reasons: list[str] = []
    warnings: list[str] = []
    install_env: dict[str, str] = {}

    if normalized.errors:
        reasons.extend(normalized.errors)
    if normalized.platform_system and normalized.platform_system.lower() != "linux":
        reasons.append("Official flash-attn support is Linux-first; this target is not Linux.")
    if not normalized.python_version:
        reasons.append("Python was not detected on the target host.")
    if not normalized.torch_available:
        reasons.append("PyTorch is not installed in the target Python environment.")
    elif not at_least(normalized.torch_version, (2, 2)):
        reasons.append("Official flash-attn docs require PyTorch 2.2 or newer.")

    decision = select_compat_rule(
        backend=normalized.backend,
        family=normalized.primary_gpu_family,
        requested_package=requested_package,
        version_spec=version,
    )
    if decision.unsupported_reason:
        reasons.append(decision.unsupported_reason)

    if normalized.backend == "cuda":
        if normalized.torch_cuda_version and version_tuple(normalized.torch_cuda_version, limit=1):
            if version_tuple(normalized.torch_cuda_version, limit=1)[0] < 11:
                reasons.append("CUDA builds below major version 11 are not supported.")
        if normalized.nvcc_version and not at_least(normalized.nvcc_version, (11, 7)):
            reasons.append("nvcc is older than 11.7, so source builds are not viable.")
        if not normalized.nvcc_version:
            warnings.append("nvcc was not detected; if no upstream wheel matches, source compilation will fail.")
        if decision.package_name == "flash-attn":
            archs = resolve_cuda_arch_list(normalized.gpu_capabilities)
            if archs:
                install_env["FLASH_ATTN_CUDA_ARCHS"] = archs
                install_env["NVCC_THREADS"] = "2"
        elif decision.package_name == "flash-attn-4" and normalized.primary_gpu_family not in {"hopper", "blackwell"}:
            reasons.append("flash-attn-4 support targets Hopper and Blackwell GPUs only.")
        elif normalized.primary_gpu_family in {"", "unknown"} and normalized.gpu_names:
            warnings.append("CUDA GPUs were detected, but their family could not be classified precisely.")
        elif normalized.primary_gpu_family == "mixed":
            warnings.append("Mixed GPU families were detected; flash-attn behavior may vary across devices.")
    elif normalized.backend == "rocm":
        if normalized.primary_gpu_family not in {"", "cdna", "mixed"}:
            reasons.append("Current ROCm docs target MI200/MI300-class GPUs.")
        if normalized.primary_gpu_family == "mixed":
            warnings.append("Mixed ROCm GPU families were detected; only MI200/MI300 are documented.")
        if not at_least(normalized.torch_hip_version or normalized.hipcc_version, (6, 0)):
            reasons.append("ROCm support requires HIP/ROCm 6.0 or newer.")
        if not normalized.hipcc_version:
            warnings.append("hipcc was not detected; if no upstream wheel matches, source compilation will fail.")
        if normalized.primary_gpu_family not in {"", "cdna"}:
            install_env["FLASH_ATTENTION_TRITON_AMD_ENABLE"] = "TRUE"
    else:
        reasons.append("Neither a CUDA nor a ROCm backend was detected in the target Python environment.")

    install_spec = compose_install_spec(
        decision.package_name,
        version,
        default=decision.default_install_spec or decision.package_name,
    )
    pinned = exact_version_from_spec(decision.package_name, install_spec)
    pinned_major = version_tuple(pinned, limit=1)
    if decision.strategy == "fa4" and pinned_major and pinned_major[0] < 4:
        reasons.append("flash-attn-4 expects a 4.x package version.")

    if force_build and normalized.backend == "cuda" and not normalized.nvcc_version:
        reasons.append("`--force-build` was requested, but nvcc is not available on the target host.")
    if force_build and normalized.backend == "rocm" and not normalized.hipcc_version:
        reasons.append("`--force-build` was requested, but hipcc is not available on the target host.")
    if force_build and decision.package_name == "flash-attn-4":
        warnings.append("flash-attn-4 is distributed via pip and may ignore source-build knobs like `--force-build`.")

    if normalized.installed:
        if pinned and normalized.flash_attn_version != pinned:
            warnings.append(f"flash-attn {normalized.flash_attn_version} is already installed and would be replaced by {pinned}.")
        elif not pinned and installed_matches_strategy(normalized.flash_attn_version, decision.strategy or decision.package_name, pinned):
            warnings.append(f"flash-attn {normalized.flash_attn_version} is already installed in the target Python environment.")
        elif not pinned:
            warnings.append(
                f"flash-attn {normalized.flash_attn_version} is already installed, but the selected strategy expects {decision.target or decision.package_name}."
            )

    if not pinned and decision.package_name == "flash-attn":
        warnings.append("No exact flash-attn version was pinned; the installer will follow the selected major-version strategy.")

    wheel_url, wheel_name = ("", "")
    if decision.package_name == "flash-attn":
        wheel_url, wheel_name = guess_flash_attn_wheel_url(normalized, pinned)
    max_jobs = recommend_max_jobs(normalized.memory_gb, normalized.cpu_count)

    if reasons:
        status = "blocked"
    elif normalized.installed and installed_matches_strategy(normalized.flash_attn_version, decision.strategy or decision.package_name, pinned):
        status = "installed"
    else:
        status = "ready"

    if status == "installed":
        summary = f"flash-attn {normalized.flash_attn_version} already imports in the target Python environment."
    elif status == "ready":
        summary = f"Target environment is compatible with {decision.target or 'flash-attn'}."
    elif decision.unsupported_reason:
        summary = "Target environment is outside the tmux-trainsh FlashAttention support matrix."
    else:
        summary = "Target environment is missing one or more flash-attn prerequisites."

    return FlashAttnPlan(
        ok=status in {"ready", "installed"},
        status=status,
        backend=normalized.backend,
        target=decision.target,
        summary=summary,
        package_name=decision.package_name,
        strategy=decision.strategy or decision.package_name,
        install_spec=install_spec,
        rule_id=decision.rule_id,
        wheel_url=wheel_url,
        wheel_name=wheel_name,
        recommended_max_jobs=max_jobs,
        install_env=install_env,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def flash_attn_install_script(
    *,
    version: str = "",
    python_bin: str = "",
    package_name: str = "flash-attn",
    install_spec: str = "",
    extra_env: dict[str, str] | None = None,
    force_build: bool = False,
    max_jobs: int | None = None,
) -> str:
    """Build a reusable shell script that installs flash-attn in one Python env."""
    package = str(package_name or "flash-attn").strip() or "flash-attn"
    resolved_spec = str(install_spec or "").strip() or compose_install_spec(package, version, default=package)
    preferred_python = str(python_bin or "").strip()
    explicit_max_jobs = ""
    if max_jobs is not None:
        try:
            parsed = int(max_jobs)
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            explicit_max_jobs = f'export MAX_JOBS="{parsed}"'
    auto_max_jobs = dedent(
        """\
        if [ -z "${MAX_JOBS:-}" ] && [ -r /proc/meminfo ]; then
          CPU_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
          MEM_GB="$(awk '/MemTotal:/{print int($2/1024/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
          if [ "${MEM_GB:-0}" -gt 0 ] && [ "${MEM_GB:-0}" -lt 96 ]; then
            AUTO_MAX_JOBS=$(( MEM_GB / 8 ))
            if [ "$AUTO_MAX_JOBS" -lt 1 ]; then AUTO_MAX_JOBS=1; fi
            if [ "$AUTO_MAX_JOBS" -lt "${CPU_COUNT:-1}" ]; then export MAX_JOBS="$AUTO_MAX_JOBS"; fi
          fi
        fi
        """
    ).strip()
    extra_env_lines = "\n".join(
        f"export {str(key).strip()}={shlex.quote(str(value))}"
        for key, value in sorted((extra_env or {}).items())
        if str(key).strip()
    )
    force_build_line = 'export FLASH_ATTENTION_FORCE_BUILD="TRUE"' if force_build else ""
    pip_prereqs = '"$PY_BIN" -m pip install packaging psutil ninja'
    pip_install_line = (
        f'"$PY_BIN" -m pip install {shlex.quote(resolved_spec)}'
        if package == "flash-attn-4"
        else f'"$PY_BIN" -m pip install --no-build-isolation {shlex.quote(resolved_spec)}'
    )
    script = dedent(
        f"""\
        set -euo pipefail
        PREFERRED_PY={shlex.quote(preferred_python)}
        if [ -n "$PREFERRED_PY" ]; then
          PY_BIN="$PREFERRED_PY"
        elif command -v python3 >/dev/null 2>&1; then
          PY_BIN="$(command -v python3)"
        elif command -v python >/dev/null 2>&1; then
          PY_BIN="$(command -v python)"
        else
          echo "Python not found on target host." >&2
          exit 1
        fi

        {pip_prereqs}
        {explicit_max_jobs}
        {auto_max_jobs}
        {extra_env_lines}
        {force_build_line}
        {pip_install_line}

        "$PY_BIN" - <<'PY'
        import flash_attn
        import sys
        print(f"flash_attn={{getattr(flash_attn, '__version__', 'unknown')}} python={{sys.version.split()[0]}}")
        PY
        """
    ).strip()
    return "\n".join(line for line in script.splitlines() if line.strip())


__all__ = [
    "FlashAttnPlan",
    "FlashAttnProbe",
    "build_flash_attn_probe_command",
    "flash_attn_install_script",
    "guess_flash_attn_wheel_url",
    "parse_flash_attn_probe_output",
    "plan_flash_attn_install",
]
