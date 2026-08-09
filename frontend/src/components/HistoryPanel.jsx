import React, { useEffect, useMemo, useState } from "react";
import { ArrowLeftRight, BarChart3, History, Loader2, Repeat, Trash2 } from "lucide-react";
import {
  compareAnalyses,
  deleteAnalysis,
  getAnalysis,
  getConsistentFactors,
  getHistory,
  getHistoryTimeline,
} from "../services/api";

const fmtDate = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

const fmtDateShort = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
};

const pct = (v) => `${Math.round(Number(v) || 0)}%`;

const FactorScore = ({ score }) => (
  <div className="history-factor-score">
    <span className="score-description">{score.description}</span>
    <span className="score-chips">
      <span className="score-chip">conf {pct(score.confidence)}</span>
      <span className="score-chip">agree {pct(score.agreement)}</span>
      <span className="score-chip">Δ {Number(score.contribution).toFixed(2)}</span>
    </span>
  </div>
);

const AnalysisDetail = ({ record, onClose }) => (
  <div className="history-detail">
    <div className="history-detail-header">
      <div className="history-detail-title">{record.narrative || record.narrative_preview}</div>
      <button className="icon-button" onClick={onClose} title="Close">
        <Trash2 className="icon" aria-hidden="true" />
      </button>
    </div>
    <div className="history-detail-meta">
      {fmtDate(record.created_at)} · {record.input_type} · {record.factor_count} factors
      {record.degraded && <span className="degraded-chip">degraded</span>}
    </div>
    {record.final_report?.recommendation && (
      <p className="history-detail-block">
        <strong>Recommendation: </strong>
        {record.final_report.recommendation}
      </p>
    )}
    {record.final_report?.synthesis && (
      <p className="history-detail-block">
        <strong>Synthesis: </strong>
        {record.final_report.synthesis}
      </p>
    )}
    {record.final_report?.confidence_report?.overall_confidence != null && (
      <p className="history-detail-block">
        <strong>Overall confidence: </strong>
        {pct(record.final_report.confidence_report.overall_confidence)}
      </p>
    )}
    {record.factor_scores?.length > 0 && (
      <div className="history-detail-block">
        <strong>Factor scores</strong>
        <div className="history-scores">
          {record.factor_scores.map((score) => (
            <FactorScore key={score.factor_id} score={score} />
          ))}
        </div>
      </div>
    )}
  </div>
);

