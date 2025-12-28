mod config;
mod error;
mod google_drive;
mod gpu;
mod host;
mod job;
mod logs;
mod recipe;
mod secrets;
mod session;
mod ssh;
mod ssh_keys;
mod storage;
mod sync;
mod terminal;
mod transfer;
mod pricing;
mod vast;

use std::path::PathBuf;

use config::{load_config, save_config as persist_config, TrainshConfig};
use error::AppError;
use host::{Host, HostConfig};
use job::{GpuRow, RemoteJobMeta, RunVastJobInput};
use logs::{LogManager, LogSnapshot, LogStreamStatus};
use session::{Session, SessionConfig, SessionMetrics};
use ssh::SshSpec;
use vast::{VastClient, VastCreateInstanceInput, VastInstance, VastOffer, VastSearchOffersInput};

use std::sync::Arc;
use tokio::sync::RwLock;
use pricing::PricingStore;
use recipe::RecipeStore;
use storage::StorageStore;
use transfer::TransferStore;

// ============================================================
// Config Commands
// ============================================================

#[tauri::command]
async fn get_config() -> Result<TrainshConfig, AppError> {
  load_config().await
}

#[tauri::command]
async fn save_config(cfg: TrainshConfig) -> Result<(), AppError> {
  persist_config(&cfg).await
}

#[tauri::command]
fn get_data_dir() -> String {
  config::get_data_dir_path()
}

#[tauri::command]
async fn migrate_legacy_data() -> Result<bool, AppError> {
  config::migrate_legacy_data().await
}

// ============================================================
// File Listing Commands (for FilePicker)
// ============================================================

/// List files in a local directory
#[tauri::command]
async fn list_local_files(path: String) -> Result<Vec<storage::FileEntry>, AppError> {
  use std::fs;
  
  let path = if path.is_empty() || path == "/" {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("/"))
  } else {
    PathBuf::from(&path)
  };
  
  let mut entries = Vec::new();
  
  if let Ok(read_dir) = fs::read_dir(&path) {
    for entry in read_dir.flatten() {
      let metadata = entry.metadata().ok();
      let is_dir = metadata.as_ref().map(|m| m.is_dir()).unwrap_or(false);
      let size = metadata.as_ref().map(|m| m.len()).unwrap_or(0);
      let modified_at = metadata
        .as_ref()
        .and_then(|m| m.modified().ok())
        .map(|t| {
          let dt: chrono::DateTime<chrono::Utc> = t.into();
          dt.to_rfc3339()
        });
      
      entries.push(storage::FileEntry {
        name: entry.file_name().to_string_lossy().to_string(),
        path: entry.path().to_string_lossy().to_string(),
        is_dir,
        size,
        modified_at,
        mime_type: None,
      });
    }
  }
  
  Ok(entries)
}

/// Create a local directory (including parents)
#[tauri::command]
async fn create_local_dir(path: String) -> Result<(), AppError> {
  if path.trim().is_empty() {
    return Err(AppError::invalid_input("Path is required"));
  }
  tokio::fs::create_dir_all(&path)
    .await
    .map_err(|e| AppError::io(format!("Failed to create directory: {}", e)))?;
  Ok(())
}

