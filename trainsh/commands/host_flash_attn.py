"""FlashAttention planning helpers for `train host`."""

from __future__ import annotations

import base64
import json
import re
import shlex
import sys
from dataclasses import dataclass
from textwrap import dedent
from typing import Optional

from ..services.flash_attn_matrix import render_compatibility_matrix
from ..services.flash_attn_state import (
    FlashAttnInstallRecord,
    load_install_record,
    sanitize_flash_attn_name,
    save_install_record,
)
from ..services.flash_attn_support import (
    FlashAttnPlan,
    FlashAttnProbe,
    build_flash_attn_probe_command,
    flash_attn_install_script,
    parse_flash_attn_probe_output,
    plan_flash_attn_install,
)
from ..services.ssh import SSHClient


USAGE = (
    "train host flash-attn <name> [--version <version|spec|auto>] [--package auto|flash-attn|flash-attn-4] "
    "[--python <path>] [--max-jobs <n>] [--force-build] [--apply] [--background] [--status] "
    "[--session <name>] [--log <path>] [--tail-lines <n>] [--json]\n"
    "train host flash-attn --matrix"
)


@dataclass(frozen=True)
class HostFlashAttnOptions:
    show_matrix: bool = False
    version: str = ""
    package_name: str = ""
    python_bin: str = ""
    max_jobs: Optional[int] = None
    force_build: bool = False
    apply: bool = False
    background: bool = False
    status: bool = False
    session_name: str = ""
    log_path: str = ""
    tail_lines: int = 40
    json_output: bool = False


def parse_host_flash_attn_args(args: list[str]) -> tuple[str, HostFlashAttnOptions]:
    """Parse CLI args for `train host flash-attn`."""
    if not args or args[0] in {"-h", "--help"}:
        print(f"Usage: {USAGE}")
        raise SystemExit(1)
    if args[0] in {"--matrix", "matrix"}:
        return "", HostFlashAttnOptions(show_matrix=True)

    name = str(args[0]).strip()
    if not name:
        print(f"Usage: {USAGE}")
        raise SystemExit(1)

    version = ""
    package_name = ""
    python_bin = ""
    max_jobs: Optional[int] = None
    force_build = False
    apply = False
    background = False
    status = False
    session_name = ""
    log_path = ""
    tail_lines = 40
    json_output = False

    index = 1
    while index < len(args):
        arg = str(args[index]).strip()
        if arg == "--version" and index + 1 < len(args):
            version = str(args[index + 1]).strip()
            index += 2
            continue
        if arg.startswith("--version="):
            version = arg.split("=", 1)[1].strip()
            index += 1
            continue
        if arg == "--package" and index + 1 < len(args):
            package_name = str(args[index + 1]).strip()
            index += 2
            continue
        if arg.startswith("--package="):
            package_name = arg.split("=", 1)[1].strip()
            index += 1
            continue
        if arg == "--python" and index + 1 < len(args):
            python_bin = str(args[index + 1]).strip()
            index += 2
            continue
        if arg.startswith("--python="):
            python_bin = arg.split("=", 1)[1].strip()
            index += 1
            continue
        if arg == "--max-jobs" and index + 1 < len(args):
            try:
                max_jobs = int(args[index + 1])
            except ValueError:
                print("--max-jobs must be an integer.")
                raise SystemExit(1)
            if max_jobs <= 0:
                print("--max-jobs must be >= 1.")
                raise SystemExit(1)
            index += 2
            continue
        if arg.startswith("--max-jobs="):
            try:
                max_jobs = int(arg.split("=", 1)[1].strip())
            except ValueError:
                print("--max-jobs must be an integer.")
                raise SystemExit(1)
            if max_jobs <= 0:
                print("--max-jobs must be >= 1.")
                raise SystemExit(1)
            index += 1
            continue
        if arg == "--tail-lines" and index + 1 < len(args):
            try:
                tail_lines = int(args[index + 1])
            except ValueError:
                print("--tail-lines must be an integer.")
                raise SystemExit(1)
            if tail_lines <= 0:
                print("--tail-lines must be >= 1.")
                raise SystemExit(1)
            index += 2
            continue
        if arg.startswith("--tail-lines="):
            try:
                tail_lines = int(arg.split("=", 1)[1].strip())
            except ValueError:
                print("--tail-lines must be an integer.")
                raise SystemExit(1)
            if tail_lines <= 0:
                print("--tail-lines must be >= 1.")
                raise SystemExit(1)
            index += 1
            continue
        if arg == "--session" and index + 1 < len(args):
            session_name = str(args[index + 1]).strip()
            index += 2
            continue
        if arg.startswith("--session="):
            session_name = arg.split("=", 1)[1].strip()
            index += 1
            continue
        if arg == "--log" and index + 1 < len(args):
            log_path = str(args[index + 1]).strip()
            index += 2
            continue
        if arg.startswith("--log="):
            log_path = arg.split("=", 1)[1].strip()
            index += 1
            continue
        if arg == "--force-build":
            force_build = True
            index += 1
            continue
        if arg == "--apply":
            apply = True
            index += 1
            continue
        if arg == "--background":
            background = True
            index += 1
            continue
        if arg == "--status":
            status = True
            index += 1
            continue
        if arg == "--json":
            json_output = True
            index += 1
            continue
        print(f"Usage: {USAGE}")
        raise SystemExit(1)

    if background and not apply:
        print("--background requires --apply.")
        raise SystemExit(1)
    if status and apply:
        print("--status cannot be combined with --apply.")
        raise SystemExit(1)
    if package_name and package_name not in {"auto", "flash-attn", "flash-attn-4"}:
        print("--package must be one of: auto, flash-attn, flash-attn-4.")
        raise SystemExit(1)

    return name, HostFlashAttnOptions(
        show_matrix=False,
        version=version,
        package_name=package_name,
        python_bin=python_bin,
        max_jobs=max_jobs,
        force_build=force_build,
        apply=apply,
        background=background,
        status=status,
        session_name=session_name,
        log_path=log_path,
        tail_lines=tail_lines,
        json_output=json_output,
    )


