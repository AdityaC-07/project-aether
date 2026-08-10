import React, { useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Coins,
  Cpu,
  Database,
  FileJson,
  FileSpreadsheet,
  FileText,
  ListChecks,
  Mail,
  Microscope,
  RefreshCw,
  Rocket,
  Scale,
  Share2,
  Target,
  Timer,
  TrendingUp,
  XCircle,
} from "lucide-react";
import { ENGINE_LABEL, isGroqBackend } from "../services/api";
import ArgumentComparison from "./ArgumentComparison";
import DebateArena from "./DebateArena";

const EXPORT_FORMATS = [
  { key: "pdf", label: "PDF", hint: "Report", icon: FileText },
  { key: "markdown", label: "Markdown", hint: "GitHub / blog", icon: FileText },
  { key: "csv", label: "CSV", hint: "Spreadsheets", icon: FileSpreadsheet },
  { key: "json", label: "JSON", hint: "Programmatic", icon: FileJson },
  { key: "html", label: "HTML", hint: "Standalone", icon: FileText },
];

const fmtMs = (ms) => (ms == null ? "—" : `${Math.round(ms)} ms`);
const fmtUsd = (v) => (v == null ? "—" : `$${Number(v).toFixed(6)}`);
const fmtPct = (v) => (v == null ? "—" : `${Math.round(Number(v) * 100)}%`);

