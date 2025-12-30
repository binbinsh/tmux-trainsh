//! Google Drive mount operations for remote hosts
//!
//! Provides operations to mount/unmount Google Drive on remote hosts (Colab/Vast.ai)
//! using rclone.

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

use crate::config;
use crate::error::AppError;
use crate::host;
use crate::storage::{Storage, StorageBackend};

use super::ssh as ssh_ops;

/// Mount Google Drive on a remote host using rclone
/// Returns success message on success
pub async fn mount(
    host_id: &str,
    storage_id: &str,
    mount_path: &str,
    gdrive_path: Option<&str>,
    vfs_cache: bool,
    cache_mode: &str,
    background: bool,
    progress: Option<std::sync::Arc<dyn Fn(&str) + Send + Sync>>,
) -> Result<String, AppError> {
    let report = |msg: &str| {
        if let Some(cb) = &progress {
            cb(msg);
        }
    };

    // Verify host has SSH
    let _ = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    // Get storage configuration
    let storage = get_storage_from_file(storage_id).await?;
    let (client_id, client_secret, token) = match &storage.backend {
        StorageBackend::GoogleDrive {
            client_id,
            client_secret,
            token,
            ..
        } => {
            let client_id = client_id
                .clone()
                .ok_or_else(|| AppError::invalid_input("Google Drive storage missing client_id"))?;
            let client_secret = client_secret.clone().ok_or_else(|| {
                AppError::invalid_input("Google Drive storage missing client_secret")
            })?;
            let token = token.clone().ok_or_else(|| {
                AppError::invalid_input(
                    "Google Drive storage missing token - please complete OAuth first",
                )
            })?;
            (client_id, client_secret, token)
        }
        _ => {
            return Err(AppError::invalid_input(format!(
                "Storage {} is not a Google Drive storage",
                storage_id
            )));
        }
    };

    // Install rclone on remote if not present
    report("Installing rclone if needed");
    install_rclone_if_needed(host_id).await?;

    // Create rclone config on remote host
    report("Configuring OAuth credentials");
    let config_content = create_rclone_config(&client_id, &client_secret, &token);
    let config_path = "~/.config/rclone/rclone.conf";

    // Ensure config directory exists and write config
    let setup_commands = format!(
        r#"mkdir -p ~/.config/rclone && cat > {} << 'RCLONE_CONFIG_EOF'
{}
RCLONE_CONFIG_EOF"#,
        config_path, config_content
    );

    run_ssh(host_id, &setup_commands).await?;

    // Create mount point
    report("Preparing mount point");
    run_ssh(host_id, &format!("mkdir -p {}", mount_path)).await?;

    // Build rclone mount command
    let gdrive_remote = if let Some(path) = gdrive_path {
        if path.is_empty() {
            "gdrive:".to_string()
        } else {
            format!("gdrive:{}", path)
        }
    } else {
        "gdrive:".to_string()
    };

    let mut mount_cmd = format!("rclone mount {} {}", gdrive_remote, mount_path);

    // Add options
    mount_cmd.push_str(" --allow-other --allow-non-empty");

    if vfs_cache {
        mount_cmd.push_str(" --vfs-cache-mode ");
        mount_cmd.push_str(cache_mode);
        mount_cmd.push_str(" --vfs-cache-max-age 1h");
        mount_cmd.push_str(" --vfs-read-chunk-size 64M");
        mount_cmd.push_str(" --vfs-read-chunk-size-limit 1G");
    }

    // Add buffer settings for better performance
    mount_cmd.push_str(" --buffer-size 64M");
    mount_cmd.push_str(" --transfers 4");

    // Ensure PATH includes ~/bin for fusermount3 if installed there
    let path_prefix = "export PATH=\"$HOME/bin:$PATH\"; ";

    if background {
        // Run in background using nohup and disown
        mount_cmd = format!(
            "{}nohup {} > /tmp/rclone-mount.log 2>&1 & disown",
            path_prefix, mount_cmd
        );
    } else {
        mount_cmd = format!("{}{}", path_prefix, mount_cmd);
    }

    // Execute mount command
    report("Starting rclone mount");
    run_ssh(host_id, &mount_cmd).await?;

    // Verify mount (give it a moment to initialize)
    report("Verifying mount");
    tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;

    // Step 1: Check if it's a mount point
    let check_cmd = format!(
        "mountpoint -q {} && echo 'mounted' || echo 'not mounted'",
        mount_path
    );
    let result = run_ssh(host_id, &check_cmd).await?;

    if !result.contains("mounted") {
        // Check rclone log for errors
        let log = run_ssh(host_id, "cat /tmp/rclone-mount.log 2>/dev/null | tail -30")
            .await
            .unwrap_or_default();

        return Err(AppError::command(format!(
            "Failed to mount Google Drive at {}. Mount point not created.\nLog:\n{}",
            mount_path, log
        )));
    }

    // Step 2: Try to actually list the directory to verify rclone is working
    // This catches cases where mount point exists but rclone can't access Drive
    let list_cmd = format!(
        "timeout 10 ls {} 2>&1 || echo 'RCLONE_LIST_FAILED'",
        mount_path
    );
    let list_result = run_ssh(host_id, &list_cmd).await?;

    if list_result.contains("RCLONE_LIST_FAILED")
        || list_result.contains("Transport endpoint is not connected")
    {
        // Mount point exists but rclone is broken - check log
        let log = run_ssh(host_id, "cat /tmp/rclone-mount.log 2>/dev/null | tail -30")
            .await
            .unwrap_or_default();

        // Also check rclone process status
        let ps_result = run_ssh(
            host_id,
            "ps aux | grep 'rclone mount' | grep -v grep || echo 'no rclone process'",
        )
        .await
        .unwrap_or_default();

        return Err(AppError::command(format!(
            "Google Drive mounted at {} but cannot access files.\n\nRclone log:\n{}\n\nProcess status:\n{}",
            mount_path, log, ps_result
        )));
    }

    // Log what we found for debugging
    let contents_preview = if list_result.trim().is_empty() {
        "(empty)".to_string()
    } else {
        list_result.lines().take(5).collect::<Vec<_>>().join(", ")
    };
    eprintln!(
        "[gdrive_mount] Mount successful at {}. Contents: {}",
        mount_path, contents_preview
    );
    report("Mount verified");

    // Return success message for display in terminal
    Ok(format!(
        "Google Drive successfully mounted at {}\nContents preview: {}",
        mount_path, contents_preview
    ))
}

