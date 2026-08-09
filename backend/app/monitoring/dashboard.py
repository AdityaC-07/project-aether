from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.monitoring.telemetry import TelemetryStore


def _iso_date(dt: datetime) -> str:
    return dt.date().isoformat()


class DashboardService:
    """Aggregates usage, cost, budget, and alert data for the operations
    dashboard. Reads the persistent JSONL logs written by the telemetry
    store, falling back to in-memory events when logs are empty."""

    def __init__(self, telemetry: Optional[TelemetryStore] = None) -> None:
        self.telemetry = telemetry
        self.now = datetime.now(timezone.utc)

    # -- event sources -----------------------------------------------------

    def _llm_events(self) -> List[Dict[str, Any]]:
        telemetry = self.telemetry
        path = Path(telemetry.api_log_file) if telemetry else None
        events = self._read_jsonl(path)
        if not events and telemetry:
            events = [event.to_dict() for event in telemetry._api_events]
        return events

    def _request_events(self) -> List[Dict[str, Any]]:
        telemetry = self.telemetry
        path = Path(telemetry.request_log_file) if telemetry else None
        events = self._read_jsonl(path)
        if not events and telemetry:
            events = [event.to_dict() for event in telemetry._request_events]
        return events

    @staticmethod
    def _read_jsonl(path: Optional[Path]) -> List[Dict[str, Any]]:
        if path is None or not path.exists():
            return []
        events: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except Exception:
                    continue
        return events

    # -- aggregations ------------------------------------------------------

    def full_report(self) -> Dict[str, Any]:
        now = self.now
        today = _iso_date(now)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        llm_events = self._llm_events()
        request_events = self._request_events()

        usage = self._usage(llm_events, request_events, today_start, month_start)
        costs = self._costs(llm_events, today, month_start)
        expensive = self._expensive_analyses(llm_events, today_start)
        trend = self._cost_trend(llm_events, days=30)
        budget = self._budget(costs, today)
        alerts = list(budget["alerts"])

        telemetry = self.telemetry
        if telemetry is not None:
            try:
                snapshot = telemetry.snapshot()
                alerts.extend(snapshot.alerts)
                usage["recent_requests_per_minute"] = snapshot.requests_per_minute
                usage["active_requests"] = snapshot.active_requests
            except Exception:
                pass

        return {
            "generated_at": now.isoformat(),
            "period": {
                "today": today,
                "today_start": today_start.isoformat(),
                "month_start": month_start.isoformat(),
                "days_in_month": (month_start.replace(month=month_start.month % 12 + 1, day=1)
                                  - month_start).days,
            },
            "usage": usage,
            "costs": costs,
            "expensive_analyses": expensive,
            "cost_trend": trend,
            "budget": budget,
            "alerts": sorted(set(alerts)),
        }

    @staticmethod
    def _usage(
        llm_events: List[Dict[str, Any]],
        request_events: List[Dict[str, Any]],
        today_start: datetime,
        month_start: datetime,
    ) -> Dict[str, Any]:
        def parse_ts(raw: Any) -> Optional[datetime]:
            try:
                return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                return None

        http_today = http_month = 0
        for event in request_events:
            ts = parse_ts(event.get("timestamp"))
            if ts is None:
                continue
            if ts >= today_start:
                http_today += 1
            if ts >= month_start:
                http_month += 1

        llm_today = llm_month = tokens_in_today = tokens_out_today = 0
        tokens_in_month = tokens_out_month = 0
        errors_today = 0
        for event in llm_events:
            ts = parse_ts(event.get("timestamp"))
            if ts is None:
                continue
            in_month = ts >= month_start
            in_day = ts >= today_start
            if in_day:
                llm_today += 1
                tokens_in_today += int(event.get("tokens_in") or 0)
                tokens_out_today += int(event.get("tokens_out") or 0)
                if event.get("status") == "error":
                    errors_today += 1
            if in_month:
                llm_month += 1
                tokens_in_month += int(event.get("tokens_in") or 0)
                tokens_out_month += int(event.get("tokens_out") or 0)

        return {
            "http_requests": {"today": http_today, "month": http_month},
            "llm_calls": {"today": llm_today, "month": llm_month},
            "llm_errors_today": errors_today,
            "llm_tokens_in": {"today": tokens_in_today, "month": tokens_in_month},
            "llm_tokens_out": {"today": tokens_out_today, "month": tokens_out_month},
        }

    @staticmethod
    def _costs(
        llm_events: List[Dict[str, Any]],
        today: str,
        month_start: datetime,
    ) -> Dict[str, Any]:
        today_cost = 0.0
        month_cost = 0.0
        by_model: Dict[str, Dict[str, float]] = defaultdict(lambda: {"calls": 0.0, "cost": 0.0})
        by_agent: Dict[str, Dict[str, float]] = defaultdict(lambda: {"calls": 0.0, "cost": 0.0})

        for event in llm_events:
            ts_raw = event.get("timestamp")
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                continue
            cost = float(event.get("cost_usd") or 0.0)
            if ts.date().isoformat() == today:
                today_cost += cost
            if ts >= month_start:
                month_cost += cost
            model = event.get("model") or "unknown"
            agent = event.get("agent") or "unknown"
            by_model[model]["calls"] += 1
            by_model[model]["cost"] += cost
            by_agent[agent]["calls"] += 1
            by_agent[agent]["cost"] += cost

        def ranked(source: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
            return sorted(
                [
                    {"name": name, "calls": int(stats["calls"]), "cost_usd": round(stats["cost"], 6)}
                    for name, stats in source.items()
                ],
                key=lambda entry: entry["cost_usd"],
                reverse=True,
            )

        return {
            "today_usd": round(today_cost, 6),
            "month_usd": round(month_cost, 6),
            "by_model": ranked(by_model),
            "by_agent": ranked(by_agent),
        }

    @staticmethod
    def _expensive_analyses(
        llm_events: List[Dict[str, Any]],
        today_start: datetime,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for event in llm_events:
            request_id = event.get("request_id")
            if not request_id:
                continue
            entry = grouped.setdefault(
                request_id,
                {"request_id": request_id, "llm_calls": 0, "cost_usd": 0.0, "models": set(), "first_seen": event.get("timestamp")},
            )
            entry["llm_calls"] += 1
            entry["cost_usd"] += float(event.get("cost_usd") or 0.0)
            entry["models"].add(event.get("model") or "unknown")
        ranked = sorted(
            grouped.values(),
            key=lambda entry: entry["cost_usd"],
            reverse=True,
        )[:limit]
        for entry in ranked:
            entry["models"] = sorted(entry["models"])
            entry["cost_usd"] = round(entry["cost_usd"], 6)
        return ranked

    def _cost_trend(self, llm_events: List[Dict[str, Any]], days: int = 30) -> List[Dict[str, Any]]:
        by_day: Dict[str, Dict[str, float]] = defaultdict(lambda: {"cost_usd": 0.0, "calls": 0.0})
        for event in llm_events:
            ts_raw = event.get("timestamp")
            try:
                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).astimezone(timezone.utc)
            except Exception:
                continue
            key = _iso_date(ts)
            by_day[key]["cost_usd"] += float(event.get("cost_usd") or 0.0)
            by_day[key]["calls"] += 1
        trend: List[Dict[str, Any]] = []
        for offset in range(days - 1, -1, -1):
            key = _iso_date(self.now - timedelta(days=offset))
            entry = by_day.get(key, {"cost_usd": 0.0, "calls": 0.0})
            trend.append(
                {
                    "date": key,
                    "cost_usd": round(entry["cost_usd"], 6),
                    "calls": int(entry["calls"]),
                }
            )
        return trend

    def _budget(self, costs: Dict[str, Any], today: str) -> Dict[str, Any]:
        settings = self.telemetry.settings if self.telemetry else None
        monthly_budget = float(getattr(settings, "monthly_budget_usd", 0.0) or 0.0)
        daily_budget = float(getattr(settings, "daily_budget_usd", 0.0) or 0.0)
        threshold = float(getattr(settings, "budget_alert_threshold", 0.8) or 0.8)

        monthly_spent = costs["month_usd"]
        daily_spent = costs["today_usd"]

        alerts: List[str] = []
        if monthly_budget > 0:
            monthly_percent = monthly_spent / monthly_budget if monthly_budget else 0.0
            if monthly_spent >= monthly_budget:
                alerts.append("budget_monthly_exceeded")
            elif monthly_percent >= threshold:
                alerts.append("budget_monthly_warning")
        else:
            monthly_percent = 0.0

        if daily_budget > 0:
            daily_percent = daily_spent / daily_budget if daily_budget else 0.0
            if daily_spent >= daily_budget:
                alerts.append("budget_daily_exceeded")
            elif daily_percent >= threshold:
                alerts.append("budget_daily_warning")
        else:
            daily_percent = 0.0

        return {
            "monthly_budget_usd": monthly_budget,
            "monthly_spent_usd": round(monthly_spent, 6),
            "monthly_percent": round(monthly_percent, 4),
            "daily_budget_usd": daily_budget,
            "daily_spent_usd": round(daily_spent, 6),
            "daily_percent": round(daily_percent, 4),
            "alert_threshold": threshold,
            "alerts": sorted(set(alerts)),
        }


_dashboard: Optional[DashboardService] = None


def get_dashboard(telemetry: Optional[TelemetryStore] = None) -> DashboardService:
    global _dashboard
    if _dashboard is None:
        _dashboard = DashboardService(telemetry=telemetry)
    return _dashboard
