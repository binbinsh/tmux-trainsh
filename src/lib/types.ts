// ============================================================
// Connection & Host Types
// ============================================================

export type HostType = "vast" | "colab" | "custom";

export type HostStatus = "online" | "offline" | "connecting" | "error";

export type SshSpec = {
  host: string;
  port: number;
  user: string;
  keyPath: string | null;
  extraArgs: string[];
  // Aliases for backwards compatibility
  key_path?: string | null;
  extra_args?: string[];
};

export type GpuCapability = {
  architecture: string;
  compute_capability: string;
  cuda_cores: number;
  tensor_cores: number | null;
  tensor_core_gen: number | null;
  rt_cores: number | null;
  rt_core_gen: number | null;
  memory_bandwidth_gbps: number | null;
  // Theoretical peak performance (TFLOPS, with sparsity where applicable)
  fp32_tflops: number | null;
  fp16_tflops: number | null;
  bf16_tflops: number | null;
  fp8_tflops: number | null;
  fp4_tflops: number | null;  // Blackwell 5th gen Tensor Core
  int8_tops: number | null;
  tf32_tflops: number | null;
};

export type GpuInfo = {
  index: number;
  name: string;
  memory_total_mb: number;
  memory_used_mb: number | null;
  utilization: number | null;
  temperature: number | null;
  // Extended runtime info
  driver_version: string | null;
  power_draw_w: number | null;
  power_limit_w: number | null;
  clock_graphics_mhz: number | null;
  clock_memory_mhz: number | null;
  fan_speed: number | null;
  compute_mode: string | null;
  pcie_gen: number | null;
  pcie_width: number | null;
  // Static capability info
  capability: GpuCapability | null;
};

export type DiskInfo = {
  mount_point: string;
  total_gb: number;
  used_gb: number;
  available_gb: number;
};

export type SystemInfo = {
  cpu_model: string | null;
  cpu_cores: number | null;
  memory_total_gb: number | null;
  memory_used_gb: number | null;
  memory_available_gb: number | null;
  disks: DiskInfo[];
  gpu_list: GpuInfo[];
  os: string | null;
  hostname: string | null;
};

export type Host = {
  id: string;
  name: string;
  type: HostType;
  status: HostStatus;
  ssh: SshSpec | null;
  // Vast specific
  vast_instance_id: number | null;
  // Colab specific
  cloudflared_hostname: string | null;
  // Environment variables to set on connection
  env_vars: Record<string, string>;
  // System information
  gpu_name: string | null;
  num_gpus: number | null;
  system_info: SystemInfo | null;
  created_at: string;
  last_seen_at: string | null;
};

export type HostConfig = {
  name: string;
  type: HostType;
  // SSH connection
  ssh_host: string | null;
  ssh_port: number | null;
  ssh_user: string | null;
  ssh_key_path: string | null;
  // Vast specific
  vast_instance_id: number | null;
  // Colab specific
  cloudflared_hostname: string | null;
  cloudflared_path: string | null;
};

export type ScamalyticsMetric = number | string;

export type ScamalyticsProxy = {
  is_datacenter: boolean | null;
  is_vpn: boolean | null;
  is_apple_icloud_private_relay: boolean | null;
  is_amazon_aws: boolean | null;
  is_google: boolean | null;
};

export type ScamalyticsCore = {
  status: string | null;
  ip: string | null;
  scamalytics_risk: string | null;
  scamalytics_score: ScamalyticsMetric | null;
  scamalytics_isp: string | null;
  scamalytics_org: string | null;
  scamalytics_isp_score: ScamalyticsMetric | null;
  scamalytics_isp_risk: string | null;
  is_blacklisted_external: boolean | null;
  scamalytics_url: string | null;
  scamalytics_proxy: ScamalyticsProxy | null;
};

export type ScamalyticsIpSource = {
  ip_country_name: string | null;
  ip_country_code: string | null;
  ip_city: string | null;
  ip_state_name: string | null;
  ip_district_name: string | null;
  asn: string | null;
  as_name: string | null;
  proxy_type: string | null;
};

