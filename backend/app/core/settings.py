from __future__ import annotations

import json
import os
from dataclasses import asdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name, "")
    try:
        return float(raw) if raw else default
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "")
    try:
        return int(raw) if raw else default
    except Exception:
        return default


def _env_json(name: str, default: Any) -> Any:
    raw = _env(name, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


@dataclass(slots=True)
class EnvironmentModelProfile:
    factor_extractor: str
    support: str
    opposition: str
    synthesis: str
    fallback_models: List[str] = field(default_factory=list)


@dataclass(slots=True)
class GroqPricing:
    input_per_1m: float = 0.0
    output_per_1m: float = 0.0


@dataclass(slots=True)
class AppSettings:
    environment: str = "development"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = 120.0
    groq_max_concurrency: int = 8
    request_rate_limit_rpm: int = 300
    request_rate_limit_alert_threshold: float = 0.8
    error_rate_alert_threshold: float = 0.05
    health_error_rate_threshold: float = 0.10
    cache_hit_alert_floor: float = 0.25
    model_profiles: Dict[str, EnvironmentModelProfile] = field(default_factory=dict)
    pricing: Dict[str, GroqPricing] = field(default_factory=dict)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    history_db_path: str = ""
    history_enabled: bool = True
    monthly_budget_usd: float = 0.0
    daily_budget_usd: float = 0.0
    budget_alert_threshold: float = 0.8
    webhook_db_path: str = ""
    webhook_retry_max_attempts: int = 5
    webhook_retry_base_delay_seconds: float = 2.0
    prompt_db_path: str = ""
    team_db_path: str = ""

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def monthly_budget_enabled(self) -> bool:
        return self.monthly_budget_usd > 0

    @property
    def daily_budget_enabled(self) -> bool:
        return self.daily_budget_usd > 0

    @classmethod
    def from_env(cls) -> "AppSettings":
        environment = _env("AETHER_ENV", _env("APP_ENV", "development")).lower()
        groq_api_key = _env("GROQ_API_KEY")
        groq_base_url = _env("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        groq_timeout_seconds = _env_float("GROQ_TIMEOUT_SECONDS", 120.0)
        groq_max_concurrency = _env_int("GROQ_MAX_CONCURRENCY", 8)

        defaults = cls._default_profiles(environment)
        model_profiles = cls._load_model_profiles(defaults)
        pricing = cls._load_pricing()

        return cls(
            environment=environment,
            groq_api_key=groq_api_key,
            groq_base_url=groq_base_url,
            groq_timeout_seconds=groq_timeout_seconds,
            groq_max_concurrency=groq_max_concurrency,
            request_rate_limit_rpm=cls._rate_limit_for_environment(environment),
            request_rate_limit_alert_threshold=_env_float(
                "GROQ_RATE_LIMIT_ALERT_THRESHOLD", 0.8
            ),
            error_rate_alert_threshold=_env_float("GROQ_ERROR_RATE_ALERT_THRESHOLD", 0.05),
            health_error_rate_threshold=_env_float("GROQ_HEALTH_ERROR_RATE_THRESHOLD", 0.10),
            cache_hit_alert_floor=_env_float("GROQ_CACHE_HIT_ALERT_FLOOR", 0.25),
            model_profiles=model_profiles,
            pricing=pricing,
            smtp_host=_env("AETHER_SMTP_HOST"),
            smtp_port=_env_int("AETHER_SMTP_PORT", 587),
            smtp_user=_env("AETHER_SMTP_USER"),
            smtp_password=_env("AETHER_SMTP_PASSWORD"),
            smtp_from=_env("AETHER_SMTP_FROM"),
            smtp_starttls=_env("AETHER_SMTP_STARTTLS", "1").lower()
            in ("1", "true", "yes", "on"),
            history_db_path=_env("AETHER_HISTORY_DB"),
            history_enabled=_env("AETHER_HISTORY_ENABLED", "1").lower()
            in ("1", "true", "yes", "on"),
            monthly_budget_usd=_env_float("AETHER_MONTHLY_BUDGET_USD", 0.0),
            daily_budget_usd=_env_float("AETHER_DAILY_BUDGET_USD", 0.0),
            budget_alert_threshold=_env_float("AETHER_BUDGET_ALERT_THRESHOLD", 0.8),
            webhook_db_path=_env("AETHER_WEBHOOK_DB"),
            webhook_retry_max_attempts=_env_int("AETHER_WEBHOOK_MAX_ATTEMPTS", 5),
            webhook_retry_base_delay_seconds=_env_float(
                "AETHER_WEBHOOK_RETRY_BASE_DELAY", 2.0
            ),
            prompt_db_path=_env("AETHER_PROMPT_DB"),
            team_db_path=_env("AETHER_TEAM_DB"),
        )

    @staticmethod
    def _default_profiles(environment: str) -> Dict[str, EnvironmentModelProfile]:
        prod = EnvironmentModelProfile(
            factor_extractor="mixtral-8x7b-32768",
            support="mixtral-8x7b-32768",
            opposition="llama-3.1-70b-versatile",
            synthesis="llama-3.1-70b-versatile",
            fallback_models=["mixtral-8x7b-32768", "llama-3.1-70b-versatile"],
        )
        staging = EnvironmentModelProfile(
            factor_extractor="mixtral-8x7b-32768",
            support="mixtral-8x7b-32768",
            opposition="mixtral-8x7b-32768",
            synthesis="mixtral-8x7b-32768",
            fallback_models=["mixtral-8x7b-32768", "llama-3.1-70b-versatile"],
        )
        return {"production": prod, "staging": staging, "development": staging}

    @classmethod
    def _load_model_profiles(cls, defaults: Dict[str, EnvironmentModelProfile]) -> Dict[str, EnvironmentModelProfile]:
        raw_profiles = _env_json("GROQ_MODEL_PROFILES_JSON", {})
        if isinstance(raw_profiles, dict) and raw_profiles:
            profiles: Dict[str, EnvironmentModelProfile] = {}
            for env_name, payload in raw_profiles.items():
                if not isinstance(payload, dict):
                    continue
                profiles[env_name.lower()] = EnvironmentModelProfile(
                    factor_extractor=str(payload.get("factor_extractor") or defaults["production"].factor_extractor),
                    support=str(payload.get("support") or defaults["production"].support),
                    opposition=str(payload.get("opposition") or defaults["production"].opposition),
                    synthesis=str(payload.get("synthesis") or defaults["production"].synthesis),
                    fallback_models=list(payload.get("fallback_models") or defaults["production"].fallback_models),
                )
            if profiles:
                return profiles
        return defaults

    @staticmethod
    def _load_pricing() -> Dict[str, GroqPricing]:
        raw = _env_json("GROQ_MODEL_PRICING_JSON", {})
        pricing: Dict[str, GroqPricing] = {}
        if isinstance(raw, dict):
            for model_name, payload in raw.items():
                if not isinstance(payload, dict):
                    continue
                pricing[model_name] = GroqPricing(
                    input_per_1m=float(payload.get("input_per_1m", 0.0)),
                    output_per_1m=float(payload.get("output_per_1m", 0.0)),
                )
        return pricing

    @staticmethod
    def _rate_limit_for_environment(environment: str) -> int:
        env = environment.lower()
        if env == "production":
            return _env_int("GROQ_RATE_LIMIT_RPM_PROD", 1200)
        if env == "staging":
            return _env_int("GROQ_RATE_LIMIT_RPM_STAGING", 300)
        return _env_int("GROQ_RATE_LIMIT_RPM_DEV", 120)

    def profile_for(self, environment: str | None = None) -> EnvironmentModelProfile:
        env = (environment or self.environment).lower()
        return self.model_profiles.get(env) or self.model_profiles.get("production") or next(iter(self.model_profiles.values()))

    def pricing_for(self, model: str) -> GroqPricing:
        return self.pricing.get(model, GroqPricing())

    def model_for(self, agent_name: str, environment: str | None = None) -> str:
        profile = self.profile_for(environment)
        normalized = agent_name.lower()
        if "factor" in normalized:
            return profile.factor_extractor
        if "support" in normalized:
            return profile.support
        if "opp" in normalized:
            return profile.opposition
        if "synth" in normalized:
            return profile.synthesis
        return profile.synthesis

    def fallback_models_for(self, environment: str | None = None) -> List[str]:
        return list(self.profile_for(environment).fallback_models)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment,
            "groq_base_url": self.groq_base_url,
            "groq_timeout_seconds": self.groq_timeout_seconds,
            "groq_max_concurrency": self.groq_max_concurrency,
            "request_rate_limit_rpm": self.request_rate_limit_rpm,
            "request_rate_limit_alert_threshold": self.request_rate_limit_alert_threshold,
            "error_rate_alert_threshold": self.error_rate_alert_threshold,
            "health_error_rate_threshold": self.health_error_rate_threshold,
            "cache_hit_alert_floor": self.cache_hit_alert_floor,
            "model_profiles": {
                name: asdict(profile) for name, profile in self.model_profiles.items()
            },
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_from": self.smtp_from,
            "smtp_starttls": self.smtp_starttls,
            "smtp_configured": self.smtp_configured,
            "history_db_path": self.history_db_path,
            "history_enabled": self.history_enabled,
            "monthly_budget_usd": self.monthly_budget_usd,
            "daily_budget_usd": self.daily_budget_usd,
            "budget_alert_threshold": self.budget_alert_threshold,
            "webhook_db_path": self.webhook_db_path,
            "webhook_retry_max_attempts": self.webhook_retry_max_attempts,
            "webhook_retry_base_delay_seconds": self.webhook_retry_base_delay_seconds,
            "prompt_db_path": self.prompt_db_path,
            "team_db_path": self.team_db_path,
        }


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.from_env()
