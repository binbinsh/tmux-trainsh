use std::time::Duration;

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
  pub ssh_host: Option<String>,
  pub ssh_port: Option<i64>,
  pub label: Option<String>,
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
      ssh_host: None,
      ssh_port: None,
      label: None,
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
  pub order: Option<String>, // e.g. "dph_total" or "-dph_total"
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
      return Err(AppError::invalid_input("Missing Vast API key (Settings → Vast.ai → API Key)"));
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

  fn url_candidates(&self, path: &str) -> [String; 2] {
    let p = path.trim_start_matches('/');
    [format!("{}/{}", self.api_base, p), format!("{}/{}/", self.api_base, p)]
  }

  async fn get_json(&self, urls: &[String], extra_query: &[(&str, &str)]) -> Result<Value, AppError> {
    let mut last_err: Option<String> = None;
    for url in urls {
      let mut req = self.http.get(url).query(&[("api_key", &self.api_key)]);
      for (k, v) in extra_query {
        req = req.query(&[(*k, *v)]);
      }
      let resp = req.send().await;
      match resp {
        Ok(resp) => {
          let status = resp.status();
          let text = resp.text().await.unwrap_or_default();
          if status.is_success() {
            let v: Value = serde_json::from_str(&text)
              .map_err(|e| AppError::vast_api(format!("Invalid JSON from Vast API: {e}. Body: {text}")))?;
            return Ok(v);
          }
          last_err = Some(format!("{status} {text}"));
        }
        Err(e) => last_err = Some(e.to_string()),
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
    urls: &[String],
    body: Option<Value>,
  ) -> Result<(), AppError> {
    let mut last_err: Option<String> = None;
    for url in urls {
      let mut req = self.http.request(method.clone(), url).query(&[("api_key", &self.api_key)]);
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
          last_err = Some(format!("{status} {text}"));
        }
        Err(e) => last_err = Some(e.to_string()),
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
    urls: &[String],
    body: Option<Value>,
  ) -> Result<Value, AppError> {
    let mut last_err: Option<String> = None;
    for url in urls {
      let mut req = self.http.request(method.clone(), url).query(&[("api_key", &self.api_key)]);
      if let Some(b) = body.clone() {
        req = req.json(&b);
      }
      let resp = req.send().await;
      match resp {
        Ok(resp) => {
          let status = resp.status();
          let text = resp.text().await.unwrap_or_default();
          if status.is_success() {
            let v: Value = serde_json::from_str(&text)
              .map_err(|e| AppError::vast_api(format!("Invalid JSON from Vast API: {e}. Body: {text}")))?;
            return Ok(v);
          }
          last_err = Some(format!("{status} {text}"));
        }
        Err(e) => last_err = Some(e.to_string()),
      }
    }
    Err(AppError::vast_api(format!(
      "Vast API request failed: {}",
      last_err.unwrap_or_else(|| "unknown error".to_string())
    )))
  }

  pub async fn list_instances(&self) -> Result<Vec<VastInstance>, AppError> {
    let urls = self.url_candidates("instances");
    // Vast CLI uses owner=me for user instances.
    let v = self.get_json(&urls, &[("owner", "me")]).await?;

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

  pub async fn start_instance(&self, instance_id: i64) -> Result<(), AppError> {
    let urls = self.url_candidates(&format!("instances/{instance_id}"));
    self
      .send_nojson(reqwest::Method::PUT, &urls, Some(serde_json::json!({ "state": "running" })))
      .await
  }

  pub async fn stop_instance(&self, instance_id: i64) -> Result<(), AppError> {
    let urls = self.url_candidates(&format!("instances/{instance_id}"));
    self
      .send_nojson(reqwest::Method::PUT, &urls, Some(serde_json::json!({ "state": "stopped" })))
      .await
  }

  pub async fn attach_ssh_key(&self, instance_id: i64) -> Result<(), AppError> {
    let urls = self.url_candidates(&format!("instances/{instance_id}/ssh"));
    self.send_nojson(reqwest::Method::POST, &urls, None).await
  }

  pub async fn label_instance(&self, instance_id: i64, label: String) -> Result<(), AppError> {
    let urls = self.url_candidates(&format!("instances/{instance_id}"));
    self
      .send_nojson(reqwest::Method::PUT, &urls, Some(serde_json::json!({ "label": label })))
      .await
  }

  pub async fn destroy_instance(&self, instance_id: i64) -> Result<(), AppError> {
    let urls = self.url_candidates(&format!("instances/{instance_id}"));
    self
      .send_nojson(reqwest::Method::DELETE, &urls, None)
      .await
  }

  pub async fn search_offers(&self, input: VastSearchOffersInput) -> Result<Vec<VastOffer>, AppError> {
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
        s if s.contains("4090") => vec![
          "NVIDIA GeForce RTX 4090",
          "RTX 4090",
          "GeForce RTX 4090",
        ],
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
        q.insert("gpu_name".to_string(), serde_json::json!({ "in": gpu_patterns }));
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
        q.insert("gpu_ram".to_string(), serde_json::json!({ "gte": v * 1024.0 }));
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
    let t = if t == "interruptible" { "bid".to_string() } else { t };
    q.insert("type".to_string(), serde_json::json!(t));

    // Sort: e.g. "-dph_total" (desc) or "dph_total" (asc)
    let order = input.order.clone().unwrap_or_else(|| "dph_total".to_string());
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
    let urls = self.url_candidates("search/asks");
    let v = self.send_json(reqwest::Method::PUT, &urls, Some(body)).await?;
    
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
    let runtype = if direct { "ssh_direc ssh_proxy" } else { "ssh_proxy" };

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

    let urls = self.url_candidates(&format!("asks/{}", input.offer_id));
    let v = self.send_json(reqwest::Method::PUT, &urls, Some(body)).await?;

    // Typical response: {"success": true, "new_contract": 7835610}
    if let Some(id) = v.get("new_contract").and_then(|x| x.as_i64()) {
      return Ok(id);
    }
    Err(AppError::vast_api(format!("Unexpected create instance response: {v}")))
  }
}