def _write_remote_result(result) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")


def _gpu_summary(probe: FlashAttnProbe) -> str:
    if not probe.gpu_names:
        return "not detected"
    family = probe.primary_gpu_family or "unknown"
    capabilities = f" cc={','.join(probe.gpu_capabilities)}" if probe.gpu_capabilities else ""
    return f"{', '.join(probe.gpu_names)} [{family}{capabilities}]"


def _torch_summary(probe: FlashAttnProbe) -> str:
    if not probe.torch_available:
        return "not installed"
    parts = [probe.torch_version]
    if probe.torch_cuda_version:
        parts.append(f"CUDA {probe.torch_cuda_version}")
    if probe.torch_hip_version:
        parts.append(f"ROCm {probe.torch_hip_version}")
    if probe.torch_cxx11_abi:
        parts.append(f"CXX11 ABI {probe.torch_cxx11_abi}")
    return " | ".join(part for part in parts if part)


def _sanitize_session_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower())
    return text.strip("-.") or "flash-attn-install"


def _session_name_for_plan(label: str, plan: FlashAttnPlan, options: HostFlashAttnOptions) -> str:
    if options.session_name:
        return _sanitize_session_name(options.session_name)
    return _sanitize_session_name(f"{label}-{plan.package_name or 'flash-attn'}-install")


def _log_path_for_session(session_name: str, options: HostFlashAttnOptions) -> str:
    return str(options.log_path or f"/tmp/{session_name}.log").strip() or f"/tmp/{session_name}.log"


def _record_name(label: str, package_name: str) -> str:
    return sanitize_flash_attn_name(f"{label}-{package_name or 'flash-attn'}")


def _print_plan(label: str, probe: FlashAttnProbe, plan: FlashAttnPlan) -> None:
    print(f"FlashAttention plan for {label}")
    print(f"Status: {plan.status}")
    print(f"Summary: {plan.summary}")
    print(f"Backend: {plan.backend or 'not detected'}")
    print(f"Package: {plan.package_name}")
    print(f"Strategy: {plan.strategy}")
    print(f"Python: {probe.python_version or '-'} ({probe.python_executable or 'unresolved'})")
    print(f"Platform: {(probe.platform_system or '-').lower()}/{probe.platform_machine or '-'}")
    print(f"Torch: {_torch_summary(probe)}")
    print(f"GPU: {_gpu_summary(probe)}")
    if probe.nvcc_version:
        print(f"nvcc: {probe.nvcc_version}")
    if probe.hipcc_version:
        print(f"hipcc: {probe.hipcc_version}")
    print(f"Install spec: {plan.install_spec}")
    if plan.install_env:
        print("Install env:")
        for key, value in sorted(plan.install_env.items()):
            print(f"  - {key}={value}")
    if plan.wheel_url:
        print(f"Wheel guess: {plan.wheel_url}")
    if plan.recommended_max_jobs:
        print(f"Recommended MAX_JOBS: {plan.recommended_max_jobs}")
    if plan.reasons:
        print("Blocking issues:")
        for reason in plan.reasons:
            print(f"  - {reason}")
    if plan.warnings:
        print("Warnings:")
        for warning in plan.warnings:
            print(f"  - {warning}")


