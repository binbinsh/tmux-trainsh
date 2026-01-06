//! Recipe execution helpers
//!
//! Shared helpers for interactive recipe execution (DAG ordering and step execution).

use std::collections::HashMap;
use std::path::Path;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use super::operations;
use super::parser::interpolate;
use super::types::*;
use crate::error::AppError;
use crate::host;
use tokio::io::AsyncWriteExt;

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
        Operation::Transfer(op) => operations::transfer::execute(op, variables, progress).await,

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
            let destination = normalize_destination_path(&interpolate(&op.destination, variables))?;
            let branch = op.branch.as_ref().map(|b| interpolate(b, variables));
            let depth = op.depth;
            // Interpolate auth_token and filter out empty strings
            let auth_token = op
                .auth_token
                .as_ref()
                .map(|t| interpolate(t, variables))
                .filter(|t| !t.is_empty());

            let mut repo_url_for_clone = repo_url.clone();
            if auth_token.is_some()
                && !repo_url_for_clone.trim().starts_with("https://")
                && looks_like_ssh_git_url(&repo_url_for_clone)
            {
                if let Some(https_url) = ssh_git_url_to_https_url(&repo_url_for_clone) {
                    if let Some(cb) = progress.as_ref() {
                        cb("Auth token detected; rewriting SSH repo URL to HTTPS.");
                    }
                    repo_url_for_clone = https_url;
                }
            }
            let use_ssh = looks_like_ssh_git_url(&repo_url_for_clone);

            // First, add GitHub/GitLab/Bitbucket host keys to known_hosts to avoid "Host key verification failed"
            let empty_env = HashMap::new();

            // If destination exists and is not an empty directory, back it up before cloning.
            let should_backup = if is_local {
                match tokio::fs::metadata(&destination).await {
                    Ok(meta) => {
                        if meta.is_dir() {
                            let mut rd = tokio::fs::read_dir(&destination).await?;
                            rd.next_entry().await?.is_some()
                        } else {
                            true
                        }
                    }
                    Err(_) => false,
                }
            } else {
                let dest = shell_escape_arg(&destination);
                let check_cmd = format!(
                    "if [ -e {dest} ] && ( [ ! -d {dest} ] || [ -n \"$(find {dest} -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)\" ] ); then exit 0; else exit 1; fi"
                );
                operations::ssh::command_succeeds(&target, &check_cmd).await?
            };

            if should_backup {
                let ts = chrono::Utc::now().format("%Y%m%d-%H%M%S").to_string();
                let suffix = uuid::Uuid::new_v4()
                    .to_string()
                    .split('-')
                    .next()
                    .unwrap_or("bak")
                    .to_string();
                let backup_path = format!("{destination}.bak.{ts}-{suffix}");
                if let Some(cb) = progress.as_ref() {
                    cb(&format!(
                        "Destination exists; moving it to backup: {backup_path}"
                    ));
                }

                if is_local {
                    tokio::fs::rename(&destination, &backup_path).await?;
                } else {
                    let mv_cmd = format!(
                        "mv {} {}",
                        shell_escape_arg(&destination),
                        shell_escape_arg(&backup_path)
                    );
                    let _ = operations::ssh::execute_command(&target, &mv_cmd, None, &empty_env).await?;
                }
            }

            // Ensure destination parent directory exists.
            if let Some(parent) = std::path::Path::new(&destination).parent() {
                if !parent.as_os_str().is_empty() {
                    let parent_str = parent.to_string_lossy().to_string();
                    if is_local {
                        tokio::fs::create_dir_all(parent).await?;
                    } else {
                        let mkdir_cmd =
                            format!("mkdir -p {}", shell_escape_arg(parent_str.as_str()));
                        let _ =
                            operations::ssh::execute_command(&target, &mkdir_cmd, None, &empty_env)
                                .await?;
                    }
                }
            }

            if use_ssh {
                if let Some(cb) = progress.as_ref() {
                    cb("Updating ~/.ssh/known_hosts for git providers…");
                }
                let add_host_keys = r#"mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keyscan -t ed25519,rsa github.com gitlab.com bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null"#;
                if is_local {
                    operations::ssh::execute_local_command(add_host_keys, None, &empty_env).await?;
                } else {
                    operations::ssh::execute_command(&target, add_host_keys, None, &empty_env).await?;
                }
            }

            // Use auth token for HTTPS (preferred for private repos).
            // Otherwise, for SSH URLs, provision the configured private key on the target host and use it via GIT_SSH_COMMAND.
            let mut clone_env: HashMap<String, String> = HashMap::new();
            clone_env.insert("GIT_TERMINAL_PROMPT".to_string(), "0".to_string());
            if !is_local {
                clone_env.insert("LC_ALL".to_string(), "C.UTF-8".to_string());
            }
            let mut cleanup_remote_key: Option<String> = None;

            if use_ssh {
                if is_local {
                    let cfg = crate::config::load_config().await?;
                    if let Some(key_input) = cfg
                        .vast
                        .ssh_key_path
                        .clone()
                        .filter(|s| !s.trim().is_empty())
                    {
                        let key_path =
                            crate::ssh_keys::materialize_private_key_path(&key_input).await?;
                        let key_path = key_path.to_string_lossy().to_string();
                        clone_env.insert(
                            "GIT_SSH_COMMAND".to_string(),
                            format!(
                                "ssh -i {} -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
                                shell_escape_arg(&key_path),
                            ),
                        );
                    }
                } else {
                    let ssh =
                        crate::host::resolve_ssh_spec_with_retry(&target, Duration::from_secs(180))
                            .await?;
                    let local_key_path = ssh
                        .key_path
                        .clone()
                        .filter(|p| !p.trim().is_empty())
                        .ok_or_else(|| {
                            AppError::invalid_input("Missing SSH key path for git clone")
                        })?;

                    let remote_key_path = format!("/tmp/doppio_git_key_{}", uuid::Uuid::new_v4());

                    if let Some(cb) = progress.as_ref() {
                        cb("Uploading identity file to target host…");
                    }
                    upload_file_via_ssh(&ssh, Path::new(&local_key_path), &remote_key_path).await?;

                    clone_env.insert(
                        "GIT_SSH_COMMAND".to_string(),
                        format!(
                            "ssh -i {} -o IdentitiesOnly=yes -o PreferredAuthentications=publickey -o PasswordAuthentication=no -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
                            shell_escape_arg(&remote_key_path),
                        ),
                    );
                    cleanup_remote_key = Some(remote_key_path);
                }
            }

            // Now clone
            let clone_cmd = if let Some(token) = auth_token {
                // Insert token into URL for HTTP auth
                // Example: https://github.com/owner/repo.git -> https://x-access-token:TOKEN@github.com/owner/repo.git
                let auth_url = if repo_url_for_clone.trim().starts_with("https://") {
                    insert_auth_token_into_https_url(&repo_url_for_clone, &token)
                } else {
                    repo_url_for_clone.clone()
                };
                build_git_clone_command(&auth_url, &destination, branch.as_deref(), depth)
            } else {
                build_git_clone_command(&repo_url_for_clone, &destination, branch.as_deref(), depth)
            };

            if let Some(cb) = progress.as_ref() {
                cb("Running git clone…");
            }
            if is_local {
                return operations::ssh::execute_local_command(&clone_cmd, None, &clone_env).await;
            }

            let result =
                operations::ssh::execute_command(&target, &clone_cmd, None, &clone_env).await;
            if let Some(remote_key_path) = cleanup_remote_key {
                let _ = operations::ssh::execute_command(
                    &target,
                    &format!("rm -f {}", remote_key_path),
                    None,
                    &empty_env,
                )
                .await;
            }
            result
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
            operations::ssh::execute_command(&host_id, &command, workdir.as_deref(), &op.env)
                .await?;
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