/// Unmount Google Drive from a remote host
pub async fn unmount(host_id: &str, mount_path: &str) -> Result<(), AppError> {
    // Try fusermount first (Linux), then umount
    let unmount_cmd = format!(
        "fusermount -uz {} 2>/dev/null || umount -l {} 2>/dev/null || true",
        mount_path, mount_path
    );

    run_ssh(host_id, &unmount_cmd).await?;

    // Kill any lingering rclone processes for this mount
    let kill_cmd = format!(
        "pkill -f 'rclone mount.*{}' 2>/dev/null || true",
        mount_path.replace('/', r"\/")
    );
    run_ssh(host_id, &kill_cmd).await?;

    Ok(())
}

/// Install rclone on remote host if not already installed
async fn install_rclone_if_needed(host_id: &str) -> Result<(), AppError> {
    // Check if rclone is installed
    let check = run_ssh(host_id, "which rclone 2>/dev/null || echo 'not found'").await?;

    if check.contains("not found") {
        // Install rclone using the official script
        let install_cmd = r#"curl -s https://rclone.org/install.sh | sudo bash 2>/dev/null || {
            # Fallback for non-root: install to user directory
            curl -O https://downloads.rclone.org/rclone-current-linux-amd64.zip && \
            unzip -o rclone-current-linux-amd64.zip && \
            mkdir -p ~/bin && \
            cp rclone-*-linux-amd64/rclone ~/bin/ && \
            chmod +x ~/bin/rclone && \
            rm -rf rclone-current-linux-amd64.zip rclone-*-linux-amd64 && \
            echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
        }"#;

        run_ssh(host_id, install_cmd).await?;

        // Verify installation
        let verify = run_ssh(host_id, "which rclone || ~/bin/rclone version 2>/dev/null").await?;
        if verify.is_empty() && !verify.contains("rclone") {
            return Err(AppError::command("Failed to install rclone on remote host"));
        }
    }

    // Ensure fuse3 is available for mounting (rclone requires fusermount3)
    let fuse3_check = run_ssh(host_id, "which fusermount3 2>/dev/null || echo 'not found'").await?;
    if fuse3_check.contains("not found") {
        eprintln!("[gdrive_mount] fusermount3 not found, installing fuse3...");

        // Install fuse3 package - more robust installation script
        let install_fuse = r#"
set -e
echo "[fuse3] Starting fuse3 installation..."

# Function to check if fusermount3 exists
check_fuse3() {
    which fusermount3 >/dev/null 2>&1 || [ -x /usr/bin/fusermount3 ] || [ -x ~/bin/fusermount3 ]
}

# Already installed?
if check_fuse3; then
    echo "[fuse3] Already installed"
    exit 0
fi

# Try apt (Debian/Ubuntu/Colab)
if command -v apt-get >/dev/null 2>&1; then
    echo "[fuse3] Using apt-get..."
    sudo apt-get update -qq 2>/dev/null || true
    if sudo apt-get install -y fuse3 2>/dev/null; then
        echo "[fuse3] Installed fuse3 via apt"
    else
        echo "[fuse3] fuse3 not available, trying fuse..."
        sudo apt-get install -y fuse 2>/dev/null || true
    fi
fi

# Try yum/dnf (RHEL/CentOS/Fedora)
if ! check_fuse3 && command -v yum >/dev/null 2>&1; then
    echo "[fuse3] Using yum..."
    sudo yum install -y fuse3 2>/dev/null || sudo yum install -y fuse 2>/dev/null || true
fi

if ! check_fuse3 && command -v dnf >/dev/null 2>&1; then
    echo "[fuse3] Using dnf..."
    sudo dnf install -y fuse3 2>/dev/null || sudo dnf install -y fuse 2>/dev/null || true
fi

# Create symlink if fusermount exists but fusermount3 doesn't
if ! check_fuse3; then
    echo "[fuse3] Creating symlink..."
    if [ -x /usr/bin/fusermount ]; then
        sudo ln -sf /usr/bin/fusermount /usr/bin/fusermount3 2>/dev/null || {
            mkdir -p ~/bin
            ln -sf /usr/bin/fusermount ~/bin/fusermount3
            export PATH="$HOME/bin:$PATH"
        }
    fi
fi

# Final check
if check_fuse3; then
    echo "[fuse3] Installation successful"
    which fusermount3 2>/dev/null || echo "fusermount3 at ~/bin/fusermount3"
else
    echo "[fuse3] ERROR: Could not install fuse3"
    exit 1
fi
"#;
        let install_result = run_ssh(host_id, install_fuse).await?;
        eprintln!("[gdrive_mount] fuse3 install output: {}", install_result);

        // Verify fuse is now available
        let verify_fuse = run_ssh(host_id, "which fusermount3 2>/dev/null || [ -x ~/bin/fusermount3 ] && echo 'found' || echo 'not found'").await?;
        if verify_fuse.contains("not found") {
            return Err(AppError::command(
                "Failed to install fuse3 on remote host. Please install fuse3 manually: sudo apt install fuse3"
            ));
        }
    } else {
        eprintln!("[gdrive_mount] fusermount3 found: {}", fuse3_check.trim());
    }

    Ok(())
}