/// Open content in external editor and return updated content
#[tauri::command]
async fn open_in_external_editor(
  content: String, 
  file_extension: Option<String>
) -> Result<String, AppError> {
  use std::io::Write;
  
  let ext = file_extension.unwrap_or_else(|| "sh".to_string());
  let temp_dir = std::env::temp_dir();
  let temp_file = temp_dir.join(format!("doppio_edit_{}.{}", uuid::Uuid::new_v4().simple(), ext));
  
  // Write content to temp file
  let mut file = std::fs::File::create(&temp_file)
    .map_err(|e| AppError::io(format!("Failed to create temp file: {}", e)))?;
  file.write_all(content.as_bytes())
    .map_err(|e| AppError::io(format!("Failed to write temp file: {}", e)))?;
  drop(file);
  
  // Get the editor command
  let editor = std::env::var("EDITOR")
    .or_else(|_| std::env::var("VISUAL"))
    .unwrap_or_else(|_| {
      if cfg!(target_os = "macos") {
        "open -t -W".to_string()
      } else if cfg!(target_os = "windows") {
        "notepad".to_string()
      } else {
        "xdg-open".to_string()
      }
    });
  
  // Parse editor command and args
  let parts: Vec<&str> = editor.split_whitespace().collect();
  let (cmd, args) = parts.split_first()
    .ok_or_else(|| AppError::command("Invalid editor command"))?;
  
  // Open editor and wait for it to close
  let mut command = std::process::Command::new(cmd);
  command.args(args);
  command.arg(&temp_file);
  
  let status = command.status()
    .map_err(|e| AppError::command(format!("Failed to open editor: {}", e)))?;
  
  if !status.success() {
    // Editor might have returned non-zero but file could still be edited
    // Continue to read the file
  }
  
  // Read the updated content
  let updated_content = tokio::fs::read_to_string(&temp_file).await
    .map_err(|e| AppError::io(format!("Failed to read updated file: {}", e)))?;
  
  // Clean up temp file
  let _ = tokio::fs::remove_file(&temp_file).await;
  
  Ok(updated_content)
}

/// List files on a remote host via SSH
#[tauri::command]
async fn list_host_files(host_id: String, path: String) -> Result<Vec<storage::FileEntry>, AppError> {
  let host = host::get_host(&host_id).await?;
  let ssh = host.ssh.as_ref()
    .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
  
  let path = if path.is_empty() { "~".to_string() } else { path };
  
  // Use ls -la to get file information
  // Note: --time-style combines date+time into one field, so we read it as 'datetime'
  // For symlinks, the output is "name -> target", so we only take the first word of 'name_and_rest'
  let cmd = format!(
    r#"cd {} 2>/dev/null && ls -la --time-style='+%Y-%m-%dT%H:%M:%S' 2>/dev/null | tail -n +2 | while read perms links owner group size datetime name_and_rest; do
      name=$(echo "$name_and_rest" | awk '{{print $1}}')
      if [ -n "$name" ] && [ "$name" != "." ] && [ "$name" != ".." ]; then
        is_dir="false"
        if [ "${{perms:0:1}}" = "d" ]; then is_dir="true"; fi
        echo "$is_dir|$size|$datetime|$name"
      fi
    done"#,
    path
  );
  
  let mut ssh_cmd = tokio::process::Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    ssh_cmd.arg(arg);
  }
  ssh_cmd.arg(ssh.target());
  ssh_cmd.arg(&cmd);
  
  let output = ssh_cmd.output().await
    .map_err(|e| AppError::command(format!("Failed to execute SSH: {e}")))?;
  
  let stdout = String::from_utf8_lossy(&output.stdout);
  
  let base_path = if path == "~" {
    "/home".to_string() // Approximate, will be resolved by the shell
  } else {
    path.clone()
  };
  
  let mut entries = Vec::new();
  for line in stdout.lines() {
    let parts: Vec<&str> = line.splitn(4, '|').collect();
    if parts.len() == 4 {
      let is_dir = parts[0] == "true";
      let size: u64 = parts[1].parse().unwrap_or(0);
      let modified_at = Some(parts[2].to_string());
      let name = parts[3].to_string();
      let full_path = format!("{}/{}", base_path.trim_end_matches('/'), name);
      
      entries.push(storage::FileEntry {
        name,
        path: full_path,
        is_dir,
        size,
        modified_at,
        mime_type: None,
      });
    }
  }
  
  Ok(entries)
}

