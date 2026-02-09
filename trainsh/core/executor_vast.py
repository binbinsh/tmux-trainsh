# tmux-trainsh vast control helpers
# Encapsulates vast.* command logic from executor main.

import os
import subprocess
import time
from datetime import datetime
from typing import Any, Callable, List, Optional


class VastControlHelper:
    """Helper for vast.* control commands."""

    def __init__(
        self,
        executor: Any,
        build_ssh_args: Callable[..., list[str]],
        format_duration: Callable[[float], str],
    ):
        self.executor = executor
        self.build_ssh_args = build_ssh_args
        self.format_duration = format_duration

    def cmd_vast_start(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.start [instance_id]"""
        from ..services.vast_api import VastAPIError, get_vast_client

        try:
            client = get_vast_client()

            instance_id = None
            if args:
                instance_id = self.executor._interpolate(args[0])
            if not instance_id:
                instance_id = self.executor.ctx.variables.get("_vast_instance_id")
            if not instance_id:
                instance_id = self.executor.ctx.variables.get("VAST_ID")

            if instance_id:
                try:
                    inst_id = int(instance_id)
                except ValueError:
                    return False, f"Invalid instance ID: {instance_id}"

                if self.executor.logger:
                    self.executor.logger.log_detail("vast_start", f"Getting instance {inst_id}", {"instance_id": inst_id})

                instance = client.get_instance(inst_id)
                instance_info = {
                    "id": instance.id,
                    "status": instance.actual_status,
                    "is_running": instance.is_running,
                    "gpu_name": instance.gpu_name,
                    "num_gpus": instance.num_gpus,
                    "ssh_host": instance.ssh_host,
                    "ssh_port": instance.ssh_port,
                    "dph_total": instance.dph_total,
                    "start_date": instance.start_date,
                }
                if self.executor.logger:
                    self.executor.logger.log_vast("get_instance", inst_id, {"instance_id": inst_id}, instance_info, True)

                if instance.is_running:
                    self.executor.ctx.variables["_vast_instance_id"] = str(inst_id)
                    if instance.start_date:
                        self.executor.ctx.variables["_vast_start_time"] = datetime.fromtimestamp(instance.start_date).isoformat()
                    else:
                        self.executor.ctx.variables["_vast_start_time"] = datetime.now().isoformat()
                    if self.executor.logger:
                        self.executor.logger.log_variable("_vast_instance_id", str(inst_id), "vast.start")
                        self.executor.logger.log_variable("_vast_start_time", self.executor.ctx.variables["_vast_start_time"], "vast.start")
                    return True, f"Instance already running: {inst_id}"

                try:
                    if self.executor.logger:
                        self.executor.logger.log_detail("vast_start", f"Starting instance {inst_id}", {"instance_id": inst_id})
                    client.start_instance(inst_id)
                    self.executor.ctx.variables["_vast_instance_id"] = str(inst_id)
                    self.executor.ctx.variables["_vast_start_time"] = datetime.now().isoformat()
                    if self.executor.logger:
                        self.executor.logger.log_vast("start_instance", inst_id, {"instance_id": inst_id}, {"started": True}, True)
                        self.executor.logger.log_variable("_vast_instance_id", str(inst_id), "vast.start")
                        self.executor.logger.log_variable("_vast_start_time", self.executor.ctx.variables["_vast_start_time"], "vast.start")
                    return True, f"Started instance: {inst_id}"
                except VastAPIError as e:
                    msg = f"Failed to start instance {inst_id}: {e}"
                    if self.executor.logger:
                        self.executor.logger.log_vast("start_instance", inst_id, {"instance_id": inst_id}, {"error": str(e)}, False)
                    try:
                        client.stop_instance(inst_id)
                        msg += "; instance stopped"
                    except VastAPIError as stop_err:
                        msg += f"; failed to stop instance: {stop_err}"
                    return False, msg

            offers = client.search_offers(limit=1)
            if not offers:
                return False, "No GPU offers available"

            new_id = client.create_instance(
                offer_id=offers[0].id,
                image="pytorch/pytorch:latest",
                disk=50,
            )

            self.executor.ctx.variables["_vast_instance_id"] = str(new_id)
            if self.executor.logger:
                self.executor.logger.log_vast("create_instance", new_id, {"offer_id": offers[0].id}, {"created": True}, True)
            return True, f"Created instance: {new_id}"

        except (VastAPIError, RuntimeError) as e:
            if self.executor.logger:
                self.executor.logger.log_vast("vast_start", None, {"args": args}, {"error": str(e)}, False)
            return False, str(e)

    def cmd_vast_stop(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.stop <instance_id>"""
        from ..services.vast_api import VastAPIError, get_vast_client

        try:
            client = get_vast_client()

            instance_id = None
            if args:
                instance_id = self.executor._interpolate(args[0])
            if not instance_id:
                instance_id = self.executor.ctx.variables.get("_vast_instance_id")
            if not instance_id:
                return False, "No instance to stop"

            if self.executor.logger:
                self.executor.logger.log_detail("vast_stop", f"Stopping instance {instance_id}", {"instance_id": instance_id})

            client.stop_instance(int(instance_id))

            if self.executor.logger:
                self.executor.logger.log_vast("stop_instance", int(instance_id), {"instance_id": instance_id}, {"stopped": True}, True)

            return True, f"Stopped instance: {instance_id}"

        except (VastAPIError, RuntimeError) as e:
            return False, str(e)

    def cmd_vast_pick(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.pick @host ..."""
        from ..services.vast_api import VastAPIError, get_vast_client

        host_name = None
        gpu_name = None
        num_gpus = None
        min_gpu_ram = None
        max_dph = None
        limit = 20
        skip_if_set = True

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                value = self.executor._interpolate(value)
                if key in ("host", "host_name"):
                    host_name = value
                elif key in ("gpu", "gpu_name"):
                    gpu_name = value
                elif key in ("num_gpus", "gpus"):
                    try:
                        num_gpus = int(value)
                    except ValueError:
                        return False, f"Invalid num_gpus: {value}"
                elif key in ("min_gpu_ram", "min_vram_gb"):
                    try:
                        min_gpu_ram = float(value)
                    except ValueError:
                        return False, f"Invalid min_gpu_ram: {value}"
                elif key in ("max_dph", "max_price"):
                    try:
                        max_dph = float(value)
                    except ValueError:
                        return False, f"Invalid max_dph: {value}"
                elif key == "limit":
                    try:
                        limit = int(value)
                    except ValueError:
                        return False, f"Invalid limit: {value}"
                elif key == "skip_if_set":
                    skip_if_set = value.lower() in ("1", "true", "yes", "y")
                continue
            if host_name is None:
                host_name = self.executor._interpolate(arg)

        if host_name:
            if host_name.startswith("@"):
                host_name = host_name[1:]
        elif "gpu" in self.executor.recipe.hosts:
            host_name = "gpu"
        else:
            return False, "No host alias provided for vast.pick"

        pick_filters = {
            "host_name": host_name,
            "gpu_name": gpu_name,
            "num_gpus": num_gpus,
            "min_gpu_ram": min_gpu_ram,
            "max_dph": max_dph,
            "limit": limit,
            "skip_if_set": skip_if_set,
        }
        if self.executor.logger:
            self.executor.logger.log_detail("vast_pick", "Picking Vast instance", pick_filters)

        existing_id: Optional[int] = None
        if skip_if_set:
            for key in ("_vast_instance_id", "VAST_ID"):
                value = self.executor.ctx.variables.get(key)
                if value and value.isdigit() and int(value) > 0:
                    existing_id = int(value)
                    break

        if existing_id:
            self.executor.recipe.hosts[host_name] = f"vast:{existing_id}"
            self.executor.ctx.variables["_vast_instance_id"] = str(existing_id)
            self.executor.ctx.variables["VAST_ID"] = str(existing_id)
            if self.executor.logger:
                self.executor.logger.log_vast("pick_existing", existing_id, pick_filters, {"using_existing": True}, True)
                self.executor.logger.log_variable("VAST_ID", str(existing_id), "vast.pick")
            return True, f"Using existing instance: {existing_id}"

        try:
            client = get_vast_client()
            instances = client.list_instances()
            if not instances:
                return False, "No Vast.ai instances found"

            if self.executor.logger:
                instances_info = [
                    {
                        "id": i.id,
                        "status": i.actual_status,
                        "gpu_name": i.gpu_name,
                        "num_gpus": i.num_gpus,
                        "gpu_memory_gb": i.gpu_memory_gb,
                        "dph_total": i.dph_total,
                    }
                    for i in instances
                ]
                self.executor.logger.log_vast("list_instances", None, {}, {"instances": instances_info, "count": len(instances)}, True)

            def matches_filters(instance: Any) -> bool:
                if gpu_name and (instance.gpu_name or "").upper() != gpu_name.upper():
                    return False
                if num_gpus and (instance.num_gpus or 0) < num_gpus:
                    return False
                if min_gpu_ram and instance.gpu_memory_gb < min_gpu_ram:
                    return False
                if max_dph and (instance.dph_total or 0.0) > max_dph:
                    return False
                return True

            instances = [i for i in instances if matches_filters(i)]
            if not instances:
                if self.executor.logger:
                    self.executor.logger.log_detail("vast_pick", "No instances match filters", pick_filters)
                return False, "No Vast.ai instances match filters"

            if limit and limit > 0:
                instances = instances[:limit]

            def status_rank(instance: Any) -> int:
                status = (instance.actual_status or "").lower()
                if status == "running":
                    return 0
                if status in ("stopped", "exited"):
                    return 1
                return 2

            instances = sorted(instances, key=lambda i: (status_rank(i), i.dph_total or 0.0))

            if self.executor.logger:
                filtered_info = [
                    {"id": i.id, "status": i.actual_status, "gpu_name": i.gpu_name, "num_gpus": i.num_gpus, "dph_total": i.dph_total}
                    for i in instances
                ]
                self.executor.logger.log_detail("vast_pick", f"Filtered to {len(instances)} instances", {"filtered_instances": filtered_info})

            from ..utils.vast_formatter import format_instance_header, format_instance_row, get_currency_settings

            currency = get_currency_settings()
            header, sep = format_instance_header(currency, show_index=True)
            print("\nSelect a Vast.ai instance:")
            print(sep)
            print(header)
            print(sep)
            for idx, inst in enumerate(instances, 1):
                row = format_instance_row(inst, currency, show_index=True, index=idx)
                print(row)
            print(sep)

            try:
                choice = input(f"Enter number (1-{len(instances)}) or instance ID: ").strip()
            except (EOFError, KeyboardInterrupt):
                return False, "Selection cancelled"

            selected = None
            if choice.isdigit():
                num = int(choice)
                if 1 <= num <= len(instances):
                    selected = instances[num - 1]
                else:
                    for inst in instances:
                        if inst.id == num:
                            selected = inst
                            break

            if not selected:
                return False, "Invalid selection"

            self.executor.ctx.variables["_vast_instance_id"] = str(selected.id)
            self.executor.ctx.variables["VAST_ID"] = str(selected.id)
            self.executor.recipe.hosts[host_name] = f"vast:{selected.id}"

            if self.executor.logger:
                self.executor.logger.log_vast("pick_selected", selected.id, pick_filters, {
                    "selected_id": selected.id,
                    "gpu_name": selected.gpu_name,
                    "status": selected.actual_status,
                }, True)
                self.executor.logger.log_variable("_vast_instance_id", str(selected.id), "vast.pick")
                self.executor.logger.log_variable("VAST_ID", str(selected.id), "vast.pick")

            return True, f"Selected instance {selected.id}"

        except (VastAPIError, RuntimeError) as e:
            if self.executor.logger:
                self.executor.logger.log_vast("pick_error", None, pick_filters, {"error": str(e)}, False)
            return False, str(e)

    def cmd_vast_wait(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.wait <instance_id> timeout=10m ..."""
        from ..config import load_config
        from ..services.vast_api import VastAPIError, get_vast_client

        instance_id = None
        timeout = 600
        poll_interval = 10
        stop_on_fail = True

        for arg in args:
            if "=" in arg:
                key, _, value = arg.partition("=")
                if key == "timeout":
                    timeout = self.executor._parse_duration(self.executor._interpolate(value))
                elif key in ("poll", "poll_interval"):
                    poll_interval = self.executor._parse_duration(self.executor._interpolate(value))
                elif key == "stop_on_fail":
                    stop_on_fail = value.lower() in ("1", "true", "yes", "y")
                continue
            if instance_id is None:
                instance_id = self.executor._interpolate(arg)

        if not instance_id:
            instance_id = self.executor.ctx.variables.get("_vast_instance_id")
        if not instance_id:
            instance_id = self.executor.ctx.variables.get("VAST_ID")
        if not instance_id:
            return False, "No instance ID provided for vast.wait"

        try:
            inst_id = int(instance_id)
        except ValueError:
            return False, f"Invalid instance ID: {instance_id}"

        self.executor.ctx.variables["_vast_instance_id"] = str(inst_id)

        wait_config = {
            "instance_id": inst_id,
            "timeout": timeout,
            "poll_interval": poll_interval,
            "stop_on_fail": stop_on_fail,
        }
        if self.executor.logger:
            self.executor.logger.log_detail("vast_wait", f"Waiting for instance {inst_id}", wait_config)

        try:
            client = get_vast_client()

            config = load_config()
            auto_attach = config.get("vast", {}).get("auto_attach_ssh_key", True)
            ssh_key_path = config.get("defaults", {}).get("ssh_key_path", "~/.ssh/id_rsa")

            if auto_attach and ssh_key_path:
                self.ensure_ssh_key_attached(client, ssh_key_path)

            start_time = time.time()
            last_status = "unknown"
            poll_count = 0

            while time.time() - start_time < timeout:
                poll_count += 1
                instance = client.get_instance(inst_id)
                last_status = instance.actual_status or "unknown"
                ssh_ready = bool(instance.ssh_host and instance.ssh_port)
                elapsed = int(time.time() - start_time)
                remaining = timeout - elapsed

                if self.executor.logger:
                    self.executor.logger.log_wait(
                        f"vast:{inst_id}",
                        f"status={last_status},ssh_ready={ssh_ready}",
                        elapsed,
                        remaining,
                        f"poll #{poll_count}: {last_status}",
                    )

                if instance.is_running and ssh_ready:
                    self.executor.log(f"  Connection details for instance {inst_id}:")
                    proxy_cmd = instance.ssh_proxy_command
                    direct_cmd = instance.ssh_direct_command
                    if proxy_cmd:
                        self.executor.log(f"    Proxy SSH: {proxy_cmd}")
                    if direct_cmd:
                        self.executor.log(f"    Direct SSH: {direct_cmd}")

                    if self.executor.logger:
                        self.executor.logger.log_detail("vast_connection", "SSH connection details", {
                            "proxy_command": proxy_cmd,
                            "direct_command": direct_cmd,
                            "ssh_host": instance.ssh_host,
                            "ssh_port": instance.ssh_port,
                            "public_ipaddr": instance.public_ipaddr,
                            "direct_port_start": instance.direct_port_start,
                            "direct_port_end": instance.direct_port_end,
                        })

                    ssh_connected = False
                    working_ssh_spec = None

                    if direct_cmd and instance.public_ipaddr and instance.direct_port_start:
                        direct_spec = f"root@{instance.public_ipaddr} -p {instance.direct_port_start}"
                        self.executor.log(f"  Trying direct SSH: {direct_cmd}")
                        if self.verify_ssh_connection(direct_spec):
                            ssh_connected = True
                            working_ssh_spec = direct_spec
                            self.executor.log("  Direct SSH connected successfully")
                        else:
                            self.executor.log("  Direct SSH failed, trying proxy...")

                    if not ssh_connected and proxy_cmd:
                        proxy_spec = f"root@{instance.ssh_host} -p {instance.ssh_port}"
                        self.executor.log(f"  Trying proxy SSH: {proxy_cmd}")
                        if self.verify_ssh_connection(proxy_spec):
                            ssh_connected = True
                            working_ssh_spec = proxy_spec
                            self.executor.log("  Proxy SSH connected successfully")
                        else:
                            self.executor.log("  Proxy SSH failed")

                    if ssh_connected and working_ssh_spec:
                        if instance.public_ipaddr and instance.direct_port_start and instance.public_ipaddr in working_ssh_spec:
                            self.executor.ctx.variables["_vast_ssh_host"] = instance.public_ipaddr
                            self.executor.ctx.variables["_vast_ssh_port"] = str(instance.direct_port_start)
                        else:
                            self.executor.ctx.variables["_vast_ssh_host"] = instance.ssh_host or ""
                            self.executor.ctx.variables["_vast_ssh_port"] = str(instance.ssh_port or "")

                        for host_name, host_value in list(self.executor.recipe.hosts.items()):
                            if host_value == f"vast:{inst_id}":
                                self.executor.recipe.hosts[host_name] = working_ssh_spec
                                self.executor.log(f"  Updated @{host_name} to use: {working_ssh_spec}")
                                if self.executor.logger:
                                    self.executor.logger.log_detail("vast_host_update", f"Updated host {host_name}", {
                                        "host_name": host_name,
                                        "old_value": f"vast:{inst_id}",
                                        "new_value": working_ssh_spec,
                                    })

                        disable_cmd = "touch ~/.no_auto_tmux"
                        ssh_args = self.build_ssh_args(working_ssh_spec, command=disable_cmd, tty=False)
                        try:
                            subprocess.run(ssh_args, capture_output=True, text=True, timeout=10)
                            if self.executor.logger:
                                self.executor.logger.log_detail("vast_config", "Disabled auto-tmux", {"command": disable_cmd})
                        except Exception:
                            pass

                        msg = f"Instance {inst_id} is ready ({last_status})"
                        self.executor.log(msg)

                        if self.executor.logger:
                            self.executor.logger.log_vast("wait_ready", inst_id, wait_config, {
                                "status": last_status,
                                "ssh_host": self.executor.ctx.variables["_vast_ssh_host"],
                                "ssh_port": self.executor.ctx.variables["_vast_ssh_port"],
                                "connection_method": "direct" if instance.public_ipaddr in working_ssh_spec else "proxy",
                                "elapsed_sec": elapsed,
                                "poll_count": poll_count,
                            }, True)
                            self.executor.logger.log_variable("_vast_ssh_host", self.executor.ctx.variables["_vast_ssh_host"], "vast.wait")
                            self.executor.logger.log_variable("_vast_ssh_port", self.executor.ctx.variables["_vast_ssh_port"], "vast.wait")

                        return True, msg
                    else:
                        self.executor.log(f"Instance {inst_id} running but SSH not accessible yet...")
                        if self.executor.logger:
                            self.executor.logger.log_detail("vast_wait", "SSH not accessible yet", {
                                "proxy_command": proxy_cmd,
                                "direct_command": direct_cmd,
                                "ssh_host": instance.ssh_host,
                                "ssh_port": instance.ssh_port,
                                "public_ipaddr": instance.public_ipaddr,
                                "direct_port_start": instance.direct_port_start,
                            })

                self.executor.log(f"Waiting for instance {inst_id}... ({last_status})")
                time.sleep(poll_interval)

            msg = f"Instance {inst_id} not ready after {self.format_duration(timeout)} (status: {last_status})"
            if self.executor.logger:
                self.executor.logger.log_vast("wait_timeout", inst_id, wait_config, {
                    "status": last_status,
                    "elapsed_sec": int(time.time() - start_time),
                    "poll_count": poll_count,
                }, False)

            if stop_on_fail:
                try:
                    client.stop_instance(inst_id)
                    msg += "; instance stopped"
                    if self.executor.logger:
                        self.executor.logger.log_vast("stop_instance", inst_id, {"reason": "wait_timeout"}, {"stopped": True}, True)
                except VastAPIError as e:
                    msg += f"; failed to stop instance: {e}"
            self.executor.log(msg)
            return False, msg

        except (VastAPIError, RuntimeError) as e:
            msg = f"Vast wait failed: {e}"
            if self.executor.logger:
                self.executor.logger.log_vast("wait_error", inst_id, wait_config, {"error": str(e)}, False)
            self.executor.log(msg)
            return False, msg

    def verify_ssh_connection(self, ssh_spec: str, timeout: int = 10) -> bool:
        """Verify SSH connectivity for a given host spec."""
        try:
            ssh_args = self.build_ssh_args(ssh_spec, command="echo ok", tty=False)
            ssh_args.insert(1, "-o")
            ssh_args.insert(2, f"ConnectTimeout={timeout}")
            ssh_args.insert(3, "-o")
            ssh_args.insert(4, "BatchMode=yes")
            ssh_args.insert(5, "-o")
            ssh_args.insert(6, "StrictHostKeyChecking=no")

            result = subprocess.run(
                ssh_args,
                capture_output=True,
                text=True,
                timeout=timeout + 5,
            )

            if self.executor.logger:
                self.executor.logger.log_ssh(ssh_spec, "echo ok", result.returncode, result.stdout, result.stderr, 0)
            return result.returncode == 0 and "ok" in result.stdout

        except (subprocess.TimeoutExpired, Exception) as e:
            if self.executor.logger:
                self.executor.logger.log_detail("ssh_verify_failed", f"SSH verify failed: {e}", {"ssh_spec": ssh_spec})
            return False

    def ensure_ssh_key_attached(self, client: Any, ssh_key_path: str) -> None:
        """Ensure local public SSH key is attached to Vast.ai account."""
        pub_key_path = os.path.expanduser(ssh_key_path)
        if not pub_key_path.endswith(".pub"):
            pub_key_path += ".pub"

        if not os.path.exists(pub_key_path):
            self.executor.log(f"SSH public key not found: {pub_key_path}")
            if self.executor.logger:
                self.executor.logger.log_detail("ssh_key", f"Public key not found: {pub_key_path}", {})
            return

        with open(pub_key_path, "r") as f:
            pub_key_content = f.read().strip()

        if not pub_key_content:
            self.executor.log(f"SSH public key is empty: {pub_key_path}")
            return

        key_parts = pub_key_content.split()
        if len(key_parts) < 2:
            self.executor.log(f"Invalid SSH public key format: {pub_key_path}")
            return

        key_type = key_parts[0]
        key_data = key_parts[1]

        try:
            existing_keys = client.list_ssh_keys()
            if self.executor.logger:
                self.executor.logger.log_detail("ssh_key", f"Found {len(existing_keys)} existing keys on Vast.ai", {
                    "existing_count": len(existing_keys)
                })

            key_exists = False
            for existing_key in existing_keys:
                existing_content = existing_key.get("ssh_key", "")
                existing_parts = existing_content.split()
                if len(existing_parts) >= 2 and existing_parts[1] == key_data:
                    key_exists = True
                    if self.executor.logger:
                        self.executor.logger.log_detail("ssh_key", "SSH key already registered on Vast.ai", {
                            "key_id": existing_key.get("id"),
                            "label": existing_key.get("label"),
                        })
                    break

            if not key_exists:
                self.executor.log("Adding SSH key to Vast.ai account...")
                try:
                    client.add_ssh_key(pub_key_content, label="tmux-trainsh")
                    self.executor.log("SSH key added successfully")
                    if self.executor.logger:
                        self.executor.logger.log_detail("ssh_key", "SSH key added to Vast.ai", {
                            "key_type": key_type,
                            "key_path": pub_key_path,
                        })
                except Exception as add_err:
                    err_str = str(add_err).lower()
                    if "already exists" in err_str or "duplicate" in err_str:
                        self.executor.log("SSH key already exists on Vast.ai")
                        if self.executor.logger:
                            self.executor.logger.log_detail("ssh_key", "SSH key already exists (ignored)", {
                                "key_type": key_type,
                            })
                    else:
                        raise add_err

        except Exception as e:
            self.executor.log(f"Warning: Failed to manage SSH keys: {e}")
            if self.executor.logger:
                self.executor.logger.log_detail("ssh_key_warning", f"Failed to manage SSH keys: {e}", {})

    def cmd_vast_cost(self, args: List[str]) -> tuple[bool, str]:
        """Handle: vast.cost <instance_id>"""
        from ..config import load_config
        from ..services.pricing import format_currency, load_pricing_settings
        from ..services.vast_api import VastAPIError, get_vast_client

        instance_id = None
        if args:
            instance_id = self.executor._interpolate(args[0])
        if not instance_id:
            instance_id = self.executor.ctx.variables.get("_vast_instance_id")
        if not instance_id:
            instance_id = self.executor.ctx.variables.get("VAST_ID")
        if not instance_id:
            msg = "Vast cost skipped: no instance ID provided"
            self.executor.log(msg)
            return True, msg

        try:
            inst_id = int(instance_id)
        except ValueError:
            msg = f"Vast cost skipped: invalid instance ID '{instance_id}'"
            self.executor.log(msg)
            return True, msg

        vast_start_time = self.executor.ctx.variables.get("_vast_start_time")
        if not vast_start_time:
            msg = "Vast cost skipped: no start time recorded in job state"
            self.executor.log(msg)
            return True, msg

        try:
            client = get_vast_client()
            inst = client.get_instance(inst_id)
            hourly_usd = inst.dph_total or 0.0
            if hourly_usd <= 0:
                msg = f"Vast cost skipped: no pricing for instance {inst_id}"
                self.executor.log(msg)
                return True, msg

            saved_start = datetime.fromisoformat(vast_start_time)
            duration_secs = (datetime.now() - saved_start).total_seconds()
            cost_usd = hourly_usd * (duration_secs / 3600.0)

            settings = load_pricing_settings()
            config = load_config()
            display_curr = config.get("ui", {}).get("currency", settings.display_currency)
            rates = settings.exchange_rates

            usage_str = self.format_duration(duration_secs)
            cost_line = f"${cost_usd:.4f}"
            if display_curr != "USD":
                converted = rates.convert(cost_usd, "USD", display_curr)
                cost_line = f"${cost_usd:.4f} ({format_currency(converted, display_curr)})"

            msg = (
                f"Vast usage: {usage_str}, "
                f"instance {inst_id}, "
                f"{inst.gpu_name or 'GPU'} @ ${hourly_usd:.4f}/hr, "
                f"total cost {cost_line}"
            )
            self.executor.log(msg)
            return True, msg

        except (VastAPIError, RuntimeError) as e:
            msg = f"Vast cost skipped: {e}"
            self.executor.log(msg)
            return True, msg
