# tmux-trainsh variable interpolation
# Supports ${var} and ${secret:key} syntax

import re
from typing import Dict, Callable, Optional, Any


class VariableInterpolator:
    """
    Handles variable interpolation in strings.

    Supports:
    - ${var_name} - Substitute with variable value
    - ${secret:KEY} - Substitute with secret value from secrets manager
    - ${env:VAR} - Substitute with environment variable
    - ${host:field} - Substitute with host field value

    Example:
        interpolator = VariableInterpolator(
            variables={"MODEL": "llama-7b"},
            secrets_getter=secrets.get
        )
        result = interpolator.interpolate("Training ${MODEL} with key ${secret:HF_TOKEN}")
    """

    # Pattern to match ${...} expressions
    VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')

    def __init__(
        self,
        variables: Dict[str, str] = None,
        secrets_getter: Callable[[str], Optional[str]] = None,
        env_getter: Callable[[str], Optional[str]] = None,
        host_getter: Callable[[str], Optional[str]] = None,
    ):
        """
        Initialize the interpolator.

        Args:
            variables: Dictionary of variable name -> value
            secrets_getter: Function to get secret by key
            env_getter: Function to get environment variable
            host_getter: Function to get host field value
        """
        self.variables = variables or {}
        self.secrets_getter = secrets_getter
        self.env_getter = env_getter
        self.host_getter = host_getter

    def interpolate(self, text: str, fail_on_missing: bool = False) -> str:
        """
        Interpolate variables in the given text.

        Args:
            text: The text containing ${...} expressions
            fail_on_missing: If True, raise an error for missing variables

        Returns:
            Text with variables substituted

        Raises:
            KeyError: If fail_on_missing is True and a variable is not found
        """
        if not text or "${" not in text:
            return text

        def replace(match: re.Match) -> str:
            expr = match.group(1)
            value = self._resolve(expr)

            if value is None:
                if fail_on_missing:
                    raise KeyError(f"Variable not found: {expr}")
                return match.group(0)  # Keep original

            return value

        return self.VAR_PATTERN.sub(replace, text)

    def _resolve(self, expr: str) -> Optional[str]:
        """
        Resolve a single variable expression.

        Args:
            expr: The expression inside ${...}

        Returns:
            The resolved value, or None if not found
        """
        # Check for prefixed expressions
        if ":" in expr:
            prefix, key = expr.split(":", 1)
            prefix = prefix.lower()

            if prefix == "secret" and self.secrets_getter:
                return self.secrets_getter(key)
            elif prefix == "env":
                import os
                if self.env_getter:
                    return self.env_getter(key)
                return os.environ.get(key)
            elif prefix == "host" and self.host_getter:
                return self.host_getter(key)
            else:
                # Unknown prefix, try as regular variable
                return self.variables.get(expr)
        else:
            # Simple variable lookup
            return self.variables.get(expr)

    def set_variable(self, name: str, value: str) -> None:
        """Set a variable value."""
        self.variables[name] = value

    def get_variable(self, name: str) -> Optional[str]:
        """Get a variable value."""
        return self.variables.get(name)

    def update_variables(self, variables: Dict[str, str]) -> None:
        """Update multiple variables at once."""
        self.variables.update(variables)

    def interpolate_dict(
        self, data: Dict[str, Any], fail_on_missing: bool = False
    ) -> Dict[str, Any]:
        """
        Recursively interpolate all string values in a dictionary.

        Args:
            data: Dictionary to interpolate
            fail_on_missing: If True, raise an error for missing variables

        Returns:
            Dictionary with interpolated values
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.interpolate(value, fail_on_missing)
            elif isinstance(value, dict):
                result[key] = self.interpolate_dict(value, fail_on_missing)
            elif isinstance(value, list):
                result[key] = self._interpolate_list(value, fail_on_missing)
            else:
                result[key] = value
        return result

    def _interpolate_list(
        self, data: list, fail_on_missing: bool = False
    ) -> list:
        """Recursively interpolate all string values in a list."""
        result = []
        for item in data:
            if isinstance(item, str):
                result.append(self.interpolate(item, fail_on_missing))
            elif isinstance(item, dict):
                result.append(self.interpolate_dict(item, fail_on_missing))
            elif isinstance(item, list):
                result.append(self._interpolate_list(item, fail_on_missing))
            else:
                result.append(item)
        return result


def interpolate_string(
    text: str,
    variables: Dict[str, str] = None,
    secrets_getter: Callable[[str], Optional[str]] = None,
) -> str:
    """
    Convenience function to interpolate a single string.

    Args:
        text: The text to interpolate
        variables: Variable dictionary
        secrets_getter: Function to get secrets

    Returns:
        Interpolated string
    """
    interpolator = VariableInterpolator(
        variables=variables,
        secrets_getter=secrets_getter,
    )
    return interpolator.interpolate(text)