/// Create a directory on a remote host via SSH
#[tauri::command]
async fn create_host_dir(host_id: String, path: String) -> Result<(), AppError> {
  if path.trim().is_empty() {
    return Err(AppError::invalid_input("Path is required"));
  }

  let host = host::get_host(&host_id).await?;
  let ssh = host.ssh.as_ref()
    .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;

  let escaped_path = shell_escape::unix::escape(path.into()).to_string();
  let cmd = format!("mkdir -p {}", escaped_path);

  let mut ssh_cmd = tokio::process::Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    ssh_cmd.arg(arg);
  }
  ssh_cmd.arg(ssh.target());
  ssh_cmd.arg(&cmd);

  let output = ssh_cmd.output().await
    .map_err(|e| AppError::command(format!("Failed to execute SSH: {e}")))?;

  if !output.status.success() {
    let stderr = String::from_utf8_lossy(&output.stderr);
    return Err(AppError::command(format!("Failed to create remote directory: {}", stderr.trim())));
  }

  Ok(())
}

// ============================================================
// SSH Key Commands
// ============================================================

#[tauri::command]
async fn ssh_key_candidates() -> Result<Vec<String>, AppError> {
  let home = dirs::home_dir().ok_or_else(|| AppError::io("Cannot resolve home directory"))?;
  let ssh_dir = home.join(".ssh");
  if !ssh_dir.exists() {
    return Ok(vec![]);
  }

  let mut out: Vec<String> = vec![];
  let mut entries = tokio::fs::read_dir(&ssh_dir).await?;
  while let Some(entry) = entries.next_entry().await? {
    let file_type = entry.file_type().await?;
    if !file_type.is_file() {
      continue;
    }
    let path = entry.path();
    let file_name = match path.file_name().and_then(|s| s.to_str()) {
      Some(name) => name,
      None => continue,
    };
    if file_name.is_empty() {
      continue;
    }
    if file_name == "config"
      || file_name == "known_hosts"
      || file_name == "known_hosts.old"
      || file_name == "authorized_keys"
    {
      continue;
    }
    if let Some(ext) = path.extension() {
      if ext == "pub" {
        continue;
      }
    }
    out.push(path.to_string_lossy().to_string());
  }
  out.sort();
  Ok(out)
}

#[tauri::command]
#[allow(non_snake_case)]
async fn ssh_public_key(privateKeyPath: String) -> Result<String, AppError> {
  ssh_keys::read_public_key(privateKeyPath).await
}

#[tauri::command]
#[allow(non_snake_case)]
async fn ssh_private_key(privateKeyPath: String) -> Result<String, AppError> {
  ssh_keys::read_private_key(privateKeyPath).await
}

#[tauri::command]
async fn ssh_generate_key(path: String, comment: Option<String>) -> Result<ssh_keys::SshKeyInfo, AppError> {
  ssh_keys::generate_key(path, comment).await
}

// ============================================================
// Host Commands
// ============================================================

#[tauri::command]
async fn host_list() -> Result<Vec<Host>, AppError> {
  host::list_hosts().await
}

#[tauri::command]
async fn host_get(id: String) -> Result<Host, AppError> {
  host::get_host(&id).await
}

#[tauri::command]
async fn host_add(config: HostConfig) -> Result<Host, AppError> {
  host::add_host(config).await
}

#[tauri::command]
async fn host_update(id: String, config: serde_json::Value) -> Result<Host, AppError> {
  host::update_host(&id, config).await
}

#[tauri::command]
async fn host_remove(id: String) -> Result<(), AppError> {
  host::delete_host(&id).await
}

#[tauri::command]
async fn host_test_connection(id: String) -> Result<serde_json::Value, AppError> {
  let (success, message) = host::test_connection(&id).await?;
  Ok(serde_json::json!({ "success": success, "message": message }))
}

#[tauri::command]
async fn host_refresh(id: String) -> Result<Host, AppError> {
  host::refresh_host(&id).await
}

#[tauri::command]
async fn host_list_tmux_sessions(id: String) -> Result<Vec<host::RemoteTmuxSession>, AppError> {
  host::list_tmux_sessions(&id).await
}

// ============================================================
// Session Commands
// ============================================================

#[tauri::command]
async fn session_list() -> Result<Vec<Session>, AppError> {
  session::list_sessions().await
}

