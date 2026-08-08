from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from app.prompts.template import PromptTemplate


class PromptRegistryError(Exception):
    """Raised when a template cannot be resolved."""


class PromptRegistry:
    """Loads and resolves versioned prompt templates.

    Templates live as YAML files in ``<dir>/versions/*.yaml``. Each file is a
    distinct immutable version. An optional ``<dir>/active_versions.json`` can
    pin the deployed version per prompt name (canary/promotion without code
    changes); otherwise the highest version whose ``status`` is ``active`` wins.

    A/B testing: pass an explicit ``version`` to ``get()`` to render an older
    or newer variant side-by-side with the deployed one.
    """

    def __init__(
        self,
        versions_dir: Optional[Path] = None,
        active_versions_file: Optional[Path] = None,
    ) -> None:
        self.versions_dir = Path(versions_dir) if versions_dir else Path(__file__).resolve().parent / "versions"
        self.active_versions_file = active_versions_file or self.versions_dir.parent / "active_versions.json"

        self._by_key: Dict[tuple[str, str], PromptTemplate] = {}
        self._active_overrides: Dict[str, str] = {}
        self._load_active_overrides()
        self._load_templates()

    def _load_active_overrides(self) -> None:
        if not self.active_versions_file.exists():
            return
        data = json.loads(self.active_versions_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise PromptRegistryError(f"active versions file must be a JSON object: {self.active_versions_file}")
        self._active_overrides = {str(k): str(v) for k, v in data.items()}

    def _load_templates(self) -> None:
        if not self.versions_dir.is_dir():
            raise PromptRegistryError(f"versions directory not found: {self.versions_dir}")

        for path in sorted(self.versions_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                template = PromptTemplate.model_validate(raw)
            except Exception as exc:
                raise PromptRegistryError(f"failed to load prompt template {path.name}: {exc}") from exc

            key = (template.name, template.version)
            if key in self._by_key:
                raise PromptRegistryError(
                    f"duplicate template '{template.name}' version {template.version}"
                )
            self._by_key[key] = template

    # -- queries ------------------------------------------------------------

    def names(self) -> List[str]:
        return sorted({name for name, _ in self._by_key})

    def versions(self, name: str) -> List[PromptTemplate]:
        return sorted(
            (t for (n, _), t in self._by_key.items() if n == name),
            key=lambda t: t.semver_tuple,
        )

    def get(
        self,
        name: str,
        version: Optional[str] = None,
    ) -> PromptTemplate:
        """Resolve a template.

        Without ``version``: the configured active override, else the highest
        version flagged ``active``. With ``version``: that exact version
        (needed for A/B testing historical variants).
        """
        if version is not None:
            template = self._by_key.get((name, version))
            if template is None:
                raise PromptRegistryError(
                    f"no version {version} of prompt '{name}'. Available: "
                    f"{[t.version for t in self.versions(name)] or 'none'}"
                )
            return template

        override = self._active_overrides.get(name)
        if override:
            pinned = self._by_key.get((name, override))
            if pinned is not None:
                return pinned
            raise PromptRegistryError(
                f"active_versions.json pins '{name}' to {override}, but no such version exists"
            )

        for template in reversed(self.versions(name)):
            if template.status == "active":
                return template

        raise PromptRegistryError(
            f"no active version of prompt '{name}'. Available: {[t.version for t in self.versions(name)] or 'none'}"
        )

    def register(self, template: PromptTemplate) -> None:
        """Register an in-memory template (useful for tests)."""
        key = (template.name, template.version)
        if key in self._by_key:
            raise PromptRegistryError(
                f"duplicate template '{template.name}' version {template.version}"
            )
        self._by_key[key] = template
