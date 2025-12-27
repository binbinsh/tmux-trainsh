use serde::Serialize;
use thiserror::Error;

#[derive(Debug, Error, Serialize)]
#[error("{message}")]
pub struct AppError {
  pub code: &'static str,
  pub message: String,
}

impl AppError {
  pub fn invalid_input(message: impl Into<String>) -> Self {
    Self {
      code: "invalid_input",
      message: message.into(),
    }
  }

  pub fn not_found(message: impl Into<String>) -> Self {
    Self {
      code: "not_found",
      message: message.into(),
    }
  }

  pub fn io(message: impl Into<String>) -> Self {
    Self {
      code: "io",
      message: message.into(),
    }
  }

  pub fn http(message: impl Into<String>) -> Self {
    Self {
      code: "http",
      message: message.into(),
    }
  }

  pub fn vast_api(message: impl Into<String>) -> Self {
    Self {
      code: "vast_api",
      message: message.into(),
    }
  }

  pub fn command(message: impl Into<String>) -> Self {
    Self {
      code: "command",
      message: message.into(),
    }
  }

  pub fn permission_denied(message: impl Into<String>) -> Self {
    Self {
      code: "permission_denied",
      message: message.into(),
    }
  }

  pub fn not_implemented(message: impl Into<String>) -> Self {
    Self {
      code: "not_implemented",
      message: message.into(),
    }
  }

  pub fn network(message: impl Into<String>) -> Self {
    Self {
      code: "network",
      message: message.into(),
    }
  }

  pub fn internal(message: impl Into<String>) -> Self {
    Self {
      code: "internal",
      message: message.into(),
    }
  }

  pub fn io_error(message: impl Into<String>) -> Self {
    Self {
      code: "io_error",
      message: message.into(),
    }
  }

  pub fn keyring(message: impl Into<String>) -> Self {
    Self {
      code: "keyring",
      message: message.into(),
    }
  }
}

impl From<std::io::Error> for AppError {
  fn from(value: std::io::Error) -> Self {
    Self::io(value.to_string())
  }
}

impl From<reqwest::Error> for AppError {
  fn from(value: reqwest::Error) -> Self {
    Self::http(value.to_string())
  }
}

impl From<serde_json::Error> for AppError {
  fn from(value: serde_json::Error) -> Self {
    Self::invalid_input(value.to_string())
  }
}


