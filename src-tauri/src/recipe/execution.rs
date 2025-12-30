//! Recipe execution helpers
//!
//! Shared helpers for interactive recipe execution (DAG ordering and step execution).

use std::collections::HashMap;
use std::sync::Arc;

use super::operations;
use super::parser::interpolate;
use super::types::*;
use crate::error::AppError;
use crate::host;

/// Execute a single step operation
/// Public so it can be used by interactive recipe execution
pub async fn execute_step(
    operation: &Operation,
    variables: &HashMap<String, String>,
    progress: Option<Arc<dyn Fn(&str) + Send + Sync>>,
) -> Result<Option<String>, AppError> {
    match operation {
        // New unified run_commands operation
        Operation::RunCommands(op) => {
            // Resolve host_id: use explicit host_id, or fall back to ${target} variable
            let target = op
                .host_id
                .as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;

            let commands = interpolate(&op.commands, variables);
            let workdir = op.workdir.as_ref().map(|w| interpolate(w, variables));

            // Check if this is local execution
            let is_local = operations::ssh::is_local_target(&target);

            match op.tmux_mode {
                crate::recipe::types::TmuxMode::None => {
                    if is_local {
                        // Execute commands locally (no SSH)
                        operations::ssh::execute_local_command(
                            &commands,
                            workdir.as_deref(),
                            &op.env,
                        )
                        .await
                    } else {
                        // Execute commands directly via SSH (blocking)
                        operations::ssh::execute_command(
                            &target,
                            &commands,
                            workdir.as_deref(),
                            &op.env,
                        )
                        .await
                    }
                }
                crate::recipe::types::TmuxMode::New => {
                    if is_local {
                        return Err(AppError::command(
                            "Tmux mode 'new' is not supported for local execution",
                        ));
                    }
                    // Create a new tmux session and run commands
                    let session_name = op
                        .session_name
                        .as_ref()
                        .map(|s| interpolate(s, variables))
                        .unwrap_or_else(|| "recipe".to_string());
                    operations::tmux::new_session(
                        &target,
                        &session_name,
                        Some(&commands),
                        workdir.as_deref(),
                    )
                    .await?;
                    Ok(None)
                }
                crate::recipe::types::TmuxMode::Existing => {
                    if is_local {
                        return Err(AppError::command(
                            "Tmux mode 'existing' is not supported for local execution",
                        ));
                    }
                    // Send commands to existing tmux session
                    let session_name = op
                        .session_name
                        .as_ref()
                        .map(|s| interpolate(s, variables))
                        .ok_or_else(|| {
                            AppError::command("session_name required for existing tmux mode")
                        })?;
                    // Send each line as a command
                    for line in commands.lines() {
                        let line = line.trim();
                        if !line.is_empty() && !line.starts_with('#') {
                            let keys = format!("{} Enter", line);
                            operations::tmux::send_keys(&target, &session_name, &keys).await?;
                        }
                    }
                    Ok(None)
                }
            }
        }

        // New unified transfer operation
        Operation::Transfer(op) => operations::transfer::execute(op, variables).await,

        // Git clone operation
        Operation::GitClone(op) => {
            let target = op
                .host_id
                .as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;

            let is_local = operations::ssh::is_local_target(&target);

            let repo_url = interpolate(&op.repo_url, variables);
            let destination = interpolate(&op.destination, variables);
            let branch = op.branch.as_ref().map(|b| interpolate(b, variables));
            // Interpolate auth_token and filter out empty strings
            let auth_token = op
                .auth_token
                .as_ref()
                .map(|t| interpolate(t, variables))
                .filter(|t| !t.is_empty());

            eprintln!(
                "[git_clone] repo_url={}, auth_token={:?}, local={}",
                repo_url,
                auth_token.as_ref().map(|_| "[REDACTED]"),
                is_local
            );

            // First, add GitHub/GitLab/Bitbucket host keys to known_hosts to avoid "Host key verification failed"
            let add_host_keys = r#"mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keyscan -t ed25519,rsa github.com gitlab.com bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null"#;
            let empty_env = HashMap::new();
            if is_local {
                operations::ssh::execute_local_command(add_host_keys, None, &empty_env).await?;
            } else {
                operations::ssh::execute_command(&target, add_host_keys, None, &empty_env).await?;
            }

            // Now clone
            let clone_cmd = if let Some(token) = auth_token {
                // Insert token into URL for auth
                // Example: https://github.com/owner/repo.git -> https://token@github.com/owner/repo.git
                let auth_url = if repo_url.starts_with("https://") {
                    repo_url.replacen("https://", &format!("https://{}@", token), 1)
                } else {
                    repo_url.clone()
                };
                format!("git clone {} {}", auth_url, destination)
            } else {
                format!("git clone {} {}", repo_url, destination)
            };

            let clone_cmd = if let Some(branch) = branch {
                format!("{} -b {}", clone_cmd, branch)
            } else {
                clone_cmd
            };

            if is_local {
                operations::ssh::execute_local_command(&clone_cmd, None, &empty_env).await?;
            } else {
                operations::ssh::execute_command(&target, &clone_cmd, None, &empty_env).await?;
            }
            Ok(None)
        }

        // Vast.ai operations
        Operation::VastStart(_op) => {
            let target = variables
                .get("target")
                .cloned()
                .ok_or_else(|| AppError::command("No target host defined"))?;
            let instance_id = resolve_vast_instance_id_for_host(&target).await?;
            operations::vast::start_instance(instance_id).await?;
            Ok(None)
        }
        Operation::VastStop(_op) => {
            let target = variables
                .get("target")
                .cloned()
                .ok_or_else(|| AppError::command("No target host defined"))?;
            let instance_id = resolve_vast_instance_id_for_host(&target).await?;
            operations::vast::stop_instance(instance_id).await?;
            Ok(None)
        }
        Operation::VastDestroy(_op) => {
            let target = variables
                .get("target")
                .cloned()
                .ok_or_else(|| AppError::command("No target host defined"))?;
            let instance_id = resolve_vast_instance_id_for_host(&target).await?;
            operations::vast::destroy_instance(instance_id).await?;
            Ok(None)
        }

        // HF download operation
        Operation::HfDownload(op) => {
            let target = op
                .host_id
                .as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;

            let is_local = operations::ssh::is_local_target(&target);

            let repo_id = interpolate(&op.repo_id, variables);
            let destination = interpolate(&op.destination, variables);
            let auth_token = op
                .auth_token
                .as_ref()
                .map(|t| interpolate(t, variables))
                .filter(|t| !t.is_empty());

            let mut cmd = format!(
                "huggingface-cli download {} --local-dir {} --repo-type {}",
                repo_id,
                destination,
                match op.repo_type {
                    HfRepoType::Model => "model",
                    HfRepoType::Dataset => "dataset",
                    HfRepoType::Space => "space",
                }
            );

            if let Some(revision) = &op.revision {
                cmd.push_str(&format!(" --revision {}", interpolate(revision, variables)));
            }

            for file in &op.files {
                cmd.push_str(&format!(" --include {}", file));
            }

            // If auth token is set, prepend HF_TOKEN env var
            if let Some(token) = auth_token {
                cmd = format!("HF_TOKEN='{}' {}", token, cmd);
            }

            let empty_env = HashMap::new();
            if is_local {
                operations::ssh::execute_local_command(&cmd, None, &empty_env).await?;
            } else {
                operations::ssh::execute_command(&target, &cmd, None, &empty_env).await?;
            }
            Ok(None)
        }

        // SSH command
        Operation::SshCommand(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let command = interpolate(&op.command, variables);
            let workdir = op.workdir.as_ref().map(|w| interpolate(w, variables));
            operations::ssh::execute_command(&host_id, &command, workdir.as_deref(), &op.env).await?;
            Ok(None)
        }

        // Rsync operations
        Operation::RsyncUpload(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let local_path = interpolate(&op.local_path, variables);
            let remote_path = interpolate(&op.remote_path, variables);
            operations::sync::upload(&host_id, &local_path, &remote_path, &[], false).await?;
            Ok(None)
        }
        Operation::RsyncDownload(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let remote_path = interpolate(&op.remote_path, variables);
            let local_path = interpolate(&op.local_path, variables);
            operations::sync::download(&host_id, &remote_path, &local_path, &[]).await?;
            Ok(None)
        }

        // Tmux operations
        Operation::TmuxNew(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            let command = op.command.as_ref().map(|c| interpolate(c, variables));
            let workdir = op.workdir.as_ref().map(|w| interpolate(w, variables));
            operations::tmux::new_session(
                &host_id,
                &session_name,
                command.as_deref(),
                workdir.as_deref(),
            )
            .await?;
            Ok(None)
        }
        Operation::TmuxSend(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            let keys = interpolate(&op.keys, variables);
            operations::tmux::send_keys(&host_id, &session_name, &keys).await?;
            Ok(None)
        }
        Operation::TmuxKill(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            operations::tmux::kill_session(&host_id, &session_name).await?;
            Ok(None)
        }
        Operation::TmuxCapture(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            let output = operations::tmux::capture_pane(&host_id, &session_name, op.lines).await?;
            Ok(Some(output))
        }

        // Google Drive operations
        Operation::GdriveMount(op) => {
            let host_id = op
                .host_id
                .as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;
            let storage_id = op
                .storage_id
                .as_ref()
                .map(|s| interpolate(s, variables))
                .unwrap_or_default();
            let mount_path = if op.mount_path.is_empty() {
                "/content/drive/MyDrive".to_string()
            } else {
                interpolate(&op.mount_path, variables)
            };
            let gdrive_path = op.gdrive_path.as_ref().map(|p| interpolate(p, variables));
            let cache_mode = if op.cache_mode.is_empty() {
                "writes".to_string()
            } else {
                interpolate(&op.cache_mode, variables)
            };

            let success_msg = operations::google_drive::mount(
                &host_id,
                &storage_id,
                &mount_path,
                gdrive_path.as_deref(),
                op.vfs_cache,
                &cache_mode,
                op.background,
                progress.clone(),
            )
            .await?;
            Ok(Some(success_msg))
        }

        Operation::GdriveUnmount(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let mount_path = interpolate(&op.mount_path, variables);

            operations::google_drive::unmount(&host_id, &mount_path).await?;
            Ok(None)
        }

        Operation::Sleep(op) => {
            tokio::time::sleep(tokio::time::Duration::from_secs(op.duration_secs)).await;
            Ok(None)
        }

        Operation::WaitCondition(op) => {
            operations::conditions::wait_for(
                &op.condition,
                variables,
                op.timeout_secs,
                op.poll_interval_secs,
            )
            .await?;
            Ok(None)
        }

        Operation::Assert(op) => {
            let result = operations::conditions::evaluate(&op.condition, variables).await?;
            if !result {
                let msg = op
                    .message
                    .as_ref()
                    .map(|m| interpolate(m, variables))
                    .unwrap_or_else(|| "Assertion failed".to_string());
                return Err(AppError::command(msg));
            }
            Ok(None)
        }

        Operation::SetVar(_op) => {
            // This is handled specially - variables are updated in the execution state
            // For now, just return success
            Ok(None)
        }

        Operation::GetValue(_op) => {
            // This is also handled specially
            Ok(None)
        }

        Operation::HttpRequest(op) => {
            let url = interpolate(&op.url, variables);
            let body = op.body.as_ref().map(|b| interpolate(b, variables));

            let response = operations::http::request(
                &op.method,
                &url,
                &op.headers,
                body.as_deref(),
                op.timeout_secs,
            )
            .await?;
            Ok(Some(response))
        }

        Operation::Notify(op) => {
            let title = interpolate(&op.title, variables);
            let message = op.message.as_ref().map(|m| interpolate(m, variables));

            operations::notify::send(&title, message.as_deref(), &op.level).await?;
            Ok(None)
        }

        Operation::Group(_op) => {
            // Groups are expanded during recipe validation/loading
            // They shouldn't appear here during execution
            Ok(None)
        }
    }
}