def _payload(
    label: str,
    probe: FlashAttnProbe,
    plan: FlashAttnPlan,
    *,
    session_name: str = "",
    log_path: str = "",
    remote_output: str = "",
) -> dict[str, object]:
    return {
        "host": label,
        "probe": probe.to_dict(),
        "plan": plan.to_dict(),
        "session_name": session_name,
        "log_path": log_path,
        "remote_output": remote_output,
    }


def _write_remote_script(ssh: SSHClient, remote_path: str, script: str) -> None:
    payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
    command = dedent(
        f"""\
        python3 - <<'PY'
        import base64
        from pathlib import Path

        Path({remote_path!r}).write_bytes(base64.b64decode({payload!r}))
        PY
        chmod +x {shlex.quote(remote_path)}
        """
    ).strip()
    result = ssh.run(f"bash -lc {shlex.quote(command)}")
    if result.exit_code != 0:
        _write_remote_result(result)
        raise SystemExit(result.exit_code if result.exit_code > 0 else 1)


def _background_start_result(
    ssh: SSHClient,
    *,
    remote_script_path: str,
    session_name: str,
    log_path: str,
    tail_lines: int,
) -> str:
    command = dedent(
        f"""\
        set -e
        SESSION={shlex.quote(session_name)}
        LOG={shlex.quote(log_path)}
        SCRIPT={shlex.quote(remote_script_path)}
        if command -v tmux >/dev/null 2>&1; then
          tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION" || true
          tmux new-session -d -s "$SESSION" "bash $SCRIPT >$LOG 2>&1"
          echo "mode=tmux"
          echo "session=$SESSION"
        else
          nohup bash "$SCRIPT" >"$LOG" 2>&1 </dev/null &
          echo "mode=nohup"
          echo "pid=$!"
        fi
        echo "log=$LOG"
        sleep 2
        [ -f "$LOG" ] && tail -n {max(1, int(tail_lines))} "$LOG" || true
        """
    ).strip()
    result = ssh.run(f"bash -lc {shlex.quote(command)}")
    if result.exit_code != 0:
        _write_remote_result(result)
        raise SystemExit(result.exit_code if result.exit_code > 0 else 1)
    return "\n".join(part for part in (result.stdout, result.stderr) if part).strip()


def _remote_status_output(
    ssh: SSHClient,
    *,
    session_name: str,
    log_path: str,
    tail_lines: int,
) -> str:
    command = dedent(
        f"""\
        set -e
        SESSION={shlex.quote(session_name)}
        LOG={shlex.quote(log_path)}
        if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION" 2>/dev/null; then
          echo "status=running"
          echo "session=$SESSION"
        else
          echo "status=idle"
        fi
        echo "log=$LOG"
        if [ -f "$LOG" ]; then
          echo "--- log ---"
          tail -n {max(1, int(tail_lines))} "$LOG"
        else
          echo "--- log ---"
          echo "(no log)"
        fi
        """
    ).strip()
    result = ssh.run(f"bash -lc {shlex.quote(command)}")
    if result.exit_code != 0:
        _write_remote_result(result)
        raise SystemExit(result.exit_code if result.exit_code > 0 else 1)
    return "\n".join(part for part in (result.stdout, result.stderr) if part).strip()


