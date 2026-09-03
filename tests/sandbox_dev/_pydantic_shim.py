"""
AEGIS-SWARM Razorpay Edition :: SANDBOX-ONLY Compatibility Shim
==================================================================
================================================================
DO NOT USE THIS IN PRODUCTION. THIS IS NOT PYDANTIC.
================================================================

This file exists ONLY because the build sandbox used to develop this
project has no network access and cannot `pip install pydantic`. It
provides a minimal, dependency-free stand-in for the small subset of
Pydantic's BaseModel API this codebase actually uses (field validation
via type hints, Field() with constraints, .model_dump()), so that the
schemas/agents/policy/evaluation LOGIC could be executed and verified
end-to-end in that sandbox.

WHAT THIS SHIM DOES NOT DO:
- Does not implement Pydantic's full validation engine, JSON schema
  generation, or error reporting.
- Does not support Literal-type enforcement as strictly as real
  Pydantic (accepts the value, does not raise on invalid literals).
- google.genai's response_schema= parameter REQUIRES real Pydantic
  models -- this shim CANNOT be used for actual Gemini API calls.
  Any code path that calls genai.Client(...).models.generate_content()
  was NOT executed against a real API in the sandbox; it was reviewed
  by inspection only.

HOW THE SWITCH WORKS:
app/schemas/*.py and other files import `from pydantic import BaseModel,
Field` directly -- that import is untouched and is what runs in a real
environment with pydantic installed. This shim is used ONLY by the
sandbox test scripts under tests/sandbox_dev/, which import from here
instead, specifically to exercise deterministic logic (Policy Gate
rules, evidence classification, baseline model integration,
orchestration wiring) without requiring pydantic/fastapi/google-genai
to be installed.

DO NOT import this file from anything under app/ -- it must stay
confined to sandbox-only test scripts so there is no risk of it
accidentally becoming a production dependency.
"""

import inspect
from typing import get_type_hints, get_origin, get_args


class _FieldInfo:
    def __init__(self, default=..., **constraints):
        self.default = default
        self.constraints = constraints


def Field(default=..., **constraints):
    return _FieldInfo(default, **constraints)


class ShimBaseModel:
    """Minimal stand-in for pydantic.BaseModel -- see module docstring."""

    def __init__(self, **data):
        hints = get_type_hints(self.__class__)
        cls_vars = {
            k: v for k, v in vars(self.__class__).items()
            if not k.startswith("_") and k in hints
        }

        for field_name, field_type in hints.items():
            if field_name in data:
                value = data[field_name]
            elif field_name in cls_vars and isinstance(cls_vars[field_name], _FieldInfo):
                default = cls_vars[field_name].default
                if default is ...:
                    raise ValueError(f"Missing required field: {field_name}")
                value = default
            elif field_name in cls_vars:
                value = cls_vars[field_name]
            else:
                origin = get_origin(field_type)
                args = get_args(field_type)
                if origin is type(None) or (args and type(None) in args):
                    value = None
                else:
                    raise ValueError(f"Missing required field: {field_name}")

            setattr(self, field_name, value)

    def model_dump(self, exclude: set | None = None) -> dict:
        exclude = exclude or set()
        hints = get_type_hints(self.__class__)
        return {k: getattr(self, k) for k in hints if k not in exclude}

    def __repr__(self):
        fields = ", ".join(f"{k}={v!r}" for k, v in self.model_dump().items())
        return f"{self.__class__.__name__}({fields})"
