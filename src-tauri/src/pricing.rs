//! Unified pricing module
//!
//! Provides pricing calculations for:
//! - Google Colab (subscription-based compute units)
//! - Vast.ai hosts (GPU hourly rate + storage + network)
//! - Custom hosts (manual pricing input)

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};
use tokio::sync::RwLock;

use crate::error::AppError;
use crate::storage::StorageUsage;

// ============================================================
// Currency Types
// ============================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum Currency {
    Usd,
    Jpy,
    Hkd,
    Cny,
    Eur,
    Gbp,
    Krw,
    Twd,
}

impl Default for Currency {
    fn default() -> Self {
        Self::Usd
    }
}

impl Currency {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Usd => "USD",
            Self::Jpy => "JPY",
            Self::Hkd => "HKD",
            Self::Cny => "CNY",
            Self::Eur => "EUR",
            Self::Gbp => "GBP",
            Self::Krw => "KRW",
            Self::Twd => "TWD",
        }
    }
}

// ============================================================
// Exchange Rates
// ============================================================

/// Exchange rates relative to USD
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExchangeRates {
    /// Base currency (always USD)
    pub base: String,
    /// Exchange rates: 1 USD = X units of target currency
    pub rates: HashMap<String, f64>,
    /// Last update timestamp (ISO 8601)
    pub updated_at: String,
}

impl Default for ExchangeRates {
    fn default() -> Self {
        // Default fallback rates (approximate)
        let mut rates = HashMap::new();
        rates.insert("USD".to_string(), 1.0);
        rates.insert("JPY".to_string(), 149.0);
        rates.insert("HKD".to_string(), 7.8);
        rates.insert("CNY".to_string(), 7.2);
        rates.insert("EUR".to_string(), 0.92);
        rates.insert("GBP".to_string(), 0.79);
        rates.insert("KRW".to_string(), 1350.0);
        rates.insert("TWD".to_string(), 32.0);

        Self {
            base: "USD".to_string(),
            rates,
            updated_at: chrono::Utc::now().to_rfc3339(),
        }
    }
}

// ============================================================
// Colab Pricing Types
// ============================================================

/// GPU pricing in compute units per hour
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColabGpuPricing {
    pub gpu_name: String,
    pub units_per_hour: f64,
}

// Default Colab GPU pricing (compute units per hour)
pub fn default_colab_gpu_pricing() -> Vec<ColabGpuPricing> {
    vec![
        ColabGpuPricing { gpu_name: "T4".to_string(), units_per_hour: 1.96 },
        ColabGpuPricing { gpu_name: "L4".to_string(), units_per_hour: 3.72 },
        ColabGpuPricing { gpu_name: "A100".to_string(), units_per_hour: 12.29 },
        ColabGpuPricing { gpu_name: "V100".to_string(), units_per_hour: 5.36 },
    ]
}

/// Colab subscription settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColabSubscription {
    /// Subscription name (e.g., "Colab Pro", "Colab Pro+")
    pub name: String,
    /// Subscription price in the specified currency
    pub price: f64,
    /// Currency of the subscription price
    pub currency: Currency,
    /// Total compute units included in the subscription
    pub total_units: f64,
}

impl Default for ColabSubscription {
    fn default() -> Self {
        Self {
            name: "Colab Pro".to_string(),
            price: 11.99,
            currency: Currency::Usd,
            total_units: 100.0,
        }
    }
}

/// Complete Colab pricing configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColabPricingConfig {
    pub subscription: ColabSubscription,
    pub gpu_pricing: Vec<ColabGpuPricing>,
}

impl Default for ColabPricingConfig {
    fn default() -> Self {
        Self {
            subscription: ColabSubscription::default(),
            gpu_pricing: default_colab_gpu_pricing(),
        }
    }
}

/// Calculated price per hour for a Colab GPU
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColabGpuHourlyPrice {
    pub gpu_name: String,
    pub units_per_hour: f64,
    pub price_usd_per_hour: f64,
    pub price_original_currency_per_hour: f64,
    pub original_currency: Currency,
}

