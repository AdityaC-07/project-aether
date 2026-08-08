from __future__ import annotations

import asyncio
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field

from app.prompts import PromptRegistry
from app.schemas.context import ReasoningContext
from app.schemas.debate import DebateTrace
from app.schemas.factor import Factor
from app.schemas.final_report import FinalReport
from app.utils.llm_client import LLMClient
from app.utils.pdf_parser import extract_metadata_and_text


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?%?")
_NEGATION_RE = re.compile(r"\b(?:not|no|never|none|cannot|can't|won't|didn't|doesn't|isn't|aren't)\b", re.I)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(_normalize(text))


def _content_tokens(text: str) -> List[str]:
    stopwords = {
        "the",
        "and",
        "of",
        "to",
        "a",
        "in",
        "for",
        "is",
        "on",
        "that",
        "with",
        "as",
        "by",
        "are",
        "be",
        "this",
        "was",
        "from",
        "it",
        "an",
        "or",
        "at",
        "which",
        "we",
        "you",
        "your",
        "our",
        "their",
        "they",
        "them",
        "its",
        "not",
        "no",
        "so",
        "but",
        "if",
        "then",
        "than",
        "when",
        "were",
        "been",
        "being",
        "can",
        "will",
        "just",
        "have",
        "has",
        "had",
        "also",
        "per",
        "share",
        "unit",
    }
    return [tok for tok in _tokens(text) if tok not in stopwords]


def _ngrams(tokens: Sequence[str], n: int) -> List[Tuple[str, ...]]:
    if len(tokens) < n:
        return []
    return list(zip(*(tokens[i:] for i in range(n))))


def _lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, ta in enumerate(a, 1):
        for j, tb in enumerate(b, 1):
            if ta == tb:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[-1][-1]


def _precision_recall_f1(overlap: float, predicted: int, reference: int) -> Dict[str, float]:
    precision = overlap / predicted if predicted else 0.0
    recall = overlap / reference if reference else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _vectorize(tokens: Sequence[str]) -> Counter[str]:
    return Counter(tokens)


def _cosine_similarity(left: Sequence[str], right: Sequence[str]) -> float:
    if not left or not right:
        return 0.0
    l_vec = _vectorize(left)
    r_vec = _vectorize(right)
    common = set(l_vec) & set(r_vec)
    dot = sum(l_vec[t] * r_vec[t] for t in common)
    l_norm = math.sqrt(sum(v * v for v in l_vec.values()))
    r_norm = math.sqrt(sum(v * v for v in r_vec.values()))
    if not l_norm or not r_norm:
        return 0.0
    return dot / (l_norm * r_norm)


def _extract_numbers(text: str) -> List[str]:
    return _NUMBER_RE.findall(text or "")


def _source_text_from_pdf_payload(document: Dict[str, Any]) -> str:
    if "text" in document and document["text"]:
        return str(document["text"])
    pages = document.get("pages") or []
    if pages:
        return "\n".join(str(page.get("text", "")) for page in pages if page.get("text"))
    return ""


@dataclass(frozen=True, slots=True)
class ExpectedArgument:
    claim: str
    evidence: str
    assumption: str = ""
    rationale: str = ""
    tool_citations: List[str] = field(default_factory=list)

    def text(self) -> str:
        parts = [self.claim, self.evidence, self.assumption, self.rationale, " ".join(self.tool_citations)]
        return " ".join(part for part in parts if part)


