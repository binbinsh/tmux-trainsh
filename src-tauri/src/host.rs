use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::time::{Duration, Instant};
use tokio::process::Command;
use uuid::Uuid;

use crate::config::{doppio_data_dir, load_config};
use crate::error::AppError;
use crate::gpu::lookup_gpu_capability;
use crate::ssh::SshSpec;
use crate::vast::{VastClient, VastInstance};

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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IpInfo {
    pub ip: Option<String>,
    pub hostname: Option<String>,
    pub city: Option<String>,
    pub region: Option<String>,
    pub country: Option<String>,
    pub loc: Option<String>,
    pub org: Option<String>,
    pub timezone: Option<String>,
    pub readme: Option<String>,
}

// ============================================================
// IP Info
// ============================================================

fn normalize_ipinfo_target(target: &str) -> Result<String, AppError> {
    let trimmed = target.trim();
    if trimmed.is_empty() {
        return Err(AppError::invalid_input("IP info target is required"));
    }
    if trimmed.len() > 255 {
        return Err(AppError::invalid_input("IP info target is too long"));
    }
    if trimmed.contains("://") {
        return Err(AppError::invalid_input(
            "IP info target must not include a scheme",
        ));
    }
    if trimmed.chars().any(|c| c.is_whitespace()) {
        return Err(AppError::invalid_input(
            "IP info target must not contain whitespace",
        ));
    }
    let disallowed = ['/', '\\', '?', '#', '@'];
    if trimmed.chars().any(|c| disallowed.contains(&c)) {
        return Err(AppError::invalid_input(
            "IP info target contains invalid characters",
        ));
    }
    if !trimmed.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | ':' | '_'))
    {
        return Err(AppError::invalid_input(
            "IP info target contains unsupported characters",
        ));
    }
    Ok(trimmed.to_string())
}

pub async fn fetch_ip_info(target: &str) -> Result<IpInfo, AppError> {
    let target = normalize_ipinfo_target(target)?;
    let url = format!("https://ipinfo.io/{}/json", target);
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(6))
        .build()
        .map_err(|e| AppError::http(format!("Failed to create HTTP client: {}", e)))?;
    let response = client
        .get(url)
        .header(reqwest::header::ACCEPT, "application/json")
        .send()
        .await
        .map_err(|e| AppError::network(format!("Failed to fetch IP info: {}", e)))?;

    if !response.status().is_success() {
        return Err(AppError::network(format!(
            "IP info request failed with status: {}",
            response.status()
        )));
    }

    let info = response
        .json::<IpInfo>()
        .await
        .map_err(|e| AppError::network(format!("Failed to parse IP info response: {}", e)))?;
    Ok(info)
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
    if let Some(vast_instance_id) = id
        .strip_prefix("vast:")
        .and_then(|s| s.trim().parse::<i64>().ok())
    {
        return resolve_vast_host(id, vast_instance_id).await;
    }

    let path = host_path(id);
    if !path.exists() {
        return Err(AppError::not_found(format!("Host not found: {}", id)));
    }
    let data = tokio::fs::read_to_string(&path).await?;
    let host: Host = serde_json::from_str(&data)
        .map_err(|e| AppError::io(format!("Invalid host JSON: {}", e)))?;
    Ok(host)
}

/// Resolve an SSH spec for executing commands on a host.
///
/// For Vast hosts (`vast:<id>`), this will:
/// - attach the configured SSH public key
/// - pick a working SSH route (proxy/direct) by probing connectivity
/// - return only when authentication succeeds
pub async fn resolve_ssh_spec(host_id: &str) -> Result<SshSpec, AppError> {
    if host_id.trim().is_empty() {
        return Err(AppError::invalid_input("host_id is required"));
    }
    if host_id == "__local__" {
        return Err(AppError::invalid_input("Local execution has no SSH spec"));
    }

    if let Some(vast_instance_id) = host_id
        .strip_prefix("vast:")
        .and_then(|s| s.trim().parse::<i64>().ok())
    {
        return resolve_vast_ssh_spec(vast_instance_id).await;
    }

    let host = get_host(host_id).await?;
    let mut ssh = host
        .ssh
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    if let Some(key_input) = ssh.key_path.clone().filter(|s| !s.trim().is_empty()) {
        let p = crate::ssh_keys::materialize_private_key_path(&key_input).await?;
        ssh.key_path = Some(p.to_string_lossy().to_string());
    }
    ssh.validate()?;
    Ok(ssh)
}