export type ScamalyticsFirehol = {
  is_proxy: boolean | null;
};

export type ScamalyticsX4Bnet = {
  is_datacenter: boolean | null;
  is_vpn: boolean | null;
  is_tor: boolean | null;
  is_blacklisted_spambot: boolean | null;
  is_bot_operamini: boolean | null;
  is_bot_semrush: boolean | null;
};

export type ScamalyticsGoogle = {
  is_google_general: boolean | null;
  is_googlebot: boolean | null;
  is_special_crawler: boolean | null;
  is_user_triggered_fetcher: boolean | null;
};

export type ScamalyticsExternalDatasources = {
  dbip: ScamalyticsIpSource | null;
  maxmind_geolite2: ScamalyticsIpSource | null;
  ip2proxy: ScamalyticsIpSource | null;
  ip2proxy_lite: ScamalyticsIpSource | null;
  firehol: ScamalyticsFirehol | null;
  x4bnet: ScamalyticsX4Bnet | null;
  google: ScamalyticsGoogle | null;
};

export type ScamalyticsInfo = {
  scamalytics: ScamalyticsCore | null;
  external_datasources: ScamalyticsExternalDatasources | null;
};

// ============================================================
// Session & Task Types
// ============================================================

export type SessionStatus =
  | "created"
  | "uploading"
  | "running"
  | "completed"
  | "failed"
  | "stopped";

export type SyncMode = "rsync" | "full";

export type SourceConfig = {
  local_path: string;
  use_gitignore: boolean;
  extra_excludes: string[];
  sync_mode: SyncMode;
};

export type DataConfig = {
  enabled: boolean;
  local_path: string | null;
  remote_path: string | null;
  skip_existing: boolean;
};

export type EnvConfig = {
  requirements_txt: string | null;
  conda_env: string | null;
  env_vars: Record<string, string>;
  setup_commands: string[];
};

export type RunConfig = {
  command: string;
  workdir: string | null;
  tmux_session: string | null;
};

export type OutputConfig = {
  model_path: string | null;
  log_path: string | null;
  auto_download: boolean;
};

export type MonitorConfig = {
  parse_stdout: boolean;
  tensorboard_dir: string | null;
  auto_shutdown_timeout: number | null; // minutes
  completion_patterns: string[];
};

export type SessionConfig = {
  name: string;
  host_id: string;
  source: SourceConfig;
  data: DataConfig;
  env: EnvConfig;
  run: RunConfig;
  output: OutputConfig;
  monitor: MonitorConfig;
};

export type Session = {
  id: string;
  name: string;
  host_id: string;
  host_name: string;
  status: SessionStatus;
  config: SessionConfig;
  // Runtime info
  remote_workdir: string | null;
  remote_job_dir: string | null;
  remote_log_path: string | null;
  tmux_session: string | null;
  // Timestamps
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  // Exit info
  exit_code: number | null;
};

// ============================================================
// Metrics Types
// ============================================================

export type GpuMetrics = {
  index: number;
  name: string;
  utilization: number;
  memory_used: number;
  memory_total: number;
  temperature: number;
  power: number;
};

export type TrainingMetrics = {
  step: number | null;
  total_steps: number | null;
  loss: number | null;
  learning_rate: number | null;
  epoch: number | null;
  samples_per_second: number | null;
};

export type SessionMetrics = {
  gpu: GpuMetrics[];
  training: TrainingMetrics | null;
  timestamp: string;
};

// ============================================================
// Sync Progress Types
// ============================================================

export type SyncProgress = {
  phase: "preparing" | "uploading" | "completed" | "failed";
  files_total: number;
  files_done: number;
  bytes_total: number;
  bytes_done: number;
  current_file: string | null;
  error: string | null;
};

// ============================================================
// Legacy Types (for backward compatibility)
// ============================================================

export type VastConfig = {
  api_key: string | null;
  url: string;
  ssh_user: string;
  ssh_key_path: string | null;
  ssh_connection_preference: "proxy" | "direct";
};

export type ColabConfig = {
  mount_drive: boolean;
  drive_dir: string;
  hf_home: string | null;
};