/// Colab pricing calculation result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ColabPricingResult {
    pub subscription: ColabSubscription,
    pub price_per_unit_usd: f64,
    pub exchange_rate_used: f64,
    pub gpu_prices: Vec<ColabGpuHourlyPrice>,
    pub calculated_at: String,
}

// ============================================================
// Host Pricing Types (Vast.ai, Custom)
// ============================================================

/// Vast.ai specific pricing rates
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VastPricingRates {
    /// Storage cost per GB per month (USD)
    pub storage_per_gb_month: f64,
    /// Network egress cost per GB (USD), usually 0 for Vast.ai
    pub network_egress_per_gb: f64,
    /// Network ingress cost per GB (USD), usually 0
    pub network_ingress_per_gb: f64,
}

impl Default for VastPricingRates {
    fn default() -> Self {
        Self {
            // Vast.ai typical rates
            storage_per_gb_month: 0.15,
            network_egress_per_gb: 0.0,
            network_ingress_per_gb: 0.0,
        }
    }
}

/// Pricing info for a specific host
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HostPricing {
    /// Host ID this pricing is associated with
    pub host_id: String,
    /// GPU hourly cost in USD (from Vast.ai dph_total or manual input)
    pub gpu_hourly_usd: Option<f64>,
    /// Storage used in GB
    pub storage_used_gb: Option<f64>,
    /// Vast.ai specific pricing rates
    pub vast_rates: Option<VastPricingRates>,
    /// Last updated timestamp
    pub updated_at: String,
    /// Source of pricing data
    pub source: PricingSource,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PricingSource {
    /// Fetched from Vast.ai API
    VastApi,
    /// Manually entered
    Manual,
    /// Colab subscription-based
    Colab,
}

/// Calculated cost breakdown for a host
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HostCostBreakdown {
    pub host_id: String,
    pub host_name: Option<String>,
    /// GPU cost per hour (USD)
    pub gpu_per_hour_usd: f64,
    /// Storage cost per hour (USD)
    pub storage_per_hour_usd: f64,
    /// Total cost per hour (USD)
    pub total_per_hour_usd: f64,
    /// Total cost per day (USD)
    pub total_per_day_usd: f64,
    /// Total cost per month (USD, 30 days)
    pub total_per_month_usd: f64,
    /// Storage details
    pub storage_gb: f64,
    /// Pricing source
    pub source: PricingSource,
}

// ============================================================
// Unified Pricing Settings
// ============================================================

/// Complete pricing settings (persisted)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PricingSettings {
    /// Colab pricing configuration
    pub colab: ColabPricingConfig,
    /// Vast.ai default pricing rates
    pub vast_rates: VastPricingRates,
    /// Per-host pricing data (keyed by host_id)
    pub host_pricing: HashMap<String, HostPricing>,
    /// Exchange rates
    pub exchange_rates: ExchangeRates,
    /// Cached storage usages (for all storage types)
    #[serde(default)]
    pub storage_usages_cache: Vec<StorageUsage>,
}

impl Default for PricingSettings {
    fn default() -> Self {
        Self {
            colab: ColabPricingConfig::default(),
            vast_rates: VastPricingRates::default(),
            host_pricing: HashMap::new(),
            exchange_rates: ExchangeRates::default(),
            storage_usages_cache: Vec::new(),
        }
    }
}

// ============================================================
// Pricing Store
// ============================================================

pub struct PricingStore {
    settings: RwLock<PricingSettings>,
    data_path: PathBuf,
}

impl PricingStore {
    pub fn new(data_dir: &std::path::Path) -> Self {
        let data_path = data_dir.join("pricing.json");
        let settings = Self::load_from_file(&data_path).unwrap_or_default();
        Self {
            settings: RwLock::new(settings),
            data_path,
        }
    }

