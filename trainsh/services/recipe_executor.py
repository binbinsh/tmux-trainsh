# tmux-trainsh recipe executor
# DAG-based recipe step execution

import asyncio
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from enum import Enum

from ..core.models import (
    Recipe, RecipeStep, OperationType, StepStatus, StepResult,
    Execution, ExecutionStatus,
)
from ..core.variables import VariableInterpolator
from ..core.secrets import get_secrets_manager
from ..core.execution_log import ExecutionLogger
from .ssh import SSHClient
from .tmux import TmuxManager
from .transfer_engine import TransferEngine
from .vast_api import get_vast_client, VastAPIError


class RecipeExecutor:
    """
    Executes recipes with DAG-based step ordering.

    Handles:
    - Variable interpolation
    - Dependency resolution
    - Parallel execution of independent steps
    - Error handling and retries
    """

    def __init__(
        self,
        recipe: Recipe,
        host_resolver: Optional[Callable[[str], Any]] = None,
        storage_resolver: Optional[Callable[[str], Any]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize the executor.

        Args:
            recipe: The recipe to execute
            host_resolver: Function to resolve host ID to Host object
            storage_resolver: Function to resolve storage ID to Storage object
            log_callback: Optional callback for log messages
        """
        self.recipe = recipe
        self.host_resolver = host_resolver
        self.storage_resolver = storage_resolver
        self.log_callback = log_callback or print

        # Runtime state
        self.variables = dict(recipe.variables)
        self.results: Dict[str, StepResult] = {}
        self.execution: Optional[Execution] = None

        # Secrets
        self.secrets = get_secrets_manager()

        # Execution logger
        self.exec_logger: Optional[ExecutionLogger] = None

        # Variable interpolator
        self.interpolator = VariableInterpolator(
            variables=self.variables,
            secrets_getter=self.secrets.get,
        )

    def log(self, message: str) -> None:
        """Log a message."""
        self.log_callback(message)
        if self.execution:
            self.execution.append_log(message + "\n")

    def execute_sync(self) -> bool:
        """
        Execute the recipe synchronously.

        Returns:
            True if all steps completed successfully
        """
        return asyncio.run(self.execute())

    async def execute(self) -> bool:
        """
        Execute the recipe asynchronously.

        Returns:
            True if all steps completed successfully
        """
        self.execution = Execution(
            recipe_id=self.recipe.id,
            status=ExecutionStatus.RUNNING,
        )

        # Initialize execution logger
        self.exec_logger = ExecutionLogger(
            exec_id=self.execution.id,
            recipe_id=self.recipe.id
        )
        self.exec_logger.start(self.recipe.name, dict(self.recipe.variables))

        start_time = datetime.now()
        self.log(f"Starting recipe: {self.recipe.name}")

        # Build step lookup
        steps_by_id = {step.id: step for step in self.recipe.steps}
        pending = set(steps_by_id.keys())
        completed = set()
        failed = set()

        while pending:
            # Find steps whose dependencies are satisfied
            ready = []
            for step_id in pending:
                step = steps_by_id[step_id]
                deps_met = all(dep in completed for dep in step.depends_on)
                deps_failed = any(dep in failed for dep in step.depends_on)

                if deps_failed:
                    # Skip this step - a dependency failed
                    self.results[step_id] = StepResult(
                        step_id=step_id,
                        status=StepStatus.SKIPPED,
                        error="Dependency failed",
                    )
                    pending.remove(step_id)
                    break  # Restart the loop
                elif deps_met:
                    ready.append(step)

            if not ready:
                if pending:
                    # Circular dependency or all remaining have failed deps
                    self.log("No more steps can be executed")
                break

            # Execute ready steps (could parallelize if desired)
            for step in ready:
                pending.remove(step.id)
                self.log(f"Executing step: {step.name}")

                # Log step start
                if self.exec_logger:
                    self.exec_logger.step_start(step.id, step.name, step.operation.value)

                result = await self._execute_step_with_retry(step)
                self.results[step.id] = result

                # Log step output and end
                if self.exec_logger:
                    if result.output:
                        self.exec_logger.step_output(step.id, result.output)

                    duration_ms = 0
                    if result.started_at and result.completed_at:
                        duration_ms = int((result.completed_at - result.started_at).total_seconds() * 1000)

                    self.exec_logger.step_end(
                        step.id,
                        result.status == StepStatus.COMPLETED,
                        duration_ms,
                        result.error or ""
                    )

                if result.status == StepStatus.COMPLETED:
                    completed.add(step.id)
                    self.log(f"Step completed: {step.name}")
                else:
                    failed.add(step.id)
                    self.log(f"Step failed: {step.name} - {result.error}")

        # Determine overall status
        all_completed = len(pending) == 0 and len(failed) == 0
        self.execution.status = (
            ExecutionStatus.COMPLETED if all_completed else ExecutionStatus.FAILED
        )
        self.execution.completed_at = datetime.now()

        # Log execution end
        total_duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        if self.exec_logger:
            self.exec_logger.end(all_completed, total_duration_ms)

        self.log(f"Recipe {'completed' if all_completed else 'failed'}")
        return all_completed

    async def _execute_step_with_retry(self, step: RecipeStep) -> StepResult:
        """Execute a step with retry logic."""
        last_result = None

        for attempt in range(step.retry_count + 1):
            if attempt > 0:
                self.log(f"Retrying step {step.name} (attempt {attempt + 1})")

            result = await self._execute_step(step)

            if result.status == StepStatus.COMPLETED:
                return result

            last_result = result

        return last_result or StepResult(
            step_id=step.id,
            status=StepStatus.FAILED,
            error="Unknown error",
        )

    async def _execute_step(self, step: RecipeStep) -> StepResult:
        """Execute a single step."""
        # Interpolate parameters
        params = self.interpolator.interpolate_dict(step.params)

        # Get operation handler
        handlers = {
            OperationType.RUN_COMMANDS: self._op_run_commands,
            OperationType.SIMPLE_COMMANDS: self._op_simple_commands,
            OperationType.TRANSFER: self._op_transfer,
            OperationType.GIT_CLONE: self._op_git_clone,
            OperationType.GIT_PULL: self._op_git_pull,
            OperationType.UV_RUN: self._op_uv_run,
            OperationType.VAST_START: self._op_vast_start,
            OperationType.VAST_STOP: self._op_vast_stop,
            OperationType.VAST_RM: self._op_vast_rm,
            OperationType.VAST_SEARCH: self._op_vast_search,
            OperationType.VAST_CREATE: self._op_vast_create,
            OperationType.VAST_WAIT_READY: self._op_vast_wait_ready,
            OperationType.SSH_CONNECT: self._op_ssh_connect,
            OperationType.HOST_TEST: self._op_host_test,
            OperationType.TMUX_NEW: self._op_tmux_new,
            OperationType.TMUX_SEND: self._op_tmux_send,
            OperationType.TMUX_CAPTURE: self._op_tmux_capture,
            OperationType.TMUX_KILL: self._op_tmux_kill,
            OperationType.GDRIVE_MOUNT: self._op_gdrive_mount,
            OperationType.GDRIVE_UNMOUNT: self._op_gdrive_unmount,
            OperationType.HF_DOWNLOAD: self._op_hf_download,
            OperationType.FETCH_EXCHANGE_RATES: self._op_fetch_exchange_rates,
            OperationType.CALCULATE_COST: self._op_calculate_cost,
            OperationType.SLEEP: self._op_sleep,
            OperationType.WAIT_CONDITION: self._op_wait_condition,
            OperationType.ASSERT: self._op_assert,
            OperationType.WAIT_FOR_FILE: self._op_wait_for_file,
            OperationType.WAIT_FOR_PORT: self._op_wait_for_port,
            OperationType.SET_VAR: self._op_set_var,
            OperationType.GET_VALUE: self._op_get_value,
            OperationType.SET_ENV: self._op_set_env,
            OperationType.NOTIFY: self._op_notify,
            OperationType.HTTP_REQUEST: self._op_http_request,
            OperationType.GROUP: self._op_group,
            OperationType.CUSTOM: self._op_custom,
        }

        handler = handlers.get(step.operation)
        if not handler:
            return StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                error=f"Unknown operation: {step.operation.value}",
            )

        try:
            result = StepResult(
                step_id=step.id,
                status=StepStatus.RUNNING,
                started_at=datetime.now(),
            )

            output, error = await handler(params)

            if error:
                result.status = StepStatus.FAILED
                result.error = error
            else:
                result.status = StepStatus.COMPLETED
                result.output = output

            result.completed_at = datetime.now()
            return result

        except Exception as e:
            return StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                error=str(e),
                completed_at=datetime.now(),
            )

    # =========================================================================
    # Operation Handlers
    # =========================================================================

    async def _op_run_commands(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Execute shell commands."""
        commands = params.get("commands", "")
        host_id = params.get("host_id")
        workdir = params.get("workdir")
        timeout = params.get("timeout_secs", 300)

        if host_id and self.host_resolver:
            host = self.host_resolver(host_id)
            if host:
                ssh = SSHClient.from_host(host)
                if workdir:
                    commands = f"cd {workdir} && {commands}"
                result = ssh.run(commands, timeout=timeout)
                if result.success:
                    return result.stdout, None
                return result.stdout, result.stderr
            return "", f"Host not found: {host_id}"
        else:
            # Local execution
            import subprocess
            try:
                result = subprocess.run(
                    commands,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=workdir,
                )
                if result.returncode == 0:
                    return result.stdout, None
                return result.stdout, result.stderr
            except subprocess.TimeoutExpired:
                return "", "Command timed out"

    async def _op_simple_commands(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Execute simple commands list."""
        commands = params if isinstance(params, list) else params.get("commands", [])
        commands_str = " && ".join(commands)
        return await self._op_run_commands({"commands": commands_str})

    async def _op_transfer(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Execute file transfer."""
        from ..core.models import TransferEndpoint

        source = params.get("source", {})
        dest = params.get("destination", {})

        src_endpoint = TransferEndpoint(
            type=source.get("type", "local"),
            path=source.get("path", ""),
            host_id=source.get("host_id"),
            storage_id=source.get("storage_id"),
        )
        dst_endpoint = TransferEndpoint(
            type=dest.get("type", "local"),
            path=dest.get("path", ""),
            host_id=dest.get("host_id"),
            storage_id=dest.get("storage_id"),
        )

        engine = TransferEngine()
        result = engine.transfer(
            source=src_endpoint,
            destination=dst_endpoint,
            delete=params.get("delete", False),
            exclude=params.get("exclude_patterns", []),
        )

        if result.success:
            return f"Transferred {result.bytes_transferred} bytes", None
        return "", result.message

    async def _op_git_clone(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Clone a git repository."""
        repo_url = params.get("repo_url", "")
        destination = params.get("destination", "")
        branch = params.get("branch")
        depth = params.get("depth")

        cmd = f"git clone"
        if branch:
            cmd += f" -b {branch}"
        if depth:
            cmd += f" --depth {depth}"
        cmd += f" {repo_url} {destination}"

        return await self._op_run_commands({
            "commands": cmd,
            "host_id": params.get("host_id"),
        })

    async def _op_vast_start(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Start a Vast.ai instance."""
        try:
            client = get_vast_client()
            template_id = params.get("template_id")

            if template_id:
                # Create new instance from template
                # For now, just search and create
                offers = client.search_offers(limit=1)
                if offers:
                    instance_id = client.create_instance(
                        offer_id=offers[0].id,
                        image=params.get("image", "pytorch/pytorch:latest"),
                        disk=params.get("disk_gb", 50),
                    )
                    # Store the instance ID as a variable
                    self.variables["vast_instance_id"] = str(instance_id)
                    self.interpolator.set_variable("vast_instance_id", str(instance_id))
                    return f"Created instance {instance_id}", None
                return "", "No offers available"
            else:
                instance_id = params.get("instance_id")
                if instance_id:
                    client.start_instance(int(instance_id))
                    return f"Started instance {instance_id}", None
                return "", "No instance_id or template_id specified"
        except VastAPIError as e:
            return "", str(e)

    async def _op_vast_stop(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Stop a Vast.ai instance."""
        try:
            client = get_vast_client()
            instance_id = params.get("instance_id") or self.variables.get("vast_instance_id")
            if instance_id:
                client.stop_instance(int(instance_id))
                return f"Stopped instance {instance_id}", None
            return "", "No instance_id specified"
        except VastAPIError as e:
            return "", str(e)

    async def _op_vast_rm(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Remove a Vast.ai instance."""
        try:
            client = get_vast_client()
            instance_id = params.get("instance_id") or self.variables.get("vast_instance_id")
            if instance_id:
                client.rm_instance(int(instance_id))
                return f"Removed instance {instance_id}", None
            return "", "No instance_id specified"
        except VastAPIError as e:
            return "", str(e)

    async def _op_tmux_new(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Create new tmux session."""
        host_id = params.get("host_id")
        session_name = params.get("session_name", "trainsh")
        command = params.get("command")
        workdir = params.get("workdir")

        ssh = None
        if host_id and self.host_resolver:
            host = self.host_resolver(host_id)
            if host:
                ssh = SSHClient.from_host(host)

        tmux = TmuxManager(ssh)
        result = tmux.create_session(
            name=session_name,
            command=command,
            workdir=workdir,
        )

        if result.success:
            return f"Created tmux session: {session_name}", None
        return "", result.stderr

    async def _op_tmux_send(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Send keys to tmux session."""
        host_id = params.get("host_id")
        session_name = params.get("session_name", "trainsh")
        keys = params.get("keys", "")

        ssh = None
        if host_id and self.host_resolver:
            host = self.host_resolver(host_id)
            if host:
                ssh = SSHClient.from_host(host)

        tmux = TmuxManager(ssh)
        result = tmux.send_keys(session_name, keys)

        if result.success:
            return f"Sent keys to {session_name}", None
        return "", result.stderr

    async def _op_tmux_capture(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Capture tmux pane output."""
        host_id = params.get("host_id")
        session_name = params.get("session_name", "trainsh")
        lines = params.get("lines")
        capture_var = params.get("capture_output")

        ssh = None
        if host_id and self.host_resolver:
            host = self.host_resolver(host_id)
            if host:
                ssh = SSHClient.from_host(host)

        tmux = TmuxManager(ssh)
        output = tmux.capture_pane(session_name, lines=lines)

        if capture_var:
            self.variables[capture_var] = output
            self.interpolator.set_variable(capture_var, output)

        return output, None

    async def _op_tmux_kill(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Kill tmux session."""
        host_id = params.get("host_id")
        session_name = params.get("session_name", "trainsh")

        ssh = None
        if host_id and self.host_resolver:
            host = self.host_resolver(host_id)
            if host:
                ssh = SSHClient.from_host(host)

        tmux = TmuxManager(ssh)
        result = tmux.kill_session(session_name)

        if result.success:
            return f"Killed tmux session: {session_name}", None
        return "", result.stderr

    async def _op_sleep(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Sleep for specified duration."""
        duration = params.get("duration_secs", 0)
        await asyncio.sleep(duration)
        return f"Slept for {duration} seconds", None

    async def _op_set_var(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Set a variable."""
        name = params.get("name", "")
        value = params.get("value", "")

        if name:
            self.variables[name] = value
            self.interpolator.set_variable(name, value)
            return f"Set {name}={value}", None
        return "", "No variable name specified"

    async def _op_notify(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Send a notification."""
        title = params.get("title", "tmux-trainsh")
        message = params.get("message", "")
        level = params.get("level", "info")

        self.log(f"[{level.upper()}] {title}: {message}")
        # Could integrate with system notifications here
        return f"Notification sent: {title}", None

    async def _op_http_request(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Make an HTTP request."""
        import urllib.request
        import json

        method = params.get("method", "GET")
        url = params.get("url", "")
        headers = params.get("headers", {})
        body = params.get("body")
        capture_var = params.get("capture_response")

        try:
            data = body.encode() if body else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method)

            with urllib.request.urlopen(req) as response:
                response_body = response.read().decode()

                if capture_var:
                    self.variables[capture_var] = response_body
                    self.interpolator.set_variable(capture_var, response_body)

                return response_body[:500], None  # Truncate for logging
        except Exception as e:
            return "", str(e)

    async def _op_vast_search(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Search for Vast.ai GPU offers."""
        try:
            client = get_vast_client()
            gpu_name = params.get("gpu_name")
            num_gpus = params.get("num_gpus", 1)
            max_dph = params.get("max_dph")

            offers = client.search_offers(
                gpu_name=gpu_name,
                num_gpus=num_gpus,
                max_dph=max_dph,
                limit=params.get("limit", 10),
            )

            if not offers:
                return "", "No offers found matching criteria"

            # Store best offer ID in variable
            best_offer = offers[0]
            self.variables["_vast_offer_id"] = best_offer.id
            self.interpolator.set_variable("_vast_offer_id", str(best_offer.id))

            return f"Found {len(offers)} offers. Best: {best_offer.gpu_name} @ ${best_offer.dph_total:.3f}/hr", None
        except VastAPIError as e:
            return "", str(e)

    async def _op_vast_create(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Create a Vast.ai instance."""
        try:
            client = get_vast_client()
            offer_id = params.get("offer_id") or self.variables.get("_vast_offer_id")

            if not offer_id:
                return "", "No offer_id specified and no search performed"

            image = params.get("image", "pytorch/pytorch:latest")
            disk = params.get("disk", 50)

            instance_id = client.create_instance(
                offer_id=int(offer_id),
                image=image,
                disk=disk,
            )

            self.variables["_vast_instance_id"] = instance_id
            self.interpolator.set_variable("_vast_instance_id", str(instance_id))

            return f"Created instance {instance_id}", None
        except VastAPIError as e:
            return "", str(e)

    async def _op_vast_wait_ready(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Wait for a Vast.ai instance to be ready."""
        import asyncio

        try:
            client = get_vast_client()
            instance_id = params.get("instance_id") or self.variables.get("_vast_instance_id")

            if not instance_id:
                return "", "No instance_id specified"

            timeout = params.get("timeout", 300)
            poll_interval = params.get("poll_interval", 10)
            elapsed = 0

            while elapsed < timeout:
                instance = client.get_instance(int(instance_id))
                if instance.is_running:
                    self.variables["_vast_ssh_host"] = instance.ssh_host
                    self.variables["_vast_ssh_port"] = instance.ssh_port
                    return f"Instance {instance_id} is ready", None

                self.log(f"Waiting for instance... ({instance.actual_status})")
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

            return "", f"Timeout waiting for instance {instance_id}"
        except VastAPIError as e:
            return "", str(e)

    async def _op_host_test(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Test SSH connection to a host."""
        host_name = params.get("host")
        if not host_name:
            return "", "No host specified"

        # Try to resolve host
        if self.host_resolver:
            host = self.host_resolver(host_name)
            if host:
                ssh = SSHClient(host)
                if ssh.test_connection():
                    return f"Connection to {host_name} successful", None
                return "", f"Failed to connect to {host_name}"

        # Try direct SSH test
        result = await self._run_local_command(f"ssh -o ConnectTimeout=5 {host_name} echo ok")
        if "ok" in result[0]:
            return f"Connection to {host_name} successful", None
        return "", f"Failed to connect to {host_name}"

    async def _op_wait_condition(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Wait for a condition to be true."""
        import asyncio

        condition = params.get("condition", "")
        timeout = params.get("timeout", 300)
        poll_interval = params.get("poll_interval", 10)
        elapsed = 0

        while elapsed < timeout:
            # Check condition type
            if condition.startswith("file_exists:"):
                path = condition.split(":", 1)[1]
                result = await self._run_local_command(f"test -f {path} && echo exists")
                if "exists" in result[0]:
                    return f"Condition met: {condition}", None

            elif condition.startswith("command:"):
                cmd = condition.split(":", 1)[1]
                result = await self._run_local_command(cmd)
                if result[0] and not result[1]:
                    return f"Condition met: {condition}", None

            self.log(f"Waiting for condition: {condition}")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return "", f"Timeout waiting for condition: {condition}"

    async def _op_hf_download(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Download a model from HuggingFace Hub."""
        repo_id = params.get("repo_id", "")
        local_dir = params.get("local_dir", "")
        token = params.get("token", "")

        if not repo_id:
            return "", "No repo_id specified"

        cmd = f"huggingface-cli download {repo_id}"
        if local_dir:
            cmd += f" --local-dir {local_dir}"
        if token:
            cmd += f" --token {token}"

        return await self._run_local_command(cmd)

    async def _op_fetch_exchange_rates(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Fetch current exchange rates."""
        from .pricing import fetch_exchange_rates, save_pricing_settings, load_pricing_settings

        try:
            rates = fetch_exchange_rates()
            settings = load_pricing_settings()
            settings.exchange_rates = rates
            save_pricing_settings(settings)

            # Store rates in variables
            for currency, rate in rates.rates.items():
                var_name = f"rate_{currency.lower()}"
                self.variables[var_name] = str(rate)
                self.interpolator.set_variable(var_name, str(rate))

            return f"Fetched {len(rates.rates)} exchange rates", None
        except Exception as e:
            return "", str(e)

    async def _op_calculate_cost(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Calculate costs for hosts/instances."""
        from .pricing import (
            load_pricing_settings, calculate_host_cost, format_currency
        )

        try:
            settings = load_pricing_settings()
            display_curr = params.get("currency", settings.display_currency)
            rates = settings.exchange_rates

            # Calculate for Vast.ai instances
            if params.get("vast", False):
                client = get_vast_client()
                instances = client.list_instances()

                total_per_hour = 0.0
                results = []

                for inst in instances:
                    if inst.dph_total:
                        cost = calculate_host_cost(
                            host_id=str(inst.id),
                            gpu_hourly_usd=inst.dph_total,
                            host_name=inst.gpu_name,
                            source="vast_api",
                        )
                        total_per_hour += cost.total_per_hour_usd
                        converted = rates.convert(cost.total_per_hour_usd, "USD", display_curr)
                        results.append(f"{inst.gpu_name}: {format_currency(converted, display_curr)}/hr")

                # Store totals in variables
                self.variables["total_cost_per_hour_usd"] = str(total_per_hour)
                self.variables["total_cost_per_day_usd"] = str(total_per_hour * 24)
                self.variables["total_cost_per_month_usd"] = str(total_per_hour * 24 * 30)

                total_converted = rates.convert(total_per_hour, "USD", display_curr)
                self.variables[f"total_cost_per_hour_{display_curr.lower()}"] = str(total_converted)

                return f"Total: {format_currency(total_converted, display_curr)}/hr", None

            # Calculate for specific host
            host_id = params.get("host_id")
            gpu_hourly = params.get("gpu_hourly_usd", 0.0)

            if host_id or gpu_hourly:
                cost = calculate_host_cost(
                    host_id=host_id or "manual",
                    gpu_hourly_usd=gpu_hourly,
                    storage_gb=params.get("storage_gb", 0.0),
                )
                converted = rates.convert(cost.total_per_hour_usd, "USD", display_curr)
                return f"{format_currency(converted, display_curr)}/hr", None

            return "", "No calculation target specified (use vast=true or host_id)"
        except Exception as e:
            return "", str(e)

    async def _run_local_command(self, command: str) -> tuple[str, Optional[str]]:
        """Run a local command."""
        import asyncio

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return stdout.decode(), stderr.decode() or f"Exit code {proc.returncode}"
            return stdout.decode(), None
        except Exception as e:
            return "", str(e)

    # =========================================================================
    # Additional Operation Handlers
    # =========================================================================

    async def _op_git_pull(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Pull latest changes from git repository."""
        directory = params.get("directory", ".")
        remote = params.get("remote", "origin")
        branch = params.get("branch", "")

        cmd = f"cd {directory} && git pull {remote}"
        if branch:
            cmd += f" {branch}"

        return await self._op_run_commands({
            "commands": cmd,
            "host_id": params.get("host_id"),
        })

    async def _op_uv_run(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Run commands with uv (fast Python package manager)."""
        command = params.get("command", "")
        packages = params.get("with", [])

        if isinstance(packages, str):
            packages = [packages]

        cmd = "uv run"
        for pkg in packages:
            cmd += f" --with {pkg}"
        cmd += f" {command}"

        return await self._op_run_commands({
            "commands": cmd,
            "host_id": params.get("host_id"),
        })

    async def _op_ssh_connect(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Test SSH connection and store connection info."""
        host_id = params.get("host_id")
        if not host_id:
            return "", "No host_id specified"

        if self.host_resolver:
            host = self.host_resolver(host_id)
            if host:
                ssh = SSHClient.from_host(host)
                if ssh.test_connection():
                    self.variables["_ssh_host"] = host.hostname
                    self.variables["_ssh_port"] = str(host.port)
                    self.variables["_ssh_user"] = host.username
                    return f"Connected to {host.hostname}", None
                return "", f"Failed to connect to {host_id}"

        return "", f"Host not found: {host_id}"

    async def _op_gdrive_mount(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Mount Google Drive (for Colab environments)."""
        mount_path = params.get("mount_path", "/content/drive")

        # This is typically used in Colab
        cmd = f"""python3 -c "
from google.colab import drive
drive.mount('{mount_path}')
print('Drive mounted at {mount_path}')
" """
        return await self._op_run_commands({
            "commands": cmd,
            "host_id": params.get("host_id"),
        })

    async def _op_gdrive_unmount(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Unmount Google Drive."""
        mount_path = params.get("mount_path", "/content/drive")

        cmd = f"""python3 -c "
from google.colab import drive
drive.flush_and_unmount()
print('Drive unmounted')
" """
        return await self._op_run_commands({
            "commands": cmd,
            "host_id": params.get("host_id"),
        })

    async def _op_assert(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Assert a condition is true."""
        condition = params.get("condition", "")
        message = params.get("message", "Assertion failed")

        # Evaluate simple conditions
        if condition.startswith("var:"):
            var_name = condition.split(":", 1)[1]
            value = self.variables.get(var_name, "")
            if value:
                return f"Assertion passed: {var_name} = {value}", None
            return "", f"{message}: {var_name} is not set"

        elif condition.startswith("file_exists:"):
            path = condition.split(":", 1)[1]
            result = await self._run_local_command(f"test -f {path} && echo exists")
            if "exists" in result[0]:
                return f"Assertion passed: file exists {path}", None
            return "", f"{message}: file not found {path}"

        elif condition.startswith("command:"):
            cmd = condition.split(":", 1)[1]
            result = await self._run_local_command(cmd)
            if result[0] and not result[1]:
                return f"Assertion passed: command succeeded", None
            return "", f"{message}: command failed"

        return "", f"Unknown condition type: {condition}"

    async def _op_wait_for_file(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Wait for a file to exist."""
        path = params.get("path", "")
        timeout = params.get("timeout", 300)
        poll_interval = params.get("poll_interval", 5)

        if not path:
            return "", "No path specified"

        elapsed = 0
        while elapsed < timeout:
            result = await self._run_local_command(f"test -f {path} && echo exists")
            if "exists" in result[0]:
                return f"File found: {path}", None

            self.log(f"Waiting for file: {path}")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return "", f"Timeout waiting for file: {path}"

    async def _op_wait_for_port(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Wait for a port to be open."""
        host = params.get("host", "localhost")
        port = params.get("port", 0)
        timeout = params.get("timeout", 300)
        poll_interval = params.get("poll_interval", 5)

        if not port:
            return "", "No port specified"

        elapsed = 0
        while elapsed < timeout:
            result = await self._run_local_command(
                f"nc -z {host} {port} 2>/dev/null && echo open || true"
            )
            if "open" in result[0]:
                return f"Port {port} is open on {host}", None

            self.log(f"Waiting for port {port} on {host}")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        return "", f"Timeout waiting for port {port} on {host}"

    async def _op_get_value(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Get a value and store it in a variable."""
        source = params.get("source", "")
        target_var = params.get("target", "")

        if not target_var:
            return "", "No target variable specified"

        if source.startswith("env:"):
            import os
            env_name = source.split(":", 1)[1]
            value = os.environ.get(env_name, "")
            self.variables[target_var] = value
            self.interpolator.set_variable(target_var, value)
            return f"Got {target_var}={value}", None

        elif source.startswith("secret:"):
            secret_name = source.split(":", 1)[1]
            value = self.secrets.get(secret_name) or ""
            self.variables[target_var] = value
            self.interpolator.set_variable(target_var, value)
            return f"Got secret {target_var}", None

        elif source.startswith("command:"):
            cmd = source.split(":", 1)[1]
            result = await self._run_local_command(cmd)
            value = result[0].strip()
            self.variables[target_var] = value
            self.interpolator.set_variable(target_var, value)
            return f"Got {target_var}={value}", None

        return "", f"Unknown source type: {source}"

    async def _op_set_env(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Set environment variable."""
        import os

        name = params.get("name", "")
        value = params.get("value", "")

        if not name:
            return "", "No environment variable name specified"

        os.environ[name] = value
        return f"Set environment variable {name}", None

    async def _op_group(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Execute a group of steps (sequential or parallel)."""
        mode = params.get("mode", "sequential")
        steps = params.get("steps", [])

        if not steps:
            return "", "No steps in group"

        if mode == "parallel":
            # Execute steps in parallel
            tasks = []
            for step_data in steps:
                step = RecipeStep.from_dict(step_data)
                tasks.append(self._execute_step(step))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            errors = [r for r in results if isinstance(r, Exception) or
                      (isinstance(r, StepResult) and r.status == StepStatus.FAILED)]

            if errors:
                return "", f"Group failed: {len(errors)} steps failed"
            return f"Group completed: {len(results)} steps", None
        else:
            # Sequential execution
            for step_data in steps:
                step = RecipeStep.from_dict(step_data)
                result = await self._execute_step(step)
                if result.status == StepStatus.FAILED:
                    return "", f"Group failed at step: {step.name}"

            return f"Group completed: {len(steps)} steps", None

    async def _op_custom(self, params: Dict[str, Any]) -> tuple[str, Optional[str]]:
        """Execute custom Python code."""
        code = params.get("code", "")

        if not code:
            return "", "No code specified"

        # Create a restricted execution environment
        local_vars = {
            "variables": self.variables,
            "log": self.log,
            "result": None,
        }

        try:
            exec(code, {"__builtins__": {}}, local_vars)
            return str(local_vars.get("result", "Custom code executed")), None
        except Exception as e:
            return "", f"Custom code error: {e}"


def load_recipe_from_file(path: str) -> Recipe:
    """
    Load a recipe from a TOML file.

    Args:
        path: Path to the TOML file

    Returns:
        Recipe object
    """
    import tomllib
    import os

    with open(os.path.expanduser(path), "rb") as f:
        data = tomllib.load(f)

    return Recipe.from_dict(data)


def run_recipe(recipe_path: str, log_callback: Optional[Callable[[str], None]] = None) -> bool:
    """
    Load and execute a recipe file.

    Args:
        recipe_path: Path to the recipe TOML file
        log_callback: Optional log callback

    Returns:
        True if successful
    """
    recipe = load_recipe_from_file(recipe_path)
    executor = RecipeExecutor(recipe, log_callback=log_callback)
    return executor.execute_sync()