export type ScamalyticsConfig = {
  api_key: string | null;
  user: string | null;
  host: string;
};

export type AppThemeName = "tokyo-night-light" | "tokyo-night-dark";
// Alias for backward compatibility
export type TerminalThemeName = AppThemeName;

export type TerminalConfig = {
  theme: AppThemeName;
};

export type TrainshConfig = {
  vast: VastConfig;
  colab: ColabConfig;
  scamalytics: ScamalyticsConfig;
  terminal: TerminalConfig;
};

export type VastInstance = {
  id: number;
  actual_status: string | null;
  gpu_name: string | null;
  num_gpus: number | null;
  gpu_util: number | null;
  driver_version: string | null;
  cpu_name: string | null;
  cpu_cores: number | null;
  cpu_cores_effective: number | null;
  cpu_ram: number | null;
  cpu_util: number | null;
  mem_limit: number | null;
  mem_usage: number | null;
  gpu_totalram: number | null;
  gpu_ram: number | null;
  gpu_mem_bw: number | null;
  gpu_lanes: number | null;
  pci_gen: number | null;
  pcie_bw: number | null;
  dph_total: number | null;
  storage_cost: number | null;
  inet_up_cost: number | null;
  inet_down_cost: number | null;
  disk_space: number | null;
  disk_name: string | null;
  disk_bw: number | null;
  disk_util: number | null;
  disk_usage: number | null;
  inet_up: number | null;
  inet_down: number | null;
  os_version: string | null;
  geolocation: string | null;
  mobo_name: string | null;
  host_id: number | null;
  machine_id: number | null;
  bundle_id: number | null;
  start_date: number | null;
  end_date: number | null;
  duration: number | null;
  host_run_time: number | null;
  uptime_mins: number | null;
  status_msg: string | null;
  intended_status: string | null;
  cur_state: string | null;
  next_state: string | null;
  verification: string | null;
  image_uuid: string | null;
  image_runtype: string | null;
  template_name: string | null;
  template_id: number | null;
  ssh_idx: string | null;
  ssh_host: string | null;
  ssh_port: number | null;
  machine_dir_ssh_port: number | null;
  public_ipaddr: string | null;
  label: string | null;
};

export type VastOffer = {
  id: number;
  gpu_name: string | null;
  num_gpus: number | null;
  gpu_ram: number | null;
  dph_total: number | null;
  reliability2: number | null;
  inet_down: number | null;
  inet_up: number | null;
  cpu_cores: number | null;
  cpu_ram: number | null;
};

export type RemoteJobMeta = {
  ts: string;
  project_dir: string;
  command: string;
  ssh: SshSpec;
  remote: {
    workdir: string;
    job_dir: string;
    log_path: string;
    output_flag: string | null;
    output_dir: string | null;
    hf_home: string;
    tmux_session: string;
  };
  local_meta_path: string;
};

export type GpuRow = {
  index: string;
  name: string;
  util_gpu: string;
  util_mem: string;
  mem_used: string;
  mem_total: string;
  temp: string;
  power: string;
};

// ============================================================
// Storage Types
// ============================================================

export type StorageBackendLocal = {
  type: "local";
  root_path: string;
};

export type StorageBackendSshRemote = {
  type: "ssh_remote";
  host_id: string;
  root_path: string;
};

export type StorageBackendGoogleDrive = {
  type: "google_drive";
  client_id?: string | null;
  client_secret?: string | null;
  token?: string | null;
  root_folder_id?: string | null;
};

export type StorageBackendCloudflareR2 = {
  type: "cloudflare_r2";
  account_id: string;
  access_key_id: string;
  secret_access_key: string;
  bucket: string;
  endpoint?: string | null;
};

export type StorageBackendGoogleCloudStorage = {
  type: "google_cloud_storage";
  project_id: string;
  service_account_json?: string | null;
  bucket: string;
};

export type StorageBackendSmb = {
  type: "smb";
  host: string;
  share: string;
  user?: string | null;
  password?: string | null;
  domain?: string | null;
};

