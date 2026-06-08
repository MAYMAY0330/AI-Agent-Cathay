from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, is_dataclass
from typing import Any


JsonSchema = dict[str, Any]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema
    callable: Callable[[dict[str, Any]], Any]

    def call(self, payload: dict[str, Any]) -> Any:
        _validate_schema(self.input_schema, payload, where=f"{self.name}.input")
        result = self.callable(payload)
        if isinstance(result, dict):
            _validate_schema(self.output_schema, result, where=f"{self.name}.output")
        return result


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AgentTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def call_tool(self, name: str, payload: dict[str, Any]) -> Any:
        return self.get(name).call(payload)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
                "output_schema": tool.output_schema,
            }
            for tool in self._tools.values()
        ]


def _validate_schema(schema: JsonSchema, payload: Any, *, where: str) -> None:
    if not schema:
        return
    if schema.get("type") != "object":
        return
    if not isinstance(payload, dict):
        raise ValueError(f"{where} must be an object")

    for key in schema.get("required", []):
        if key not in payload:
            raise ValueError(f"{where} missing required field: {key}")

    properties = schema.get("properties", {})
    for key, expected in properties.items():
        if key not in payload:
            continue
        _validate_type(expected, payload[key], where=f"{where}.{key}")


def _validate_type(schema: JsonSchema, value: Any, *, where: str) -> None:
    expected_type = schema.get("type")
    if expected_type is None:
        return
    if expected_type == "object":
        if not isinstance(value, dict) and not is_dataclass(value):
            raise ValueError(f"{where} must be an object")
        return
    if expected_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{where} must be an array")
        return
    if expected_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{where} must be a string")
        return
    if expected_type == "integer":
        if not isinstance(value, int):
            raise ValueError(f"{where} must be an integer")
        return
    if expected_type == "number":
        if not isinstance(value, int | float):
            raise ValueError(f"{where} must be a number")
        return
    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"{where} must be a boolean")