    fn load_from_file(path: &PathBuf) -> Option<PricingSettings> {
        let content = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&content).ok()
    }

    async fn save_to_file(&self) -> Result<(), AppError> {
        let content = {
            let settings = self.settings.read().await;
            serde_json::to_string_pretty(&*settings)?
        };
        tokio::fs::write(&self.data_path, content).await?;
        Ok(())
    }

    pub async fn get_settings(&self) -> PricingSettings {
        self.settings.read().await.clone()
    }

    // ========================
    // Colab Pricing Methods
    // ========================

    pub async fn update_colab_subscription(&self, subscription: ColabSubscription) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            settings.colab.subscription = subscription;
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }

    pub async fn update_colab_gpu_pricing(&self, gpu_pricing: Vec<ColabGpuPricing>) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            settings.colab.gpu_pricing = gpu_pricing;
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }

    pub async fn calculate_colab_pricing(&self) -> ColabPricingResult {
        let settings = self.settings.read().await;
        
        // Get exchange rate for the subscription currency
        let exchange_rate = settings
            .exchange_rates
            .rates
            .get(settings.colab.subscription.currency.code())
            .copied()
            .unwrap_or(1.0);

        // Calculate price per unit in USD
        let subscription_price_usd = settings.colab.subscription.price / exchange_rate;
        let price_per_unit_usd = subscription_price_usd / settings.colab.subscription.total_units;

        // Calculate hourly prices for each GPU
        let gpu_prices: Vec<ColabGpuHourlyPrice> = settings
            .colab
            .gpu_pricing
            .iter()
            .map(|gpu| {
                let price_usd_per_hour = gpu.units_per_hour * price_per_unit_usd;
                let price_original = price_usd_per_hour * exchange_rate;
                
                ColabGpuHourlyPrice {
                    gpu_name: gpu.gpu_name.clone(),
                    units_per_hour: gpu.units_per_hour,
                    price_usd_per_hour,
                    price_original_currency_per_hour: price_original,
                    original_currency: settings.colab.subscription.currency,
                }
            })
            .collect();

        ColabPricingResult {
            subscription: settings.colab.subscription.clone(),
            price_per_unit_usd,
            exchange_rate_used: exchange_rate,
            gpu_prices,
            calculated_at: chrono::Utc::now().to_rfc3339(),
        }
    }

    // ========================
    // Host Pricing Methods
    // ========================

    pub async fn update_vast_rates(&self, rates: VastPricingRates) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            settings.vast_rates = rates;
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }

    pub async fn set_host_pricing(&self, host_id: String, pricing: HostPricing) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            settings.host_pricing.insert(host_id, pricing);
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }

    pub async fn remove_host_pricing(&self, host_id: &str) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            settings.host_pricing.remove(host_id);
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }

    pub async fn get_host_pricing(&self, host_id: &str) -> Option<HostPricing> {
        let settings = self.settings.read().await;
        settings.host_pricing.get(host_id).cloned()
    }

    pub async fn calculate_host_cost(&self, host_id: &str, host_name: Option<String>) -> Option<HostCostBreakdown> {
        let settings = self.settings.read().await;
        let pricing = settings.host_pricing.get(host_id)?;

        let gpu_per_hour = pricing.gpu_hourly_usd.unwrap_or(0.0);
        let storage_gb = pricing.storage_used_gb.unwrap_or(0.0);
        
        // Calculate storage cost per hour
        let storage_rate = pricing.vast_rates.as_ref().unwrap_or(&settings.vast_rates);
        let storage_per_month = storage_gb * storage_rate.storage_per_gb_month;
        let storage_per_hour = storage_per_month / (30.0 * 24.0);

        let total_per_hour = gpu_per_hour + storage_per_hour;
        let total_per_day = total_per_hour * 24.0;
        let total_per_month = total_per_day * 30.0;

        Some(HostCostBreakdown {
            host_id: host_id.to_string(),
            host_name,
            gpu_per_hour_usd: gpu_per_hour,
            storage_per_hour_usd: storage_per_hour,
            total_per_hour_usd: total_per_hour,
            total_per_day_usd: total_per_day,
            total_per_month_usd: total_per_month,
            storage_gb,
            source: pricing.source,
        })
    }

    pub async fn calculate_all_host_costs(&self) -> Vec<HostCostBreakdown> {
        let settings = self.settings.read().await;
        let mut results = Vec::new();

        for (host_id, pricing) in &settings.host_pricing {
            let gpu_per_hour = pricing.gpu_hourly_usd.unwrap_or(0.0);
            let storage_gb = pricing.storage_used_gb.unwrap_or(0.0);
            
            let storage_rate = pricing.vast_rates.as_ref().unwrap_or(&settings.vast_rates);
            let storage_per_month = storage_gb * storage_rate.storage_per_gb_month;
            let storage_per_hour = storage_per_month / (30.0 * 24.0);

            let total_per_hour = gpu_per_hour + storage_per_hour;
            let total_per_day = total_per_hour * 24.0;
            let total_per_month = total_per_day * 30.0;

            results.push(HostCostBreakdown {
                host_id: host_id.clone(),
                host_name: None,
                gpu_per_hour_usd: gpu_per_hour,
                storage_per_hour_usd: storage_per_hour,
                total_per_hour_usd: total_per_hour,
                total_per_day_usd: total_per_day,
                total_per_month_usd: total_per_month,
                storage_gb,
                source: pricing.source,
            });
        }

        results
    }

    // ========================
    // Exchange Rate Methods
    // ========================

    pub async fn update_exchange_rates(&self, rates: ExchangeRates) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            settings.exchange_rates = rates;
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }

    pub async fn reset_to_defaults(&self) -> Result<PricingSettings, AppError> {
        {
            let mut settings = self.settings.write().await;
            *settings = PricingSettings::default();
        }
        self.save_to_file().await?;
        Ok(self.get_settings().await)
    }
}