export type StorageBackend =
  | StorageBackendLocal
  | StorageBackendSshRemote
  | StorageBackendGoogleDrive
  | StorageBackendCloudflareR2
  | StorageBackendGoogleCloudStorage
  | StorageBackendSmb;

export type Storage = {
  id: string;
  name: string;
  icon?: string | null;
  backend: StorageBackend;
  readonly: boolean;
  created_at: string;
  last_accessed_at?: string | null;
};

export type StorageCreateInput = {
  name: string;
  icon?: string | null;
  backend: StorageBackend;
  readonly?: boolean;
};

export type StorageUpdateInput = {
  name?: string | null;
  icon?: string | null;
  readonly?: boolean | null;
  backend?: StorageBackend | null;
};

export type StorageTestResult = {
  success: boolean;
  message: string;
  latency_ms?: number | null;
};

export type StorageUsage = {
  storage_id: string;
  storage_name: string;
  backend_type: string;
  bucket_name?: string | null;
  total_bytes?: number | null;
  total_gb?: number | null;
  used_bytes: number;
  used_gb: number;
  free_bytes?: number | null;
  free_gb?: number | null;
  object_count?: number | null;
  fetched_at: string;
};

export type FileEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  modified_at?: string | null;
  mime_type?: string | null;
};

// ============================================================
// Transfer Types
// ============================================================

export type TransferOperation = "copy" | "move" | "sync" | "sync_no_delete";

export type TransferStatus =
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type TransferProgress = {
  files_total: number;
  files_done: number;
  bytes_total: number;
  bytes_done: number;
  speed_bps: number;
  eta_seconds?: number | null;
  current_file?: string | null;
};

export type TransferTask = {
  id: string;
  source_storage_id: string;
  source_path: string;
  dest_storage_id: string;
  dest_path: string;
  operation: TransferOperation;
  status: TransferStatus;
  progress: TransferProgress;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
};

export type TransferCreateInput = {
  source_storage_id: string;
  source_paths: string[];
  dest_storage_id: string;
  dest_path: string;
  operation: TransferOperation;
};

// ============================================================
// Log Types
// ============================================================

export type LogEntry = {
  session_id: string;
  timestamp: string;
  content: string;
  total_lines: number;
};

export type LogSnapshot = {
  session_id: string;
  lines: string[];
  captured_at: string;
  is_alive: boolean;
};

export type LogStreamStatus = {
  session_id: string;
  is_streaming: boolean;
  lines_captured: number;
  last_capture_at: string | null;
  error: string | null;
};

// ============================================================
// Pricing Types (Unified)
// ============================================================

export type Currency = "USD" | "JPY" | "HKD" | "CNY" | "EUR" | "GBP" | "KRW" | "TWD";

export type ExchangeRates = {
  base: string;
  rates: Record<string, number>;
  updated_at: string;
};

// Colab Pricing
export type ColabGpuPricing = {
  gpu_name: string;
  units_per_hour: number;
};

export type ColabSubscription = {
  name: string;
  price: number;
  currency: Currency;
  total_units: number;
};

export type ColabPricingConfig = {
  subscription: ColabSubscription;
  gpu_pricing: ColabGpuPricing[];
};

export type ColabGpuHourlyPrice = {
  gpu_name: string;
  units_per_hour: number;
  price_usd_per_hour: number;
  price_original_currency_per_hour: number;
  original_currency: Currency;
};

export type ColabPricingResult = {
  subscription: ColabSubscription;
  price_per_unit_usd: number;
  exchange_rate_used: number;
  gpu_prices: ColabGpuHourlyPrice[];
  calculated_at: string;
};

// Host Pricing (Vast.ai, Custom)
export type VastPricingRates = {
  storage_per_gb_month: number;
  network_egress_per_gb: number;
  network_ingress_per_gb: number;
};

export type PricingSource = "vast_api" | "manual" | "colab";

export type HostPricing = {
  host_id: string;
  gpu_hourly_usd?: number | null;
  storage_used_gb?: number | null;
  vast_rates?: VastPricingRates | null;
  updated_at: string;
  source: PricingSource;
};