#[tauri::command]
async fn session_get(id: String) -> Result<Session, AppError> {
  session::get_session(&id).await
}

#[tauri::command]
async fn session_create(config: SessionConfig) -> Result<Session, AppError> {
  session::create_session(config).await
}

#[tauri::command]
async fn session_delete(id: String) -> Result<(), AppError> {
  session::delete_session(&id).await
}

#[tauri::command]
async fn session_sync(id: String, app: tauri::AppHandle) -> Result<Session, AppError> {
  session::sync_session(&id, Some(&app)).await
}

#[tauri::command]
async fn session_run(id: String) -> Result<Session, AppError> {
  session::run_session(&id).await
}

#[tauri::command]
async fn session_stop(id: String) -> Result<Session, AppError> {
  session::stop_session(&id).await
}

#[tauri::command]
async fn session_get_metrics(id: String) -> Result<SessionMetrics, AppError> {
  session::get_session_metrics(&id).await
}

#[tauri::command]
async fn session_get_logs(id: String, lines: Option<usize>) -> Result<Vec<String>, AppError> {
  session::get_session_logs(&id, lines.unwrap_or(200)).await
}

#[tauri::command]
async fn session_download(id: String, local_dir: String, app: tauri::AppHandle) -> Result<(), AppError> {
  session::download_session_outputs(&id, &local_dir, Some(&app)).await
}

// ============================================================
// Log Commands
// ============================================================

#[tauri::command]
async fn log_start_stream(
  session_id: String,
  tmux_session: String,
  poll_interval_ms: Option<u64>,
  log_manager: tauri::State<'_, LogManager>,
  app: tauri::AppHandle,
) -> Result<(), AppError> {
  // Get session to find host SSH config
  let session = session::get_session(&session_id).await?;
  let host = host::get_host(&session.host_id).await?;
  let ssh = host.ssh.ok_or_else(|| AppError::invalid_input("Host has no SSH config"))?;

  log_manager.start_stream(
    session_id,
    ssh,
    tmux_session,
    app,
    poll_interval_ms.unwrap_or(1000), // Default 1 second polling
  ).await
}

#[tauri::command]
async fn log_stop_stream(
  session_id: String,
  log_manager: tauri::State<'_, LogManager>,
) -> Result<(), AppError> {
  log_manager.stop_stream(&session_id).await
}

#[tauri::command]
async fn log_stream_status(
  session_id: String,
  log_manager: tauri::State<'_, LogManager>,
) -> Result<LogStreamStatus, AppError> {
  Ok(log_manager.get_status(&session_id).await)
}

#[tauri::command]
async fn log_capture_now(
  session_id: String,
  tmux_session: String,
  tail_lines: Option<i64>,
) -> Result<LogSnapshot, AppError> {
  let session = session::get_session(&session_id).await?;
  let host = host::get_host(&session.host_id).await?;
  let ssh = host.ssh.ok_or_else(|| AppError::invalid_input("Host has no SSH config"))?;

  logs::capture_tmux_pane(&ssh, &tmux_session, tail_lines.map(|n| -n.abs()), true).await
}

#[tauri::command]
async fn log_read_local(session_id: String) -> Result<Vec<String>, AppError> {
  logs::read_local_logs(&session_id)
}

#[tauri::command]
async fn log_clear_local(session_id: String) -> Result<(), AppError> {
  logs::clear_local_logs(&session_id)
}

// ============================================================
// Vast.ai Commands
// ============================================================

async fn resolve_vast_instance(instance_id: i64) -> Result<(TrainshConfig, VastClient, VastInstance), AppError> {
  if instance_id <= 0 {
    return Err(AppError::invalid_input("instance_id must be positive"));
  }
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  let insts = client.list_instances().await?;
  let inst = insts
    .into_iter()
    .find(|x| x.id == instance_id)
    .ok_or_else(|| AppError::not_found(format!("Vast instance {instance_id} not found")))?;
  Ok((cfg, client, inst))
}

