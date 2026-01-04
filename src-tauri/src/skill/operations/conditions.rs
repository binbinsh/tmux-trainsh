//! Condition evaluation

use std::collections::HashMap;

use regex::Regex;

use super::google_drive;
use super::ssh;
use super::tmux;
use crate::error::AppError;
use crate::host;
use crate::skill::parser::interpolate;
use crate::skill::types::*;

/// Evaluate a condition
pub async fn evaluate(
    condition: &Condition,
    variables: &HashMap<String, String>,
) -> Result<bool, AppError> {
    match condition {
        Condition::FileExists(c) => {
            let host_id = interpolate(&c.host_id, variables);
            let path = interpolate(&c.path, variables);

            let cmd = format!("test -e {} && echo yes || echo no", path);
            let output = ssh::get_output(&host_id, &cmd).await?;
            Ok(output.trim() == "yes")
        }

        Condition::FileContains(c) => {
            let host_id = interpolate(&c.host_id, variables);
            let path = interpolate(&c.path, variables);
            let pattern = interpolate(&c.pattern, variables);

            let cmd = format!("grep -q '{}' {} && echo yes || echo no", pattern, path);
            let output = ssh::get_output(&host_id, &cmd).await?;
            Ok(output.trim() == "yes")
        }

        Condition::CommandSucceeds(c) => {
            let host_id = interpolate(&c.host_id, variables);
            let command = interpolate(&c.command, variables);

            ssh::command_succeeds(&host_id, &command).await
        }

        Condition::OutputMatches(c) => {
            let host_id = interpolate(&c.host_id, variables);
            let command = interpolate(&c.command, variables);
            let pattern = interpolate(&c.pattern, variables);

            let output = ssh::get_output(&host_id, &command).await?;
            let re = Regex::new(&pattern)
                .map_err(|e| AppError::invalid_input(format!("Invalid regex: {e}")))?;
            Ok(re.is_match(&output))
        }

        Condition::VarEquals(c) => {
            let name = &c.name;
            let expected = interpolate(&c.value, variables);
            let actual = variables.get(name).cloned().unwrap_or_default();
            Ok(actual == expected)
        }

        Condition::VarMatches(c) => {
            let name = &c.name;
            let pattern = interpolate(&c.pattern, variables);
            let actual = variables.get(name).cloned().unwrap_or_default();

            let re = Regex::new(&pattern)
                .map_err(|e| AppError::invalid_input(format!("Invalid regex: {e}")))?;
            Ok(re.is_match(&actual))
        }

        Condition::HostOnline(c) => {
            let host_id = interpolate(&c.host_id, variables);

            match host::get_host(&host_id).await {
                Ok(h) => Ok(h.status == host::HostStatus::Online),
                Err(_) => Ok(false),
            }
        }

        Condition::TmuxAlive(c) => {
            let host_id = interpolate(&c.host_id, variables);
            let session_name = interpolate(&c.session_name, variables);

            tmux::session_exists(&host_id, &session_name).await
        }

        Condition::GpuAvailable(c) => {
            let host_id = interpolate(&c.host_id, variables);

            let host = host::get_host(&host_id).await?;
            let gpu_count = host.num_gpus.unwrap_or(0) as u32;
            Ok(gpu_count >= c.min_count)
        }

        Condition::GdriveMounted(c) => {
            let host_id = interpolate(&c.host_id, variables);
            let mount_path = interpolate(&c.mount_path, variables);

            google_drive::is_mounted(&host_id, &mount_path).await
        }

        Condition::Not(inner) => {
            let result = Box::pin(evaluate(inner, variables)).await?;
            Ok(!result)
        }

        Condition::And(conditions) => {
            for cond in conditions {
                if !Box::pin(evaluate(cond, variables)).await? {
                    return Ok(false);
                }
            }
            Ok(true)
        }

        Condition::Or(conditions) => {
            for cond in conditions {
                if Box::pin(evaluate(cond, variables)).await? {
                    return Ok(true);
                }
            }
            Ok(false)
        }

        Condition::Always => Ok(true),
        Condition::Never => Ok(false),
    }
}

/// Wait for a condition to be met
pub async fn wait_for(
    condition: &Condition,
    variables: &HashMap<String, String>,
    timeout_secs: u64,
    poll_interval_secs: u64,
) -> Result<(), AppError> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);

    loop {
        if evaluate(condition, variables).await? {
            return Ok(());
        }

        if std::time::Instant::now() >= deadline {
            return Err(AppError::command(format!(
                "Timeout waiting for condition after {}s",
                timeout_secs
            )));
        }

        tokio::time::sleep(tokio::time::Duration::from_secs(poll_interval_secs)).await;
    }
}
