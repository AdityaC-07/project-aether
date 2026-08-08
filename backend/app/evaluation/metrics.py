from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Type

from pydantic import BaseModel, Field

# Matches { ... } as a JSON object, tolerating markdown code fences around it.
_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


class PromptMetrics(BaseModel):
    """Deterministic quality metrics for a single prompt run.

    All scores are 0..1. A score of 1.0 means perfect on that axis. These are
    proxy signals (no LLM judge required) so they are cheap, reproducible, and
    safe to run on every production call.
    """

    relevance_score: float = Field(ge=0, le=1, description="Output grounded in the source context")
    format_adherence: float = Field(ge=0, le=1, description="Output parses into the expected schema")
    argument_strength: float = Field(ge=0, le=1, description="Claims are specific, quantified, assumption-aware")
    hallucination_risk: float = Field(ge=0, le=1, description="Fraction of output tokens absent from context")
    overall_score: float = Field(ge=0, le=1, description="Weighted combination used for ranking")


_STOPWORDS = frozenset(
    """the and of to a in for is on that with as by are be this was from it an or
    at which we you your our their they them its not no so but if then than when
    were been being can will just have has had also per per_ share unit""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_NUMERIC_RE = re.compile(r"(?:\d[\d,.]*|%|percent|up\s*by|down\s*by|grew|fell|rose|rose to|declined)")


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def _content_tokens(text: str) -> List[str]:
    return [tok for tok in _tokens(text) if tok not in _STOPWORDS]


def _bigrams(tokens: Sequence[str]) -> List[Tuple[str, str]]:
    return list(zip(tokens, tokens[1:]))


def extract_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from raw LLM output.

    Handles JSON-only responses, markdown-fenced blocks, and trailing prose.
    """
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass

    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass

    raise ValueError("no JSON object found in output")


def _token_overlap(output_tokens: Sequence[str], context_tokens: Set[str]) -> float:
    if not output_tokens:
        return 0.0
    return sum(1 for tok in output_tokens if tok in context_tokens) / len(output_tokens)


def token_overlap_ratio(text_a: str, text_b: str) -> float:
    """Fraction of A's content tokens found in B (0..1). Cheap lexical overlap.

    Used for evidence grounding and chain-coherence checks: not semantics, but
    a fast, deterministic proxy that flags disconnected or invented content.
    """
    tokens_a = _content_tokens(text_a)
    tokens_b = set(_content_tokens(text_b))
    if not tokens_a or not tokens_b:
        return 0.0
    return sum(1 for tok in tokens_a if tok in tokens_b) / len(tokens_a)


def relevance(output: str, context_text: str) -> float:
    """How much of the output is grounded in the source context.

    Uses the mean of unigram and bigram containment, so a response that
    rephrases the context still scores well while invented content scores low.
    """
    if not context_text.strip() or not output.strip():
        return 0.0

    out_uni = _content_tokens(output)
    ctx_uni = set(_content_tokens(context_text))
    unigram = _token_overlap(out_uni, ctx_uni)

    out_bi = _bigrams(out_uni)
    ctx_bi = set(_bigrams(_content_tokens(context_text)))
    bigram = _token_overlap(out_bi, ctx_bi)

    return round((unigram + bigram) / 2.0, 4)


def hallucination_risk(output: str, context_text: str) -> float:
    """Fraction of meaningful output tokens not present in the context."""
    if not context_text.strip() or not output.strip():
        return 0.0
    out_uni = _content_tokens(output)
    ctx_uni = set(_content_tokens(context_text))
    if not out_uni:
        return 0.0
    novel = sum(1 for tok in out_uni if tok not in ctx_uni) / len(out_uni)
    return round(novel, 4)


def format_adherence(output: str, expected_schema: Optional[Type[BaseModel]]) -> float:
    """Whether the raw output parses into the expected Pydantic schema.

    Perfect parse -> 1.0. Valid JSON but missing required fields -> partial
    credit proportional to fields present. Not JSON at all -> 0.0. When no
    schema contract is supplied -> 1.0 (not measured).
    """
    if expected_schema is None:
        return 1.0

    try:
        data = extract_json(output)
    except ValueError:
        return 0.0

    try:
        expected_schema.model_validate(data)
        return 1.0
    except Exception:
        pass

    required_fields = [n for n, f in expected_schema.model_fields.items() if f.is_required()]
    if not required_fields:
        return 1.0
    present = sum(1 for f in required_fields if f in data)
    return round(present / len(required_fields), 4)


_ARGUMENT_LISTS = ("support_arguments", "counter_arguments")


def _text_component_score(text: str, *, min_good: int, min_ok: int) -> float:
    text = text.strip()
    if not text:
        return 0.0
    if len(text) >= min_good:
        return 1.0
    if len(text) >= min_ok:
        return 0.7
    return 0.4


def _numeric_component_score(text: str) -> float:
    text = text.strip()
    if not text:
        return 0.0
    if _NUMERIC_RE.search(text):
        return 1.0
    return 0.6


def _assumption_score(text: str) -> float:
    text = text.strip()
    if not text:
        return 0.0
    if 1 < len(text) <= 160:
        return 1.0
    return 0.5  # over-long assumptions get flagged


def _score_argument(argument: Dict[str, Any]) -> float:
    claim = _text_component_score(argument.get("claim", ""), min_good=20, min_ok=8)
    evidence = _numeric_component_score(argument.get("evidence", ""))
    assumption = _assumption_score(argument.get("assumption", ""))
    return round((claim + evidence + assumption) / 3.0, 4)


def argument_strength(data: Dict[str, Any]) -> float:
    """Average strength across structured arguments in parsed output.

    A strong argument names a concrete claim, backs it with quantified
    evidence, and states an explicit assumption. Missing components are
    penalized. If the output has no argument structure, returns 0.5 (neutral).
    """
    arguments: List[Dict[str, Any]] = []
    for key in _ARGUMENT_LISTS:
        items = data.get(key)
        if isinstance(items, list):
            arguments.extend(
                item for item in items if isinstance(item, dict) and "claim" in item
            )

    if not arguments:
        return 0.5
    return round(sum(_score_argument(a) for a in arguments) / len(arguments), 4)


class MetricsEngine:
    """Computes PromptMetrics for one run.

    Deterministic by design: no LLM in the loop, so it can run on 100% of
    production calls and feed the A/B report without extra cost.
    """

    DEFAULT_WEIGHTS = {"relevance_score": 0.4, "format_adherence": 0.3, "argument_strength": 0.3}

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        weights = weights or self.DEFAULT_WEIGHTS
        unknown = set(weights) - set(self.DEFAULT_WEIGHTS)
        if unknown:
            raise ValueError(f"unknown metric weights: {sorted(unknown)}")
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"metric weights must sum to 1.0, got {total}")
        self.weights = dict(weights)

    def evaluate(
        self,
        *,
        output: str,
        context_text: Optional[str] = None,
        expected_schema: Optional[Type[BaseModel]] = None,
    ) -> PromptMetrics:
        relevance_score = relevance(output, context_text or "")
        format_score = format_adherence(output, expected_schema)
        hallucination = hallucination_risk(output, context_text or "")

        try:
            data = extract_json(output)
            strength_score = argument_strength(data)
        except ValueError:
            strength_score = 0.5  # not a structured argument payload

        overall = (
            self.weights["relevance_score"] * relevance_score
            + self.weights["format_adherence"] * format_score
            + self.weights["argument_strength"] * strength_score
        )

        return PromptMetrics(
            relevance_score=relevance_score,
            format_adherence=format_score,
            argument_strength=strength_score,
            hallucination_risk=hallucination,
            overall_score=round(overall, 4),
        )
