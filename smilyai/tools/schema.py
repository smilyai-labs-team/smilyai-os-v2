from __future__ import annotations

from typing import Any


class ValidationError(ValueError):
    pass


def validate(arguments: Any, schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValidationError("Tool arguments must be an object")
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    unknown = set(arguments) - set(properties)
    missing = required - set(arguments)
    if unknown:
        raise ValidationError(f"Unknown arguments: {', '.join(sorted(unknown))}")
    if missing:
        raise ValidationError(f"Missing arguments: {', '.join(sorted(missing))}")
    output: dict[str, Any] = {}
    for key, value in arguments.items():
        rule = properties[key]
        expected = rule.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ValidationError(f"{key} must be a string")
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValidationError(f"{key} must be an integer")
        if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise ValidationError(f"{key} must be a number")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValidationError(f"{key} must be a boolean")
        if expected == "array" and not isinstance(value, list):
            raise ValidationError(f"{key} must be an array")
        if "enum" in rule and value not in rule["enum"]:
            raise ValidationError(f"{key} must be one of {rule['enum']}")
        if isinstance(value, (int, float)):
            if "minimum" in rule and value < rule["minimum"]:
                raise ValidationError(f"{key} is below the minimum")
            if "maximum" in rule and value > rule["maximum"]:
                raise ValidationError(f"{key} is above the maximum")
        if isinstance(value, str):
            if len(value) > rule.get("maxLength", 4096):
                raise ValidationError(f"{key} is too long")
        output[key] = value
    for key, rule in properties.items():
        if key not in output and "default" in rule:
            output[key] = rule["default"]
    return output

