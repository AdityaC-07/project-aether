"""Structured exporters (Markdown, CSV, JSON, HTML) for AETHER analysis results.

The PDF export lives in ``app.utils.pdf_generator``; ``build_export`` dispatches
to it for the "pdf" format so callers get a single entry point.
"""

from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from io import StringIO
from typing import Any, Dict, Tuple

REPORT_FORMATS: Dict[str, Tuple[str, str]] = {
    "pdf": ("application/pdf", "AETHER_Report.pdf"),
    "markdown": ("text/markdown", "AETHER_Report.md"),
    "md": ("text/markdown", "AETHER_Report.md"),
    "csv": ("text/csv", "AETHER_Report.csv"),
    "json": ("application/json", "AETHER_Report.json"),
    "html": ("text/html", "AETHER_Report.html"),
}

SUPPORTED_FORMATS = tuple(REPORT_FORMATS.keys())


def _normalize_format(fmt: str) -> str:
    fmt = (fmt or "pdf").strip().lower()
    if fmt == "md":
        return "markdown"
    return fmt


def _arg_confidence(debate: Dict[str, Any], role: str, index: int, arg: Dict[str, Any]) -> float | None:
    """Return per-argument confidence (0-100) from the confidence surface, if present."""
    conf_data = debate.get("confidence_data") or {}
    for entry in conf_data.get("arguments") or []:
        if entry.get("role") == role and entry.get("argument_index") == index + 1:
            value = entry.get("confidence")
            if value is not None:
                return float(value)
    return None


def _factor_confidence(debate: Dict[str, Any]) -> float | None:
    conf_data = debate.get("confidence_data") or {}
    value = conf_data.get("confidence")
    return float(value) if value is not None else None


def _executive_sections(final_report: Dict[str, Any]) -> Dict[str, str]:
    return {
        "What Worked": final_report.get("what_worked"),
        "What Failed": final_report.get("what_failed"),
        "Why It Happened": final_report.get("why_it_happened"),
        "How to Improve": final_report.get("how_to_improve"),
        "Synthesis": final_report.get("synthesis"),
        "Recommendation": final_report.get("recommendation"),
    }