// ============================================================
// Exchange Rate Fetching
// ============================================================

/// Fetch exchange rates from free API
pub async fn fetch_exchange_rates() -> Result<ExchangeRates, AppError> {
    let url = "https://api.frankfurter.app/latest?from=USD&to=JPY,HKD,CNY,EUR,GBP,KRW,TWD";
    
    let response = reqwest::get(url)
        .await
        .map_err(|e| AppError::network(format!("Failed to fetch exchange rates: {}", e)))?;

    if !response.status().is_success() {
        return Err(AppError::network(format!(
            "Exchange rate API returned status: {}",
            response.status()
        )));
    }

    let body: serde_json::Value = response
        .json()
        .await
        .map_err(|e| AppError::network(format!("Failed to parse exchange rate response: {}", e)))?;

    let mut rates = HashMap::new();
    rates.insert("USD".to_string(), 1.0);

    if let Some(rates_obj) = body.get("rates").and_then(|r| r.as_object()) {
        for (currency, rate) in rates_obj {
            if let Some(rate_val) = rate.as_f64() {
                rates.insert(currency.clone(), rate_val);
            }
        }
    }

    Ok(ExchangeRates {
        base: "USD".to_string(),
        rates,
        updated_at: chrono::Utc::now().to_rfc3339(),
    })
}

// ============================================================
// Tauri Commands
// ============================================================

#[tauri::command]
pub async fn pricing_get(app: AppHandle) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    Ok(store.get_settings().await)
}

#[tauri::command]
pub async fn pricing_fetch_rates(app: AppHandle) -> Result<ExchangeRates, AppError> {
    let rates = fetch_exchange_rates().await?;
    let store = app.state::<Arc<PricingStore>>();
    store.update_exchange_rates(rates.clone()).await?;
    Ok(rates)
}

#[tauri::command]
pub async fn pricing_reset(app: AppHandle) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    store.reset_to_defaults().await
}

// ========================
// Colab Commands
// ========================

#[tauri::command]
pub async fn pricing_colab_update_subscription(
    app: AppHandle,
    subscription: ColabSubscription,
) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    store.update_colab_subscription(subscription).await
}

#[tauri::command]
pub async fn pricing_colab_update_gpu(
    app: AppHandle,
    gpu_pricing: Vec<ColabGpuPricing>,
) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    store.update_colab_gpu_pricing(gpu_pricing).await
}