pub async fn resolve_ssh_spec_with_retry(
    host_id: &str,
    timeout: Duration,
) -> Result<SshSpec, AppError> {
    let start = Instant::now();
    let deadline = Instant::now() + timeout;
    let mut last_err: Option<AppError> = None;

    loop {
        match resolve_ssh_spec(host_id).await {
            Ok(ssh) => return Ok(ssh),
            Err(e) => {
                let elapsed = start.elapsed();
                let retryable = if is_auth_error(&e) {
                    // Vast key attachment can take a moment to propagate; retry briefly.
                    elapsed < Duration::from_secs(30)
                } else {
                    is_retryable_ssh_error(&e)
                };
                let timed_out = Instant::now() >= deadline;
                if !retryable || timed_out {
                    return Err(last_err.unwrap_or(e));
                }
                last_err = Some(e);
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
        }
    }
}

fn is_auth_error(e: &AppError) -> bool {
    let m = e.message.as_str();
    e.code == "permission_denied" || m.contains("Permission denied") || m.contains("publickey")
}

fn is_retryable_ssh_error(e: &AppError) -> bool {
    let m = e.message.as_str();
    if m.contains("Missing Vast SSH key path") || m.contains("SSH private key not found") {
        return false;
    }
    m.contains("Vast SSH route is not available yet")
        || m.contains("Connection timed out")
        || m.contains("Connection refused")
        || m.contains("Network is unreachable")
        || m.contains("No route to host")
        || m.contains("Temporary failure in name resolution")
        || m.contains("Could not resolve hostname")
}

async fn resolve_vast_ssh_spec(vast_instance_id: i64) -> Result<SshSpec, AppError> {
    if vast_instance_id <= 0 {
        return Err(AppError::invalid_input("vast_instance_id must be positive"));
    }

    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;

    let ssh_user = {
        let u = cfg.vast.ssh_user.trim();
        if u.is_empty() {
            "root".to_string()
        } else {
            u.to_string()
        }
    };

    let key_input = cfg
        .vast
        .ssh_key_path
        .clone()
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| {
            AppError::invalid_input("Missing Vast SSH key path (Settings → Vast.ai → SSH Key Path)")
        })?;

    let key_path = crate::ssh_keys::materialize_private_key_path(&key_input).await?;
    let key_path_str = key_path.to_string_lossy().to_string();

    let ssh_key = crate::ssh_keys::read_public_key(key_path_str.clone()).await?;
    client.attach_ssh_key(vast_instance_id, ssh_key).await?;

    let inst = client.get_instance(vast_instance_id).await?;

    let direct = inst
        .public_ipaddr
        .clone()
        .filter(|s| !s.trim().is_empty())
        .zip(inst.machine_dir_ssh_port);

    let raw_proxy_port = inst.ssh_port;
    let proxy_host_from_api = inst.ssh_host.clone().filter(|s| !s.trim().is_empty());
    let normalized_ssh_idx = inst.ssh_idx.clone().and_then(|idx| {
        let idx = idx.trim().to_string();
        if idx.is_empty() {
            return None;
        }
        Some(if idx.starts_with("ssh") {
            idx
        } else {
            format!("ssh{idx}")
        })
    });
    let proxy_host = match proxy_host_from_api {
        Some(h) if h.contains("vast.ai") => Some(h),
        _ => normalized_ssh_idx.map(|x| format!("{x}.vast.ai")),
    }
    .map(|s| s.trim().to_string())
    .filter(|s| !s.is_empty());
    let proxy = proxy_host.zip(raw_proxy_port);

    let prefer_direct = matches!(
        cfg.vast.ssh_connection_preference,
        crate::config::VastSshConnectionPreference::Direct
    );
    let ordered: Vec<(String, i64)> = if prefer_direct {
        direct.into_iter().chain(proxy.into_iter()).collect()
    } else {
        proxy.into_iter().chain(direct.into_iter()).collect()
    };

    if ordered.is_empty() {
        return Err(AppError::command(
            "Vast SSH route is not available yet (wait for instance SSH info to appear)".to_string(),
        ));
    }

    crate::ssh::ensure_bin("ssh").await?;

    let ssh_extra_args: Vec<String> = vec![
        "-o".to_string(),
        "IdentitiesOnly=yes".to_string(),
        "-o".to_string(),
        "PreferredAuthentications=publickey".to_string(),
        "-o".to_string(),
        "PasswordAuthentication=no".to_string(),
        "-o".to_string(),
        "BatchMode=yes".to_string(),
    ];

    let mut last_error: Option<AppError> = None;
    let mut saw_auth_error = false;

    for (host, port) in ordered {
        let ssh = SshSpec {
            host,
            port,
            user: ssh_user.clone(),
            key_path: Some(key_path_str.clone()),
            extra_args: ssh_extra_args.clone(),
        };

        if let Err(e) = ssh.validate() {
            last_error = Some(e);
            continue;
        }

        let mut cmd = tokio::process::Command::new("ssh");
        for a in ssh.common_ssh_options() {
            cmd.arg(a);
        }
        cmd.arg(ssh.target());
        cmd.arg("true");

        match crate::ssh::run_checked_with_timeout(cmd, Duration::from_secs(20)).await {
            Ok(_) => return Ok(ssh),
            Err(e) => {
                if e.message.contains("Permission denied") || e.message.contains("publickey") {
                    saw_auth_error = true;
                }
                last_error = Some(e);
            }
        }
    }

    if saw_auth_error {
        return Err(AppError::permission_denied(format!(
            "SSH authentication failed for Vast instance {vast_instance_id}. Check Settings → Vast.ai → SSH User / SSH Key Path."
        )));
    }
    Err(last_error.unwrap_or_else(|| AppError::command("SSH connection failed".to_string())))
}