export type HostCostBreakdown = {
  host_id: string;
  host_name?: string | null;
  gpu_per_hour_usd: number;
  storage_per_hour_usd: number;
  total_per_hour_usd: number;
  total_per_day_usd: number;
  total_per_month_usd: number;
  storage_gb: number;
  source: PricingSource;
};

// Unified Settings
export type PricingSettings = {
  colab: ColabPricingConfig;
  vast_rates: VastPricingRates;
  host_pricing: Record<string, HostPricing>;
  exchange_rates: ExchangeRates;
  display_currency: Currency;
};

// ============================================================
// Recipe Types
// ============================================================

export type Recipe = {
  name: string;
  version: string;
  description?: string | null;
  /** Target host requirements (host selected at runtime) */
  target?: TargetRequirements | null;
  variables: Record<string, string>;
  steps: Step[];
};

/** Target host requirements for a recipe */
export type TargetRequirements = {
  /** Required host type */
  type: TargetHostType;
  /** Minimum GPUs required */
  min_gpus?: number | null;
  /** Minimum memory in GB */
  min_memory_gb?: number | null;
  /** Specific GPU type (e.g., "T4", "A100") */
  gpu_type?: string | null;
};

export type TargetHostType = "any" | "local" | "vast" | "colab" | "custom";

export type Step = {
  id: string;
  name?: string | null;
  depends_on: string[];
  retry?: RetryConfig | null;
  timeout_secs?: number | null;
  when?: string | null;
  continue_on_failure: boolean;
} & Operation;

export type RetryConfig = {
  max_attempts: number;
  delay_secs: number;
  backoff_multiplier?: number | null;
};

// Operation types - flattened for TOML serialization
export type Operation = 
  // New unified operations
  | { run_commands: RunCommandsOp }
  | { transfer: TransferOp }
  // Legacy operations (for backwards compatibility)
  | { ssh_command: SshCommandOp }
  | { rsync_upload: RsyncUploadOp }
  | { rsync_download: RsyncDownloadOp }
  // Vast.ai operations
  | { vast_start: VastInstanceOp }
  | { vast_stop: VastInstanceOp }
  | { vast_destroy: VastInstanceOp }
  | { vast_copy: VastCopyOp }
  // Tmux operations
  | { tmux_new: TmuxNewOp }
  | { tmux_send: TmuxSendOp }
  | { tmux_capture: TmuxCaptureOp }
  | { tmux_kill: TmuxKillOp }
  // Google Drive operations
  | { gdrive_mount: GdriveMountOp }
  | { gdrive_unmount: GdriveUnmountOp }
  // Git operations
  | { git_clone: GitCloneOp }
  // HuggingFace operations
  | { hf_download: HfDownloadOp }
  // Control flow
  | { sleep: SleepOp }
  | { wait_condition: WaitConditionOp }
  | { assert: AssertOp }
  // Utility
  | { set_var: SetVarOp }
  | { get_value: GetValueOp }
  | { http_request: HttpRequestOp }
  | { notify: NotifyOp }
  | { group: GroupOp };

/** Run commands on target host with optional tmux support */
export type RunCommandsOp = {
  /** Host ID (if null, uses recipe target) */
  host_id?: string | null;
  /** Commands to execute (one per line) */
  commands: string;
  /** How to run: none (direct), new (new tmux), existing (existing tmux) */
  tmux_mode?: TmuxMode;
  /** Session name for tmux modes */
  session_name?: string | null;
  /** Working directory */
  workdir?: string | null;
  /** Environment variables */
  env?: Record<string, string>;
  /** Store output in variable (only with tmux_mode: none) */
  capture_output?: string | null;
  /** Timeout in seconds (only with tmux_mode: none) */
  timeout_secs?: number | null;
};

export type TmuxMode = "none" | "new" | "existing";

/** Unified file transfer between any endpoints */
export type TransferOp = {
  /** Source endpoint */
  source: TransferEndpoint;
  /** Destination endpoint */
  destination: TransferEndpoint;
  /** Explicitly included paths (if empty, includes all) */
  include_paths?: string[];
  /** Exclude patterns (glob) */
  exclude_patterns?: string[];
  /** Use .gitignore from source */
  use_gitignore?: boolean;
  /** Delete files in destination not in source */
  delete?: boolean;
};

