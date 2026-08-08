from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

import httpx
from google.genai import types
from sqlalchemy import create_engine, text as sql_text

from app.schemas.tooling import ToolInvocationRecord


ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any] | Any]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    display_name: str
    description: str
    parameters_json_schema: Dict[str, Any]
    handler: ToolHandler

    def to_gemini_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=self.parameters_json_schema,
        )


def _ensure_list(values: Any) -> List[float]:
    if values is None:
        return []
    if isinstance(values, list):
        return [float(v) for v in values]
    return [float(v) for v in list(values)]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if percentile <= 0:
        return float(ordered[0])
    if percentile >= 100:
        return float(ordered[-1])
    rank = (len(ordered) - 1) * (percentile / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    weight = rank - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _linear_trend(values: Sequence[float]) -> Dict[str, float]:
    n = len(values)
    if n < 2:
        return {"slope": 0.0, "intercept": values[0] if values else 0.0, "r_value": 0.0}

    x_vals = list(range(n))
    x_mean = _mean(x_vals)
    y_mean = _mean(values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, values))
    denominator = sum((x - x_mean) ** 2 for x in x_vals) or 1.0
    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    ss_tot = sum((y - y_mean) ** 2 for y in values)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, values))
    r_squared = 1.0 - (ss_res / ss_tot) if ss_tot else 0.0
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r_value": float(math.sqrt(max(r_squared, 0.0))),
    }