#[tauri::command]
async fn vast_list_instances() -> Result<Vec<VastInstance>, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.list_instances().await
}

#[tauri::command]
async fn vast_test_connection(instance_id: i64) -> Result<serde_json::Value, AppError> {
  let (cfg, client, inst) = resolve_vast_instance(instance_id).await?;
  client.attach_ssh_key(instance_id).await?;
  let ssh_host = inst
    .ssh_host
    .ok_or_else(|| AppError::invalid_input("Instance is not running or SSH host unavailable"))?;
  let ssh_port = inst.ssh_port.unwrap_or(22);
  let ssh = SshSpec {
    host: ssh_host,
    port: ssh_port,
    user: "root".to_string(),
    key_path: cfg.vast.ssh_key_path.clone(),
    extra_args: vec![],
  };
  ssh.validate()?;

  let mut cmd = tokio::process::Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg("echo ok");

  let output = cmd.output().await?;
  if output.status.success() {
    Ok(serde_json::json!({ "success": true, "message": "Connection successful" }))
  } else {
    let stderr = String::from_utf8_lossy(&output.stderr);
    let msg = stderr.trim();
    if msg.contains("Permission denied") {
      Ok(serde_json::json!({ "success": false, "message": "Connection failed: Permission denied. Check your SSH key." }))
    } else if msg.contains("Connection refused") {
      Ok(serde_json::json!({ "success": false, "message": "Connection failed: Connection refused. Is the host running?" }))
    } else if msg.contains("Connection timed out") || msg.contains("timed out") {
      Ok(serde_json::json!({ "success": false, "message": "Connection failed: Timed out. Check your network connection." }))
    } else {
      Ok(serde_json::json!({ "success": false, "message": format!("Connection failed: {msg}") }))
    }
  }
}

#[tauri::command]
async fn vast_attach_ssh_key(instance_id: i64) -> Result<(), AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.attach_ssh_key(instance_id).await
}

#[tauri::command]
async fn vast_fetch_system_info(instance_id: i64) -> Result<host::SystemInfo, AppError> {
  let (cfg, client, inst) = resolve_vast_instance(instance_id).await?;
  client.attach_ssh_key(instance_id).await?;
  let ssh_host = inst
    .ssh_host
    .ok_or_else(|| AppError::invalid_input("Instance is not running or SSH host unavailable"))?;
  let ssh_port = inst.ssh_port.unwrap_or(22);
  let ssh = SshSpec {
    host: ssh_host,
    port: ssh_port,
    user: "root".to_string(),
    key_path: cfg.vast.ssh_key_path.clone(),
    extra_args: vec![],
  };
  host::fetch_system_info(&ssh, host::HostType::Vast).await
}

#[tauri::command]
async fn vast_start_instance(instance_id: i64) -> Result<VastInstance, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.start_instance(instance_id).await?;
  let insts = client.list_instances().await?;
  insts
    .into_iter()
    .find(|x| x.id == instance_id)
    .ok_or_else(|| AppError::vast_api(format!("Instance not found after start: {instance_id}")))
}

#[tauri::command]
async fn vast_stop_instance(instance_id: i64) -> Result<VastInstance, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.stop_instance(instance_id).await?;
  let insts = client.list_instances().await?;
  insts
    .into_iter()
    .find(|x| x.id == instance_id)
    .ok_or_else(|| AppError::vast_api(format!("Instance not found after stop: {instance_id}")))
}

#[tauri::command]
async fn vast_label_instance(instance_id: i64, label: String) -> Result<VastInstance, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.label_instance(instance_id, label).await?;
  let insts = client.list_instances().await?;
  insts
    .into_iter()
    .find(|x| x.id == instance_id)
    .ok_or_else(|| AppError::vast_api(format!("Instance not found after label: {instance_id}")))
}

#[tauri::command]
async fn vast_destroy_instance(instance_id: i64) -> Result<(), AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.destroy_instance(instance_id).await
}