export type TransferEndpoint =
  | { local: { path: string } }
  | { host: { host_id?: string | null; path: string } }
  | { storage: { storage_id: string; path: string } };

/** Git clone operation */
export type GitCloneOp = {
  /** Host ID (if null, uses recipe target) */
  host_id?: string | null;
  /** Repository URL */
  repo_url: string;
  /** Destination path */
  destination: string;
  /** Branch to checkout */
  branch?: string | null;
  /** Depth for shallow clone */
  depth?: number | null;
  /** Auth token for private repos */
  auth_token?: string | null;
};

/** HuggingFace download operation */
export type HfDownloadOp = {
  /** Host ID (if null, uses recipe target) */
  host_id?: string | null;
  /** Repo ID (e.g., "meta-llama/Llama-2-7b") */
  repo_id: string;
  /** Destination path */
  destination: string;
  /** Repo type */
  repo_type?: HfRepoType;
  /** Specific files to download (empty = all) */
  files?: string[];
  /** Revision/branch/tag */
  revision?: string | null;
  /** Auth token for gated repos */
  auth_token?: string | null;
};

export type HfRepoType = "model" | "dataset" | "space";

/** SSH command (legacy, prefer run_commands) */
export type SshCommandOp = {
  host_id: string;
  command: string;
  workdir?: string | null;
  env?: Record<string, string>;
  capture_output?: string | null;
  timeout_secs?: number | null;
};

export type RsyncUploadOp = {
  host_id: string;
  local_path: string;
  remote_path: string;
  excludes?: string[];
  use_gitignore?: boolean;
  delete?: boolean;
};

export type RsyncDownloadOp = {
  host_id: string;
  remote_path: string;
  local_path: string;
  excludes?: string[];
};

export type VastInstanceOp = Record<string, never>;

export type VastCopyOp = {
  /** Source location in Vast copy syntax */
  src: string;
  /** Destination location in Vast copy syntax */
  dst: string;
  /** Optional SSH identity file for rsync transfers */
  identity_file?: string | null;
};

export type TmuxNewOp = {
  host_id: string;
  session_name: string;
  command?: string | null;
  workdir?: string | null;
};

export type TmuxSendOp = {
  host_id: string;
  session_name: string;
  keys: string;
};

export type TmuxCaptureOp = {
  host_id: string;
  session_name: string;
  lines?: number | null;
  capture_output?: string | null;
};

export type TmuxKillOp = {
  host_id: string;
  session_name: string;
};

export type GdriveMountOp = {
  host_id?: string | null;
  storage_id?: string | null;
  mount_path: string;
  gdrive_path?: string | null;
  vfs_cache?: boolean;
  cache_mode?: string;
  background?: boolean;
};

export type GdriveUnmountOp = {
  host_id: string;
  mount_path: string;
};

export type SleepOp = {
  duration_secs: number;
};

export type WaitConditionOp = {
  condition: Condition;
  timeout_secs?: number;
  poll_interval_secs?: number;
};

export type AssertOp = {
  condition: Condition;
  message?: string | null;
};

export type SetVarOp = {
  name: string;
  value: string;
};

export type GetValueOp = {
  source: ValueSource;
  pattern?: string | null;
  var_name: string;
};

export type ValueSource =
  | { var: string }
  | { command: { host_id: string; command: string } }
  | { step_output: string };

export type HttpRequestOp = {
  method: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  url: string;
  headers?: Record<string, string>;
  body?: string | null;
  capture_response?: string | null;
  timeout_secs?: number | null;
};

export type NotifyOp = {
  title: string;
  message?: string | null;
  level?: "info" | "success" | "warning" | "error";
};

export type GroupOp = {
  mode?: "sequential" | "parallel";
  steps: string[];
};