def run_host_flash_attn(host, *, label: str, options: HostFlashAttnOptions) -> None:
    """Probe one host and optionally apply the resulting install script."""
    if options.show_matrix:
        print(render_compatibility_matrix())
        return

    try:
        ssh = SSHClient.from_host(host)
    except Exception as exc:
        print(f"Connection setup failed: {exc}")
        raise SystemExit(1)

    probe_result = ssh.run(build_flash_attn_probe_command(options.python_bin), timeout=120)
    combined_output = "\n".join(part for part in (probe_result.stdout, probe_result.stderr) if part)
    if probe_result.exit_code != 0:
        _write_remote_result(probe_result)
        print("Failed to probe the remote Python environment.")
        raise SystemExit(probe_result.exit_code if probe_result.exit_code > 0 else 1)

    probe = parse_flash_attn_probe_output(combined_output)
    plan = plan_flash_attn_install(
        probe,
        version=options.version,
        package_name=options.package_name,
        force_build=options.force_build,
    )
    record_name = _record_name(label, plan.package_name)
    existing_record = load_install_record(record_name)
    session_name = _session_name_for_plan(label, plan, options)
    log_path = _log_path_for_session(session_name, options)
    if existing_record is not None:
        if not options.session_name and existing_record.session_name:
            session_name = existing_record.session_name
        if not options.log_path and existing_record.log_path:
            log_path = existing_record.log_path

    if not options.json_output:
        _print_plan(label, probe, plan)

    if options.status:
        status_output = _remote_status_output(
            ssh,
            session_name=session_name,
            log_path=log_path,
            tail_lines=options.tail_lines,
        )
        persisted_status = (
            "installed"
            if plan.status == "installed"
            else "running"
            if "status=running" in status_output
            else "idle"
        )
        save_install_record(
            FlashAttnInstallRecord(
                name=record_name,
                host_name=label,
                host=host.to_dict(),
                python_executable=probe.python_executable,
                package_name=plan.package_name,
                install_spec=plan.install_spec,
                session_name=session_name,
                log_path=log_path,
                status=persisted_status,
                strategy=plan.strategy,
            )
        )
        if options.json_output:
            print(json.dumps(_payload(label, probe, plan, session_name=session_name, log_path=log_path, remote_output=status_output), ensure_ascii=False, indent=2))
        else:
            print(status_output)
        return

    if not options.apply:
        if options.json_output:
            print(json.dumps(_payload(label, probe, plan, session_name=session_name, log_path=log_path), ensure_ascii=False, indent=2))
        return

    if not plan.ok:
        if options.json_output:
            print(json.dumps(_payload(label, probe, plan, session_name=session_name, log_path=log_path), ensure_ascii=False, indent=2))
        if not options.json_output:
            print("Refusing to apply because the target environment is not ready.")
        raise SystemExit(1)

    if plan.status == "installed" and not options.force_build:
        save_install_record(
            FlashAttnInstallRecord(
                name=record_name,
                host_name=label,
                host=host.to_dict(),
                python_executable=probe.python_executable,
                package_name=plan.package_name,
                install_spec=plan.install_spec,
                session_name=session_name,
                log_path=log_path,
                status="installed",
                strategy=plan.strategy,
            )
        )
        if options.json_output:
            print(json.dumps(_payload(label, probe, plan, session_name=session_name, log_path=log_path), ensure_ascii=False, indent=2))
        if not options.json_output:
            print("flash-attn is already importable in the selected Python environment; skipping apply.")
        return

    install_script = flash_attn_install_script(
        version=options.version,
        python_bin=probe.python_executable or options.python_bin,
        package_name=plan.package_name,
        install_spec=plan.install_spec,
        extra_env=plan.install_env,
        force_build=options.force_build,
        max_jobs=options.max_jobs or plan.recommended_max_jobs or None,
    )

    if options.background:
        remote_script_path = f"/tmp/{session_name}.sh"
        _write_remote_script(ssh, remote_script_path, install_script)
        remote_output = _background_start_result(
            ssh,
            remote_script_path=remote_script_path,
            session_name=session_name,
            log_path=log_path,
            tail_lines=options.tail_lines,
        )
        save_install_record(
            FlashAttnInstallRecord(
                name=record_name,
                host_name=label,
                host=host.to_dict(),
                python_executable=probe.python_executable,
                package_name=plan.package_name,
                install_spec=plan.install_spec,
                session_name=session_name,
                log_path=log_path,
                status="running",
                strategy=plan.strategy,
            )
        )
        if options.json_output:
            print(json.dumps(_payload(label, probe, plan, session_name=session_name, log_path=log_path, remote_output=remote_output), ensure_ascii=False, indent=2))
        else:
            print(f"Started background install on {label}.")
            print(f"Session: {session_name}")
            print(f"Log: {log_path}")
            if remote_output:
                print(remote_output)
        return

    if not options.json_output:
        print(f"Applying install script on {label}...")

    install_result = ssh.run(f"bash -lc {shlex.quote(install_script)}")
    _write_remote_result(install_result)
    if install_result.exit_code == 0:
        save_install_record(
            FlashAttnInstallRecord(
                name=record_name,
                host_name=label,
                host=host.to_dict(),
                python_executable=probe.python_executable,
                package_name=plan.package_name,
                install_spec=plan.install_spec,
                session_name=session_name,
                log_path=log_path,
                status="installed",
                strategy=plan.strategy,
            )
        )
    else:
        save_install_record(
            FlashAttnInstallRecord(
                name=record_name,
                host_name=label,
                host=host.to_dict(),
                python_executable=probe.python_executable,
                package_name=plan.package_name,
                install_spec=plan.install_spec,
                session_name=session_name,
                log_path=log_path,
                status="failed",
                strategy=plan.strategy,
            )
        )
    if install_result.exit_code != 0:
        raise SystemExit(install_result.exit_code if install_result.exit_code > 0 else 1)


__all__ = [
    "HostFlashAttnOptions",
    "USAGE",
    "parse_host_flash_attn_args",
    "run_host_flash_attn",
]