fn looks_like_ssh_git_url(url: &str) -> bool {
    let u = url.trim();
    if u.is_empty() {
        return false;
    }
    u.starts_with("git@")
        || u.starts_with("ssh://")
        || u.starts_with("git+ssh://")
        || u.starts_with("ssh+git://")
}

fn ssh_git_url_to_https_url(url: &str) -> Option<String> {
    let u = url.trim();
    if u.is_empty() {
        return None;
    }

    // SCP-like URL: git@github.com:owner/repo.git
    if let Some(rest) = u.strip_prefix("git@") {
        let (host, path) = rest.split_once(':')?;
        let host = host.trim();
        let path = path.trim().trim_start_matches('/');
        if host.is_empty() || path.is_empty() {
            return None;
        }
        return Some(format!("https://{host}/{path}"));
    }

    // URL-like SSH schemes: ssh://git@github.com/owner/repo.git
    let mut rest = None;
    for scheme in ["ssh://", "git+ssh://", "ssh+git://"] {
        if let Some(r) = u.strip_prefix(scheme) {
            rest = Some(r);
            break;
        }
    }
    let rest = rest?;

    let (authority, path) = rest.split_once('/')?;
    let authority = authority.trim();
    let path = path.trim().trim_start_matches('/');
    if authority.is_empty() || path.is_empty() {
        return None;
    }

    let host_part = authority
        .rsplit_once('@')
        .map(|(_, h)| h)
        .unwrap_or(authority);
    let host_part = host_part
        .split_once(':')
        .map(|(h, _)| h)
        .unwrap_or(host_part)
        .trim();
    if host_part.is_empty() {
        return None;
    }

    Some(format!("https://{host_part}/{path}"))
}

