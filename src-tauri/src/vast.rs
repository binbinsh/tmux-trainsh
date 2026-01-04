use std::{collections::HashMap, time::Duration};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::{config::TrainshConfig, error::AppError};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct VastInstance {
    pub id: i64,
    pub actual_status: Option<String>,
    pub gpu_name: Option<String>,
    pub num_gpus: Option<i64>,
    pub gpu_util: Option<f64>,
    pub dph_total: Option<f64>,
    pub storage_cost: Option<f64>,
    pub inet_up_cost: Option<f64>,
    pub inet_down_cost: Option<f64>,
    pub disk_space: Option<f64>,
    pub ssh_idx: Option<String>,
    pub ssh_host: Option<String>,
    pub ssh_port: Option<i64>,
    pub machine_dir_ssh_port: Option<i64>,
    pub public_ipaddr: Option<String>,
    pub label: Option<String>,
    #[serde(flatten)]
    pub extra: HashMap<String, Value>,
}

impl Default for VastInstance {
    fn default() -> Self {
        Self {
            id: 0,
            actual_status: None,
            gpu_name: None,
            num_gpus: None,
            gpu_util: None,
            dph_total: None,
            storage_cost: None,
            inet_up_cost: None,
            inet_down_cost: None,
            disk_space: None,
            ssh_idx: None,
            ssh_host: None,
            ssh_port: None,
            machine_dir_ssh_port: None,
            public_ipaddr: None,
            label: None,
            extra: HashMap::new(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct VastExecuteResponse {
    pub success: Option<bool>,
    pub writeable_path: Option<String>,
    pub result_url: Option<String>,
    pub msg: Option<String>,
    pub error: Option<String>,
}

impl Default for VastExecuteResponse {
    fn default() -> Self {
        Self {
            success: None,
            writeable_path: None,
            result_url: None,
            msg: None,
            error: None,
        }
    }
}

pub struct VastClient {
    http: reqwest::Client,
    api_base: String,
    api_key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct VastOffer {
    pub id: i64,
    pub gpu_name: Option<String>,
    pub num_gpus: Option<i64>,
    pub gpu_ram: Option<f64>,
    pub dph_total: Option<f64>,
    pub reliability2: Option<f64>,
    pub inet_down: Option<f64>,
    pub inet_up: Option<f64>,
    pub cpu_cores: Option<i64>,
    pub cpu_ram: Option<f64>,
}

impl Default for VastOffer {
    fn default() -> Self {
        Self {
            id: 0,
            gpu_name: None,
            num_gpus: None,
            gpu_ram: None,
            dph_total: None,
            reliability2: None,
            inet_down: None,
            inet_up: None,
            cpu_cores: None,
            cpu_ram: None,
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct VastSearchOffersInput {
    pub gpu_name: Option<String>,
    pub num_gpus: Option<i64>,
    pub min_gpu_ram: Option<f64>,
    pub max_dph_total: Option<f64>,
    pub min_reliability2: Option<f64>,
    pub limit: Option<i64>,
    pub order: Option<String>,  // e.g. "dph_total" or "-dph_total"
    pub r#type: Option<String>, // on-demand | bid | reserved
}

#[derive(Debug, Clone, Deserialize)]
pub struct VastCreateInstanceInput {
    pub offer_id: i64,
    pub image: String,
    pub disk: f64,
    pub label: Option<String>,
    pub onstart: Option<String>,
    pub direct: Option<bool>,
    pub cancel_unavail: Option<bool>,
}

impl VastClient {
    pub fn from_cfg(cfg: &TrainshConfig) -> Result<Self, AppError> {
        let key = cfg
            .vast
            .api_key
            .clone()
            .unwrap_or_default()
            .trim()
            .to_string();
        if key.is_empty() {
            return Err(AppError::invalid_input(
                "Missing Vast API key (Settings → Vast.ai → API Key)",
            ));
        }
        let base = cfg.vast.url.trim().trim_end_matches('/').to_string();
        let http = reqwest::Client::builder()
            .timeout(Duration::from_secs(15))
            .connect_timeout(Duration::from_secs(10))
            .build()
            .map_err(|e| AppError::http(format!("Failed to create HTTP client: {}", e)))?;
        Ok(Self {
            http,
            api_base: format!("{base}/api/v0"),
            api_key: key,
        })
    }

    fn url(&self, path: &str) -> String {
        let p = path.trim().trim_start_matches('/').trim_end_matches('/');
        format!("{}/{}/", self.api_base, p)
    }

    fn with_auth(&self, req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        req.bearer_auth(&self.api_key)
    }

    fn format_api_error(status: reqwest::StatusCode, body: &str) -> String {
        if let Ok(v) = serde_json::from_str::<Value>(body) {
            let msg = v.get("msg").and_then(|x| x.as_str()).unwrap_or("").trim();
            let err = v.get("error").and_then(|x| x.as_str()).unwrap_or("").trim();
            if !msg.is_empty() && !err.is_empty() {
                return format!("{status} {err}: {msg}");
            }
            if !msg.is_empty() {
                return format!("{status} {msg}");
            }
        }
        let trimmed = body.trim();
        if trimmed.is_empty() {
            format!("{status}")
        } else {
            format!("{status} {trimmed}")
        }
    }

    async fn get_json(&self, url: &str, extra_query: &[(&str, &str)]) -> Result<Value, AppError> {
        const MAX_ATTEMPTS: usize = 5;
        let mut last_err: Option<String> = None;

        for attempt in 1..=MAX_ATTEMPTS {
            let mut req = self.with_auth(self.http.get(url));
            for (k, v) in extra_query {
                req = req.query(&[(*k, *v)]);
            }

            let resp = req.send().await;
            match resp {
                Ok(resp) => {
                    let status = resp.status();
                    let text = resp.text().await.unwrap_or_default();
                    if status.is_success() {
                        let v: Value = serde_json::from_str(&text).map_err(|e| {
                            AppError::vast_api(format!("Invalid JSON from Vast API: {e}. Body: {text}"))
                        })?;
                        return Ok(v);
                    }

                    let retryable = status == reqwest::StatusCode::TOO_MANY_REQUESTS
                        || status.is_server_error();
                    if retryable && attempt < MAX_ATTEMPTS {
                        last_err = Some(Self::format_api_error(status, &text));
                        let backoff_ms = (300u64 * (1u64 << (attempt - 1))).min(3_000);
                        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                        continue;
                    }

                    return Err(AppError::vast_api(format!(
                        "Vast API request failed: {}",
                        Self::format_api_error(status, &text)
                    )));
                }
                Err(e) => {
                    let retryable = e.is_timeout() || e.is_connect() || e.is_request();
                    if retryable && attempt < MAX_ATTEMPTS {
                        last_err = Some(e.to_string());
                        let backoff_ms = (300u64 * (1u64 << (attempt - 1))).min(3_000);
                        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                        continue;
                    }
                    return Err(AppError::vast_api(format!("Vast API request failed: {e}")));
                }
            }
        }

        Err(AppError::vast_api(format!(
            "Vast API request failed: {}",
            last_err.unwrap_or_else(|| "unknown error".to_string())
        )))
    }

    async fn send_nojson(
        &self,
        method: reqwest::Method,
        url: &str,
        body: Option<Value>,
    ) -> Result<(), AppError> {
        const MAX_ATTEMPTS: usize = 5;
        let mut last_err: Option<String> = None;

        for attempt in 1..=MAX_ATTEMPTS {
            let mut req = self.with_auth(self.http.request(method.clone(), url));
            if let Some(b) = body.clone() {
                req = req.json(&b);
            }

            let resp = req.send().await;
            match resp {
                Ok(resp) => {
                    let status = resp.status();
                    let text = resp.text().await.unwrap_or_default();
                    if status.is_success() {
                        return Ok(());
                    }

                    let retryable = status == reqwest::StatusCode::TOO_MANY_REQUESTS
                        || status.is_server_error();
                    if retryable && attempt < MAX_ATTEMPTS {
                        last_err = Some(Self::format_api_error(status, &text));
                        let backoff_ms = (300u64 * (1u64 << (attempt - 1))).min(3_000);
                        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                        continue;
                    }

                    return Err(AppError::vast_api(format!(
                        "Vast API request failed: {}",
                        Self::format_api_error(status, &text)
                    )));
                }
                Err(e) => {
                    let retryable = e.is_timeout() || e.is_connect() || e.is_request();
                    if retryable && attempt < MAX_ATTEMPTS {
                        last_err = Some(e.to_string());
                        let backoff_ms = (300u64 * (1u64 << (attempt - 1))).min(3_000);
                        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                        continue;
                    }
                    return Err(AppError::vast_api(format!("Vast API request failed: {e}")));
                }
            }
        }

        Err(AppError::vast_api(format!(
            "Vast API request failed: {}",
            last_err.unwrap_or_else(|| "unknown error".to_string())
        )))
    }

    async fn send_json(
        &self,
        method: reqwest::Method,
        url: &str,
        body: Option<Value>,
    ) -> Result<Value, AppError> {
        const MAX_ATTEMPTS: usize = 5;
        let mut last_err: Option<String> = None;

        for attempt in 1..=MAX_ATTEMPTS {
            let mut req = self.with_auth(self.http.request(method.clone(), url));
            if let Some(b) = body.clone() {
                req = req.json(&b);
            }

            let resp = req.send().await;
            match resp {
                Ok(resp) => {
                    let status = resp.status();
                    let text = resp.text().await.unwrap_or_default();
                    if status.is_success() {
                        let v: Value = serde_json::from_str(&text).map_err(|e| {
                            AppError::vast_api(format!("Invalid JSON from Vast API: {e}. Body: {text}"))
                        })?;
                        return Ok(v);
                    }

                    let retryable = status == reqwest::StatusCode::TOO_MANY_REQUESTS
                        || status.is_server_error();
                    if retryable && attempt < MAX_ATTEMPTS {
                        last_err = Some(Self::format_api_error(status, &text));
                        let backoff_ms = (300u64 * (1u64 << (attempt - 1))).min(3_000);
                        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                        continue;
                    }

                    return Err(AppError::vast_api(format!(
                        "Vast API request failed: {}",
                        Self::format_api_error(status, &text)
                    )));
                }
                Err(e) => {
                    let retryable = e.is_timeout() || e.is_connect() || e.is_request();
                    if retryable && attempt < MAX_ATTEMPTS {
                        last_err = Some(e.to_string());
                        let backoff_ms = (300u64 * (1u64 << (attempt - 1))).min(3_000);
                        tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                        continue;
                    }
                    return Err(AppError::vast_api(format!("Vast API request failed: {e}")));
                }
            }
        }

        Err(AppError::vast_api(format!(
            "Vast API request failed: {}",
            last_err.unwrap_or_else(|| "unknown error".to_string())
        )))
    }

    pub async fn list_instances(&self) -> Result<Vec<VastInstance>, AppError> {
        let url = self.url("instances");
        let v = self.get_json(&url, &[]).await?;

        let arr_opt = v
            .get("instances")
            .and_then(|x| x.as_array())
            .cloned()
            .or_else(|| v.as_array().cloned());

        let Some(arr) = arr_opt else {
            return Err(AppError::vast_api(format!(
                "Unexpected Vast instances response shape: {v}"
            )));
        };

        let mut out: Vec<VastInstance> = vec![];
        for item in arr {
            let inst: VastInstance = serde_json::from_value(item)
                .map_err(|e| AppError::vast_api(format!("Failed to parse Vast instance: {e}")))?;
            out.push(inst);
        }
        Ok(out)
    }

    pub async fn get_instance(&self, instance_id: i64) -> Result<VastInstance, AppError> {
        let url = self.url(&format!("instances/{instance_id}"));
        let v = self.get_json(&url, &[]).await?;
        if let Some(inst) = v.get("instances") {
            let parsed: VastInstance = serde_json::from_value(inst.clone())
                .map_err(|e| AppError::vast_api(format!("Failed to parse Vast instance: {e}")))?;
            return Ok(parsed);
        }
        let parsed: VastInstance = serde_json::from_value(v)
            .map_err(|e| AppError::vast_api(format!("Failed to parse Vast instance: {e}")))?;
        Ok(parsed)
    }

    pub async fn execute_command(
        &self,
        instance_id: i64,
        command: &str,
    ) -> Result<VastExecuteResponse, AppError> {
        if instance_id <= 0 {
            return Err(AppError::invalid_input("instance_id must be positive"));
        }
        let trimmed = command.trim();
        if trimmed.is_empty() {
            return Err(AppError::invalid_input("command is required"));
        }
        if trimmed.len() > 512 {
            return Err(AppError::invalid_input("command must be <= 512 characters"));
        }
        let url = self.url(&format!("instances/{instance_id}/command"));
        let body = serde_json::json!({ "command": trimmed });
        let v = self
            .send_json(reqwest::Method::POST, &url, Some(body))
            .await?;
        serde_json::from_value(v)
            .map_err(|e| AppError::vast_api(format!("Failed to parse Vast execute response: {e}")))
    }

    pub async fn execute_and_fetch_result(
        &self,
        instance_id: i64,
        command: &str,
    ) -> Result<String, AppError> {
        let resp = self.execute_command(instance_id, command).await?;
        if resp.success == Some(false) {
            let msg = resp
                .msg
                .or(resp.error)
                .unwrap_or_else(|| "Command failed".to_string());
            return Err(AppError::vast_api(msg));
        }
        let result_url = resp
            .result_url
            .filter(|s| !s.trim().is_empty())
            .ok_or_else(|| AppError::vast_api("Missing result_url from Vast execute response"))?;
        self.wait_for_execute_result(&result_url).await
    }

    async fn wait_for_execute_result(&self, result_url: &str) -> Result<String, AppError> {
        let mut last_err: Option<String> = None;
        for _ in 0..10 {
            let resp = self.http.get(result_url).send().await;
            match resp {
                Ok(resp) => {
                    let status = resp.status();
                    let text = resp.text().await.unwrap_or_default();
                    if status.is_success() {
                        if !text.trim().is_empty() {
                            return Ok(text);
                        }
                        last_err = Some("Empty result from Vast execute".to_string());
                    } else {
                        last_err = Some(format!("{status} {text}"));
                    }
                }
                Err(e) => last_err = Some(e.to_string()),
            }
            tokio::time::sleep(Duration::from_millis(700)).await;
        }
        Err(AppError::vast_api(format!(
            "Vast execute result not ready: {}",
            last_err.unwrap_or_else(|| "unknown error".to_string())
        )))
    }

    pub async fn start_instance(&self, instance_id: i64) -> Result<(), AppError> {
        let url = self.url(&format!("instances/{instance_id}"));
        self.send_nojson(
            reqwest::Method::PUT,
            &url,
            Some(serde_json::json!({ "state": "running" })),
        )
        .await
    }

    pub async fn stop_instance(&self, instance_id: i64) -> Result<(), AppError> {
        let url = self.url(&format!("instances/{instance_id}"));
        self.send_nojson(
            reqwest::Method::PUT,
            &url,
            Some(serde_json::json!({ "state": "stopped" })),
        )
        .await
    }

    pub async fn attach_ssh_key(&self, instance_id: i64, ssh_key: String) -> Result<(), AppError> {
        let url = self.url(&format!("instances/{instance_id}/ssh"));
        self.send_nojson(
            reqwest::Method::POST,
            &url,
            Some(serde_json::json!({ "ssh_key": ssh_key })),
        )
        .await
    }

    pub async fn label_instance(&self, instance_id: i64, label: String) -> Result<(), AppError> {
        let url = self.url(&format!("instances/{instance_id}"));
        self.send_nojson(
            reqwest::Method::PUT,
            &url,
            Some(serde_json::json!({ "label": label })),
        )
        .await
    }

    pub async fn destroy_instance(&self, instance_id: i64) -> Result<(), AppError> {
        let url = self.url(&format!("instances/{instance_id}"));
        self.send_nojson(reqwest::Method::DELETE, &url, None).await
    }

    pub async fn search_offers(
        &self,
        input: VastSearchOffersInput,
    ) -> Result<Vec<VastOffer>, AppError> {
        let mut q = serde_json::Map::<String, Value>::new();
        // CLI defaults - be less restrictive
        q.insert("rentable".to_string(), serde_json::json!({ "eq": true }));
        q.insert("rented".to_string(), serde_json::json!({ "eq": false }));

        // GPU name - use substring matching
        // Vast API operators: eq, neq, lt, lte, gt, gte, in, nin, notnull, isnull
        // For GPU name, we need to build a list of known GPU names that match the pattern
        if let Some(name) = input.gpu_name.clone().filter(|s| !s.trim().is_empty()) {
            let name = name.trim().to_uppercase().replace('_', " ");
            // Map common shorthand to known GPU model patterns
            let gpu_patterns = match name.as_str() {
                s if s.contains("H100") => vec![
                    "NVIDIA H100 80GB HBM3",
                    "NVIDIA H100 PCIe",
                    "H100 SXM",
                    "H100_SXM5",
                    "H100_PCIE",
                    "H100_NVL",
                ],
                s if s.contains("H200") => vec!["H200"],
                s if s.contains("A100") => vec![
                    "NVIDIA A100-SXM4-80GB",
                    "NVIDIA A100-SXM4-40GB",
                    "NVIDIA A100-PCIE-40GB",
                    "NVIDIA A100 80GB PCIe",
                    "A100_SXM4",
                    "A100_PCIE",
                ],
                s if s.contains("4090") => {
                    vec!["NVIDIA GeForce RTX 4090", "RTX 4090", "GeForce RTX 4090"]
                }
                s if s.contains("3090") => vec![
                    "NVIDIA GeForce RTX 3090",
                    "RTX 3090",
                    "RTX 3090 Ti",
                    "GeForce RTX 3090",
                ],
                s if s.contains("L40") => vec!["L40S", "L40", "NVIDIA L40S", "NVIDIA L40"],
                s if s.contains("L4") => vec!["L4", "NVIDIA L4"],
                s if s.contains("A6000") => vec!["RTX A6000", "NVIDIA RTX A6000"],
                s if s.contains("A5000") => vec!["RTX A5000", "NVIDIA RTX A5000"],
                _ => vec![],
            };

            if !gpu_patterns.is_empty() {
                // Use "in" operator with known GPU names
                q.insert(
                    "gpu_name".to_string(),
                    serde_json::json!({ "in": gpu_patterns }),
                );
            } else {
                // Try exact match with the user's input
                q.insert("gpu_name".to_string(), serde_json::json!({ "eq": name }));
            }
        }
        if let Some(n) = input.num_gpus {
            if n > 0 {
                q.insert("num_gpus".to_string(), serde_json::json!({ "gte": n }));
            }
        }
        if let Some(v) = input.min_gpu_ram {
            if v > 0.0 {
                // API returns gpu_ram in MB, user inputs in GB, so multiply by 1024
                q.insert(
                    "gpu_ram".to_string(),
                    serde_json::json!({ "gte": v * 1024.0 }),
                );
            }
        }
        if let Some(v) = input.max_dph_total {
            if v > 0.0 {
                q.insert("dph_total".to_string(), serde_json::json!({ "lte": v }));
            }
        }
        if let Some(v) = input.min_reliability2 {
            if v > 0.0 {
                q.insert("reliability2".to_string(), serde_json::json!({ "gte": v }));
            }
        }

        let t = input.r#type.unwrap_or_else(|| "on-demand".to_string());
        let t = if t == "interruptible" {
            "bid".to_string()
        } else {
            t
        };
        q.insert("type".to_string(), serde_json::json!(t));

        // Sort: e.g. "-dph_total" (desc) or "dph_total" (asc)
        let order = input
            .order
            .clone()
            .unwrap_or_else(|| "dph_total".to_string());
        let raw = order.trim();
        let (field, dir) = if let Some(rest) = raw.strip_prefix('-') {
            (rest, "desc")
        } else if let Some(rest) = raw.strip_prefix('+') {
            (rest, "asc")
        } else {
            (raw, "asc")
        };
        q.insert("order".to_string(), serde_json::json!([[field, dir]]));

        let limit = input.limit.unwrap_or(50);

        let body = serde_json::json!({
          "select_cols": ["*"],
          "q": Value::Object(q),
          "limit": limit
        });

        // Use search/asks endpoint with PUT
        let url = self.url("search/asks");
        let v = self
            .send_json(reqwest::Method::PUT, &url, Some(body))
            .await?;

        // Try different response shapes
        let offers = v
            .get("offers")
            .and_then(|x| x.as_array())
            .cloned()
            .or_else(|| v.as_array().cloned())
            .unwrap_or_default();

        let mut out: Vec<VastOffer> = vec![];
        for item in offers {
            if let Ok(offer) = serde_json::from_value::<VastOffer>(item) {
                out.push(offer);
            }
        }

        // Apply limit manually if needed
        out.truncate(limit as usize);
        Ok(out)
    }

    pub async fn create_instance(&self, input: VastCreateInstanceInput) -> Result<i64, AppError> {
        if input.offer_id <= 0 {
            return Err(AppError::invalid_input("offer_id must be > 0"));
        }
        if input.image.trim().is_empty() {
            return Err(AppError::invalid_input("image is required"));
        }
        if input.disk <= 0.0 {
            return Err(AppError::invalid_input("disk must be > 0 (GB)"));
        }

        let direct = input.direct.unwrap_or(false);
        let runtype = if direct {
            "ssh_direc ssh_proxy"
        } else {
            "ssh_proxy"
        };

        let body = serde_json::json!({
          "client_id": "me",
          "image": input.image.trim(),
          "env": {},
          "disk": input.disk,
          "label": input.label.clone().unwrap_or_default(),
          "onstart": input.onstart.clone().unwrap_or_default(),
          "runtype": runtype,
          "cancel_unavail": input.cancel_unavail.unwrap_or(false),
          "force": false
        });

        let url = self.url(&format!("asks/{}", input.offer_id));
        let v = self
            .send_json(reqwest::Method::PUT, &url, Some(body))
            .await?;

        // Typical response: {"success": true, "new_contract": 7835610}
        if let Some(id) = v.get("new_contract").and_then(|x| x.as_i64()) {
            return Ok(id);
        }
        Err(AppError::vast_api(format!(
            "Unexpected create instance response: {v}"
        )))
    }
}
