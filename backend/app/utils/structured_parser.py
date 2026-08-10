from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Type, Union

from pydantic import BaseModel

LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
PARSE_FAILURES_FILE = LOGS_DIR / "parse_failures.jsonl"


class ParseFailureError(ValueError):
    """Raised when no parse strategy produced a schema-valid output."""


# --------------------------------------------------------------------------- #
# 1. JSON extraction from raw Groq text.
#    Groq has no native JSON mode guarantee, so the model's response is treated
#    as untrusted prose and we hunt for the JSON object inside it.
# --------------------------------------------------------------------------- #

def extract_json_object(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the first valid JSON *object* embedded in ``text``, else ``None``.

    Attempts, in order of increasing tolerance:
      1. The text parsed as-is.
      2. A stripped copy.
      3. Markdown fenced blocks (`````json ... ```````).
      4. The slice between the first ``{`` and last ``}``.
      5. A greedy regex ``{...}`` block.

    Anything that does not decode to a ``dict`` is skipped, so stray prose,
    trailing explanations, or multiple blocks cannot poison the result.
    """
    if not text:
        return None

    candidates: List[str] = [text]
    stripped = text.strip()
    if stripped and stripped != text:
        candidates.append(stripped)

    fence = re.match(r"^\s*```(?:json)?\s*([\s\S]*?)\s*```\s*$", text)
    if fence:
        candidates.append(fence.group(1))

    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])

    regex = re.search(r"\{[\s\S]*\}", text)
    if regex:
        candidates.append(regex.group(0))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


# --------------------------------------------------------------------------- #
# 3. FallbackParser - build a schema-valid structure when every parse attempt
#    failed. Salvages any top-level JSON keys that survive validation, then
#    fills the rest with type-appropriate scaffolding so the pipeline can keep
#    running in degraded mode.
# --------------------------------------------------------------------------- #

def _default_for_required(field_info) -> Any:
    """Type-appropriate value for a required field with no default."""
    annotation = field_info.annotation

    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())
    if origin is Union and type(None) in args:
        return None

    for meta in getattr(field_info, "metadata", ()) or ():
        ge = getattr(meta, "ge", None)
        if ge is not None and isinstance(ge, (int, float)):
            return ge if isinstance(ge, float) else int(ge)
        gt = getattr(meta, "gt", None)
        if gt is not None and isinstance(gt, (int, float)):
            return int(gt) + 1

    if annotation is str:
        return ""
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return scaffold_model(annotation)
    if origin is list or annotation is list or annotation is Sequence:
        return []
    if origin is dict or annotation is dict:
        return {}
    return None


def scaffold_model(model: Type[BaseModel]) -> Dict[str, Any]:
    """Build a schema-valid dict for ``model`` using defaults + type defaults.

    Non-required fields are omitted so their ``default`` / ``default_factory``
    apply normally. Required fields receive empty-but-valid values.
    """
    data: Dict[str, Any] = {}
    for name, field_info in model.model_fields.items():
        if not field_info.is_required():
            continue
        data[name] = _default_for_required(field_info)
    return data


class FallbackParser:
    """Constructs a valid instance of ``schema`` when the raw text is unusable.

    ``build`` merges any top-level keys recovered from partial JSON into the
    scaffold; if that merged dict validates, the salvaged data is kept,
    otherwise the pure scaffold is returned.
    """

    def build(self, raw: str, *, schema: Type[BaseModel], agent: str = "agent") -> Dict[str, Any]:
        scaffold = scaffold_model(schema)
        partial = extract_json_object(raw) or {}
        if partial:
            candidate = {**scaffold, **partial}
            try:
                schema(**candidate)
                return candidate
            except Exception:
                pass
        return scaffold


# --------------------------------------------------------------------------- #
# 4. ParseAudit - success-rate tracking + debugging dump of failed raw outputs.
# --------------------------------------------------------------------------- #

@dataclass
class ParseAudit:
    """Collects per-agent parse outcomes and logs unparseable raw responses.

    A single module-level instance (:data:`default_audit`) is shared across all
    agents so failure rates can be compared across the pipeline. Writes are
    lock-protected (agents run concurrently inside one orchestrator request).
    """

    failure_file: Path = field(default=PARSE_FAILURES_FILE, kw_only=True)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _per_agent: Dict[str, Dict[str, int]] = field(default_factory=dict, init=False, repr=False)

    def _row(self, agent: str) -> Dict[str, int]:
        row = self._per_agent.get(agent)
        if row is None:
            row = {
                "total": 0,
                "attempts": 0,
                "ok_first": 0,
                "ok_after_retry": 0,
                "fallback": 0,
                "failed": 0,
            }
            self._per_agent[agent] = row
        return row

    def record(
        self,
        *,
        agent: str,
        schema: str,
        ok: bool,
        attempts: int,
        used_fallback: bool,
        raw: str,
        model: Optional[BaseModel],
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            row = self._row(agent)
            row["total"] += 1
            row["attempts"] += attempts
            if not ok:
                row["failed"] += 1
            elif used_fallback:
                row["fallback"] += 1
            elif attempts <= 1:
                row["ok_first"] += 1
            else:
                row["ok_after_retry"] += 1

        # Log raw outputs that could not be parsed on the first attempt (both
        # retry-successes and fallbacks) so bad model behavior is debuggable.
        if not ok or used_fallback or attempts > 1:
            self._write_failure(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "agent": agent,
                    "schema": schema,
                    "attempts": attempts,
                    "used_fallback": used_fallback,
                    "ok": ok,
                    "error": error,
                    "raw": raw,
                }
            )

    def _write_failure(self, record: Dict[str, Any]) -> None:
        try:
            self.failure_file.parent.mkdir(parents=True, exist_ok=True)
            with self.failure_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass  # logging must never break the pipeline

    def stats(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = []
            for agent, row in sorted(self._per_agent.items()):
                total = row["total"]
                success = row["ok_first"] + row["ok_after_retry"]
                failures = row["fallback"] + row["failed"]
                rows.append(
                    {
                        "agent": agent,
                        "total": total,
                        "ok_first": row["ok_first"],
                        "ok_after_retry": row["ok_after_retry"],
                        "fallback": row["fallback"],
                        "failed": row["failed"],
                        "success_rate": round(success / total, 4) if total else 0.0,
                        "parse_failure_rate": round(failures / total, 4) if total else 0.0,
                        "avg_attempts": round(row["attempts"] / total, 2) if total else 0.0,
                    }
                )
            return rows

    def worst_agents(self, limit: int = 5) -> List[Dict[str, Any]]:
        return sorted(self.stats(), key=lambda row: row["parse_failure_rate"], reverse=True)[:limit]


default_audit = ParseAudit()


# --------------------------------------------------------------------------- #
# 2. ParseRetry - re-prompt the model with a strict-JSON instruction when the
#    first output failed validation.
# --------------------------------------------------------------------------- #

_RETRY_INSTRUCTION = (
    "Your previous response could not be parsed as valid JSON.\n"
    "RESPOND ONLY WITH VALID JSON. Do not include markdown code fences, "
    "explanations, or any text outside the JSON object.\n\n"
)


@dataclass
class StructuredParseResult:
    """Outcome of one structured-parse attempt, whatever the strategy."""

    data: Optional[Dict[str, Any]]
    model: Optional[BaseModel]
    raw: str
    attempts: int
    used_fallback: bool
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.model is not None


class StructuredOutputParser:
    """Extract -> validate -> re-prompt -> fallback, with audit logging.

    ``llm`` may be an object exposing ``acompletion(prompt, system, json_mode,
    config, agent_name)`` (both ``GroqLLMClient`` and ``ResilientLLMClient``
    qualify) or a plain async callable with the same signature. Pass ``None``
    to disable re-prompting (extraction + fallback only).
    """

    def __init__(
        self,
        llm: Any = None,
        *,
        max_retries: int = 2,
        audit: Optional[ParseAudit] = None,
        fallback_parser: Optional[FallbackParser] = None,
    ) -> None:
        self.llm = llm
        self.max_retries = max(0, int(max_retries))
        self.audit = audit if audit is not None else default_audit
        self.fallback_parser = fallback_parser or FallbackParser()

    # ------------------------------------------------------------------ public

    async def parse(
        self,
        content: str,
        *,
        schema: Type[BaseModel],
        agent: str = "agent",
        system: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> StructuredParseResult:
        schema_name = getattr(schema, "__name__", str(schema))

        data, model = self._validate(content, schema)
        attempts = 1

        if model is None and self.llm is not None:
            for _ in range(self.max_retries):
                attempts += 1
                retry_prompt = self._retry_prompt(content, schema)
                try:
                    retried = await self._invoke_llm(
                        retry_prompt, agent=agent, system=system, config=config
                    )
                except Exception:
                    break
                data, model = self._validate(retried, schema)
                if model is not None:
                    content = retried
                    break

        used_fallback = False
        error: Optional[str] = None
        if model is None:
            used_fallback = True
            try:
                data = self.fallback_parser.build(content, schema=schema, agent=agent)
                model = schema(**data)
            except Exception as exc:
                error = str(exc)
                data = None
                model = None

        self.audit.record(
            agent=agent,
            schema=schema_name,
            ok=model is not None,
            attempts=attempts,
            used_fallback=used_fallback,
            raw=content,
            model=model,
            error=error,
        )
        return StructuredParseResult(
            data=data,
            model=model,
            raw=content,
            attempts=attempts,
            used_fallback=used_fallback,
            error=error,
        )

    # --------------------------------------------------------------- internal

    @staticmethod
    def _validate(
        content: str, schema: Type[BaseModel]
    ) -> tuple[Optional[Dict[str, Any]], Optional[BaseModel]]:
        data = extract_json_object(content)
        if data is None:
            return None, None
        try:
            return data, schema(**data)
        except Exception:
            return None, None

    async def _invoke_llm(
        self,
        prompt: str,
        *,
        agent: str,
        system: Optional[str],
        config: Optional[Dict[str, Any]],
    ) -> str:
        llm = self.llm
        if hasattr(llm, "acompletion"):
            return await llm.acompletion(
                prompt,
                system=system,
                json_mode=True,
                config=config,
                agent_name=agent,
            )
        return await llm(
            prompt,
            system=system,
            json_mode=True,
            config=config,
            agent_name=agent,
        )

    @staticmethod
    def _retry_prompt(content: str, schema: Type[BaseModel]) -> str:
        try:
            schema_json = json.dumps(
                schema.model_json_schema(), ensure_ascii=False, indent=2, default=str
            )
        except Exception:
            schema_json = getattr(schema, "__name__", str(schema))
        try:
            example = json.dumps(
                scaffold_model(schema), ensure_ascii=False, indent=2, default=str
            )
        except Exception:
            example = "{}"
        return (
            _RETRY_INSTRUCTION
            + f"Required JSON structure:\n{schema_json}\n\n"
            + f"Valid example:\n{example}\n\n"
            + "Here is your previous output. Rewrite ONLY the JSON object, correcting any issues:\n"
            + (content[:8000])
        )