const HistoryPanel = ({ refreshKey }) => {
  const [list, setList] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [consistent, setConsistent] = useState([]);
  const [tab, setTab] = useState("history");
  const [selectedIds, setSelectedIds] = useState([]);
  const [detail, setDetail] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const [historyRes, timelineRes, consistentRes] = await Promise.all([
        getHistory(50, 0),
        getHistoryTimeline(100),
        getConsistentFactors(2),
      ]);
      setList(historyRes);
      setTimeline(timelineRes.timeline || []);
      setConsistent(consistentRes.factors || []);
    } catch (err) {
      setError(err.message || "Could not load history.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  const analyses = list?.analyses || [];
  const maxConfidence = useMemo(
    () => Math.max(1, ...timeline.map((t) => Number(t.confidence_score) || 0)),
    [timeline],
  );

  const toggleSelect = (id) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const openDetail = async (id) => {
    setError("");
    try {
      setDetail(await getAnalysis(id));
    } catch (err) {
      setError(err.message || "Could not load analysis.");
    }
  };

  const runCompare = async () => {
    if (selectedIds.length < 2) {
      setError("Select at least two analyses to compare.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const res = await compareAnalyses(selectedIds);
      setComparison(res.analyses);
    } catch (err) {
      setError(err.message || "Comparison failed.");
    } finally {
      setLoading(false);
    }
  };

  const remove = async (id) => {
    setError("");
    try {
      await deleteAnalysis(id);
      setDetail(null);
      setComparison(null);
      setSelectedIds([]);
      await load();
    } catch (err) {
      setError(err.message || "Delete failed.");
    }
  };

  return (
    <div className="card history-panel">
      <div className="card-header">
        <h3>
          <History className="icon" aria-hidden="true" />
          History
        </h3>
        <div className="history-tabs">
          {[
            ["history", "Analyses"],
            ["compare", "Compare"],
            ["trends", "Trends"],
          ].map(([key, label]) => (
            <button
              key={key}
              className={`tab ${tab === key ? "active" : ""}`}
              onClick={() => setTab(key)}
            >
              {key === "compare" && <ArrowLeftRight className="icon" aria-hidden="true" />}
              {key === "trends" && <BarChart3 className="icon" aria-hidden="true" />}
              {label}
            </button>
          ))}
        </div>
      </div>

      {loading && !list && (
        <div className="history-loading">
          <Loader2 className="icon spin" aria-hidden="true" />
          Loading history…
        </div>
      )}
      {error && <div className="email-status error">{error}</div>}

      {tab === "history" && (
        <div className="history-list">
          {!loading && !analyses.length && (
            <div className="history-empty">
              No analyses recorded yet. Run an analysis and it will show up here.
            </div>
          )}
          {analyses.map((a) => (
            <div key={a.analysis_id} className="history-row">
              <input
                type="checkbox"
                title="Select for comparison"
                checked={selectedIds.includes(a.analysis_id)}
                onChange={() => toggleSelect(a.analysis_id)}
              />
              <button className="history-row-main" onClick={() => openDetail(a.analysis_id)}>
                <span className="history-row-title">
                  {a.narrative_preview || a.analysis_id}
                  {a.degraded && <span className="degraded-chip">degraded</span>}
                </span>
                <span className="history-row-meta">
                  {fmtDate(a.created_at)} · {a.input_type} · {a.factor_count} factors
                </span>
              </button>
              <span className="history-confidence">{pct(a.confidence_score)}</span>
              <button className="icon-button danger" title="Delete" onClick={() => remove(a.analysis_id)}>
                <Trash2 className="icon" aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}

      {tab === "compare" && (
        <div className="history-compare">
          {comparison && comparison.length > 0 ? (
            <div className="compare-grid">
              <div className="compare-sticky">
                <div className="compare-cell compare-label">Date</div>
                <div className="compare-cell compare-label">Confidence</div>
                <div className="compare-cell compare-label">Recommendation</div>
                <div className="compare-cell compare-label">Synthesis</div>
                <div className="compare-cell compare-label">Factors</div>
              </div>
              {comparison.map((c) => (
                <div key={c.analysis_id} className="compare-column">
                  <div className="compare-cell compare-date">{fmtDate(c.created_at)}</div>
                  <div className="compare-cell">{pct(c.confidence_score)}</div>
                  <div className="compare-cell">{c.final_report?.recommendation || "—"}</div>
                  <div className="compare-cell">{c.final_report?.synthesis || "—"}</div>
                  <div className="compare-cell">
                    <div className="history-scores">
                      {c.factor_scores?.map((score) => (
                        <FactorScore key={score.factor_id} score={score} />
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="compare-picker">
              <p>
                {selectedIds.length >= 2
                  ? `${selectedIds.length} analyses selected.`
                  : "Select two or more analyses (checkboxes in the Analyses tab), then compare them side by side."}
              </p>
              <button className="button" onClick={runCompare} disabled={selectedIds.length < 2 || loading}>
                <ArrowLeftRight className="icon" aria-hidden="true" />
                Compare selected
              </button>
            </div>
          )}
        </div>
      )}

      {tab === "trends" && (
        <div className="history-trends">
          {timeline.length > 0 && (
            <div className="trend-block">
              <h4>
                <Repeat className="icon" aria-hidden="true" />
                Confidence over time
              </h4>
              <div className="trend-bars">
                {timeline.map((t) => (
                  <div key={t.analysis_id} className="trend-bar-col" title={fmtDate(t.created_at)}>
                    <span className="trend-bar-value">{pct(t.confidence_score)}</span>
                    <div
                      className="trend-bar"
                      style={{ height: `${Math.max(6, (t.confidence_score / maxConfidence) * 100)}%` }}
                    />
                    <span className="trend-bar-date">{fmtDateShort(t.created_at)}</span>
                  </div>
                ))}
              </div>
              <div className="trend-notes">
                {timeline.map((t) => (
                  <div key={t.analysis_id} className="trend-note">
                    <strong>{t.recommendation || "No recommendation"}</strong>
                    <span className="trend-note-meta">
                      {fmtDate(t.created_at)} · {t.factor_count} factors
                    </span>
                    {t.synthesis && <span className="trend-note-synthesis">{t.synthesis}</span>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {consistent.length > 0 && (
            <div className="trend-block">
              <h4>
                <Repeat className="icon" aria-hidden="true" />
                Consistently important factors
              </h4>
              <div className="consistent-list">
                {consistent.map((f) => (
                  <div key={f.description} className="consistent-item">
                    <span className="consistent-description">{f.description}</span>
                    <span className="consistent-meta">
                      appeared in {f.occurrences} runs · avg conf {pct(f.avg_confidence)} · avg
                      agreement {pct(f.avg_agreement)} · avg |Δ| {Number(f.avg_abs_contribution).toFixed(2)}
                    </span>
                    <span className="consistent-domains">
                      {f.domains.map((d) => (
                        <span key={d} className={`domain-chip ${d}`}>
                          {d}
                        </span>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!loading && !timeline.length && !consistent.length && (
            <div className="history-empty">Not enough history for trends yet.</div>
          )}
        </div>
      )}

      {detail && <AnalysisDetail record={detail} onClose={() => setDetail(null)} />}
    </div>
  );
};

export default HistoryPanel;