#[tauri::command]
async fn vast_search_offers(input: VastSearchOffersInput) -> Result<Vec<VastOffer>, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.search_offers(input).await
}

#[tauri::command]
async fn vast_create_instance(input: VastCreateInstanceInput) -> Result<i64, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  client.create_instance(input).await
}

#[tauri::command]
async fn vast_run_job(input: RunVastJobInput) -> Result<RemoteJobMeta, AppError> {
  let cfg = load_config().await?;
  let client = VastClient::from_cfg(&cfg)?;
  let insts = client.list_instances().await?;
  let inst = insts
    .into_iter()
    .find(|x| x.id == input.instance_id)
    .ok_or_else(|| AppError::invalid_input(format!("Instance not found: {}", input.instance_id)))?;

  let host = inst
    .ssh_host
    .clone()
    .unwrap_or_default()
    .trim()
    .to_string();
  let port = inst.ssh_port.unwrap_or(0);
  if host.is_empty() || port <= 0 {
    return Err(AppError::invalid_input(
      "Instance does not have SSH info yet (is it running and provisioned?)",
    ));
  }

  let ssh = SshSpec {
    host,
    port,
    user: cfg.vast.ssh_user.clone(),
    key_path: cfg.vast.ssh_key_path.clone(),
    extra_args: vec![],
  };

  job::run_remote_job(input, ssh, cfg.colab.hf_home.clone()).await
}

// ============================================================
// Job Commands (Legacy)
// ============================================================

#[tauri::command]
async fn job_tail_logs(ssh: SshSpec, log_path: String, lines: usize) -> Result<Vec<String>, AppError> {
  job::tail_logs(ssh, log_path, lines).await
}

#[tauri::command]
async fn job_fetch_gpu(ssh: SshSpec) -> Result<Vec<GpuRow>, AppError> {
  job::fetch_gpu(ssh).await
}

#[tauri::command]
async fn job_get_exit_code(ssh: SshSpec, job_dir: String) -> Result<Option<i32>, AppError> {
  job::get_exit_code(ssh, job_dir).await
}

#[tauri::command]
async fn download_remote_dir(ssh: SshSpec, remote_dir: String, local_dir: String, delete: bool) -> Result<(), AppError> {
  job::download_dir(ssh, remote_dir, local_dir, delete).await
}

#[tauri::command]
async fn job_list_local() -> Result<Vec<RemoteJobMeta>, AppError> {
  job::list_local_jobs().await
}

// ============================================================
// Main
// ============================================================

