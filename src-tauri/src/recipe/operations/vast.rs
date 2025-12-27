//! Vast.ai operations

use crate::config::load_config;
use crate::error::AppError;
use crate::vast::VastClient;

/// Start a Vast.ai instance
pub async fn start_instance(instance_id: i64) -> Result<(), AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    client.start_instance(instance_id).await
}

/// Stop a Vast.ai instance
pub async fn stop_instance(instance_id: i64) -> Result<(), AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    client.stop_instance(instance_id).await
}

/// Destroy a Vast.ai instance
pub async fn destroy_instance(instance_id: i64) -> Result<(), AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    client.destroy_instance(instance_id).await
}