fn git_http_username_for_url(url: &str) -> &'static str {
    let rest = url.trim().strip_prefix("https://").unwrap_or("");
    let authority = rest.split('/').next().unwrap_or("");
    let authority = authority.rsplit_once('@').map(|(_, h)| h).unwrap_or(authority);
    let host = authority.split(':').next().unwrap_or(authority).trim().to_ascii_lowercase();
    match host.as_str() {
        "github.com" => "x-access-token",
        "gitlab.com" => "oauth2",
        "bitbucket.org" => "x-token-auth",
        _ => "token",
    }
}

fn insert_auth_token_into_https_url(repo_url: &str, token: &str) -> String {
    let user = git_http_username_for_url(repo_url);
    let token = urlencoding::encode(token);
    repo_url.replacen("https://", &format!("https://{user}:{token}@"), 1)
}

fn build_git_clone_command(
    repo_url: &str,
    destination: &str,
    branch: Option<&str>,
    depth: Option<u32>,
) -> String {
    let mut args: Vec<String> = vec!["git".to_string(), "clone".to_string(), "--progress".to_string()];
    if let Some(depth) = depth {
        if depth > 0 {
            args.push("--depth".to_string());
            args.push(depth.to_string());
        }
    }
    if let Some(branch) = branch.map(str::trim).filter(|b| !b.is_empty()) {
        args.push("-b".to_string());
        args.push(branch.to_string());
    }
    args.push(repo_url.to_string());
    args.push(destination.to_string());

    args.into_iter()
        .map(|s| shell_escape_arg(&s))
        .collect::<Vec<_>>()
        .join(" ")
}

fn normalize_destination_path(destination: &str) -> Result<String, AppError> {
    let mut dest = destination.trim().to_string();
    if dest.is_empty() {
        return Err(AppError::invalid_input("Destination path is required"));
    }
    while dest.ends_with('/') && dest.len() > 1 {
        dest.pop();
    }
    if dest == "/" || dest == "." || dest == ".." {
        return Err(AppError::invalid_input("Invalid destination path"));
    }
    Ok(dest)
}

fn shell_escape_arg(s: &str) -> String {
    shell_escape::unix::escape(s.into()).to_string()
}

async fn upload_file_via_ssh(
    ssh: &crate::ssh::SshSpec,
    local_path: &Path,
    remote_path: &str,
) -> Result<(), AppError> {
    crate::ssh::ensure_bin("ssh").await?;
    ssh.validate()?;
    if !local_path.exists() {
        return Err(AppError::invalid_input(format!(
            "Local SSH key not found: {}",
            local_path.display()
        )));
    }

    let bytes = tokio::fs::read(local_path).await?;

    let remote = shell_escape_arg(remote_path);
    let cmd_str = format!("umask 077; cat > {remote} && chmod 600 {remote}");

    let mut c = tokio::process::Command::new("ssh");
    c.args(ssh.common_ssh_options());
    c.arg(ssh.target());
    c.arg(cmd_str);
    c.stdin(Stdio::piped());

    let mut child = c
        .spawn()
        .map_err(|e| AppError::command(format!("Failed to execute SSH: {e}")))?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or_else(|| AppError::command("Failed to open stdin for SSH upload"))?;
    stdin.write_all(&bytes).await?;
    stdin.shutdown().await?;

    let out = child
        .wait_with_output()
        .await
        .map_err(|e| AppError::command(format!("Failed to wait for SSH upload: {e}")))?;

    if !out.status.success() {
        let stdout = String::from_utf8_lossy(&out.stdout).to_string();
        let stderr = String::from_utf8_lossy(&out.stderr).to_string();
        return Err(AppError::command(format!(
            "SSH upload failed (code={:?}): {stdout}{stderr}",
            out.status.code()
        )));
    }
    Ok(())
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
