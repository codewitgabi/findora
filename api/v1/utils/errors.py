from fastapi.exceptions import RequestValidationError


def field_validation_error(field: str, message: str) -> RequestValidationError:
    """Build a 422 that renders through the standard ``errors: [{field, ...}]`` envelope."""
    return RequestValidationError(
        [{"loc": ("body", field), "msg": message, "type": "value_error", "input": None}]
    )
