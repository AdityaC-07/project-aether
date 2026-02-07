import React from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Download,
  ListChecks,
  MessageSquareText,
  Microscope,
  Rocket,
  Target,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
  XCircle,
} from "lucide-react";

const ResultsDisplay = ({ result, error, loading, status, onDownloadPDF }) => {
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
        </div>
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
    return (
      <div className="card error">
        <h3>
          <AlertTriangle className="icon" aria-hidden="true" />
          Error
        </h3>
        <p>{error}</p>
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

      {onDownloadPDF && (
        <div className="form-actions" style={{ marginBottom: "20px" }}>
          <button
            onClick={onDownloadPDF}
            className="button-full-width"
            style={{
              background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            }}
          >
            <Download className="icon" aria-hidden="true" />
            Download PDF Report
          </button>
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
            <MessageSquareText className="icon" aria-hidden="true" />
            Debate Analysis
          </strong>
          <div className="debate-logs">
            {result.debate_logs.map((debate, idx) => (
              <div key={idx} className="debate-trace">
                <div className="debate-header">
                  <span className="factor-badge">
                    Factor {debate.factor_id}
                  </span>
                  <span className="factor-description">
                    {debate.factor?.description}
                  </span>
                </div>

                {debate.support?.support_arguments &&
                  debate.support.support_arguments.length > 0 && (
                    <div className="debate-side support-side">
                      <h5>
                        <ThumbsUp className="icon" aria-hidden="true" />
                        Support Arguments
                      </h5>
                      {debate.support.support_arguments.map((arg, argIdx) => (
                        <div key={argIdx} className="argument-card">
                          <div className="argument-item">
                            <strong>Claim:</strong> {arg.claim}
                          </div>
                          <div className="argument-item">
                            <strong>Evidence:</strong> {arg.evidence}
                          </div>
                          <div className="argument-item">
                            <strong>Assumption:</strong> {arg.assumption}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                {debate.opposition?.counter_arguments &&
                  debate.opposition.counter_arguments.length > 0 && (
                    <div className="debate-side opposition-side">
                      <h5>
                        <ThumbsDown className="icon" aria-hidden="true" />
                        Counter Arguments
                      </h5>
                      {debate.opposition.counter_arguments.map(
                        (counter, counterIdx) => (
                          <div key={counterIdx} className="argument-card">
                            <div className="argument-item">
                              <strong>Target Claim:</strong>{" "}
                              {counter.target_claim}
                            </div>
                            <div className="argument-item">
                              <strong>Challenge:</strong> {counter.challenge}
                            </div>
                            <div className="argument-item">
                              <strong>Risk:</strong> {counter.risk}
                            </div>
                          </div>
                        ),
                      )}
                    </div>
                  )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ResultsDisplay;