def _safe_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    return value


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[str, ToolDefinition] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        self.register(
            ToolDefinition(
                name="summarize_metric",
                display_name="SummarizeMetric",
                description="Calculate sum, average, or percentile over numeric values.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "values": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Numeric values to summarize.",
                        },
                        "operation": {
                            "type": "string",
                            "enum": ["sum", "average", "percentile"],
                            "description": "Metric to compute.",
                        },
                        "percentile": {
                            "type": "number",
                            "description": "Percentile to compute when operation is percentile.",
                        },
                        "metric_name": {"type": "string", "description": "Optional metric label."},
                    },
                    "required": ["values", "operation"],
                },
                handler=self._summarize_metric,
            )
        )
        self.register(
            ToolDefinition(
                name="trend_analysis",
                display_name="TrendAnalysis",
                description="Analyze a numeric series for direction, slope, and change over time.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "values": {
                            "type": "array",
                            "items": {"type": "number"},
                            "description": "Ordered numeric series.",
                        },
                        "labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional labels for each observation.",
                        },
                        "series_name": {"type": "string"},
                    },
                    "required": ["values"],
                },
                handler=self._trend_analysis,
            )
        )
        self.register(
            ToolDefinition(
                name="statistical_test",
                display_name="StatisticalTest",
                description="Run a basic statistical test such as a Welch t-test or paired t-test.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "test_type": {
                            "type": "string",
                            "enum": ["welch_t", "paired_t", "one_sample_t"],
                        },
                        "sample_a": {"type": "array", "items": {"type": "number"}},
                        "sample_b": {"type": "array", "items": {"type": "number"}},
                        "population_mean": {"type": "number"},
                        "alpha": {"type": "number", "default": 0.05},
                    },
                    "required": ["test_type", "sample_a"],
                },
                handler=self._statistical_test,
            )
        )
        self.register(
            ToolDefinition(
                name="fetch_external_data",
                display_name="FetchExternalData",
                description="Fetch data from an external API or a SQL database source.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {
                        "source_type": {
                            "type": "string",
                            "enum": ["http", "sql"],
                        },
                        "source": {
                            "type": "string",
                            "description": "HTTP URL or SQLAlchemy connection string.",
                        },
                        "resource": {
                            "type": "string",
                            "description": "HTTP path/query or SQL SELECT statement.",
                        },
                        "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                        "params": {"type": "object"},
                        "headers": {"type": "object"},
                        "body": {"type": "object"},
                        "limit": {"type": "integer", "default": 20},
                    },
                    "required": ["source_type", "source", "resource"],
                },
                handler=self._fetch_external_data,
            )
        )

    def register(self, definition: ToolDefinition) -> None:
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        if name not in self._definitions:
            raise KeyError(f"Unknown tool: {name}")
        return self._definitions[name]

    def list_tools(self, names: Optional[Sequence[str]] = None) -> List[ToolDefinition]:
        if names is None:
            return list(self._definitions.values())
        return [self.get(name) for name in names if name in self._definitions]

    def describe(self, names: Optional[Sequence[str]] = None) -> str:
        tools = self.list_tools(names)
        lines = []
        for tool in tools:
            lines.append(f"- {tool.display_name} ({tool.name}): {tool.description}")
        return "\n".join(lines)

    def build_gemini_tools(self, names: Optional[Sequence[str]] = None) -> List[types.Tool]:
        declarations = [tool.to_gemini_declaration() for tool in self.list_tools(names)]
        if not declarations:
            return []
        return [types.Tool(function_declarations=declarations)]

    async def execute(self, name: str, arguments: Dict[str, Any], *, agent: str) -> ToolInvocationRecord:
        definition = self.get(name)
        started = time.perf_counter()
        try:
            result = definition.handler(arguments)
            if inspect.isawaitable(result):
                result = await result
            result = _safe_json(result)
            return ToolInvocationRecord(
                tool_name=definition.name,
                display_name=definition.display_name,
                agent=agent,
                arguments=_safe_json(arguments),
                result=result,
                success=True,
                latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )
        except Exception as exc:
            return ToolInvocationRecord(
                tool_name=definition.name,
                display_name=definition.display_name,
                agent=agent,
                arguments=_safe_json(arguments),
                result=None,
                success=False,
                error=str(exc),
                latency_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )

    def _summarize_metric(self, args: Dict[str, Any]) -> Dict[str, Any]:
        values = _ensure_list(args.get("values"))
        operation = str(args.get("operation", "average")).lower()
        metric_name = str(args.get("metric_name") or "metric")
        percentile = float(args.get("percentile", 50))

        if operation == "sum":
            value = float(sum(values))
        elif operation == "average":
            value = float(_mean(values))
        elif operation == "percentile":
            value = float(_percentile(values, percentile))
        else:
            raise ValueError(f"Unsupported operation: {operation}")

        return {
            "metric_name": metric_name,
            "operation": operation,
            "value": value,
            "count": len(values),
            "percentile": percentile if operation == "percentile" else None,
        }

    def _trend_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        values = _ensure_list(args.get("values"))
        labels = [str(label) for label in args.get("labels", []) or []]
        series_name = str(args.get("series_name") or "series")

        if len(values) < 2:
            return {
                "series_name": series_name,
                "direction": "flat",
                "slope": 0.0,
                "pct_change": 0.0,
                "start_value": values[0] if values else 0.0,
                "end_value": values[-1] if values else 0.0,
                "r_value": 0.0,
                "labels": labels,
            }

        trend = _linear_trend(values)
        start_value = values[0]
        end_value = values[-1]
        pct_change = ((end_value - start_value) / abs(start_value) * 100.0) if start_value else 0.0
        slope = trend["slope"]
        if abs(slope) < 1e-12:
            direction = "flat"
        elif slope > 0:
            direction = "up"
        else:
            direction = "down"

        return {
            "series_name": series_name,
            "direction": direction,
            "slope": round(slope, 6),
            "pct_change": round(pct_change, 4),
            "start_value": start_value,
            "end_value": end_value,
            "min_value": min(values),
            "max_value": max(values),
            "r_value": round(trend["r_value"], 6),
            "labels": labels,
        }

    def _statistical_test(self, args: Dict[str, Any]) -> Dict[str, Any]:
        test_type = str(args.get("test_type", "welch_t")).lower()
        sample_a = _ensure_list(args.get("sample_a"))
        sample_b = _ensure_list(args.get("sample_b"))
        population_mean = args.get("population_mean")
        alpha = float(args.get("alpha", 0.05))

        if len(sample_a) < 1:
            raise ValueError("sample_a must contain at least one value")

        if test_type == "one_sample_t":
            if population_mean is None or len(sample_a) < 2:
                raise ValueError("one_sample_t requires population_mean and at least 2 sample_a values")
            mean_a = _mean(sample_a)
            std_a = math.sqrt(sum((x - mean_a) ** 2 for x in sample_a) / (len(sample_a) - 1))
            if std_a == 0:
                statistic = 0.0
                df = len(sample_a) - 1
            else:
                statistic = (mean_a - float(population_mean)) / (std_a / math.sqrt(len(sample_a)))
                df = len(sample_a) - 1
            p_value = 2 * (1 - NormalDist().cdf(abs(statistic)))
            return {
                "test_type": test_type,
                "statistic": round(statistic, 6),
                "degrees_of_freedom": df,
                "p_value": round(p_value, 6),
                "alpha": alpha,
                "significant": p_value < alpha,
                "sample_a_mean": round(mean_a, 6),
                "population_mean": population_mean,
            }

        if not sample_b:
            raise ValueError(f"{test_type} requires sample_b")

        mean_a = _mean(sample_a)
        mean_b = _mean(sample_b)
        var_a = sum((x - mean_a) ** 2 for x in sample_a) / (len(sample_a) - 1 if len(sample_a) > 1 else 1)
        var_b = sum((x - mean_b) ** 2 for x in sample_b) / (len(sample_b) - 1 if len(sample_b) > 1 else 1)

        if test_type == "paired_t":
            if len(sample_a) != len(sample_b):
                raise ValueError("paired_t requires equal-length samples")
            diffs = [a - b for a, b in zip(sample_a, sample_b)]
            mean_diff = _mean(diffs)
            if len(diffs) < 2:
                statistic = 0.0
                df = len(diffs) - 1
            else:
                std_diff = math.sqrt(sum((x - mean_diff) ** 2 for x in diffs) / (len(diffs) - 1))
                statistic = mean_diff / (std_diff / math.sqrt(len(diffs))) if std_diff else 0.0
                df = len(diffs) - 1
            p_value = 2 * (1 - NormalDist().cdf(abs(statistic)))
            return {
                "test_type": test_type,
                "statistic": round(statistic, 6),
                "degrees_of_freedom": df,
                "p_value": round(p_value, 6),
                "alpha": alpha,
                "significant": p_value < alpha,
                "sample_a_mean": round(mean_a, 6),
                "sample_b_mean": round(mean_b, 6),
                "mean_difference": round(mean_diff, 6),
            }

        if test_type != "welch_t":
            raise ValueError(f"Unsupported test_type: {test_type}")

        se = math.sqrt((var_a / len(sample_a)) + (var_b / len(sample_b)))
        statistic = (mean_a - mean_b) / se if se else 0.0
        numerator = (var_a / len(sample_a) + var_b / len(sample_b)) ** 2
        denominator = 0.0
        if len(sample_a) > 1 and var_a:
            denominator += ((var_a / len(sample_a)) ** 2) / (len(sample_a) - 1)
        if len(sample_b) > 1 and var_b:
            denominator += ((var_b / len(sample_b)) ** 2) / (len(sample_b) - 1)
        df = numerator / denominator if denominator else min(len(sample_a), len(sample_b)) - 1
        p_value = 2 * (1 - NormalDist().cdf(abs(statistic)))
        return {
            "test_type": test_type,
            "statistic": round(statistic, 6),
            "degrees_of_freedom": round(df, 4),
            "p_value": round(p_value, 6),
            "alpha": alpha,
            "significant": p_value < alpha,
            "sample_a_mean": round(mean_a, 6),
            "sample_b_mean": round(mean_b, 6),
            "mean_difference": round(mean_a - mean_b, 6),
        }

    async def _fetch_external_data(self, args: Dict[str, Any]) -> Dict[str, Any]:
        source_type = str(args.get("source_type", "")).lower()
        source = str(args.get("source", ""))
        resource = str(args.get("resource", ""))
        method = str(args.get("method", "GET")).upper()
        params = args.get("params") or {}
        headers = args.get("headers") or {}
        body = args.get("body") or {}
        limit = int(args.get("limit", 20))

        if source_type == "http":
            url = source.rstrip("/") + "/" + resource.lstrip("/")
            async with httpx.AsyncClient(timeout=20.0) as client:
                if method == "POST":
                    response = await client.post(url, params=params, json=body, headers=headers)
                else:
                    response = await client.get(url, params=params, headers=headers)

            content_type = response.headers.get("content-type", "")
            parsed: Any
            if "application/json" in content_type:
                try:
                    parsed = response.json()
                except Exception:
                    parsed = response.text
            else:
                parsed = response.text

            return {
                "source_type": source_type,
                "url": url,
                "status_code": response.status_code,
                "content_type": content_type,
                "data": parsed,
            }

        if source_type == "sql":
            connection_string = source
            query = resource.strip()
            if not query.lower().startswith("select"):
                raise ValueError("SQL fetch only allows SELECT queries")
            engine = create_engine(connection_string)

            def _run_query() -> Dict[str, Any]:
                with engine.connect() as connection:
                    result = connection.execute(sql_text(query))
                    columns = list(result.keys())
                    rows = [dict(zip(columns, row)) for row in result.fetchall()]
                    return {
                        "source_type": source_type,
                        "source": connection_string,
                        "columns": columns,
                        "row_count": len(rows),
                        "rows": rows[:limit],
                    }

            return await asyncio.to_thread(_run_query)

        raise ValueError(f"Unsupported source_type: {source_type}")