/// Create rclone config content for Google Drive
fn create_rclone_config(client_id: &str, client_secret: &str, token: &str) -> String {
    // Token must be a valid JSON string - rclone expects it as-is without extra quotes
    // But we need to ensure it's on a single line
    let token_single_line = token.replace('\n', "").replace('\r', "");
    format!(
        r#"[gdrive]
type = drive
client_id = {}
client_secret = {}
scope = drive
token = {}
team_drive = 
"#,
        client_id, client_secret, token_single_line
    )
}

/// Helper to get storage from file system
async fn get_storage_from_file(storage_id: &str) -> Result<Storage, AppError> {
    let data_dir = PathBuf::from(config::get_data_dir_path());
    let storages_path = data_dir.join("storages.json");

    let content = tokio::fs::read_to_string(&storages_path)
        .await
        .map_err(|e| AppError::io(format!("Failed to read storages file: {}", e)))?;

    let storages: HashMap<String, Storage> = serde_json::from_str(&content)
        .map_err(|e| AppError::io(format!("Failed to parse storages file: {}", e)))?;

    storages
        .get(storage_id)
        .cloned()
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))
}

/// Check if Google Drive is mounted at the specified path
pub async fn is_mounted(host_id: &str, mount_path: &str) -> Result<bool, AppError> {
    let check_cmd = format!("mountpoint -q {} && echo 'yes' || echo 'no'", mount_path);
    let result = run_ssh(host_id, &check_cmd).await?;

    Ok(result.trim() == "yes")
}

/// Find the first configured Google Drive storage
pub async fn find_gdrive_storage() -> Result<String, AppError> {
    let data_dir = PathBuf::from(config::get_data_dir_path());
    let storages_path = data_dir.join("storages.json");

    let content = tokio::fs::read_to_string(&storages_path)
        .await
        .map_err(|e| AppError::io(format!("Failed to read storages file: {}", e)))?;

    let storages: HashMap<String, Storage> = serde_json::from_str(&content)
        .map_err(|e| AppError::io(format!("Failed to parse storages file: {}", e)))?;

    for (id, storage) in storages {
        if matches!(storage.backend, StorageBackend::GoogleDrive { .. }) {
            return Ok(id);
        }
    }

    Err(AppError::not_found(
        "No Google Drive storage configured. Please add a Google Drive storage in Settings → Storage."
    ))
}

/// Helper to run SSH command and return output as string
async fn run_ssh(host_id: &str, command: &str) -> Result<String, AppError> {
    let empty_env = HashMap::new();
    let result = ssh_ops::execute_command(host_id, command, None, &empty_env).await?;
    Ok(result.unwrap_or_default())
}
