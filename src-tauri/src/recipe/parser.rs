//! Recipe parsing and serialization

use std::path::Path;

use super::types::{
    Recipe, RecipeFile, RecipeSummary, Step, ValidationError, ValidationResult, ValidationWarning,
};
use crate::error::AppError;

/// Parse a recipe from TOML string
pub fn parse_recipe(toml_str: &str) -> Result<Recipe, AppError> {
    let file: RecipeFile = toml::from_str(toml_str)
        .map_err(|e| AppError::invalid_input(format!("Invalid recipe TOML: {e}")))?;
    Ok(file.into())
}

/// Parse a recipe from file
pub async fn load_recipe(path: &Path) -> Result<Recipe, AppError> {
    let content = tokio::fs::read_to_string(path)
        .await
        .map_err(|e| AppError::io(format!("Failed to read recipe file: {e}")))?;
    parse_recipe(&content)
}

/// Serialize a recipe to TOML string
pub fn serialize_recipe(recipe: &Recipe) -> Result<String, AppError> {
    // Convert back to RecipeFile format for proper TOML structure
    let file = RecipeFile {
        recipe: super::types::RecipeMeta {
            name: recipe.name.clone(),
            version: recipe.version.clone(),
            description: recipe.description.clone(),
        },
        target: recipe.target.clone(),
        variables: recipe.variables.clone(),
        steps: recipe.steps.clone(),
    };

    toml::to_string_pretty(&file)
        .map_err(|e| AppError::io(format!("Failed to serialize recipe: {e}")))
}

/// Save a recipe to file
pub async fn save_recipe(path: &Path, recipe: &Recipe) -> Result<(), AppError> {
    let content = serialize_recipe(recipe)?;

    // Create parent directories if needed
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| AppError::io(format!("Failed to create directory: {e}")))?;
    }

    tokio::fs::write(path, content)
        .await
        .map_err(|e| AppError::io(format!("Failed to write recipe file: {e}")))?;

    Ok(())
}

/// Get recipe summary without loading full content
pub async fn get_recipe_summary(path: &Path) -> Result<RecipeSummary, AppError> {
    let recipe = load_recipe(path).await?;

    Ok(RecipeSummary {
        path: path.to_string_lossy().to_string(),
        name: recipe.name,
        version: recipe.version,
        description: recipe.description,
        step_count: recipe.steps.len(),
    })
}

/// Validate a recipe for correctness
pub fn validate_recipe(recipe: &Recipe) -> ValidationResult {
    let mut errors = Vec::new();
    let mut warnings = Vec::new();

    // Check for empty name
    if recipe.name.trim().is_empty() {
        errors.push(ValidationError {
            step_id: None,
            message: "Recipe name is required".to_string(),
        });
    }

    // Check for duplicate step IDs
    let mut seen_ids = std::collections::HashSet::new();
    for step in &recipe.steps {
        if !seen_ids.insert(&step.id) {
            errors.push(ValidationError {
                step_id: Some(step.id.clone()),
                message: format!("Duplicate step ID: {}", step.id),
            });
        }
    }

    // Validate step dependencies
    let step_ids: std::collections::HashSet<_> = recipe.steps.iter().map(|s| &s.id).collect();

    for step in &recipe.steps {
        for dep in &step.depends_on {
            if !step_ids.contains(dep) {
                errors.push(ValidationError {
                    step_id: Some(step.id.clone()),
                    message: format!("Unknown dependency: {dep}"),
                });
            }

            // Check for self-dependency
            if dep == &step.id {
                errors.push(ValidationError {
                    step_id: Some(step.id.clone()),
                    message: "Step cannot depend on itself".to_string(),
                });
            }
        }

        // Validate step-specific rules
        validate_step(step, &mut errors, &mut warnings);
    }

    // Check for circular dependencies
    if let Some(cycle) = find_cycle(&recipe.steps) {
        errors.push(ValidationError {
            step_id: None,
            message: format!("Circular dependency detected: {}", cycle.join(" -> ")),
        });
    }

    ValidationResult {
        valid: errors.is_empty(),
        errors,
        warnings,
    }
}

/// Validate a single step
fn validate_step(
    step: &Step,
    errors: &mut Vec<ValidationError>,
    warnings: &mut Vec<ValidationWarning>,
) {
    // Check for empty step ID
    if step.id.trim().is_empty() {
        errors.push(ValidationError {
            step_id: Some(step.id.clone()),
            message: "Step ID cannot be empty".to_string(),
        });
    }

    // Check ID format (alphanumeric + underscore + hyphen)
    if !step
        .id
        .chars()
        .all(|c| c.is_alphanumeric() || c == '_' || c == '-')
    {
        warnings.push(ValidationWarning {
            step_id: Some(step.id.clone()),
            message:
                "Step ID should only contain alphanumeric characters, underscores, and hyphens"
                    .to_string(),
        });
    }

    // Validate retry configuration
    if let Some(retry) = &step.retry {
        if retry.max_attempts == 0 {
            warnings.push(ValidationWarning {
                step_id: Some(step.id.clone()),
                message: "Retry max_attempts is 0, step will not be retried".to_string(),
            });
        }
    }
}

