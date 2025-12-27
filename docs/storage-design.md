# Storage Management System Design

## Overview

Doppio 的统一存储管理系统，基于 rclone 作为后端引擎，提供图形化的文件管理和传输功能。

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                              │
├─────────────────────────────────────────────────────────────────────┤
│  StoragePage    │  FileBrowser   │  TransferPanel  │  SyncConfig    │
│  (storage list) │  (dual-pane)   │  (task queue)   │  (rules)       │
└────────┬────────┴───────┬────────┴────────┬────────┴───────┬────────┘
         │                │                 │                │
         └────────────────┴─────────────────┴────────────────┘
                                   │
                    Tauri IPC (invoke/listen)
                                   │
┌─────────────────────────────────────────────────────────────────────┐
│                         Rust Backend                                 │
├─────────────────────────────────────────────────────────────────────┤
│  storage.rs     │  transfer.rs  │  rclone_wrapper.rs                │
│  (CRUD storage) │  (task mgmt)  │  (librclone RPC)                  │
└────────┬────────┴───────┬───────┴───────────┬───────────────────────┘
         │                │                   │
         └────────────────┴───────────────────┘
                          │
                    librclone (embedded)
                          │
    ┌─────────────────────┼─────────────────────┐
    │                     │                     │
    ▼                     ▼                     ▼
┌────────┐          ┌──────────┐          ┌──────────────┐
│ Local  │          │ SSH/SFTP │          │ Cloud        │
│ Files  │          │ Remotes  │          │ (S3/GCS/R2)  │
└────────┘          └──────────┘          └──────────────┘
```

## Storage Types

### 1. Local Storage
- 本地文件系统访问
- 支持选择特定目录作为 "storage root"
- 用于管理项目文件、模型缓存等

### 2. SSH Remote Storage  
- 通过 SSH/SFTP 连接到远程主机
- 复用现有 Host 的 SSH 配置
- 支持 cloudflared 代理（Colab 兼容）

### 3. Google Drive
- 直接通过 rclone 的 Google Drive backend
- OAuth 授权流程
- **Colab 特殊处理**: 检测并使用已挂载的 `/content/drive`

### 4. Cloudflare R2
- S3 兼容 API
- 需要配置 Access Key + Secret + Endpoint

### 5. Google Cloud Storage
- 支持 Service Account 或 OAuth
- 适合大规模数据存储

### 6. NAS Storage (SAMBA/SMB)
- SMB/CIFS 协议
- 局域网文件共享

---

## Data Models

### StorageBackend (Rust Enum)
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum StorageBackend {
    Local {
        root_path: String,
    },
    SshRemote {
        host_id: String,  // Reference to existing Host
        root_path: String,
    },
    GoogleDrive {
        client_id: Option<String>,
        client_secret: Option<String>,
        token: Option<String>,  // OAuth token (stored encrypted)
        root_folder_id: Option<String>,
    },
    CloudflareR2 {
        account_id: String,
        access_key_id: String,
        secret_access_key: String,  // stored encrypted
        bucket: String,
    },
    GoogleCloudStorage {
        project_id: String,
        service_account_json: Option<String>,  // stored encrypted
        bucket: String,
    },
    Smb {
        host: String,
        share: String,
        user: Option<String>,
        password: Option<String>,  // stored encrypted
        domain: Option<String>,
    },
}
```

### Storage (Main Model)
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Storage {
    pub id: String,
    pub name: String,
    pub icon: Option<String>,  // emoji or icon name
    pub backend: StorageBackend,
    pub readonly: bool,
    pub created_at: String,
    pub last_accessed_at: Option<String>,
}
```

### FileEntry
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileEntry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size: u64,
    pub modified_at: Option<String>,
    pub mime_type: Option<String>,
}
```