// Conditions
export type Condition =
  | { file_exists: { host_id: string; path: string } }
  | { file_contains: { host_id: string; path: string; pattern: string } }
  | { command_succeeds: { host_id: string; command: string } }
  | { output_matches: { host_id: string; command: string; pattern: string } }
  | { var_equals: { name: string; value: string } }
  | { var_matches: { name: string; pattern: string } }
  | { host_online: { host_id: string } }
  | { tmux_alive: { host_id: string; session_name: string } }
  | { gpu_available: { host_id: string; min_count?: number } }
  | { gdrive_mounted: { host_id: string; mount_path: string } }
  | { not: Condition }
  | { and: Condition[] }
  | { or: Condition[] }
  | "always"
  | "never";

// Execution state
export type StepStatus =
  | "pending"
  | "waiting"
  | "running"
  | "success"
  | "failed"
  | "skipped"
  | "retrying"
  | "cancelled";

export type RecipeSummary = {
  path: string;
  name: string;
  version: string;
  description?: string | null;
  step_count: number;
};

// Alias for RecipeSummary (used in UI as "Skills")
export type SkillSummary = RecipeSummary;

export type ValidationResult = {
  valid: boolean;
  errors: ValidationError[];
  warnings: ValidationWarning[];
};

export type ValidationError = {
  step_id?: string | null;
  message: string;
};

export type ValidationWarning = {
  step_id?: string | null;
  message: string;
};

// ============================================================
// Interactive Recipe Execution Types
// ============================================================

export type InteractiveStatus =
  | "pending"
  | "connecting"
  | "running"
  | "paused"
  | "waiting_for_input"
  | "completed"
  | "failed"
  | "cancelled";

export type InteractiveTerminal = {
  title: string;
  tmux_session?: string | null;
  cols: number;
  rows: number;
};

export type InteractiveStepState = {
  step_id: string;
  name?: string | null;
  status: StepStatus;
  command?: string | null;
};

export type InteractiveExecution = {
  id: string;
  recipe_path: string;
  recipe_name: string;
  terminal_id?: string | null;
  terminal: InteractiveTerminal;
  host_id: string;
  status: InteractiveStatus;
  intervention_locked: boolean;
  current_step?: string | null;
  steps: InteractiveStepState[];
  step_progress?: Record<string, string>;
  variables: Record<string, string>;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
};

// Interactive recipe events
export type InteractiveRecipeEvent =
  | { type: "interactive_started"; execution_id: string; terminal_id: string }
  | { type: "connected"; execution_id: string; host_id: string }
  | { type: "step_started"; execution_id: string; step_id: string; command?: string | null }
  | { type: "command_pending"; execution_id: string; step_id: string; command: string }
  | { type: "command_sent"; execution_id: string; step_id: string; command: string }
  | { type: "step_completed"; execution_id: string; step_id: string }
  | { type: "step_failed"; execution_id: string; step_id: string; error: string }
  | { type: "step_progress"; execution_id: string; step_id: string; progress?: string | null }
  | { type: "intervention_lock_changed"; execution_id: string; locked: boolean }
  | { type: "waiting_for_confirmation"; execution_id: string; step_id: string; command: string }
  | { type: "execution_paused"; execution_id: string }
  | { type: "execution_resumed"; execution_id: string }
  | { type: "execution_completed"; execution_id: string }
  | { type: "execution_failed"; execution_id: string; error: string }
  | { type: "execution_cancelled"; execution_id: string };

// ============================================================
// Secret Types
// ============================================================

/** Secret metadata (stored in app data, actual value in OS keychain) */
export type SecretMeta = {
  name: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
};

/** Secret with its value (only used for display/edit, never persisted to disk) */
export type Secret = {
  name: string;
  value: string;
  description?: string | null;
  created_at: string;
  updated_at: string;
};

/** Input for creating/updating a secret */
export type SecretInput = {
  name: string;
  value: string;
  description?: string | null;
};

/** Suggested secret template */
export type SecretSuggestion = {
  name: string;
  label: string;
  description: string;
};

/** Result of validating secret references in a template */
export type SecretValidationResult = {
  valid: boolean;
  found: string[];
  missing: string[];
};
