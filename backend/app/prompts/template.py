from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.factor import DomainEnum


class PromptRenderError(ValueError):
    """Raised when a PromptTemplate cannot be rendered with given variables."""


class FewShotExample(BaseModel):
    """A single input -> output demonstration used for in-context learning."""

    model_config = ConfigDict(extra="forbid")

    input: str = Field(..., description="Example input shown to the model")
    output: str = Field(..., description="Ideal model output for that input")

    @field_validator("input", "output")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("few-shot input/output must not be empty")
        return value


class TemplateVariable(BaseModel):
    """Declared runtime variable for a prompt template."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Variable key injected at render time")
    required: bool = Field(default=True)
    description: Optional[str] = None


class RenderedPrompt(BaseModel):
    """The fully composed prompt plus the exact template version that produced it."""

    name: str
    version: str
    domain: Optional[DomainEnum] = None
    text: str


# Matches {identifier} placeholders, leaving JSON braces (e.g. {"factors": ...})
# untouched so few-shot examples never get mangled by substitution.
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_DEFAULT_DOMAIN_KEY = "default"


class PromptTemplate(BaseModel):
    """Versioned, structured prompt following LLM best practices.

    Sections (in render order):
      1. role            - system persona
      2. task_definition - what the model must accomplish
      3. context_boundaries - what sources the model may/may not use
      4. few_shot_examples  - domain-adaptive demonstrations
      5. output_format_spec - strict output contract
      6. rules              - hard constraints
      7. Input payload      - injected variables

    Every file that defines a template is a *version*. Prompts are never mutated
    in place; improvements ship as a new version so outputs stay attributable.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Stable identifier, e.g. 'support'")
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$", description="Semver")
    description: Optional[str] = None
    status: Literal["draft", "active", "archived"] = Field(
        default="active", description="Lifecycle state used for default resolution"
    )
    created_at: Optional[datetime] = None

    role: str = Field(..., description="System persona the model adopts")
    task_definition: str = Field(..., description="Primary objective")
    context_boundaries: Optional[str] = Field(
        None, description="What information the model may rely on"
    )
    few_shot_examples: Dict[str, List[FewShotExample]] = Field(
        default_factory=dict,
        description="Domain-keyed demonstrations; 'default' applies when no match",
    )
    output_format_spec: str = Field(..., description="Required output structure")
    rules: List[str] = Field(default_factory=list)
    variables: List[TemplateVariable] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_matches_file(cls, value: str) -> str:
        if not re.match(r"^[a-z][a-z0-9_]*$", value):
            raise ValueError(f"invalid template name '{value}'")
        return value

    @field_validator("few_shot_examples")
    @classmethod
    def _validate_domain_keys(cls, value: Dict[str, List[FewShotExample]]) -> Dict[str, List[FewShotExample]]:
        valid = set(DomainEnum.__members__) | {_DEFAULT_DOMAIN_KEY}
        for key in value:
            if key not in valid:
                raise ValueError(
                    f"unknown few-shot domain '{key}'; use 'default' or one of {sorted(valid)}"
                )
        return value

    def _examples_for(self, domain: Optional[DomainEnum]) -> List[FewShotExample]:
        if domain is not None:
            key = domain.value if isinstance(domain, DomainEnum) else str(domain)
            if key in self.few_shot_examples:
                return self.few_shot_examples[key]
        return self.few_shot_examples.get(_DEFAULT_DOMAIN_KEY, [])

    def _substitute(self, text: str, variables: Dict[str, Any]) -> str:
        def _replace(match: re.Match) -> str:
            name = match.group(1)
            if name in variables:
                return str(variables[name])
            return match.group(0)  # leave unknown braces untouched

        return _PLACEHOLDER_RE.sub(_replace, text)

    def render(self, domain: Optional[DomainEnum | str] = None, **variables: Any) -> RenderedPrompt:
        """Compose the final prompt text.

        Args:
            domain: Optional DomainEnum to select domain-specific few-shot examples.
            **variables: Values for declared template variables (and any extra
                keys you want surfaced in the Input payload section).
        """
        resolved_domain = None
        if domain is not None:
            resolved_domain = domain if isinstance(domain, DomainEnum) else DomainEnum(domain)

        missing = [
            v.name
            for v in self.variables
            if v.required and variables.get(v.name) is None
        ]
        if missing:
            raise PromptRenderError(
                f"template '{self.name}' v{self.version} missing required "
                f"variable(s): {', '.join(missing)}"
            )

        declared = {v.name for v in self.variables}
        unknown = set(variables) - declared
        if unknown:
            raise PromptRenderError(
                f"template '{self.name}' v{self.version} received undeclared "
                f"variable(s): {', '.join(sorted(unknown))}"
            )

        sections: List[str] = [self.role]

        if self.task_definition:
            sections.append(
                "## Task\n" + self._substitute(self.task_definition, variables)
            )
        if self.context_boundaries:
            sections.append(
                "## Context Boundaries\n" + self._substitute(self.context_boundaries, variables)
            )

        examples = self._examples_for(resolved_domain)
        if examples:
            blocks = []
            for index, example in enumerate(examples, 1):
                blocks.append(
                    f"### Example {index}\n"
                    f"Input:\n{example.input}\n\n"
                    f"Output:\n{example.output}"
                )
            sections.append("## Examples\n" + "\n\n".join(blocks))

        if self.output_format_spec:
            sections.append(
                "## Output Format\n" + self._substitute(self.output_format_spec, variables)
            )
        if self.rules:
            numbered = "\n".join(f"{i}. {self._substitute(r, variables)}" for i, r in enumerate(self.rules, 1))
            sections.append("## Rules\n" + numbered)

        payload = [
            f"{key}:\n{value}" for key, value in variables.items() if value is not None
        ]
        if payload:
            sections.append("## Input\n" + "\n\n".join(payload))

        text = "\n\n".join(section for section in sections if section.strip())

        return RenderedPrompt(
            name=self.name,
            version=self.version,
            domain=resolved_domain,
            text=text,
        )

    @property
    def semver_tuple(self) -> tuple[int, int, int]:
        parts = self.version.split(".")
        return tuple(int(p) for p in parts)  # type: ignore[return-value]

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(timezone.utc)