### TransferTask
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferTask {
    pub id: String,
    pub source_storage_id: String,
    pub source_path: String,
    pub dest_storage_id: String,
    pub dest_path: String,
    pub operation: TransferOperation,
    pub status: TransferStatus,
    pub progress: TransferProgress,
    pub created_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TransferOperation {
    Copy,      // Keep source
    Move,      // Delete source after copy
    Sync,      // Mirror (with delete)
    SyncNoDelete,  // Mirror (no delete)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum TransferStatus {
    Queued,
    Running,
    Paused,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferProgress {
    pub files_total: u64,
    pub files_done: u64,
    pub bytes_total: u64,
    pub bytes_done: u64,
    pub speed_bps: u64,
    pub eta_seconds: Option<u64>,
    pub current_file: Option<String>,
}
```

### SyncRule (for automated syncing)
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncRule {
    pub id: String,
    pub name: String,
    pub source_storage_id: String,
    pub source_path: String,
    pub dest_storage_id: String,
    pub dest_path: String,
    pub direction: SyncDirection,
    pub filters: SyncFilters,
    pub schedule: Option<SyncSchedule>,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SyncDirection {
    OneWay,        // Source -> Dest
    TwoWay,        // Bidirectional
    Mirror,        // Source -> Dest with delete
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncFilters {
    pub include_patterns: Vec<String>,
    pub exclude_patterns: Vec<String>,
    pub min_size: Option<u64>,
    pub max_size: Option<u64>,
    pub min_age: Option<String>,  // duration
    pub max_age: Option<String>,
}
```

---

## API Design (Tauri Commands)

### Storage CRUD
```rust
#[tauri::command]
async fn storage_list() -> Result<Vec<Storage>, AppError>;

#[tauri::command]
async fn storage_get(id: String) -> Result<Storage, AppError>;

#[tauri::command]
async fn storage_create(config: StorageCreateInput) -> Result<Storage, AppError>;

#[tauri::command]
async fn storage_update(id: String, config: StorageUpdateInput) -> Result<Storage, AppError>;

#[tauri::command]
async fn storage_delete(id: String) -> Result<(), AppError>;

#[tauri::command]
async fn storage_test(id: String) -> Result<StorageTestResult, AppError>;
```

### File Operations
```rust
#[tauri::command]
async fn storage_list_files(
    storage_id: String,
    path: String,
    recursive: bool,
) -> Result<Vec<FileEntry>, AppError>;

#[tauri::command]
async fn storage_mkdir(
    storage_id: String,
    path: String,
) -> Result<(), AppError>;

#[tauri::command]
async fn storage_delete_file(
    storage_id: String,
    path: String,
) -> Result<(), AppError>;

#[tauri::command]
async fn storage_rename(
    storage_id: String,
    old_path: String,
    new_path: String,
) -> Result<(), AppError>;

#[tauri::command]
async fn storage_get_info(
    storage_id: String,
    path: String,
) -> Result<FileEntry, AppError>;

#[tauri::command]
async fn storage_read_text(
    storage_id: String,
    path: String,
    max_size: Option<u64>,
) -> Result<String, AppError>;
```

### Transfer Operations
```rust
#[tauri::command]
async fn transfer_create(
    source_storage_id: String,
    source_paths: Vec<String>,
    dest_storage_id: String,
    dest_path: String,
    operation: TransferOperation,
) -> Result<TransferTask, AppError>;

#[tauri::command]
async fn transfer_list() -> Result<Vec<TransferTask>, AppError>;

#[tauri::command]
async fn transfer_get(id: String) -> Result<TransferTask, AppError>;

#[tauri::command]
async fn transfer_pause(id: String) -> Result<(), AppError>;

#[tauri::command]
async fn transfer_resume(id: String) -> Result<(), AppError>;

#[tauri::command]
async fn transfer_cancel(id: String) -> Result<(), AppError>;

#[tauri::command]
async fn transfer_retry(id: String) -> Result<TransferTask, AppError>;
```

### Sync Rules
```rust
#[tauri::command]
async fn sync_rule_list() -> Result<Vec<SyncRule>, AppError>;

#[tauri::command]
async fn sync_rule_create(config: SyncRuleConfig) -> Result<SyncRule, AppError>;

#[tauri::command]
async fn sync_rule_update(id: String, config: SyncRuleConfig) -> Result<SyncRule, AppError>;

#[tauri::command]
async fn sync_rule_delete(id: String) -> Result<(), AppError>;

#[tauri::command]
async fn sync_rule_run_now(id: String) -> Result<TransferTask, AppError>;
```

### Google Drive OAuth (special flow)
```rust
#[tauri::command]
async fn gdrive_get_auth_url(client_id: Option<String>) -> Result<String, AppError>;

#[tauri::command]
async fn gdrive_exchange_code(code: String, client_id: Option<String>) -> Result<String, AppError>;
```

---

## Frontend Components

### StoragePage (`/storage`)
主页面，显示所有已配置的存储：
- 存储卡片列表（图标、名称、类型、状态）
- 快速操作：测试连接、打开文件浏览器、编辑、删除
- "Add Storage" 按钮打开配置向导

### AddStorageModal
分步骤向导：
1. 选择存储类型
2. 配置连接参数
3. 测试连接
4. 命名并保存

### FileBrowserPage (`/storage/:id/browse`)
双面板文件浏览器（类似 Commander 风格）：
- 左侧：当前存储的文件列表
- 右侧：可选择另一个存储进行对比/传输
- 工具栏：刷新、新建文件夹、删除、复制、移动、同步
- 支持拖拽选择和传输
- 面包屑导航
- 文件预览（文本、图片）

### TransferPanel
底部抽屉或侧边栏：
- 当前进行中的传输任务
- 已完成/失败的任务历史
- 进度条、速度、ETA
- 暂停/恢复/取消按钮

### SyncRulesPage (`/storage/sync`)
同步规则管理：
- 规则列表
- 创建/编辑规则
- 手动触发同步
- 查看同步历史

---

## Colab Google Drive 特殊处理

### 场景
当 Host 是 Colab 类型时，Google Drive 可能已经挂载到 `/content/drive`。

### 检测策略
```rust
async fn detect_colab_drive(host: &Host) -> Result<Option<String>, AppError> {
    // Check if /content/drive/MyDrive exists
    let ssh = host.ssh.as_ref().ok_or(...)?;
    let output = ssh_exec(ssh, "test -d /content/drive/MyDrive && echo 'mounted'").await?;
    if output.trim() == "mounted" {
        Ok(Some("/content/drive/MyDrive".to_string()))
    } else {
        Ok(None)
    }
}
```

### 挂载命令（如果未挂载）
生成 Python 代码供用户在 Colab 中执行：
```python
from google.colab import drive
drive.mount('/content/drive')
```

### 作为存储使用
当检测到 Colab 已挂载 Drive 时，自动创建一个 "Colab Drive" 存储：
```rust
StorageBackend::SshRemote {
    host_id: colab_host_id,
    root_path: "/content/drive/MyDrive".to_string(),
}
```

---

## UI/UX Design Notes

### 存储页面卡片设计
```
┌────────────────────────────────────┐
│ 🗂️  My Local Projects              │
│ ─────────────────────────────────  │
│ Type: Local                        │
│ Path: ~/Projects                   │
│ Status: ● Available                │
│                                    │
│ [Browse] [Edit] [···]              │
└────────────────────────────────────┘
```

### 文件浏览器布局
```
┌─────────────────────────────────────────────────────────────┐
│ 📁 My Local > Projects > ml-training          [⟲] [📁+] [🗑] │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────┐ ┌─────────────────────────────┐ │
│ │ Local Storage           │ │ Vast GPU Server            │ │
│ ├─────────────────────────┤ ├─────────────────────────────┤ │
│ │ 📁 data/                │ │ 📁 workspace/              │ │
│ │ 📁 models/              │ │ 📁 outputs/                │ │
│ │ 📁 src/                 │ │ 📄 train.py               │ │
│ │ 📄 requirements.txt     │ │ 📄 config.yaml            │ │
│ │ 📄 train.py             │ │                           │ │
│ │                         │ │                           │ │
│ └─────────────────────────┘ └─────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ [← Copy] [Copy →] [← Sync] [Sync →]                        │
└─────────────────────────────────────────────────────────────┘
```

### 传输进度面板
```
┌─────────────────────────────────────────────────────────────┐
│ Transfers (2 active, 5 completed)                     [▾]  │
├─────────────────────────────────────────────────────────────┤
│ ▶ Syncing models/ → vast-server:/models                    │
│   ████████████░░░░░░░░  62% · 1.2 GB/s · ETA 3:42         │
│   [⏸ Pause] [✕ Cancel]                                     │
│ ─────────────────────────────────────────────────────────── │
│ ▶ Copying dataset.tar.gz → r2://ml-data/                   │
│   ██████░░░░░░░░░░░░░░  32% · 850 MB/s · ETA 12:05        │
│   [⏸ Pause] [✕ Cancel]                                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Priority

### Phase 1: Core Infrastructure
1. `storage.rs` - Storage CRUD 和持久化
2. `rclone_wrapper.rs` - 封装 librclone RPC 调用
3. 基本 Tauri commands

### Phase 2: File Operations
1. 文件列表、创建、删除、重命名
2. SSH Remote 和 Local 存储实现
3. 基础文件浏览器 UI

### Phase 3: Transfer System
1. 传输任务队列
2. 进度事件流
3. 暂停/恢复/取消
4. 传输面板 UI

### Phase 4: Cloud Storage
1. Google Drive OAuth 流程
2. Cloudflare R2 配置
3. Google Cloud Storage
4. SMB/NAS

### Phase 5: Advanced Features
1. Sync Rules
2. Colab Drive 自动检测
3. 文件预览
4. 拖拽操作

---

## Security Considerations

1. **敏感信息加密**: API keys、tokens 使用 Tauri 的 secure storage 或系统 keychain
2. **OAuth Tokens**: 定期刷新，安全存储
3. **权限最小化**: 只请求必要的 OAuth scopes
4. **路径验证**: 防止路径遍历攻击

---

## Dependencies

已有:
- `librclone = "0.9"` ✓

可能需要添加:
- `keyring` 或 `secrecy` - 安全存储敏感信息
- `notify` - 文件系统监控（可选，用于自动同步）

