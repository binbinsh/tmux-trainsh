use std::{
    fs::File,
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use flate2::{write::GzEncoder, Compression};
use serde::{Deserialize, Serialize};
use tar::Builder;
use tokio::process::Command;
use uuid::Uuid;
use walkdir::WalkDir;

use crate::{
    error::AppError,
    ssh::{ensure_bin, run_checked, SshSpec},
};

#[derive(Debug, Clone, Deserialize)]
pub struct RunVastJobInput {
    pub project_dir: String,
    pub command: String,
    pub instance_id: i64,
    pub workdir: Option<String>,
    pub remote_output_dir: Option<String>,
    pub hf_home: Option<String>,
    pub sync: Option<bool>,
    pub include_data: Option<bool>,
    pub include_models: Option<bool>,
    pub include_dotenv: Option<bool>,
    pub extra_excludes: Option<String>,
    #[allow(dead_code)]
    pub delete_remote: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteJobMeta {
    pub ts: String,
    pub project_dir: String,
    pub command: String,
    pub ssh: SshSpec,
    pub remote: RemoteJobRemote,
    pub local_meta_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteJobRemote {
    pub workdir: String,
    pub job_dir: String,
    pub log_path: String,
    pub output_flag: String,
    pub output_dir: String,
    pub hf_home: String,
    pub tmux_session: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuRow {
    pub index: String,
    pub name: String,
    pub util_gpu: String,
    pub util_mem: String,
    pub mem_used: String,
    pub mem_total: String,
    pub temp: String,
    pub power: String,
}

fn default_out_dir() -> PathBuf {
    let base = dirs::cache_dir().unwrap_or_else(std::env::temp_dir);
    base.join("doppio")
}

fn parse_excludes(
    extra_excludes: Option<String>,
    include_data: bool,
    include_models: bool,
    include_dotenv: bool,
) -> Vec<PathBuf> {
    let mut excludes: Vec<PathBuf> = vec![
        PathBuf::from(".git"),
        PathBuf::from("node_modules"),
        PathBuf::from("dist"),
        PathBuf::from("build"),
        PathBuf::from("src-tauri/target"),
        PathBuf::from("src-tauri/gen"),
    ];

    if !include_data {
        excludes.push(PathBuf::from("data"));
    }
    if !include_models {
        excludes.push(PathBuf::from("models"));
    }
    if !include_dotenv {
        excludes.push(PathBuf::from(".env"));
        excludes.push(PathBuf::from(".env.local"));
    }

    if let Some(extra) = extra_excludes {
        for tok in extra
            .split(|c: char| c == ',' || c == '\n' || c == '\t' || c == '\r')
            .map(|s| s.trim())
            .filter(|s| !s.is_empty())
        {
            excludes.push(PathBuf::from(tok));
        }
    }

    excludes
}

fn is_excluded(rel: &Path, excludes: &[PathBuf]) -> bool {
    excludes.iter().any(|p| rel.starts_with(p))
}

fn bundle_project(
    project_dir: &Path,
    bundle_path: &Path,
    excludes: &[PathBuf],
) -> Result<(), AppError> {
    if let Some(parent) = bundle_path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let file = File::create(bundle_path)?;
    let enc = GzEncoder::new(file, Compression::default());
    let mut tar = Builder::new(enc);

    for entry in WalkDir::new(project_dir).follow_links(false) {
        let entry = entry.map_err(|e| AppError::io(e.to_string()))?;
        let path = entry.path();
        if path == project_dir {
            continue;
        }
        let rel = path
            .strip_prefix(project_dir)
            .map_err(|e| AppError::io(format!("Failed to compute relative path: {e}")))?;

        if is_excluded(rel, excludes) {
            continue;
        }

        if entry.file_type().is_dir() {
            continue;
        }
        tar.append_path_with_name(path, rel)
            .map_err(|e| AppError::io(format!("Failed to add {rel:?} to tar: {e}")))?;
    }

    let enc = tar.into_inner().map_err(|e| AppError::io(e.to_string()))?;
    enc.finish().map_err(|e| AppError::io(e.to_string()))?;
    Ok(())
}

async fn ssh_bash(ssh: &SshSpec, cmd: &str) -> Result<String, AppError> {
    ensure_bin("ssh").await?;
    ssh.validate()?;

    let mut c = Command::new("ssh");
    c.args(ssh.common_ssh_options());
    c.arg(ssh.target());
    c.arg("--");
    c.arg("bash");
    c.arg("-lc");
    c.arg(cmd);
    let out = run_checked(c).await?;
    Ok(out.stdout)
}

async fn scp_upload(ssh: &SshSpec, local_path: &Path, remote_path: &str) -> Result<(), AppError> {
    ensure_bin("scp").await?;
    ssh.validate()?;
    if !local_path.exists() {
        return Err(AppError::invalid_input(format!(
            "Local file not found: {}",
            local_path.display()
        )));
    }

    let quoted_remote = shell_escape::unix::escape(remote_path.into()).to_string();
    let remote_spec = format!("{}:{}", ssh.target(), quoted_remote);

    let mut c = Command::new("scp");
    c.args(ssh.common_scp_options());
    c.arg(local_path);
    c.arg(remote_spec);
    run_checked(c).await?;
    Ok(())
}

/// Rsync configuration with path and appropriate progress flag
struct RsyncConfig {
    /// Path to rsync binary
    path: String,
    /// Progress flag: "--info=progress2" for modern rsync (3.1+), "--progress" for legacy
    progress_flag: String,
}

/// Detect the best rsync available and its capabilities.
/// Prefers Homebrew rsync (supports --info=progress2) over macOS system rsync.
fn get_rsync_config() -> RsyncConfig {
    use std::process::Command as StdCommand;

    // Check Homebrew paths first (they have modern rsync with --info=progress2 support)
    let homebrew_paths = [
        "/opt/homebrew/bin/rsync", // Apple Silicon
        "/usr/local/bin/rsync",     // Intel Mac
    ];

    for path in homebrew_paths {
        if std::path::Path::new(path).exists() {
            // Verify it's a modern rsync by checking version
            if let Ok(output) = StdCommand::new(path).arg("--version").output() {
                let version_str = String::from_utf8_lossy(&output.stdout);
                // rsync version 3.1+ supports --info=progress2
                if version_str.contains("rsync  version 3.") || version_str.contains("rsync  version 4.") {
                    return RsyncConfig {
                        path: path.to_string(),
                        progress_flag: "--info=progress2".to_string(),
                    };
                }
            }
        }
    }

    // Fall back to system rsync with legacy --progress flag
    RsyncConfig {
        path: "rsync".to_string(),
        progress_flag: "--progress".to_string(),
    }
}

async fn scp_download_dir(
    ssh: &SshSpec,
    remote_dir: &str,
    local_dir: &Path,
) -> Result<(), AppError> {
    ensure_bin("scp").await?;
    ssh.validate()?;

    if let Some(parent) = local_dir.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    tokio::fs::create_dir_all(local_dir).await?;

    let quoted_remote = shell_escape::unix::escape(remote_dir.into()).to_string();
    let remote_spec = format!("{}:{}", ssh.target(), quoted_remote);

    let mut c = Command::new("scp");
    c.args(ssh.common_scp_options());
    c.arg("-r");
    c.arg(remote_spec);
    c.arg(local_dir);
    run_checked(c).await?;
    Ok(())
}

async fn rsync_download_dir(
    ssh: &SshSpec,
    remote_dir: &str,
    local_dir: &Path,
) -> Result<(), AppError> {
    ensure_bin("ssh").await?;
    ssh.validate()?;

    // Get the best rsync available with appropriate flags
    let rsync_config = get_rsync_config();

    if let Some(parent) = local_dir.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    tokio::fs::create_dir_all(local_dir).await?;

    let quoted_remote = shell_escape::unix::escape(remote_dir.into()).to_string();
    let remote_spec = format!("{}:{}", ssh.target(), quoted_remote);

    let mut rsh_parts: Vec<String> = vec!["ssh".to_string()];
    rsh_parts.extend(ssh.common_ssh_options());
    // rsync expects a single string after -e.
    let rsh = rsh_parts.join(" ");

    let mut c = Command::new(&rsync_config.path);
    c.arg("-az");
    c.arg("--partial");
    c.arg(&rsync_config.progress_flag);
    c.arg("-e");
    c.arg(rsh);
    c.arg(remote_spec);
    c.arg(local_dir);
    run_checked(c).await?;
    Ok(())
}

pub async fn run_remote_job(
    input: RunVastJobInput,
    ssh: SshSpec,
    default_hf_home_cfg: Option<String>,
) -> Result<RemoteJobMeta, AppError> {
    let _delete_remote = input.delete_remote.unwrap_or(false);
    if input.project_dir.trim().is_empty() {
        return Err(AppError::invalid_input("project_dir is required"));
    }
    if input.command.trim().is_empty() {
        return Err(AppError::invalid_input("command is required"));
    }
    let project_dir = PathBuf::from(input.project_dir.trim());
    if !project_dir.is_dir() {
        return Err(AppError::invalid_input(format!(
            "project_dir is not a directory: {}",
            project_dir.display()
        )));
    }

    ensure_bin("ssh").await?;
    ensure_bin("scp").await?;
    ssh.validate()?;

    // Ensure connectivity + resolve remote HOME so we can avoid '~' issues.
    let remote_home = ssh_bash(&ssh, "printf %s \"$HOME\"")
        .await?
        .trim()
        .to_string();
    if remote_home.is_empty() {
        return Err(AppError::command("Failed to resolve remote $HOME"));
    }

    let do_sync = input.sync.unwrap_or(true);
    let include_data = input.include_data.unwrap_or(false);
    let include_models = input.include_models.unwrap_or(false);
    let include_dotenv = input.include_dotenv.unwrap_or(false);

    let id = Uuid::new_v4().to_string();
    let job_base = format!("{remote_home}/doppio");
    let job_dir = format!("{job_base}/job-{id}");
    let project_root = format!("{job_dir}/project");

    let workdir = match input.workdir.clone().unwrap_or_default().trim().to_string() {
        s if s.is_empty() => project_root.clone(),
        s if s.starts_with('/') => s,
        s => format!("{project_root}/{s}"),
    };

    let output_dir = match input
        .remote_output_dir
        .clone()
        .unwrap_or_default()
        .trim()
        .to_string()
    {
        s if s.is_empty() => format!("{job_dir}/output"),
        s if s.starts_with('/') => s,
        s => format!("{workdir}/{s}"),
    };

    let hf_home = match input.hf_home.clone().unwrap_or_default().trim().to_string() {
        s if !s.is_empty() => {
            if s.starts_with('/') {
                s
            } else if s.starts_with("~/") {
                format!("{remote_home}/{}", s.trim_start_matches("~/"))
            } else {
                // Treat as relative to remote home.
                format!("{remote_home}/{s}")
            }
        }
        _ => {
            let from_cfg = default_hf_home_cfg.unwrap_or_default().trim().to_string();
            if !from_cfg.is_empty() {
                from_cfg
            } else {
                format!("{remote_home}/.cache/huggingface")
            }
        }
    };

    let log_path = format!("{job_dir}/train.log");
    let output_flag = format!("{job_dir}/output_dir.txt");
    let tmux_session = format!(
        "doppio_{}_{}",
        input.instance_id,
        id.chars().take(8).collect::<String>()
    );

    // Create remote dirs.
    ssh_bash(
        &ssh,
        &format!(
            "mkdir -p {}",
            shell_escape::unix::escape(job_dir.clone().into())
        ),
    )
    .await?;
    ssh_bash(
        &ssh,
        &format!(
            "mkdir -p {} {}",
            shell_escape::unix::escape(project_root.clone().into()),
            shell_escape::unix::escape(output_dir.clone().into())
        ),
    )
    .await?;

    // Persist output dir marker for convenience.
    ssh_bash(
        &ssh,
        &format!(
            "printf %s {} > {}",
            shell_escape::unix::escape(output_dir.clone().into()),
            shell_escape::unix::escape(output_flag.clone().into())
        ),
    )
    .await?;

    // Bundle + upload project.
    if do_sync {
        let excludes = parse_excludes(
            input.extra_excludes.clone(),
            include_data,
            include_models,
            include_dotenv,
        );
        let out_dir = default_out_dir();
        let bundle_path = out_dir.join(format!("bundle-{id}.tar.gz"));

        tokio::task::spawn_blocking({
            let project_dir = project_dir.clone();
            let bundle_path = bundle_path.clone();
            move || bundle_project(&project_dir, &bundle_path, &excludes)
        })
        .await
        .map_err(|e| AppError::io(e.to_string()))??;

        let remote_bundle = format!("{job_dir}/bundle.tar.gz");
        scp_upload(&ssh, &bundle_path, &remote_bundle).await?;

        ssh_bash(
            &ssh,
            &format!(
                "tar -xzf {} -C {}",
                shell_escape::unix::escape(remote_bundle.clone().into()),
                shell_escape::unix::escape(project_root.clone().into())
            ),
        )
        .await?;
    }

    // Build run.sh locally and upload.
    let run_sh = default_out_dir().join(format!("run-{id}.sh"));
    if let Some(parent) = run_sh.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let script = format!(
        r#"#!/usr/bin/env bash
set -uo pipefail

export HF_HOME={hf_home}
export TRAINSH_OUTPUT_DIR={output_dir}

mkdir -p "$TRAINSH_OUTPUT_DIR"
mkdir -p {job_dir_esc}

cd {workdir}

(
  set +e
  bash -lc {user_cmd}
  ec=$?
  echo $ec > {exit_code}
  touch {done_flag}
  exit $ec
) 2>&1 | tee -a {log_path}
"#,
        hf_home = shell_escape::unix::escape(hf_home.clone().into()),
        output_dir = shell_escape::unix::escape(output_dir.clone().into()),
        job_dir_esc = shell_escape::unix::escape(job_dir.clone().into()),
        workdir = shell_escape::unix::escape(workdir.clone().into()),
        user_cmd = shell_escape::unix::escape(input.command.trim().into()),
        exit_code = shell_escape::unix::escape(format!("{job_dir}/exit_code").into()),
        done_flag = shell_escape::unix::escape(format!("{job_dir}/done").into()),
        log_path = shell_escape::unix::escape(log_path.clone().into()),
    );
    {
        let mut f = File::create(&run_sh)?;
        f.write_all(script.as_bytes())?;
        f.write_all(b"\n")?;
    }

    let remote_run = format!("{job_dir}/run.sh");
    scp_upload(&ssh, &run_sh, &remote_run).await?;
    ssh_bash(
        &ssh,
        &format!(
            "chmod +x {}",
            shell_escape::unix::escape(remote_run.clone().into())
        ),
    )
    .await?;

    // Ensure tmux exists and start.
    ssh_bash(&ssh, "command -v tmux >/dev/null 2>&1").await?;
    ssh_bash(
        &ssh,
        &format!(
            "tmux new-session -d -s {sess} {run} && tmux set-option -t {sess} -g remain-on-exit on",
            sess = shell_escape::unix::escape(tmux_session.clone().into()),
            run = shell_escape::unix::escape(remote_run.clone().into())
        ),
    )
    .await?;

    // Persist meta locally.
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis().to_string())
        .unwrap_or_else(|_| "0".to_string());

    let meta = RemoteJobMeta {
        ts,
        project_dir: input.project_dir.trim().to_string(),
        command: input.command.trim().to_string(),
        ssh: ssh.clone(),
        remote: RemoteJobRemote {
            workdir: workdir.clone(),
            job_dir: job_dir.clone(),
            log_path: log_path.clone(),
            output_flag: output_flag.clone(),
            output_dir: output_dir.clone(),
            hf_home: hf_home.clone(),
            tmux_session: tmux_session.clone(),
        },
        local_meta_path: "".to_string(), // filled below
    };

    let meta_dir = default_out_dir().join("jobs");
    tokio::fs::create_dir_all(&meta_dir).await?;
    let meta_path = meta_dir.join(format!("job-{id}.json"));
    let mut meta_to_write = meta.clone();
    meta_to_write.local_meta_path = meta_path.to_string_lossy().to_string();
    let raw = serde_json::to_string_pretty(&meta_to_write)
        .map_err(|e| AppError::io(format!("Failed to serialize job meta: {e}")))?;
    tokio::fs::write(&meta_path, format!("{raw}\n")).await?;

    Ok(meta_to_write)
}

pub async fn tail_logs(
    ssh: SshSpec,
    log_path: String,
    lines: usize,
) -> Result<Vec<String>, AppError> {
    let out = ssh_bash(
        &ssh,
        &format!(
            "if test -f {p}; then tail -n {n} {p}; fi",
            p = shell_escape::unix::escape(log_path.into()),
            n = lines
        ),
    )
    .await?;
    Ok(out.lines().map(|s| s.to_string()).collect())
}

pub async fn fetch_gpu(ssh: SshSpec) -> Result<Vec<GpuRow>, AppError> {
    let out = ssh_bash(
    &ssh,
    "if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi --query-gpu=index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw --format=csv,noheader,nounits; fi",
  )
  .await?;

    let mut rows: Vec<GpuRow> = vec![];
    for line in out.lines().map(|s| s.trim()).filter(|s| !s.is_empty()) {
        let parts: Vec<String> = line.split(',').map(|s| s.trim().to_string()).collect();
        if parts.len() < 8 {
            continue;
        }
        rows.push(GpuRow {
            index: parts[0].clone(),
            name: parts[1].clone(),
            util_gpu: parts[2].clone(),
            util_mem: parts[3].clone(),
            mem_used: parts[4].clone(),
            mem_total: parts[5].clone(),
            temp: parts[6].clone(),
            power: parts[7].clone(),
        });
    }
    Ok(rows)
}

pub async fn get_exit_code(ssh: SshSpec, job_dir: String) -> Result<Option<i32>, AppError> {
    let out = ssh_bash(
        &ssh,
        &format!(
            "if test -f {p}; then cat {p}; fi",
            p = shell_escape::unix::escape(format!("{job_dir}/exit_code").into())
        ),
    )
    .await?;
    let s = out.trim();
    if s.is_empty() {
        return Ok(None);
    }
    let v: i32 = s
        .parse()
        .map_err(|_| AppError::io(format!("Invalid exit_code: {s}")))?;
    Ok(Some(v))
}

pub async fn download_dir(
    ssh: SshSpec,
    remote_dir: String,
    local_dir: String,
    delete: bool,
) -> Result<(), AppError> {
    let local_dir = PathBuf::from(local_dir);

    // Prefer rsync if available (faster, incremental), fallback to scp.
    let rsync_ok = which::which("rsync").is_ok() && which::which("ssh").is_ok();
    if rsync_ok {
        if let Err(_) = rsync_download_dir(&ssh, &remote_dir, &local_dir).await {
            scp_download_dir(&ssh, &remote_dir, &local_dir).await?;
        }
    } else {
        scp_download_dir(&ssh, &remote_dir, &local_dir).await?;
    }

    if delete {
        ssh_bash(
            &ssh,
            &format!("rm -rf {}", shell_escape::unix::escape(remote_dir.into())),
        )
        .await?;
    }

    Ok(())
}

pub async fn list_local_jobs() -> Result<Vec<RemoteJobMeta>, AppError> {
    let meta_dir = default_out_dir().join("jobs");
    if !meta_dir.exists() {
        return Ok(vec![]);
    }

    let mut out: Vec<RemoteJobMeta> = vec![];
    let mut rd = tokio::fs::read_dir(&meta_dir).await?;
    while let Some(ent) = rd.next_entry().await? {
        let path = ent.path();
        if path.extension().and_then(|s| s.to_str()) != Some("json") {
            continue;
        }
        let raw = match tokio::fs::read_to_string(&path).await {
            Ok(s) => s,
            Err(_) => continue,
        };
        let mut meta: RemoteJobMeta = match serde_json::from_str(&raw) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if meta.local_meta_path.trim().is_empty() {
            meta.local_meta_path = path.to_string_lossy().to_string();
        }
        out.push(meta);
    }

    out.sort_by(|a, b| {
        let ta = a.ts.parse::<i128>().unwrap_or(0);
        let tb = b.ts.parse::<i128>().unwrap_or(0);
        tb.cmp(&ta)
    });

    Ok(out)
}