async fn resolve_vast_instance_id_for_host(host_id: &str) -> Result<i64, AppError> {
    if host_id.trim().is_empty() {
        return Err(AppError::invalid_input("target host_id is required"));
    }
    if host_id == operations::ssh::LOCAL_TARGET {
        return Err(AppError::invalid_input(
            "Vast operations are not supported for local execution",
        ));
    }

    if let Some(vast_instance_id) = host_id
        .strip_prefix("vast:")
        .and_then(|s| s.trim().parse::<i64>().ok())
    {
        if vast_instance_id <= 0 {
            return Err(AppError::invalid_input("vast instance id must be positive"));
        }
        return Ok(vast_instance_id);
    }

    let host = host::get_host(host_id).await?;
    if host.host_type != host::HostType::Vast {
        return Err(AppError::invalid_input(format!(
            "Target host is not a Vast host: {}",
            host_id
        )));
    }
    host.vast_instance_id.ok_or_else(|| {
        AppError::invalid_input(format!(
            "Vast host is missing vast_instance_id: {}",
            host_id
        ))
    })
}

/// Compute topological order of steps
pub fn compute_execution_order(steps: &[Step]) -> Result<Vec<String>, AppError> {
    use std::collections::VecDeque;

    // Build adjacency list and in-degree count
    let mut in_degree: HashMap<&str, usize> = HashMap::new();
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();

    for step in steps {
        in_degree.entry(&step.id).or_insert(0);
        adj.entry(&step.id).or_default();

        for dep in &step.depends_on {
            adj.entry(dep.as_str()).or_default().push(&step.id);
            *in_degree.entry(&step.id).or_insert(0) += 1;
        }
    }

    // Kahn's algorithm
    let mut queue: VecDeque<&str> = in_degree
        .iter()
        .filter(|(_, &deg)| deg == 0)
        .map(|(&id, _)| id)
        .collect();

    let mut order = Vec::new();

    while let Some(node) = queue.pop_front() {
        order.push(node.to_string());

        if let Some(neighbors) = adj.get(node) {
            for &neighbor in neighbors {
                if let Some(deg) = in_degree.get_mut(neighbor) {
                    *deg -= 1;
                    if *deg == 0 {
                        queue.push_back(neighbor);
                    }
                }
            }
        }
    }

    if order.len() != steps.len() {
        return Err(AppError::command("Circular dependency detected in recipe"));
    }

    Ok(order)
}