@dataclass(frozen=True, slots=True)
class ExpectedArgumentBundle:
    support: List[ExpectedArgument] = field(default_factory=list)
    counter: List[ExpectedArgument] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    input_context: ReasoningContext
    expected_factors: List[Factor]
    expected_arguments: Dict[str, ExpectedArgumentBundle] = field(default_factory=dict)
    source_document: Optional[Dict[str, Any]] = None
    expected_summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_pdf_path(
        cls,
        pdf_path: str | Path,
        *,
        expected_factors: Sequence[Factor],
        expected_arguments: Optional[Dict[str, ExpectedArgumentBundle]] = None,
        case_id: Optional[str] = None,
        expected_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "BenchmarkCase":
        pdf_path = Path(pdf_path)
        pdf_data = extract_metadata_and_text(pdf_path.read_bytes())
        context = ReasoningContext(
            narrative=_source_text_from_pdf_payload(pdf_data),
            extracted_facts=[],
            metrics=pdf_data.get("metrics", []),
            assumptions=[],
            limitations=[],
        )
        return cls(
            case_id=case_id or pdf_path.stem,
            input_context=context,
            expected_factors=list(expected_factors),
            expected_arguments=expected_arguments or {},
            source_document=pdf_data,
            expected_summary=expected_summary,
            metadata={
                **(metadata or {}),
                "pdf_path": str(pdf_path),
                "title": pdf_data.get("metadata", {}).get("title", ""),
            },
        )

    def annotation_template(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "input_context": self.input_context.model_dump(),
            "expected_factors": [factor.model_dump() for factor in self.expected_factors],
            "expected_arguments": {
                factor_id: {
                    "support": [asdict(arg) for arg in bundle.support],
                    "counter": [asdict(arg) for arg in bundle.counter],
                }
                for factor_id, bundle in self.expected_arguments.items()
            },
            "expected_summary": self.expected_summary or "",
            "metadata": self.metadata,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.annotation_template(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_annotation_payload(cls, payload: Dict[str, Any]) -> "BenchmarkCase":
        input_context = ReasoningContext.model_validate(payload["input_context"])
        expected_factors = [Factor.model_validate(item) for item in payload.get("expected_factors", [])]
        expected_arguments: Dict[str, ExpectedArgumentBundle] = {}
        for factor_id, bundle in (payload.get("expected_arguments") or {}).items():
            expected_arguments[factor_id] = ExpectedArgumentBundle(
                support=[ExpectedArgument(**item) for item in bundle.get("support", [])],
                counter=[ExpectedArgument(**item) for item in bundle.get("counter", [])],
            )
        return cls(
            case_id=payload["case_id"],
            input_context=input_context,
            expected_factors=expected_factors,
            expected_arguments=expected_arguments,
            expected_summary=payload.get("expected_summary") or None,
            metadata=payload.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class TestDataset:
    name: str
    cases: List[BenchmarkCase]
    description: str = ""
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self, *, indent: int = 2) -> str:
        payload = {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "metadata": self.metadata,
            "cases": [case.annotation_template() for case in self.cases],
        }
        return json.dumps(payload, ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "TestDataset":
        payload = json.loads(text)
        return cls(
            name=payload["name"],
            description=payload.get("description", ""),
            version=payload.get("version", "1.0.0"),
            metadata=payload.get("metadata") or {},
            cases=[BenchmarkCase.from_annotation_payload(item) for item in payload.get("cases", [])],
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "TestDataset":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(indent=2), encoding="utf-8")


class MetricsCalculator:
    def rouge_score(self, reference: str, candidate: str) -> Dict[str, Any]:
        ref_tokens = _content_tokens(reference)
        cand_tokens = _content_tokens(candidate)

        ref_unigrams = Counter(ref_tokens)
        cand_unigrams = Counter(cand_tokens)
        unigram_overlap = sum((ref_unigrams & cand_unigrams).values())
        rouge1 = _precision_recall_f1(unigram_overlap, len(cand_tokens), len(ref_tokens))

        ref_bigrams = Counter(_ngrams(ref_tokens, 2))
        cand_bigrams = Counter(_ngrams(cand_tokens, 2))
        bigram_overlap = sum((ref_bigrams & cand_bigrams).values())
        rouge2 = _precision_recall_f1(bigram_overlap, max(len(cand_tokens) - 1, 0), max(len(ref_tokens) - 1, 0))

        lcs = _lcs_length(ref_tokens, cand_tokens)
        rouge_l = _precision_recall_f1(lcs, len(cand_tokens), len(ref_tokens))

        score = round(0.4 * rouge1["f1"] + 0.3 * rouge2["f1"] + 0.3 * rouge_l["f1"], 4)
        return {
            "rouge1": rouge1,
            "rouge2": rouge2,
            "rougeL": rouge_l,
            "score": score,
        }

    def semantic_similarity(self, reference: str, candidate: str) -> Dict[str, Any]:
        ref_tokens = _content_tokens(reference)
        cand_tokens = _content_tokens(candidate)
        unigram_cosine = _cosine_similarity(ref_tokens, cand_tokens)
        bigram_cosine = _cosine_similarity([" ".join(bg) for bg in _ngrams(ref_tokens, 2)], [" ".join(bg) for bg in _ngrams(cand_tokens, 2)])
        jaccard = self._jaccard(ref_tokens, cand_tokens)
        score = round(0.5 * unigram_cosine + 0.3 * bigram_cosine + 0.2 * jaccard, 4)
        return {
            "cosine_unigram": round(unigram_cosine, 4),
            "cosine_bigram": round(bigram_cosine, 4),
            "jaccard": round(jaccard, 4),
            "score": score,
        }

    def factual_consistency(self, reference: str, candidate: str) -> Dict[str, Any]:
        ref_tokens = _content_tokens(reference)
        cand_tokens = _content_tokens(candidate)
        ref_numbers = set(_extract_numbers(reference))
        cand_numbers = set(_extract_numbers(candidate))

        token_coverage = self._coverage(ref_tokens, cand_tokens)
        candidate_grounding = self._coverage(cand_tokens, ref_tokens)

        numeric_recall = len(ref_numbers & cand_numbers) / len(ref_numbers) if ref_numbers else 1.0
        numeric_precision = len(ref_numbers & cand_numbers) / len(cand_numbers) if cand_numbers else 1.0
        numeric_f1 = (2 * numeric_recall * numeric_precision / (numeric_recall + numeric_precision)) if (numeric_recall and numeric_precision) else 0.0

        negation_penalty = 1.0 if _NEGATION_RE.search(candidate) and not _NEGATION_RE.search(reference) else 0.0
        hallucination = 1.0 - candidate_grounding

        score = round(
            max(
                0.0,
                min(
                    1.0,
                    0.45 * token_coverage + 0.35 * numeric_f1 + 0.20 * (1.0 - hallucination) - 0.15 * negation_penalty,
                ),
            ),
            4,
        )
        return {
            "token_coverage": round(token_coverage, 4),
            "candidate_grounding": round(candidate_grounding, 4),
            "numeric_precision": round(numeric_precision, 4),
            "numeric_recall": round(numeric_recall, 4),
            "numeric_f1": round(numeric_f1, 4),
            "negation_penalty": round(negation_penalty, 4),
            "hallucination_ratio": round(hallucination, 4),
            "score": score,
        }

    def composite_score(self, reference: str, candidate: str) -> Dict[str, Any]:
        rouge = self.rouge_score(reference, candidate)
        semantic = self.semantic_similarity(reference, candidate)
        factual = self.factual_consistency(reference, candidate)
        score = round(0.35 * rouge["score"] + 0.35 * semantic["score"] + 0.30 * factual["score"], 4)
        return {
            "rouge": rouge,
            "semantic": semantic,
            "factual": factual,
            "score": score,
        }

    @staticmethod
    def _coverage(reference_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> float:
        if not reference_tokens:
            return 1.0
        reference_set = set(reference_tokens)
        candidate_set = set(candidate_tokens)
        return len(reference_set & candidate_set) / len(reference_set)

    @staticmethod
    def _jaccard(left: Sequence[str], right: Sequence[str]) -> float:
        left_set = set(left)
        right_set = set(right)
        if not left_set and not right_set:
            return 1.0
        if not left_set or not right_set:
            return 0.0
        return len(left_set & right_set) / len(left_set | right_set)


@dataclass(frozen=True, slots=True)
class BenchmarkConfiguration:
    name: str
    model: str
    prompt_versions: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ItemScore(BaseModel):
    item_id: Optional[str] = None
    expected_text: str
    actual_text: str
    rouge: Dict[str, Any]
    semantic: Dict[str, Any]
    factual: Dict[str, Any]
    score: float
    passed: bool
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SectionScore(BaseModel):
    section: str
    score: float
    passed: bool
    threshold: float
    factual_threshold: float
    item_count: int
    matched_count: int
    missing_count: int
    extra_count: int
    items: List[ItemScore] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class CaseRunResult(BaseModel):
    case_id: str
    dataset_name: str
    configuration: str
    model: str
    prompt_versions: Dict[str, str]
    passed: bool
    overall_score: float
    section_scores: Dict[str, SectionScore]
    actual_output: Dict[str, Any]
    expected_snapshot: Dict[str, Any]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConfigurationSummary(BaseModel):
    configuration: str
    model: str
    prompt_versions: Dict[str, str]
    case_count: int
    pass_rate: float
    mean_score: float
    mean_factor_score: float
    mean_support_score: float
    mean_opposition_score: float
    mean_synthesis_score: float


class BenchmarkReport(BaseModel):
    generated_at: datetime
    dataset_name: str
    thresholds: Dict[str, float]
    configurations: List[ConfigurationSummary]
    case_results: List[CaseRunResult]

    def to_json(self, *, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)


class BenchmarkEvaluator:
    def __init__(
        self,
        *,
        metrics: Optional[MetricsCalculator] = None,
        pass_threshold: float = 0.72,
        factual_threshold: float = 0.68,
        section_weights: Optional[Dict[str, float]] = None,
        max_concurrency: int = 1,
        tracker_dir: Optional[Path] = None,
    ) -> None:
        self.metrics = metrics or MetricsCalculator()
        self.pass_threshold = pass_threshold
        self.factual_threshold = factual_threshold
        self.section_weights = section_weights or {
            "factor_extraction": 0.30,
            "support": 0.25,
            "opposition": 0.20,
            "synthesis": 0.25,
        }
        self.max_concurrency = max(1, max_concurrency)
        self.tracker_dir = tracker_dir or Path(__file__).resolve().parents[2] / "logs" / "benchmarks"
        self.tracker_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        dataset: TestDataset,
        configurations: Sequence[BenchmarkConfiguration],
    ) -> BenchmarkReport:
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [
            self._run_case_config(dataset.name, case, config, semaphore)
            for config in configurations
            for case in dataset.cases
        ]
        case_results = await asyncio.gather(*tasks)
        summaries = self._summaries(configurations, case_results)
        return BenchmarkReport(
            generated_at=datetime.now(timezone.utc),
            dataset_name=dataset.name,
            thresholds={
                "pass_threshold": self.pass_threshold,
                "factual_threshold": self.factual_threshold,
            },
            configurations=summaries,
            case_results=case_results,
        )

    async def _run_case_config(
        self,
        dataset_name: str,
        case: BenchmarkCase,
        config: BenchmarkConfiguration,
        semaphore: asyncio.Semaphore,
    ) -> CaseRunResult:
        async with semaphore:
            output = await self._execute_case(case, config)
            section_scores = self._score_case(case, output)
            overall_score = self._overall_score(section_scores)
            passed = self._is_passing(section_scores)

            return CaseRunResult(
                case_id=case.case_id,
                dataset_name=dataset_name,
                configuration=config.name,
                model=config.model,
                prompt_versions=dict(config.prompt_versions),
                passed=passed,
                overall_score=overall_score,
                section_scores=section_scores,
                actual_output=output,
                expected_snapshot=self._expected_snapshot(case),
                metadata={**case.metadata, **config.metadata},
            )

    async def _execute_case(self, case: BenchmarkCase, config: BenchmarkConfiguration) -> Dict[str, Any]:
        from app.orchestrator import AetherOrchestrator
        from app.evaluation.tracker import PromptTracker

        tracker_path = self.tracker_dir / f"{config.name}_prompt_runs.jsonl"
        llm = LLMClient(model=config.model)
        registry = PromptRegistry(active_overrides=config.prompt_versions)
        orchestrator = AetherOrchestrator(
            llm=llm,
            prompt_registry=registry,
            prompt_tracker=PromptTracker(tracker_path),
        )
        return await orchestrator.analyze(
            case.input_context,
            source_document=case.source_document,
        )

    def _score_case(self, case: BenchmarkCase, output: Dict[str, Any]) -> Dict[str, SectionScore]:
        factor_section = self._score_factors(case.expected_factors, output.get("factors", []))
        debate_logs = output.get("debate_logs", [])
        support_section, opposition_section = self._score_debates(case, debate_logs)
        synthesis_section = self._score_synthesis(case, output.get("final_report", {}))
        return {
            "factor_extraction": factor_section,
            "support": support_section,
            "opposition": opposition_section,
            "synthesis": synthesis_section,
        }

    def _score_factors(self, expected: Sequence[Factor], actual: Sequence[Dict[str, Any]]) -> SectionScore:
        expected_items = [factor.model_dump() for factor in expected]
        actual_items = list(actual or [])
        matches, missing, extra = self._match_items(
            expected_items,
            actual_items,
            expected_key=lambda item: f"{item.get('factor_id', '')} {item.get('description', '')} {item.get('domain', '')}",
            actual_key=lambda item: f"{item.get('factor_id', '')} {item.get('description', '')} {item.get('domain', '')}",
        )
        return self._section_from_matches(
            "factor_extraction",
            matches,
            missing,
            extra,
        )

    def _score_debates(
        self,
        case: BenchmarkCase,
        debate_logs: Sequence[Dict[str, Any]],
    ) -> Tuple[SectionScore, SectionScore]:
        support_items: List[Dict[str, Any]] = []
        counter_items: List[Dict[str, Any]] = []
        for debate in debate_logs or []:
            factor_id = str(debate.get("factor_id", ""))
            bundle = case.expected_arguments.get(factor_id)
            support_actual = debate.get("support", {}).get("support_arguments", [])
            opposition_actual = debate.get("opposition", {}).get("counter_arguments", [])
            if bundle is not None:
                support_items.extend(
                    self._score_item_bundle(
                        factor_id,
                        bundle.support,
                        support_actual,
                        role="support",
                    )
                )
                counter_items.extend(
                    self._score_item_bundle(
                        factor_id,
                        bundle.counter,
                        opposition_actual,
                        role="counter",
                    )
                )

        support_section = self._section_from_item_scores("support", support_items)
        opposition_section = self._section_from_item_scores("opposition", counter_items)
        return support_section, opposition_section

    def _score_synthesis(self, case: BenchmarkCase, final_report: Dict[str, Any]) -> SectionScore:
        reference = case.expected_summary or self._build_reference_summary(case)
        actual = " ".join(
            str(final_report.get(field, ""))
            for field in ("what_worked", "what_failed", "why_it_happened", "how_to_improve", "synthesis", "recommendation")
        )
        match = self._build_item_score(
            item_id="synthesis",
            expected_text=reference,
            actual_text=actual,
            metadata={"section": "synthesis"},
        )
        return self._section_from_item_scores("synthesis", [match])

    def _build_reference_summary(self, case: BenchmarkCase) -> str:
        parts: List[str] = [case.input_context.narrative]
        for factor in case.expected_factors:
            parts.append(f"{factor.factor_id}: {factor.description} ({factor.domain.value})")
            bundle = case.expected_arguments.get(factor.factor_id)
            if bundle:
                for arg in bundle.support:
                    parts.append(f"support: {arg.claim} | {arg.evidence} | {arg.assumption}")
                for arg in bundle.counter:
                    parts.append(f"counter: {arg.claim} | {arg.evidence} | {arg.assumption}")
        return " ".join(parts)

    def _score_item_bundle(
        self,
        factor_id: str,
        expected_items: Sequence[ExpectedArgument],
        actual_items: Sequence[Dict[str, Any]],
        *,
        role: str,
    ) -> List[ItemScore]:
        expected_payloads = [asdict(item) for item in expected_items]
        actual_payloads = list(actual_items or [])
        matches, _, _ = self._match_items(
            expected_payloads,
            actual_payloads,
            expected_key=lambda item: item.get("claim", ""),
            actual_key=lambda item: item.get("claim", ""),
        )
        for match in matches:
            match.metadata["factor_id"] = factor_id
            match.metadata["role"] = role
        return matches

    def _match_items(
        self,
        expected_items: Sequence[Dict[str, Any]],
        actual_items: Sequence[Dict[str, Any]],
        *,
        expected_key,
        actual_key,
    ) -> Tuple[List[ItemScore], int, int]:
        remaining = list(range(len(actual_items)))
        matches: List[ItemScore] = []

        for index, expected in enumerate(expected_items):
            best_idx = None
            best_score = -1.0
            expected_text = expected_key(expected)
            for candidate_idx in remaining:
                actual = actual_items[candidate_idx]
                actual_text = actual_key(actual)
                score = self.metrics.composite_score(expected_text, actual_text)["score"]
                if score > best_score:
                    best_score = score
                    best_idx = candidate_idx

            if best_idx is None:
                matches.append(
                    self._build_item_score(
                        item_id=str(expected.get("factor_id") or index),
                        expected_text=expected_text,
                        actual_text="",
                        metadata={"expected": expected},
                    )
                )
                continue

            remaining.remove(best_idx)
            actual = actual_items[best_idx]
            matches.append(
                self._build_item_score(
                    item_id=str(expected.get("factor_id") or index),
                    expected_text=expected_text,
                    actual_text=actual_key(actual),
                    metadata={"expected": expected, "actual": actual},
                )
            )

        extra = len(remaining)
        missing = max(0, len(expected_items) - len(matches))
        return matches, missing, extra

    def _build_item_score(
        self,
        *,
        item_id: Optional[str],
        expected_text: str,
        actual_text: str,
        metadata: Dict[str, Any],
    ) -> ItemScore:
        composite = self.metrics.composite_score(expected_text, actual_text)
        passed = composite["score"] >= self.pass_threshold and composite["factual"]["score"] >= self.factual_threshold
        return ItemScore(
            item_id=item_id,
            expected_text=expected_text,
            actual_text=actual_text,
            rouge=composite["rouge"],
            semantic=composite["semantic"],
            factual=composite["factual"],
            score=composite["score"],
            passed=passed,
            metadata=metadata,
        )

    def _section_from_matches(
        self,
        section: str,
        matches: Sequence[ItemScore],
        missing: int = 0,
        extra: int = 0,
    ) -> SectionScore:
        return self._section_from_item_scores(section, list(matches), missing=missing, extra=extra)

    def _section_from_item_scores(
        self,
        section: str,
        item_scores: Sequence[ItemScore],
        *,
        missing: int = 0,
        extra: int = 0,
    ) -> SectionScore:
        items = list(item_scores)
        if items:
            mean_score = round(sum(item.score for item in items) / len(items), 4)
            factual_mean = round(sum(item.factual["score"] for item in items) / len(items), 4)
        else:
            mean_score = 0.0
            factual_mean = 0.0
        passed = mean_score >= self.pass_threshold and factual_mean >= self.factual_threshold
        return SectionScore(
            section=section,
            score=mean_score,
            passed=passed,
            threshold=self.pass_threshold,
            factual_threshold=self.factual_threshold,
            item_count=len(items),
            matched_count=len(items),
            missing_count=missing,
            extra_count=extra,
            items=items,
            summary={
                "mean_factual": factual_mean,
                "mean_rouge": round(sum(item.rouge["score"] for item in items) / len(items), 4) if items else 0.0,
                "mean_semantic": round(sum(item.semantic["score"] for item in items) / len(items), 4) if items else 0.0,
            },
        )

    def _overall_score(self, section_scores: Dict[str, SectionScore]) -> float:
        total = 0.0
        for section, weight in self.section_weights.items():
            total += weight * section_scores.get(section, SectionScore(
                section=section,
                score=0.0,
                passed=False,
                threshold=self.pass_threshold,
                factual_threshold=self.factual_threshold,
                item_count=0,
                matched_count=0,
                missing_count=0,
                extra_count=0,
            )).score
        return round(total, 4)

    def _is_passing(self, section_scores: Dict[str, SectionScore]) -> bool:
        return all(score.passed for score in section_scores.values())

    def _expected_snapshot(self, case: BenchmarkCase) -> Dict[str, Any]:
        return {
            "expected_factors": [factor.model_dump() for factor in case.expected_factors],
            "expected_arguments": {
                factor_id: {
                    "support": [asdict(arg) for arg in bundle.support],
                    "counter": [asdict(arg) for arg in bundle.counter],
                }
                for factor_id, bundle in case.expected_arguments.items()
            },
            "expected_summary": case.expected_summary,
        }

    def _summaries(
        self,
        configurations: Sequence[BenchmarkConfiguration],
        case_results: Sequence[CaseRunResult],
    ) -> List[ConfigurationSummary]:
        grouped: Dict[str, List[CaseRunResult]] = defaultdict(list)
        for result in case_results:
            grouped[result.configuration].append(result)

        summaries: List[ConfigurationSummary] = []
        for config in configurations:
            runs = grouped.get(config.name, [])
            if runs:
                mean_score = round(sum(run.overall_score for run in runs) / len(runs), 4)
                pass_rate = round(sum(1 for run in runs if run.passed) / len(runs), 4)
                mean_factor = round(sum(run.section_scores["factor_extraction"].score for run in runs) / len(runs), 4)
                mean_support = round(sum(run.section_scores["support"].score for run in runs) / len(runs), 4)
                mean_opposition = round(sum(run.section_scores["opposition"].score for run in runs) / len(runs), 4)
                mean_synthesis = round(sum(run.section_scores["synthesis"].score for run in runs) / len(runs), 4)
            else:
                mean_score = pass_rate = mean_factor = mean_support = mean_opposition = mean_synthesis = 0.0

            summaries.append(
                ConfigurationSummary(
                    configuration=config.name,
                    model=config.model,
                    prompt_versions=dict(config.prompt_versions),
                    case_count=len(runs),
                    pass_rate=pass_rate,
                    mean_score=mean_score,
                    mean_factor_score=mean_factor,
                    mean_support_score=mean_support,
                    mean_opposition_score=mean_opposition,
                    mean_synthesis_score=mean_synthesis,
                )
            )

        summaries.sort(key=lambda item: item.mean_score, reverse=True)
        return summaries


class BenchmarkRunner:
    def __init__(
        self,
        dataset: TestDataset,
        configurations: Sequence[BenchmarkConfiguration],
        *,
        evaluator: Optional[BenchmarkEvaluator] = None,
    ) -> None:
        self.dataset = dataset
        self.configurations = list(configurations)
        self.evaluator = evaluator or BenchmarkEvaluator()

    async def run(self) -> BenchmarkReport:
        return await self.evaluator.run(self.dataset, self.configurations)

    async def compare_prompt_versions(self) -> BenchmarkReport:
        return await self.run()

    def export_json(self, report: BenchmarkReport, path: str | Path) -> None:
        Path(path).write_text(report.to_json(indent=2), encoding="utf-8")


def build_prompt_version_matrix(
    *,
    name: str,
    model: str,
    prompt_name: str,
    versions: Sequence[str],
    baseline: Optional[Dict[str, str]] = None,
) -> List[BenchmarkConfiguration]:
    baseline = dict(baseline or {})
    configs: List[BenchmarkConfiguration] = []
    for version in versions:
        prompt_versions = dict(baseline)
        prompt_versions[prompt_name] = version
        configs.append(
            BenchmarkConfiguration(
                name=f"{name}:{prompt_name}@{version}",
                model=model,
                prompt_versions=prompt_versions,
            )
        )
    return configs