def report_to_markdown(result: Dict[str, Any], input_text: str = "") -> str:
    lines: list[str] = []
    lines.append("# Project AETHER — Analysis Report")
    lines.append("")
    lines.append(f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if result.get("request_id"):
        lines.append(f"- **Request ID:** {result['request_id']}")
    final_report = result.get("final_report") or {}
    confidence_report = final_report.get("confidence_report") or {}
    if confidence_report.get("overall_confidence") is not None:
        lines.append(
            f"- **Overall confidence:** {confidence_report['overall_confidence']}%"
        )
    if confidence_report.get("synthesizer_confidence") is not None:
        lines.append(
            f"- **Synthesizer confidence:** {confidence_report['synthesizer_confidence']}%"
        )
    lines.append("")

    lines.append("## Executive Summary")
    lines.append("")
    for label, value in _executive_sections(final_report).items():
        if value:
            lines.append(f"### {label}")
            lines.append(str(value).strip())
            lines.append("")

    factors = result.get("factors") or []
    if factors:
        lines.append("## Factors")
        lines.append("")
        lines.append("| # | Factor | Domain |")
        lines.append("|---|--------|--------|")
        for index, factor in enumerate(factors, 1):
            description = str(factor.get("description") or "").replace("|", "\\|")
            domain = str(factor.get("domain") or "")
            lines.append(f"| {index} | {description} | {domain} |")
        lines.append("")

    debates = result.get("debate_logs") or []
    if debates:
        lines.append("## Debate Analysis")
        lines.append("")
        for index, debate in enumerate(debates, 1):
            factor = debate.get("factor") or {}
            title = str(factor.get("description") or f"Factor {index}")
            lines.append(f"### Factor {index}: {title}")
            domain = factor.get("domain")
            if domain:
                lines.append(f"*Domain: {domain}*")
            factor_conf = _factor_confidence(debate)
            if factor_conf is not None:
                lines.append(f"*Factor confidence: {factor_conf:.0f}%*")
            lines.append("")

            support = (debate.get("support") or {}).get("support_arguments") or []
            lines.append("#### Support")
            lines.append("")
            if support:
                for arg_index, arg in enumerate(support, 1):
                    conf = _arg_confidence(debate, "support", arg_index - 1, arg)
                    suffix = f" — **strength {conf:.0f}%**" if conf is not None else ""
                    lines.append(f"{arg_index}. **{str(arg.get('claim') or '')}**{suffix}")
                    if arg.get("evidence"):
                        lines.append(f"   - Evidence: {arg['evidence']}")
                    if arg.get("assumption"):
                        lines.append(f"   - Assumption: {arg['assumption']}")
                    lines.append("")
            else:
                lines.append("_No support arguments generated._")
                lines.append("")

            opposition = (
                (debate.get("opposition") or {}).get("counter_arguments") or []
            )
            lines.append("#### Opposition")
            lines.append("")
            if opposition:
                for arg_index, arg in enumerate(opposition, 1):
                    conf = _arg_confidence(debate, "opposition", arg_index - 1, arg)
                    suffix = f" — **strength {conf:.0f}%**" if conf is not None else ""
                    lines.append(f"{arg_index}. **{str(arg.get('challenge') or '')}**{suffix}")
                    if arg.get("target_claim"):
                        lines.append(f"   - Responds to: {arg['target_claim']}")
                    if arg.get("risk"):
                        lines.append(f"   - Risk: {arg['risk']}")
                    lines.append("")
            else:
                lines.append("_No counter-arguments generated._")
                lines.append("")

    lines.append("---")
    lines.append("_Generated by Project AETHER._")
    return "\n".join(lines).strip() + "\n"


def report_to_csv(result: Dict[str, Any], input_text: str = "") -> str:
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "factor_id",
            "factor",
            "type",
            "argument_index",
            "claim",
            "evidence",
            "assumption",
            "challenge",
            "target_claim",
            "risk",
            "confidence",
        ]
    )

    debates = result.get("debate_logs") or []
    if not debates:
        for index, factor in enumerate(result.get("factors") or [], 1):
            writer.writerow(
                [
                    factor.get("id") or f"F{index}",
                    factor.get("description") or "",
                    "factor",
                    "",
                    factor.get("description") or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        return "\ufeff" + out.getvalue()

    for debate in debates:
        factor = debate.get("factor") or {}
        factor_id = factor.get("id") or debate.get("factor_id") or "?"
        factor_desc = factor.get("description") or ""
        factor_conf = _factor_confidence(debate)
        writer.writerow(
            [
                factor_id,
                factor_desc,
                "factor",
                "",
                factor_desc,
                "",
                "",
                "",
                "",
                "",
                factor_conf if factor_conf is not None else "",
            ]
        )

        support = (debate.get("support") or {}).get("support_arguments") or []
        for arg_index, arg in enumerate(support, 1):
            conf = _arg_confidence(debate, "support", arg_index - 1, arg)
            writer.writerow(
                [
                    factor_id,
                    factor_desc,
                    "support",
                    arg_index,
                    arg.get("claim") or "",
                    arg.get("evidence") or "",
                    arg.get("assumption") or "",
                    "",
                    "",
                    "",
                    conf if conf is not None else "",
                ]
            )

        opposition = (debate.get("opposition") or {}).get("counter_arguments") or []
        for arg_index, arg in enumerate(opposition, 1):
            conf = _arg_confidence(debate, "opposition", arg_index - 1, arg)
            writer.writerow(
                [
                    factor_id,
                    factor_desc,
                    "opposition",
                    arg_index,
                    "",
                    "",
                    "",
                    arg.get("challenge") or "",
                    arg.get("target_claim") or "",
                    arg.get("risk") or "",
                    conf if conf is not None else "",
                ]
            )

    return "\ufeff" + out.getvalue()


def report_to_json(result: Dict[str, Any], input_text: str = "") -> str:
    return json.dumps(result, indent=2, ensure_ascii=False) + "\n"


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _html_report_section(label: str, value: Any) -> str:
    if not value:
        return ""
    return (
        f'<div class="report-section"><h3>{_esc(label)}</h3>'
        f"<p>{_esc(value)}</p></div>"
    )


def report_to_html(result: Dict[str, Any], input_text: str = "") -> str:
    final_report = result.get("final_report") or {}
    confidence_report = final_report.get("confidence_report") or {}
    factors = result.get("factors") or []
    debates = result.get("debate_logs") or []

    style = """
      :root { color-scheme: light; }
      * { box-sizing: border-box; }
      body {
        margin: 0; padding: 32px 16px;
        font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        color: #1e293b; background: #f1f5f9; line-height: 1.6;
      }
      .container { max-width: 920px; margin: 0 auto; }
      h1 { margin: 0 0 4px; font-size: 30px; color: #0f172a; }
      .meta { color: #64748b; font-size: 14px; margin-bottom: 24px; }
      .meta span { margin-right: 18px; }
      .report-section {
        background: #fff; border-radius: 12px; padding: 18px 20px;
        border: 1px solid #e2e8f0; margin-bottom: 16px;
      }
      .report-section h3 { margin: 0 0 8px; font-size: 15px; color: #334155; }
      .report-section p { margin: 0; }
      .confidence { font-weight: 700; color: #2563eb; }
      table { width: 100%; border-collapse: collapse; background: #fff;
        border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0;
        margin-bottom: 24px; }
      th, td { text-align: left; padding: 10px 14px; font-size: 14px;
        border-bottom: 1px solid #eef2f7; }
      th { background: #0f172a; color: #e2e8f0; font-size: 13px; }
      h2 { font-size: 20px; color: #0f172a; margin: 32px 0 14px; }
      .debate { background: #fff; border: 1px solid #e2e8f0; border-radius: 14px;
        padding: 20px; margin-bottom: 20px; }
      .debate h3 { margin: 0 0 4px; font-size: 17px; }
      .domain { color: #64748b; font-size: 13px; margin-bottom: 10px; }
      .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
      @media (max-width: 640px) { .columns { grid-template-columns: 1fr; } }
      .side { background: #f8fafc; border-radius: 10px; padding: 14px; }
      .side h4 { margin: 0 0 10px; font-size: 13px; text-transform: uppercase;
        letter-spacing: .05em; color: #64748b; }
      .arg { padding: 10px 12px; background: #fff; border-radius: 8px;
        margin-bottom: 10px; border: 1px solid #e2e8f0; font-size: 14px; }
      .arg:last-child { margin-bottom: 0; }
      .arg strong { display: block; margin-bottom: 4px; }
      .arg .strength { font-size: 12px; color: #2563eb; font-weight: 700; }
      .arg .detail { font-size: 13px; color: #475569; margin-top: 4px; }
      footer { text-align: center; color: #94a3b8; font-size: 13px;
        margin-top: 32px; }
    """

    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append("<html lang='en'><head><meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    parts.append("<title>Project AETHER — Analysis Report</title>")
    parts.append(f"<style>{style}</style></head><body>")
    parts.append("<main class='container'>")

    parts.append("<h1>Project AETHER — Analysis Report</h1>")
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts.append(f'<div class="meta"><span>Generated: {_esc(generated)}</span>')
    if result.get("request_id"):
        parts.append(f"<span>Request ID: {_esc(result['request_id'])}</span>")
    parts.append("</div>")

    overall = confidence_report.get("overall_confidence")
    synth = confidence_report.get("synthesizer_confidence")
    if overall is not None or synth is not None:
        parts.append('<div class="report-section">')
        if overall is not None:
            parts.append(f'<p>Overall confidence: <span class="confidence">{_esc(overall)}%</span></p>')
        if synth is not None:
            parts.append(f'<p>Synthesizer confidence: <span class="confidence">{_esc(synth)}%</span></p>')
        parts.append("</div>")

    for label, value in _executive_sections(final_report).items():
        parts.append(_html_report_section(label, value))

    if factors:
        parts.append("<h2>Factors</h2>")
        parts.append("<table><thead><tr><th>#</th><th>Factor</th><th>Domain</th></tr></thead><tbody>")
        for index, factor in enumerate(factors, 1):
            parts.append(
                f"<tr><td>{index}</td><td>{_esc(factor.get('description') or '')}</td>"
                f"<td>{_esc(factor.get('domain') or '')}</td></tr>"
            )
        parts.append("</tbody></table>")

    if debates:
        parts.append("<h2>Debate Analysis</h2>")
        for index, debate in enumerate(debates, 1):
            factor = debate.get("factor") or {}
            parts.append('<div class="debate">')
            title = factor.get("description") or f"Factor {index}"
            parts.append(f"<h3>Factor {index}: {_esc(title)}</h3>")
            domain = factor.get("domain")
            factor_conf = _factor_confidence(debate)
            if domain or factor_conf is not None:
                bits = []
                if domain:
                    bits.append(f"Domain: {_esc(domain)}")
                if factor_conf is not None:
                    bits.append(f"Factor confidence: <span class='confidence'>{factor_conf:.0f}%</span>")
                parts.append(f'<div class="domain">{" • ".join(bits)}</div>')
            parts.append('<div class="columns">')

            support = (debate.get("support") or {}).get("support_arguments") or []
            parts.append('<div class="side"><h4>Support</h4>')
            if support:
                for arg_index, arg in enumerate(support, 1):
                    conf = _arg_confidence(debate, "support", arg_index - 1, arg)
                    strength = (
                        f'<span class="strength">Strength: {conf:.0f}%</span>'
                        if conf is not None
                        else ""
                    )
                    parts.append('<div class="arg">')
                    parts.append(f"<strong>{_esc(arg.get('claim') or '')}</strong>{strength}")
                    if arg.get("evidence"):
                        parts.append(
                            f'<div class="detail"><b>Evidence:</b> {_esc(arg["evidence"])}</div>'
                        )
                    if arg.get("assumption"):
                        parts.append(
                            f'<div class="detail"><b>Assumption:</b> {_esc(arg["assumption"])}</div>'
                        )
                    parts.append("</div>")
            else:
                parts.append('<div class="arg">No support generated.</div>')
            parts.append("</div>")

            opposition = (
                (debate.get("opposition") or {}).get("counter_arguments") or []
            )
            parts.append('<div class="side"><h4>Opposition</h4>')
            if opposition:
                for arg_index, arg in enumerate(opposition, 1):
                    conf = _arg_confidence(debate, "opposition", arg_index - 1, arg)
                    strength = (
                        f'<span class="strength">Strength: {conf:.0f}%</span>'
                        if conf is not None
                        else ""
                    )
                    parts.append('<div class="arg">')
                    parts.append(f"<strong>{_esc(arg.get('challenge') or '')}</strong>{strength}")
                    if arg.get("target_claim"):
                        parts.append(
                            f'<div class="detail"><b>Responds to:</b> {_esc(arg["target_claim"])}</div>'
                        )
                    if arg.get("risk"):
                        parts.append(
                            f'<div class="detail"><b>Risk:</b> {_esc(arg["risk"])}</div>'
                        )
                    parts.append("</div>")
            else:
                parts.append('<div class="arg">No counter-arguments generated.</div>')
            parts.append("</div>")

            parts.append("</div>")
            parts.append("</div>")

    parts.append("<footer>Generated by Project AETHER — AI-powered debate &amp; synthesis.</footer>")
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def build_export(
    result: Dict[str, Any], input_text: str = "", fmt: str = "pdf"
) -> Tuple[bytes, str, str]:
    """Render ``result`` to the requested format.

    Returns ``(payload_bytes, media_type, filename)``.
    """
    fmt = _normalize_format(fmt)
    if fmt not in REPORT_FORMATS:
        raise ValueError(f"Unsupported export format: {fmt}")

    if fmt == "pdf":
        from app.utils.pdf_generator import AETHERPDFGenerator

        data = AETHERPDFGenerator().generate_report(result, input_text)
        return data, REPORT_FORMATS["pdf"][0], REPORT_FORMATS["pdf"][1]

    renderers = {
        "markdown": report_to_markdown,
        "csv": report_to_csv,
        "json": report_to_json,
        "html": report_to_html,
    }
    text = renderers[fmt](result, input_text)
    return text.encode("utf-8"), REPORT_FORMATS[fmt][0], REPORT_FORMATS[fmt][1]
