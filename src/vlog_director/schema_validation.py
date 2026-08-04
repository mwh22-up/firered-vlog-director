from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


@lru_cache(maxsize=1)
def _enhancement_validator() -> Draft202012Validator:
    schema_path = files("vlog_director.schemas").joinpath(
        "enhancement-plan.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def enhancement_schema_errors(document: dict[str, Any]) -> list[ValidationError]:
    return sorted(
        _enhancement_validator().iter_errors(document),
        key=lambda error: tuple(str(value) for value in error.absolute_path),
    )


@lru_cache(maxsize=1)
def _effect_plan_validator() -> Draft202012Validator:
    schema_path = files("vlog_director.schemas").joinpath("effect-plan.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def effect_plan_schema_errors(document: dict[str, Any]) -> list[ValidationError]:
    return sorted(
        _effect_plan_validator().iter_errors(document),
        key=lambda error: tuple(str(value) for value in error.absolute_path),
    )