fn vast_instance_status(inst: &VastInstance) -> HostStatus {
    let v = inst
        .actual_status
        .clone()
        .unwrap_or_default()
        .to_lowercase();
    if v.contains("running") || v.contains("active") || v.contains("online") {
        return HostStatus::Online;
    }
    if v.contains("stopped") || v.contains("exited") || v.contains("offline") {
        return HostStatus::Offline;
    }
    if v.contains("error") || v.contains("failed") {
        return HostStatus::Error;
    }
    HostStatus::Connecting
}

async fn resolve_vast_host(host_id: &str, vast_instance_id: i64) -> Result<Host, AppError> {
    if vast_instance_id <= 0 {
        return Err(AppError::invalid_input("vast_instance_id must be positive"));
    }

    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;

    let inst = client.get_instance(vast_instance_id).await?;

    let label = inst
        .label
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| format!("Vast #{}", vast_instance_id));

    let direct_host = inst.public_ipaddr.clone().filter(|s| !s.trim().is_empty());
    let direct_port = inst.machine_dir_ssh_port;

    let raw_proxy_port = inst.ssh_port;
    let proxy_host_from_api = inst.ssh_host.clone().filter(|s| !s.trim().is_empty());
    let normalized_ssh_idx = inst.ssh_idx.clone().and_then(|idx| {
        let idx = idx.trim().to_string();
        if idx.is_empty() {
            return None;
        }
        Some(if idx.starts_with("ssh") {
            idx
        } else {
            format!("ssh{idx}")
        })
    });
    let proxy_host = match proxy_host_from_api {
        Some(h) if h.contains("vast.ai") => Some(h),
        _ => normalized_ssh_idx.map(|x| format!("{x}.vast.ai")),
    }
    .map(|s| s.trim().to_string())
    .filter(|s| !s.is_empty());

    let ssh_user = cfg.vast.ssh_user.trim().to_string();
    let ssh = if ssh_user.is_empty() {
        None
    } else {
        let prefer_direct = matches!(
            cfg.vast.ssh_connection_preference,
            crate::config::VastSshConnectionPreference::Direct
        );

        let direct = direct_host.zip(direct_port);
        let proxy = proxy_host.zip(raw_proxy_port);
        let chosen = if prefer_direct {
            direct.or(proxy)
        } else {
            proxy.or(direct)
        };

        let key_input = cfg
            .vast
            .ssh_key_path
            .clone()
            .filter(|s| !s.trim().is_empty());
        let key_path = if let Some(key_input) = &key_input {
            let p = crate::ssh_keys::materialize_private_key_path(key_input).await?;
            let p_str = p.to_string_lossy().to_string();
            let ssh_key = crate::ssh_keys::read_public_key(p_str.clone()).await?;
            client.attach_ssh_key(vast_instance_id, ssh_key).await?;
            Some(p_str)
        } else {
            None
        };

        let extra_args = if key_path.is_some() {
            vec![
                "-o".to_string(),
                "IdentitiesOnly=yes".to_string(),
                "-o".to_string(),
                "PreferredAuthentications=publickey".to_string(),
                "-o".to_string(),
                "PasswordAuthentication=no".to_string(),
            ]
        } else {
            vec![]
        };

        chosen.and_then(|(host, port)| {
            let spec = SshSpec {
                host,
                port,
                user: ssh_user.clone(),
                key_path: key_path.clone(),
                extra_args,
            };
            spec.validate().ok().map(|_| spec)
        })
    };

    Ok(Host {
        id: host_id.to_string(),
        name: label,
        host_type: HostType::Vast,
        status: vast_instance_status(&inst),
        ssh,
        vast_instance_id: Some(vast_instance_id),
        cloudflared_hostname: None,
        env_vars: std::collections::HashMap::new(),
        gpu_name: inst.gpu_name.clone(),
        num_gpus: inst.num_gpus.and_then(|n| i32::try_from(n).ok()),
        system_info: None,
        created_at: chrono::Utc::now().to_rfc3339(),
        last_seen_at: None,
    })
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
            env.insert(
                "LD_LIBRARY_PATH".to_string(),
                "/usr/lib64-nvidia:/usr/local/nvidia/lib64:$LD_LIBRARY_PATH".to_string(),
            );
            // Also set CUDA paths
            env.insert("PATH".to_string(), "/usr/local/cuda/bin:$PATH".to_string());
            // Ensure consistent locale for CLI tools
            env.insert("LC_ALL".to_string(), "en_US.UTF-8".to_string());
        }
        HostType::Vast => {
            // Vast.ai instances typically have NVIDIA libraries in standard paths
            env.insert(
                "LD_LIBRARY_PATH".to_string(),
                "/usr/local/nvidia/lib64:/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH".to_string(),
            );
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
                    user: {
                        let u = cfg.vast.ssh_user.trim();
                        if u.is_empty() {
                            "root".to_string()
                        } else {
                            u.to_string()
                        }
                    },
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
            if let (Some(host), Some(port), Some(user)) =
                (&config.ssh_host, config.ssh_port, &config.ssh_user)
            {
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
    let new_host = updates
        .get("ssh_host")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    let new_port = updates.get("ssh_port").and_then(|v| v.as_i64());
    let new_user = updates
        .get("ssh_user")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());
    let new_key = updates.get("sshKeyPath").and_then(|v| v.as_str());
    let new_cloudflared = updates
        .get("cloudflared_hostname")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty());

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
                    user: new_user
                        .map(|s| s.to_string())
                        .unwrap_or_else(|| "root".to_string()),
                    key_path: new_key
                        .filter(|s| !s.is_empty())
                        .map(|s| s.to_string())
                        .or(cfg.vast.ssh_key_path.clone()),
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
            return Ok((
                false,
                "cloudflared not found. Install it with:\n\
         macOS: brew install cloudflared\n\
         Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared"
                    .to_string(),
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
        if msg.contains("command not found: cloudflared") || msg.contains("cloudflared: not found")
        {
            Ok((
                false,
                "cloudflared not found. Install it with:\n\
         macOS: brew install cloudflared\n\
         Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared"
                    .to_string(),
            ))
        } else if msg.contains("Permission denied") {
            Ok((
                false,
                "Connection failed: Permission denied. Check your SSH key.".to_string(),
            ))
        } else if msg.contains("Connection refused") {
            Ok((
                false,
                "Connection failed: Connection refused. Is the host running?".to_string(),
            ))
        } else if msg.contains("Connection timed out") || msg.contains("timed out") {
            Ok((
                false,
                "Connection failed: Timed out. Check your network connection.".to_string(),
            ))
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
    let info_script = format!(
        r#"
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
"#,
        disk_mounts
    );

    let mut cmd = Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg("bash -s");
    cmd.stdin(std::process::Stdio::piped());
    cmd.stdout(std::process::Stdio::piped());
    cmd.stderr(std::process::Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::command(format!("SSH spawn failed: {}", e)))?;

    // Write script to stdin
    if let Some(mut stdin) = child.stdin.take() {
        use tokio::io::AsyncWriteExt;
        stdin
            .write_all(info_script.as_bytes())
            .await
            .map_err(|e| AppError::command(format!("Failed to write script: {}", e)))?;
        stdin.flush().await.ok();
    }

    let output = child
        .wait_with_output()
        .await
        .map_err(|e| AppError::command(format!("SSH failed: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        eprintln!("fetch_system_info failed: {}", stderr);
        return Err(AppError::command(format!(
            "Failed to fetch system info: {}",
            stderr
        )));
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
                        parts[2].parse::<u64>(),
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
                            parts[3].parse::<u64>(),
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
                                let cleaned =
                                    s.trim().replace("[N/A]", "").replace("[Not Supported]", "");
                                cleaned.parse().ok()
                            };
                            let parse_f64 = |s: &str| -> Option<f64> {
                                let cleaned =
                                    s.trim().replace("[N/A]", "").replace("[Not Supported]", "");
                                cleaned.parse().ok()
                            };
                            let name = parts[1].to_string();
                            let capability = lookup_gpu_capability(&name);
                            let gpu = GpuInfo {
                                index,
                                name,
                                memory_total_mb: parts
                                    .get(2)
                                    .and_then(|s| s.parse().ok())
                                    .unwrap_or(0),
                                memory_used_mb: parts.get(3).and_then(|s| s.parse().ok()),
                                utilization: parts.get(4).and_then(|s| parse_opt(s)),
                                temperature: parts.get(5).and_then(|s| parse_opt(s)),
                                driver_version: parts
                                    .get(6)
                                    .map(|s| s.trim().to_string())
                                    .filter(|s| !s.is_empty() && s != "[N/A]"),
                                power_draw_w: parts.get(7).and_then(|s| parse_f64(s)),
                                power_limit_w: parts.get(8).and_then(|s| parse_f64(s)),
                                clock_graphics_mhz: parts.get(9).and_then(|s| parse_opt(s)),
                                clock_memory_mhz: parts.get(10).and_then(|s| parse_opt(s)),
                                fan_speed: parts.get(11).and_then(|s| parse_opt(s)),
                                compute_mode: parts
                                    .get(12)
                                    .map(|s| s.trim().to_string())
                                    .filter(|s| !s.is_empty() && s != "[N/A]"),
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

pub fn parse_system_info_output(output: &str) -> Result<SystemInfo, AppError> {
    parse_system_info(output)
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
        None => {
            return Err(AppError::invalid_input(
                "No SSH configuration for this host",
            ))
        }
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
        return Err(AppError::command(format!(
            "Failed to list tmux sessions: {}",
            stderr.trim()
        )));
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