#[tauri::command]
pub async fn pricing_colab_calculate(app: AppHandle) -> Result<ColabPricingResult, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    Ok(store.calculate_colab_pricing().await)
}

// ========================
// Host Pricing Commands
// ========================

#[tauri::command]
pub async fn pricing_vast_update_rates(
    app: AppHandle,
    rates: VastPricingRates,
) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    store.update_vast_rates(rates).await
}

#[tauri::command]
pub async fn pricing_host_set(
    app: AppHandle,
    host_id: String,
    gpu_hourly_usd: Option<f64>,
    storage_used_gb: Option<f64>,
    source: PricingSource,
) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    let settings = store.get_settings().await;
    
    let pricing = HostPricing {
        host_id: host_id.clone(),
        gpu_hourly_usd,
        storage_used_gb,
        vast_rates: Some(settings.vast_rates.clone()),
        updated_at: chrono::Utc::now().to_rfc3339(),
        source,
    };
    
    store.set_host_pricing(host_id, pricing).await
}

#[tauri::command]
pub async fn pricing_host_remove(
    app: AppHandle,
    host_id: String,
) -> Result<PricingSettings, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    store.remove_host_pricing(&host_id).await
}

#[tauri::command]
pub async fn pricing_host_get(
    app: AppHandle,
    host_id: String,
) -> Result<Option<HostPricing>, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    Ok(store.get_host_pricing(&host_id).await)
}

#[tauri::command]
pub async fn pricing_host_calculate(
    app: AppHandle,
    host_id: String,
    host_name: Option<String>,
) -> Result<Option<HostCostBreakdown>, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    Ok(store.calculate_host_cost(&host_id, host_name).await)
}

#[tauri::command]
pub async fn pricing_host_calculate_all(
    app: AppHandle,
) -> Result<Vec<HostCostBreakdown>, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    Ok(store.calculate_all_host_costs().await)
}

/// Sync pricing from Vast.ai instance data
#[tauri::command]
pub async fn pricing_sync_vast_instance(
    app: AppHandle,
    host_id: String,
    vast_instance_id: i64,
) -> Result<HostPricing, AppError> {
    // Fetch Vast instance to get dph_total
    let cfg = crate::config::load_config().await?;
    let client = crate::vast::VastClient::from_cfg(&cfg)?;
    let instances = client.list_instances().await?;
    
    let instance = instances
        .into_iter()
        .find(|i| i.id == vast_instance_id)
        .ok_or_else(|| AppError::not_found(format!("Vast instance {} not found", vast_instance_id)))?;

    let store = app.state::<Arc<PricingStore>>();
    let settings = store.get_settings().await;
    
    let pricing = HostPricing {
        host_id: host_id.clone(),
        gpu_hourly_usd: instance.dph_total,
        storage_used_gb: None, // Would need to query disk usage separately
        vast_rates: Some(settings.vast_rates.clone()),
        updated_at: chrono::Utc::now().to_rfc3339(),
        source: PricingSource::VastApi,
    };
    
    store.set_host_pricing(host_id, pricing.clone()).await?;
    Ok(pricing)
}

// ============================================================
// Storage Usage Cache Commands
// ============================================================

/// Get cached storage usages (supports backward compatibility with r2_cache)
#[tauri::command]
pub async fn pricing_get_r2_cache(app: AppHandle) -> Result<Vec<StorageUsage>, AppError> {
    let store = app.state::<Arc<PricingStore>>();
    let settings = store.get_settings().await;
    Ok(settings.storage_usages_cache.clone())
}

/// Save storage usages to cache
#[tauri::command]
pub async fn pricing_save_r2_cache(
    app: AppHandle,
    usages: Vec<StorageUsage>,
) -> Result<(), AppError> {
    let store = app.state::<Arc<PricingStore>>();
    {
        let mut settings = store.settings.write().await;
        settings.storage_usages_cache = usages;
    }
    store.save_to_file().await
}