fn main() {
  // Initialize rclone
  sync::init_rclone();
  
  // Get data directory for storage persistence
  let data_dir = PathBuf::from(config::get_data_dir_path());
  std::fs::create_dir_all(&data_dir).expect("Failed to create data directory");
  
  tauri::Builder::default()
    .plugin(tauri_plugin_clipboard_manager::init())
    .plugin(tauri_plugin_shell::init())
    .manage(terminal::TerminalManager::default())
    .manage(LogManager::default())
    .manage(Arc::new(StorageStore::new(&data_dir)))
    .manage(Arc::new(TransferStore::new(&data_dir)))
    .manage(Arc::new(PricingStore::new(&data_dir)))
    .manage(Arc::new(RwLock::new(RecipeStore::new(&data_dir))))
    .invoke_handler(tauri::generate_handler![
      // Config
      get_config,
      save_config,
      get_data_dir,
      migrate_legacy_data,
      // File Listing (for FilePicker)
      list_local_files,
      list_host_files,
      create_local_dir,
      create_host_dir,
      // External Editor
      open_in_external_editor,
      // SSH Keys
      ssh_key_candidates,
      ssh_public_key,
      ssh_private_key,
      ssh_generate_key,
      // Hosts
      host_list,
      host_get,
      host_add,
      host_update,
      host_remove,
      host_test_connection,
      host_refresh,
      host_list_tmux_sessions,
      // Sessions
      session_list,
      session_get,
      session_create,
      session_delete,
      session_sync,
      session_run,
      session_stop,
      session_get_metrics,
      session_get_logs,
      session_download,
      // Logs
      log_start_stream,
      log_stop_stream,
      log_stream_status,
      log_capture_now,
      log_read_local,
      log_clear_local,
      // Vast.ai
      vast_list_instances,
      vast_attach_ssh_key,
      vast_test_connection,
      vast_fetch_system_info,
      vast_start_instance,
      vast_stop_instance,
      vast_label_instance,
      vast_destroy_instance,
      vast_search_offers,
      vast_create_instance,
      vast_run_job,
      // Jobs (legacy)
      job_tail_logs,
      job_fetch_gpu,
      job_get_exit_code,
      download_remote_dir,
      job_list_local,
      // Terminal
      terminal::term_list,
      terminal::term_open_ssh_tmux,
      terminal::term_open_instance_tmux,
      terminal::term_open_local,
      terminal::term_write,
      terminal::term_resize,
      terminal::term_close,
      terminal::term_open_native_ssh,
      terminal::term_open_host,
      terminal::term_history_info,
      terminal::term_history_range,
      terminal::term_history_tail,
      terminal::term_history_steps,
      // Storage
      storage::storage_list,
      storage::storage_get,
      storage::storage_create,
      storage::storage_update,
      storage::storage_delete,
      storage::storage_test,
      storage::storage_list_files,
      storage::storage_mkdir,
      storage::storage_delete_file,
      storage::storage_get_usage,
      storage::storage_get_r2_usages,
      // Transfer
      transfer::transfer_list,
      transfer::transfer_get,
      transfer::transfer_create,
      transfer::transfer_cancel,
      transfer::transfer_clear_completed,
      // Pricing (unified)
      pricing::pricing_get,
      pricing::pricing_fetch_rates,
      pricing::pricing_update_display_currency,
      pricing::pricing_reset,
      // Colab Pricing
      pricing::pricing_colab_update_subscription,
      pricing::pricing_colab_update_gpu,
      pricing::pricing_colab_calculate,
      // Host Pricing (Vast.ai, Custom)
      pricing::pricing_vast_update_rates,
      pricing::pricing_host_set,
      pricing::pricing_host_remove,
      pricing::pricing_host_get,
      pricing::pricing_host_calculate,
      pricing::pricing_host_calculate_all,
      pricing::pricing_sync_vast_instance,
      pricing::pricing_get_r2_cache,
      pricing::pricing_save_r2_cache,
      // Recipe
      recipe::recipe_list,
      recipe::recipe_get,
      recipe::recipe_save,
      recipe::recipe_delete,
      recipe::recipe_validate,
      recipe::recipe_create,
      recipe::recipe_run,
      recipe::recipe_pause,
      recipe::recipe_resume,
      recipe::recipe_cancel,
      recipe::recipe_retry_step,
      recipe::recipe_skip_step,
      recipe::recipe_get_execution,
      recipe::recipe_list_executions,
      recipe::recipe_import,
      recipe::recipe_export,
      recipe::recipe_duplicate,
      // Recipe Interactive Execution
      recipe::recipe_run_interactive,
      recipe::recipe_interactive_send,
      recipe::recipe_interactive_interrupt,
      recipe::recipe_interactive_lock,
      recipe::recipe_interactive_get,
      recipe::recipe_interactive_list,
      recipe::recipe_interactive_pause,
      recipe::recipe_interactive_resume,
      recipe::recipe_interactive_cancel,
      recipe::recipe_interactive_mark_complete,
      recipe::recipe_interactive_exec_command,
      // Google Drive
      google_drive::gdrive_generate_auth_url,
      google_drive::gdrive_exchange_code,
      google_drive::gdrive_verify_token,
      google_drive::gdrive_test_connection,
      // Secrets
      secrets::secret_list,
      secrets::secret_get,
      secrets::secret_upsert,
      secrets::secret_delete,
      secrets::secret_check_exists,
      secrets::secret_suggestions,
      secrets::secret_validate_refs
    ])
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
