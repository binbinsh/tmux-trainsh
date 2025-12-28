use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tokio::process::Command;
use uuid::Uuid;

use crate::config::{doppio_data_dir, load_config};
use crate::error::AppError;
use crate::gpu::lookup_gpu_capability;
use crate::ssh::SshSpec;

// Re-export GPU types for other modules that import from host
pub use crate::gpu::GpuInfo;

// ============================================================
// Types
// ============================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostType {
  Vast,
  Colab,
  Custom,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostStatus {
  Online,
  Offline,
  Connecting,
  Error,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SystemInfo {
  pub cpu_model: Option<String>,
  pub cpu_cores: Option<i32>,
  pub memory_total_gb: Option<f64>,
  #[serde(default)]
  pub memory_used_gb: Option<f64>,
  pub memory_available_gb: Option<f64>,
  #[serde(default)]
  pub disks: Vec<DiskInfo>,
  // Legacy fields for backward compatibility (will be removed in future)
  #[serde(default, skip_serializing)]
  pub disk_total_gb: Option<f64>,
  #[serde(default, skip_serializing)]
  pub disk_available_gb: Option<f64>,
  #[serde(default)]
  pub gpu_list: Vec<GpuInfo>,
  pub os: Option<String>,
  pub hostname: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiskInfo {
  pub mount_point: String,
  pub total_gb: f64,
  pub used_gb: f64,
  pub available_gb: f64,
}


#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Host {
  pub id: String,
  pub name: String,
  #[serde(rename = "type")]
  pub host_type: HostType,
  pub status: HostStatus,
  pub ssh: Option<SshSpec>,
  // Vast specific
  pub vast_instance_id: Option<i64>,
  // Colab specific
  pub cloudflared_hostname: Option<String>,
  // Environment variables to set on connection
  #[serde(default)]
  pub env_vars: std::collections::HashMap<String, String>,
  // System information
  pub gpu_name: Option<String>,
  pub num_gpus: Option<i32>,
  #[serde(default)]
  pub system_info: Option<SystemInfo>,
  pub created_at: String,
  pub last_seen_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HostConfig {
  pub name: String,
  #[serde(rename = "type")]
  pub host_type: HostType,
  // SSH connection
  pub ssh_host: Option<String>,
  pub ssh_port: Option<i64>,
  pub ssh_user: Option<String>,
  pub ssh_key_path: Option<String>,
  // Vast specific
  pub vast_instance_id: Option<i64>,
  // Colab specific
  pub cloudflared_hostname: Option<String>,
  pub cloudflared_path: Option<String>,
}

// ============================================================
// Storage
// ============================================================

fn hosts_dir() -> PathBuf {
  doppio_data_dir().join("hosts")
}

fn host_path(id: &str) -> PathBuf {
  hosts_dir().join(format!("{}.json", id))
}

pub async fn list_hosts() -> Result<Vec<Host>, AppError> {
  let dir = hosts_dir();
  if !dir.exists() {
    return Ok(vec![]);
  }

  let mut hosts = vec![];
  let mut entries = tokio::fs::read_dir(&dir).await?;
  while let Some(entry) = entries.next_entry().await? {
    let path = entry.path();
    if path.extension().map_or(false, |e| e == "json") {
      let data = tokio::fs::read_to_string(&path).await?;
      match serde_json::from_str::<Host>(&data) {
        Ok(host) => hosts.push(host),
        Err(e) => {
          // Log error but continue loading other hosts
          eprintln!("Failed to parse host file {:?}: {}", path, e);
        }
      }
    }
  }

  // Sort by created_at descending
  hosts.sort_by(|a, b| b.created_at.cmp(&a.created_at));
  Ok(hosts)
}

pub async fn get_host(id: &str) -> Result<Host, AppError> {
  let path = host_path(id);
  if !path.exists() {
    return Err(AppError::not_found(format!("Host not found: {}", id)));
  }
  let data = tokio::fs::read_to_string(&path).await?;
  let host: Host = serde_json::from_str(&data)
    .map_err(|e| AppError::io(format!("Invalid host JSON: {}", e)))?;
  Ok(host)
}

pub async fn save_host(host: &Host) -> Result<(), AppError> {
  let dir = hosts_dir();
  tokio::fs::create_dir_all(&dir).await?;
  let path = host_path(&host.id);
  let data = serde_json::to_string_pretty(host)
    .map_err(|e| AppError::io(format!("Failed to serialize host: {}", e)))?;
  tokio::fs::write(&path, format!("{}\n", data)).await?;
  Ok(())
}

pub async fn delete_host(id: &str) -> Result<(), AppError> {
  let path = host_path(id);
  if path.exists() {
    tokio::fs::remove_file(&path).await?;
  }
  Ok(())
}

// ============================================================
// Operations
// ============================================================

/// Returns default environment variables for a host type
pub fn default_env_vars(host_type: &HostType) -> std::collections::HashMap<String, String> {
  let mut env = std::collections::HashMap::new();
  
  match host_type {
    HostType::Colab => {
      // Colab needs NVIDIA library path for GPU access
      env.insert("LD_LIBRARY_PATH".to_string(), 
        "/usr/lib64-nvidia:/usr/local/nvidia/lib64:$LD_LIBRARY_PATH".to_string());
      // Also set CUDA paths
      env.insert("PATH".to_string(),
        "/usr/local/cuda/bin:$PATH".to_string());
      // Ensure consistent locale for CLI tools
      env.insert("LC_ALL".to_string(), "en_US.UTF-8".to_string());
    }
    HostType::Vast => {
      // Vast.ai instances typically have NVIDIA libraries in standard paths
      env.insert("LD_LIBRARY_PATH".to_string(),
        "/usr/local/nvidia/lib64:/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH".to_string());
    }
    HostType::Custom => {
      // No default env vars for custom hosts
    }
  }
  
  env
}

pub async fn add_host(config: HostConfig) -> Result<Host, AppError> {
  let cfg = load_config().await?;
  let now = chrono::Utc::now().to_rfc3339();
  let id = Uuid::new_v4().to_string();

  let ssh = match config.host_type {
    HostType::Vast => {
      if config.vast_instance_id.is_some() {
        // We'll resolve SSH from Vast API later when refreshing
        Some(SshSpec {
          host: config.ssh_host.unwrap_or_default(),
          port: config.ssh_port.unwrap_or(22),
          user: cfg.vast.ssh_user.clone(),
          key_path: cfg.vast.ssh_key_path.clone(),
          extra_args: vec![],
        })
      } else {
        None
      }
    }
    HostType::Colab => {
      if let Some(hostname) = &config.cloudflared_hostname {
        let cloudflared = config.cloudflared_path.as_deref().unwrap_or("cloudflared");
        let proxy = format!("{} access ssh --hostname {}", cloudflared, hostname);
        Some(SshSpec {
          host: hostname.clone(),
          port: 22,
          user: config.ssh_user.unwrap_or_else(|| "root".to_string()),
          key_path: cfg.vast.ssh_key_path.clone(),
          extra_args: vec!["-o".to_string(), format!("ProxyCommand={}", proxy)],
        })
      } else {
        None
      }
    }
    HostType::Custom => {
      if let (Some(host), Some(port), Some(user)) = (&config.ssh_host, config.ssh_port, &config.ssh_user) {
        Some(SshSpec {
          host: host.clone(),
          port,
          user: user.clone(),
          key_path: config.ssh_key_path.clone(),
          extra_args: vec![],
        })
      } else {
        None
      }
    }
  };

  // Set default environment variables based on host type
  let env_vars = default_env_vars(&config.host_type);

  let host = Host {
    id,
    name: config.name,
    host_type: config.host_type,
    status: HostStatus::Offline,
    ssh,
    vast_instance_id: config.vast_instance_id,
    cloudflared_hostname: config.cloudflared_hostname,
    env_vars,
    gpu_name: None,
    num_gpus: None,
    system_info: None,
    created_at: now.clone(),
    last_seen_at: None,
  };

  save_host(&host).await?;
  Ok(host)
}

pub async fn update_host(id: &str, updates: serde_json::Value) -> Result<Host, AppError> {
  let cfg = load_config().await?;
  let mut host = get_host(id).await?;

  // Apply name update
  if let Some(name) = updates.get("name").and_then(|v| v.as_str()) {
    if !name.trim().is_empty() {
      host.name = name.to_string();
    }
  }

  // Get SSH updates
  let new_host = updates.get("ssh_host").and_then(|v| v.as_str()).filter(|s| !s.is_empty());
  let new_port = updates.get("ssh_port").and_then(|v| v.as_i64());
  let new_user = updates.get("ssh_user").and_then(|v| v.as_str()).filter(|s| !s.is_empty());
  let new_key = updates.get("sshKeyPath").and_then(|v| v.as_str());
  let new_cloudflared = updates.get("cloudflared_hostname").and_then(|v| v.as_str()).filter(|s| !s.is_empty());

  // Update cloudflared_hostname for Colab hosts
  if host.host_type == HostType::Colab {
    if new_cloudflared.is_some() || updates.get("cloudflared_hostname").is_some() {
      host.cloudflared_hostname = new_cloudflared.map(|s| s.to_string());
    }
  }

  // Rebuild or update SSH spec based on host type
  match host.host_type {
    HostType::Colab => {
      if let Some(hostname) = &host.cloudflared_hostname {
        let proxy = format!("cloudflared access ssh --hostname {}", hostname);
        host.ssh = Some(SshSpec {
          host: hostname.clone(),
          port: new_port.unwrap_or(22),
          user: new_user.map(|s| s.to_string()).unwrap_or_else(|| "root".to_string()),
          key_path: new_key.filter(|s| !s.is_empty()).map(|s| s.to_string()).or(cfg.vast.ssh_key_path.clone()),
          extra_args: vec!["-o".to_string(), format!("ProxyCommand={}", proxy)],
        });
      }
    }
    HostType::Custom => {
      if let Some(ref mut ssh) = host.ssh {
        if let Some(h) = new_host {
          ssh.host = h.to_string();
        }
        if let Some(p) = new_port {
          ssh.port = p;
        }
        if let Some(u) = new_user {
          ssh.user = u.to_string();
        }
        if updates.get("sshKeyPath").is_some() {
          ssh.key_path = new_key.filter(|s| !s.is_empty()).map(|s| s.to_string());
        }
      } else if new_host.is_some() && new_user.is_some() {
        // Create new SSH spec if we have host and user
        host.ssh = Some(SshSpec {
          host: new_host.unwrap().to_string(),
          port: new_port.unwrap_or(22),
          user: new_user.unwrap().to_string(),
          key_path: new_key.filter(|s| !s.is_empty()).map(|s| s.to_string()),
          extra_args: vec![],
        });
      }
    }
    HostType::Vast => {
      // For Vast hosts, SSH is managed by the Vast API, but we can update the key path
      if let Some(ref mut ssh) = host.ssh {
        if updates.get("sshKeyPath").is_some() {
          ssh.key_path = new_key.filter(|s| !s.is_empty()).map(|s| s.to_string());
        }
      }
    }
  }

  // Update environment variables if provided
  if let Some(env_obj) = updates.get("env_vars").and_then(|v| v.as_object()) {
    host.env_vars.clear();
    for (k, v) in env_obj {
      if let Some(val) = v.as_str() {
        host.env_vars.insert(k.clone(), val.to_string());
      }
    }
  }

  save_host(&host).await?;
  Ok(host)
}

pub async fn test_connection(id: &str) -> Result<(bool, String), AppError> {
  let host = get_host(id).await?;
  
  let ssh = match &host.ssh {
    Some(s) => s,
    None => return Ok((false, "No SSH configuration".to_string())),
  };

  ssh.validate()?;

  // For Colab hosts, check if cloudflared is installed
  if host.host_type == HostType::Colab {
    if which::which("cloudflared").is_err() {
      return Ok((false, 
        "cloudflared not found. Install it with:\n\
         macOS: brew install cloudflared\n\
         Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared".to_string()
      ));
    }
  }

  let mut cmd = Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg("echo ok");

  let output = cmd.output().await?;
  if output.status.success() {
    Ok((true, "Connection successful".to_string()))
  } else {
    let stderr = String::from_utf8_lossy(&output.stderr);
    let msg = stderr.trim();
    
    // Provide more helpful error messages
    if msg.contains("command not found: cloudflared") || msg.contains("cloudflared: not found") {
      Ok((false, 
        "cloudflared not found. Install it with:\n\
         macOS: brew install cloudflared\n\
         Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared".to_string()
      ))
    } else if msg.contains("Permission denied") {
      Ok((false, "Connection failed: Permission denied. Check your SSH key.".to_string()))
    } else if msg.contains("Connection refused") {
      Ok((false, "Connection failed: Connection refused. Is the host running?".to_string()))
    } else if msg.contains("Connection timed out") || msg.contains("timed out") {
      Ok((false, "Connection failed: Timed out. Check your network connection.".to_string()))
    } else {
      Ok((false, format!("Connection failed: {}", msg)))
    }
  }
}

/// Fetch system information from host via SSH
pub async fn fetch_system_info(ssh: &SshSpec, host_type: HostType) -> Result<SystemInfo, AppError> {
  ssh.validate()?;

  // Determine which disk mount points to check based on host type
  let disk_mounts = match host_type {
    HostType::Vast => "/ /workspace",
    HostType::Colab => "/ /content /content/drive",
    HostType::Custom => "/ /home /data /workspace",
  };

  // Script to gather system info
  // Using /proc/meminfo for more reliable memory reading across different Linux distros
  let info_script = format!(r#"
echo "===CPU==="
cat /proc/cpuinfo | grep "model name" | head -1 | cut -d: -f2 | xargs
nproc
echo "===MEM==="
# Read from /proc/meminfo for reliability (values in kB, we'll convert)
MEM_TOTAL=$(grep MemTotal /proc/meminfo | awk '{{print $2}}')
MEM_FREE=$(grep MemFree /proc/meminfo | awk '{{print $2}}')
MEM_AVAIL=$(grep MemAvailable /proc/meminfo | awk '{{print $2}}')
MEM_BUFFERS=$(grep Buffers /proc/meminfo | awk '{{print $2}}')
MEM_CACHED=$(grep "^Cached:" /proc/meminfo | awk '{{print $2}}')
# Calculate used = total - free - buffers - cached
MEM_USED=$((MEM_TOTAL - MEM_FREE - MEM_BUFFERS - MEM_CACHED))
echo "$MEM_TOTAL $MEM_USED $MEM_AVAIL"
echo "===DISK==="
for mount in {}; do
  if [ -d "$mount" ]; then
    df -B1 "$mount" 2>/dev/null | tail -1 | awk '{{print $6, $2, $3, $4}}'
  fi
done
echo "===OS==="
cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '"' || uname -s
hostname
echo "===GPU==="
# Add common NVIDIA library paths for non-interactive shells (especially Colab)
export LD_LIBRARY_PATH=/usr/lib64-nvidia:/usr/local/nvidia/lib64:$LD_LIBRARY_PATH
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu,temperature.gpu,driver_version,power.draw,power.limit,clocks.current.graphics,clocks.current.memory,fan.speed,compute_mode,pcie.link.gen.max,pcie.link.width.max --format=csv,noheader,nounits 2>/dev/null || echo "no-gpu"
"#, disk_mounts);

  let mut cmd = Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg("bash -s");
  cmd.stdin(std::process::Stdio::piped());
  cmd.stdout(std::process::Stdio::piped());
  cmd.stderr(std::process::Stdio::piped());

  let mut child = cmd.spawn()
    .map_err(|e| AppError::command(format!("SSH spawn failed: {}", e)))?;

  // Write script to stdin
  if let Some(mut stdin) = child.stdin.take() {
    use tokio::io::AsyncWriteExt;
    stdin.write_all(info_script.as_bytes()).await
      .map_err(|e| AppError::command(format!("Failed to write script: {}", e)))?;
    stdin.flush().await.ok();
  }

  let output = child.wait_with_output().await
    .map_err(|e| AppError::command(format!("SSH failed: {}", e)))?;

  if !output.status.success() {
    let stderr = String::from_utf8_lossy(&output.stderr);
    eprintln!("fetch_system_info failed: {}", stderr);
    return Err(AppError::command(format!("Failed to fetch system info: {}", stderr)));
  }

  let stdout = String::from_utf8_lossy(&output.stdout);
  parse_system_info(&stdout)
}

fn parse_system_info(output: &str) -> Result<SystemInfo, AppError> {
  let mut info = SystemInfo::default();
  let mut section = "";

  for line in output.lines() {
    let line = line.trim();
    if line.starts_with("===") && line.ends_with("===") {
      section = line.trim_matches('=');
      continue;
    }

    match section {
      "CPU" => {
        if info.cpu_model.is_none() {
          info.cpu_model = Some(line.to_string());
        } else if info.cpu_cores.is_none() {
          info.cpu_cores = line.parse().ok();
        }
      }
      "MEM" => {
        // Format: total_kb used_kb available_kb (from /proc/meminfo, values in kB)
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() >= 3 {
          if let (Ok(total_kb), Ok(used_kb), Ok(avail_kb)) = (
            parts[0].parse::<u64>(),
            parts[1].parse::<u64>(),
            parts[2].parse::<u64>()
          ) {
            // Convert kB to GB (1 GB = 1024 * 1024 kB)
            let kb_to_gb = 1024.0 * 1024.0;
            info.memory_total_gb = Some(total_kb as f64 / kb_to_gb);
            info.memory_used_gb = Some(used_kb as f64 / kb_to_gb);
            info.memory_available_gb = Some(avail_kb as f64 / kb_to_gb);
          }
        }
      }
      "DISK" => {
        // Format: mount_point total used available (in bytes)
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() >= 4 {
          let mount = parts[0].to_string();
          // Skip duplicate mount points
          if !info.disks.iter().any(|d| d.mount_point == mount) {
            if let (Ok(total), Ok(used), Ok(avail)) = (
              parts[1].parse::<u64>(),
              parts[2].parse::<u64>(),
              parts[3].parse::<u64>()
            ) {
              info.disks.push(DiskInfo {
                mount_point: mount,
                total_gb: total as f64 / 1073741824.0,
                used_gb: used as f64 / 1073741824.0,
                available_gb: avail as f64 / 1073741824.0,
              });
            }
          }
        }
      }
      "OS" => {
        if info.os.is_none() {
          info.os = Some(line.to_string());
        } else if info.hostname.is_none() {
          info.hostname = Some(line.to_string());
        }
      }
      "GPU" => {
        if line != "no-gpu" && !line.is_empty() {
          // Parse: index, name, memory.total, memory.used, utilization.gpu, temperature.gpu, driver_version, power.draw, power.limit, clocks.graphics, clocks.memory, fan.speed, compute_mode, pcie.gen.max, pcie.width.max
          let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
          if parts.len() >= 3 {
            if let Ok(index) = parts[0].parse::<i32>() {
              let parse_opt = |s: &str| -> Option<i32> {
                let cleaned = s.trim().replace("[N/A]", "").replace("[Not Supported]", "");
                cleaned.parse().ok()
              };
              let parse_f64 = |s: &str| -> Option<f64> {
                let cleaned = s.trim().replace("[N/A]", "").replace("[Not Supported]", "");
                cleaned.parse().ok()
              };
              let name = parts[1].to_string();
              let capability = lookup_gpu_capability(&name);
              let gpu = GpuInfo {
                index,
                name,
                memory_total_mb: parts.get(2).and_then(|s| s.parse().ok()).unwrap_or(0),
                memory_used_mb: parts.get(3).and_then(|s| s.parse().ok()),
                utilization: parts.get(4).and_then(|s| parse_opt(s)),
                temperature: parts.get(5).and_then(|s| parse_opt(s)),
                driver_version: parts.get(6).map(|s| s.trim().to_string()).filter(|s| !s.is_empty() && s != "[N/A]"),
                power_draw_w: parts.get(7).and_then(|s| parse_f64(s)),
                power_limit_w: parts.get(8).and_then(|s| parse_f64(s)),
                clock_graphics_mhz: parts.get(9).and_then(|s| parse_opt(s)),
                clock_memory_mhz: parts.get(10).and_then(|s| parse_opt(s)),
                fan_speed: parts.get(11).and_then(|s| parse_opt(s)),
                compute_mode: parts.get(12).map(|s| s.trim().to_string()).filter(|s| !s.is_empty() && s != "[N/A]"),
                pcie_gen: parts.get(13).and_then(|s| parse_opt(s)),
                pcie_width: parts.get(14).and_then(|s| parse_opt(s)),
                capability,
              };
              info.gpu_list.push(gpu);
            }
          }
        }
      }
      _ => {}
    }
  }

  Ok(info)
}

// ============================================================
// Tmux Session Management
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteTmuxSession {
  pub name: String,
  pub windows: i32,
  pub attached: bool,
  pub created_at: Option<String>,
}

/// List tmux sessions on a remote host via SSH
pub async fn list_tmux_sessions(id: &str) -> Result<Vec<RemoteTmuxSession>, AppError> {
  let host = get_host(id).await?;
  
  let ssh = match &host.ssh {
    Some(s) => s,
    None => return Err(AppError::invalid_input("No SSH configuration for this host")),
  };

  ssh.validate()?;

  // Use tmux list-sessions with a format string to get structured output
  // Format: session_name:window_count:attached (1 or 0):created_timestamp
  let tmux_cmd = "tmux list-sessions -F '#{session_name}:#{session_windows}:#{session_attached}:#{session_created}' 2>/dev/null || echo ''";

  let mut cmd = Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg(tmux_cmd);

  let output = cmd.output().await?;
  
  if !output.status.success() {
    // SSH failed - might be connection issue
    let stderr = String::from_utf8_lossy(&output.stderr);
    return Err(AppError::command(format!("Failed to list tmux sessions: {}", stderr.trim())));
  }

  let stdout = String::from_utf8_lossy(&output.stdout);
  let mut sessions: Vec<RemoteTmuxSession> = Vec::new();

  for line in stdout.lines() {
    let line = line.trim();
    if line.is_empty() {
      continue;
    }

    let parts: Vec<&str> = line.split(':').collect();
    if parts.len() >= 3 {
      let name = parts[0].to_string();
      let windows: i32 = parts[1].parse().unwrap_or(1);
      let attached = parts[2] == "1";
      let created_at = parts.get(3).map(|s| {
        // Convert Unix timestamp to ISO 8601 if possible
        if let Ok(ts) = s.parse::<i64>() {
          chrono::DateTime::from_timestamp(ts, 0)
            .map(|dt| dt.to_rfc3339())
            .unwrap_or_else(|| s.to_string())
        } else {
          s.to_string()
        }
      });

      sessions.push(RemoteTmuxSession {
        name,
        windows,
        attached,
        created_at,
      });
    }
  }

  Ok(sessions)
}

pub async fn refresh_host(id: &str) -> Result<Host, AppError> {
  let mut host = get_host(id).await?;
  
  // Test connection and update status
  match test_connection(id).await {
    Ok((true, _)) => {
      host.status = HostStatus::Online;
      host.last_seen_at = Some(chrono::Utc::now().to_rfc3339());
      
      // Fetch system info if connection successful
      if let Some(ssh) = &host.ssh {
        if let Ok(sys_info) = fetch_system_info(ssh, host.host_type).await {
          // Update GPU info from system info
          if !sys_info.gpu_list.is_empty() {
            host.gpu_name = Some(sys_info.gpu_list[0].name.clone());
            host.num_gpus = Some(sys_info.gpu_list.len() as i32);
          }
          host.system_info = Some(sys_info);
        }
      }
    }
    Ok((false, _)) => {
      host.status = HostStatus::Offline;
    }
    Err(_) => {
      host.status = HostStatus::Error;
    }
  }

  save_host(&host).await?;
  Ok(host)
}