const RuntimePanel = ({ result, metrics }) => {
  const decisions = result?.resilience?.decisions || [];
  const hasMetrics = !!(metrics && Object.keys(metrics).length);
  const modelCounts = hasMetrics ? Object.entries(metrics.model_counts || {}) : [];
  const agentLatency = hasMetrics
    ? Object.entries(metrics.agent_latency_ms || {})
    : [];
  const alerts = hasMetrics ? metrics.alerts || [] : [];

  return (
    <div className="section">
      <strong className="section-header">
        <Cpu className="icon" aria-hidden="true" />
        Runtime
      </strong>
      <div className="runtime-panel">
        <div className="runtime-row">
          <span className="runtime-label">Engine</span>
          <span className="runtime-value">
            <span className="engine-badge groq">{ENGINE_LABEL}</span>
          </span>
        </div>

        {decisions.length > 0 && (
          <>
            <div className="runtime-subheader">Model calls</div>
            {decisions.map((d, i) => (
              <div className="runtime-row" key={i}>
                <span className="runtime-label">{d.agent || "agent"}</span>
                <span className="runtime-value">
                  {d.model}
                  <span className="runtime-muted"> · {fmtMs(d.elapsed_ms)}</span>
                  {d.cached && <span className="cache-tag">cached</span>}
                  {d.error_code && (
                    <span className="runtime-warn">
                      {d.recovery_action || d.error_code}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </>
        )}

        {modelCounts.length > 0 && (
          <>
            <div className="runtime-subheader">Models used</div>
            {modelCounts.map(([model, count]) => (
              <div className="runtime-row" key={model}>
                <span className="runtime-label">{model}</span>
                <span className="runtime-value">
                  {count} call{count === 1 ? "" : "s"}
                </span>
              </div>
            ))}
          </>
        )}

        {agentLatency.length > 0 && (
          <>
            <div className="runtime-subheader">Avg response per agent</div>
            {agentLatency.map(([agent, info]) => (
              <div className="runtime-row" key={agent}>
                <span className="runtime-label">{agent}</span>
                <span className="runtime-value">{fmtMs(info?.avg_ms)}</span>
              </div>
            ))}
          </>
        )}

        {hasMetrics && (
          <div className="runtime-grid">
            <div className="runtime-stat">
              <Coins className="icon" aria-hidden="true" />
              <span className="runtime-stat-label">Cost today</span>
              <span className="runtime-stat-value">
                {fmtUsd(metrics.cost_today_usd)}
              </span>
            </div>
            <div className="runtime-stat">
              <Database className="icon" aria-hidden="true" />
              <span className="runtime-stat-label">Cache hit</span>
              <span className="runtime-stat-value">
                {fmtPct(metrics.cache_hit_ratio)}
              </span>
            </div>
            <div className="runtime-stat">
              <Timer className="icon" aria-hidden="true" />
              <span className="runtime-stat-label">Requests/min</span>
              <span className="runtime-stat-value">
                {metrics.requests_per_minute ?? "—"}
              </span>
            </div>
          </div>
        )}

        {alerts.length > 0 && (
          <div className="runtime-alerts">
            {alerts.map((alert) => (
              <div className="runtime-alert-row" key={alert}>
                <AlertTriangle className="icon" aria-hidden="true" />
                {alert}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const ResultsDisplay = ({
  result,
  error,
  loading,
  status,
  metrics,
  emailState,
  onRetry,
  onDownload,
  onEmail,
}) => {
  const [email, setEmail] = useState("");
  const [emailFormat, setEmailFormat] = useState("pdf");
  const steps = [
    { key: "extracting", label: "Extracting factors" },
    { key: "support", label: "Generating support" },
    { key: "opposition", label: "Generating opposition" },
    { key: "synthesizing", label: "Synthesizing final report" },
  ];

  const currentPhase = status?.phase;
  const statusMessage = status?.message || "Starting analysis";
  const factorMeta =
    status?.factor_index && status?.factor_total
      ? `Factor ${status.factor_index}/${status.factor_total}`
      : null;
  if (loading) {
    return (
      <div className="card">
        <div className="loading-state">
          <span className="loading-spinner"></span>
          Processing your analysis...
          <span className="engine-badge groq">{ENGINE_LABEL}</span>
        </div>
        {isGroqBackend && (
          <div className="status-note">
            Powered by Groq for fast turnaround.
          </div>
        )}
        <DebateArena status={status} loading />
        <div className="status-panel">
          <div className="status-header">{statusMessage}</div>
          {factorMeta && <div className="status-meta">{factorMeta}</div>}
          <ul className="status-list">
            {steps.map((step) => {
              const isActive = step.key === currentPhase;
              const isComplete =
                currentPhase === "done" ||
                steps.findIndex((s) => s.key === currentPhase) >
                  steps.findIndex((s) => s.key === step.key);
              return (
                <li
                  key={step.key}
                  className={`status-item ${isActive ? "active" : ""} ${
                    isComplete ? "complete" : ""
                  }`}
                >
                  <span className="status-dot"></span>
                  <span>{step.label}</span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    );
  }

  if (error) {
    const message = typeof error === "string" ? error : error.message;
    const requestId = typeof error === "object" ? error.requestId : null;
    const retryable = typeof error === "object" && error.retryable;
    const degraded = typeof error === "object" && error.degraded;
    return (
      <div className="card error">
        <h3>
          <AlertTriangle className="icon" aria-hidden="true" />
          Error
        </h3>
        {degraded && (
          <div className="degraded-banner">
            The AI service is temporarily unavailable. This can happen during
            rate limiting or provider outages. Please try again shortly.
          </div>
        )}
        <p>{message}</p>
        {retryable && onRetry && (
          <div className="form-actions">
            <button onClick={onRetry} className="button-full-width">
              <RefreshCw className="icon" aria-hidden="true" />
              Retry
            </button>
          </div>
        )}
        {requestId && <p className="error-meta">Request ID: {requestId}</p>}
      </div>
    );
  }

  if (!result) {
    return (
      <div className="card">
        <h3>
          <Rocket className="icon" aria-hidden="true" />
          Ready to Analyze
        </h3>
        <p className="empty-state">
          Upload a PDF or paste text content to begin the analysis. The system
          will extract factors, generate debates between support and opposition
          agents, and synthesize a comprehensive report.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <h3>
        <BarChart3 className="icon" aria-hidden="true" />
        Analysis Results
      </h3>

      {result.resilience?.degraded && (
        <div className="degraded-banner">
          <AlertTriangle className="icon" aria-hidden="true" />
          This analysis completed in degraded mode — some agents were skipped
          or produced partial output due to LLM service issues.
        </div>
      )}

      {onDownload && (
        <div className="section">
          <strong className="section-header">
            <Share2 className="icon" aria-hidden="true" />
            Export & Share
          </strong>
          <div className="export-panel">
            <div className="export-grid">
              {EXPORT_FORMATS.map((f) => {
                const Icon = f.icon;
                return (
                  <button
                    key={f.key}
                    className="export-btn"
                    onClick={() => onDownload(f.key)}
                    title={`Download as ${f.label}`}
                  >
                    <Icon className="icon" aria-hidden="true" />
                    <span className="export-btn-label">{f.label}</span>
                    <span className="export-btn-hint">{f.hint}</span>
                  </button>
                );
              })}
            </div>

            {onEmail && (
              <div className="email-form">
                <Mail className="icon email-icon" aria-hidden="true" />
                <input
                  type="email"
                  className="email-input"
                  placeholder="email@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={emailState?.status === "sending"}
                />
                <select
                  className="email-format-select"
                  value={emailFormat}
                  onChange={(e) => setEmailFormat(e.target.value)}
                  disabled={emailState?.status === "sending"}
                  aria-label="Email format"
                >
                  {EXPORT_FORMATS.map((f) => (
                    <option key={f.key} value={f.key}>
                      {f.label}
                    </option>
                  ))}
                </select>
                <button
                  className="email-send"
                  onClick={() => email.trim() && onEmail(email.trim(), emailFormat)}
                  disabled={!email.trim() || emailState?.status === "sending"}
                >
                  {emailState?.status === "sending"
                    ? "Sending..."
                    : "Email Report"}
                </button>
              </div>
            )}

            {emailState?.status === "success" && (
              <div className="email-status ok">{emailState.message}</div>
            )}
            {emailState?.status === "error" && (
              <div className="email-status error">{emailState.message}</div>
            )}
          </div>
        </div>
      )}

      {result.final_report && (
        <div className="section">
          <strong className="section-header">
            <Target className="icon" aria-hidden="true" />
            Final Report
          </strong>
          <div className="final-report">
            <div className="report-section success">
              <h4>
                <CheckCircle2 className="icon" aria-hidden="true" />
                What Worked
              </h4>
              <p>{result.final_report.what_worked}</p>
            </div>
            <div className="report-section failure">
              <h4>
                <XCircle className="icon" aria-hidden="true" />
                What Failed
              </h4>
              <p>{result.final_report.what_failed}</p>
            </div>
            <div className="report-section analysis">
              <h4>
                <Microscope className="icon" aria-hidden="true" />
                Why It Happened
              </h4>
              <p>{result.final_report.why_it_happened}</p>
            </div>
            <div className="report-section improvement">
              <h4>
                <TrendingUp className="icon" aria-hidden="true" />
                How to Improve
              </h4>
              <p>{result.final_report.how_to_improve}</p>
            </div>
          </div>
        </div>
      )}

      {result.factors && result.factors.length > 0 && (
        <div className="section">
          <strong className="section-header">
            <ListChecks className="icon" aria-hidden="true" />
            Extracted Factors
          </strong>
          <ul className="factor-list">
            {result.factors.map((factor, idx) => (
              <li
                key={idx}
                className={`domain-${
                  factor.domain?.toLowerCase() || "unknown"
                }`}
              >
                <div className="factor-id">F{idx + 1}</div>
                <div>
                  <div className="factor-desc">{factor.description}</div>
                  <div className="factor-domain">
                    {factor.domain}{" "}
                    {factor.importance && `• ${factor.importance}`}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.debate_logs && result.debate_logs.length > 0 && (
        <div className="section">
          <strong className="section-header">
            <ListChecks className="icon" aria-hidden="true" />
            Debate Analysis
          </strong>
          <DebateArena result={result} />
        </div>
      )}

      {result.debate_logs && result.debate_logs.length > 0 && (
        <div className="section">
          <strong className="section-header">
            <Scale className="icon" aria-hidden="true" />
            Side-by-Side Comparison
          </strong>
          <ArgumentComparison result={result} />
        </div>
      )}

      {(isGroqBackend ||
        (metrics && Object.keys(metrics).length > 0)) && (
        <RuntimePanel result={result} metrics={metrics} />
      )}
    </div>
  );
};

export default ResultsDisplay;