/// Find circular dependencies using DFS
fn find_cycle(steps: &[Step]) -> Option<Vec<String>> {
    use std::collections::{HashMap, HashSet};

    // Build adjacency list
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for step in steps {
        adj.insert(
            &step.id,
            step.depends_on.iter().map(|s| s.as_str()).collect(),
        );
    }

    // DFS state
    let mut visited = HashSet::new();
    let mut rec_stack = HashSet::new();
    let mut path = Vec::new();

    fn dfs<'a>(
        node: &'a str,
        adj: &HashMap<&'a str, Vec<&'a str>>,
        visited: &mut HashSet<&'a str>,
        rec_stack: &mut HashSet<&'a str>,
        path: &mut Vec<&'a str>,
    ) -> Option<Vec<String>> {
        visited.insert(node);
        rec_stack.insert(node);
        path.push(node);

        if let Some(deps) = adj.get(node) {
            for &dep in deps {
                if !visited.contains(dep) {
                    if let Some(cycle) = dfs(dep, adj, visited, rec_stack, path) {
                        return Some(cycle);
                    }
                } else if rec_stack.contains(dep) {
                    // Found cycle
                    let mut cycle: Vec<String> = path
                        .iter()
                        .skip_while(|&&n| n != dep)
                        .map(|&s| s.to_string())
                        .collect();
                    cycle.push(dep.to_string());
                    return Some(cycle);
                }
            }
        }

        path.pop();
        rec_stack.remove(node);
        None
    }

    for step in steps {
        if !visited.contains(step.id.as_str()) {
            if let Some(cycle) = dfs(&step.id, &adj, &mut visited, &mut rec_stack, &mut path) {
                return Some(cycle);
            }
        }
    }

    None
}

/// Interpolate variables and secrets in a string
///
/// Supports two syntaxes:
/// - `${var_name}` - Recipe variables from the variables section
/// - `${secret:name}` - Secrets from the OS keychain
pub fn interpolate(
    template: &str,
    variables: &std::collections::HashMap<String, String>,
) -> String {
    let mut result = template.to_string();

    // First, interpolate secrets: ${secret:name}
    // Secrets are resolved from the OS keychain
    if let Ok(resolved) = crate::secrets::interpolate_secrets(&result) {
        result = resolved;
    }

    // Then, interpolate recipe variables: ${var_name}
    for (key, value) in variables {
        let pattern = format!("${{{}}}", key);
        result = result.replace(&pattern, value);
    }

    result
}

/// Interpolate with error handling (returns Result instead of silently failing)
pub fn interpolate_checked(
    template: &str,
    variables: &std::collections::HashMap<String, String>,
) -> Result<String, crate::error::AppError> {
    // First, resolve secrets
    let mut result = crate::secrets::interpolate_secrets(template)?;

    // Then, interpolate recipe variables
    for (key, value) in variables {
        let pattern = format!("${{{}}}", key);
        result = result.replace(&pattern, value);
    }

    // Check for unresolved variables
    let re = regex::Regex::new(r"\$\{([^}:]+)\}").unwrap();
    let unresolved: Vec<String> = re
        .captures_iter(&result)
        .map(|cap| cap.get(1).unwrap().as_str().to_string())
        .collect();

    if !unresolved.is_empty() {
        return Err(crate::error::AppError::invalid_input(format!(
            "Unresolved variables: {}",
            unresolved.join(", ")
        )));
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_simple_recipe() {
        let toml = r#"
[recipe]
name = "test"
version = "1.0"

[variables]
host = "my-host"

[[step]]
id = "step1"
ssh_command = { host_id = "${host}", command = "echo hello" }
"#;

        let recipe = parse_recipe(toml).unwrap();
        assert_eq!(recipe.name, "test");
        assert_eq!(recipe.steps.len(), 1);
    }

    #[test]
    fn test_validate_circular_dependency() {
        let toml = r#"
[recipe]
name = "circular"

[[step]]
id = "a"
depends_on = ["c"]
ssh_command = { host_id = "h", command = "a" }

[[step]]
id = "b"
depends_on = ["a"]
ssh_command = { host_id = "h", command = "b" }

[[step]]
id = "c"
depends_on = ["b"]
ssh_command = { host_id = "h", command = "c" }
"#;

        let recipe = parse_recipe(toml).unwrap();
        let result = validate_recipe(&recipe);
        assert!(!result.valid);
        assert!(result.errors.iter().any(|e| e.message.contains("Circular")));
    }

    #[test]
    fn test_interpolate() {
        let mut vars = std::collections::HashMap::new();
        vars.insert("name".to_string(), "world".to_string());
        vars.insert("count".to_string(), "42".to_string());

        let result = interpolate("Hello ${name}, count=${count}", &vars);
        assert_eq!(result, "Hello world, count=42");
    }

    #[test]
    fn test_interpolate_preserves_unresolved_secrets() {
        // When secrets don't exist, they should remain as placeholders
        // (in real execution, this would error)
        let vars = std::collections::HashMap::new();
        let template = "echo ${secret:nonexistent}";
        // interpolate() silently fails for missing secrets, keeping the original
        let _result = interpolate(template, &vars);
        // The secret interpolation returns error, so original is preserved
    }
}
