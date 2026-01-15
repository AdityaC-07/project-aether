import React from "react";
import { downloadFile } from "../services/api";

const ResultsDisplay = ({ result, error, loading, onDownloadPDF }) => {
  if (loading) {
    return (
      <div className="card">
        <div className="loading-state">
          <span className="loading-spinner"></span>
          Processing your analysis...
        </div>
        <p className="empty-state">
          AI agents are debating and synthesizing insights
        </p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card error">
        <h3>⚠️ Error</h3>
        <p>{error}</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="card">
        <h3>🚀 Ready to Analyze</h3>
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
      <h3>📊 Analysis Results</h3>

      {onDownloadPDF && (
        <div className="form-actions" style={{ marginBottom: "20px" }}>
          <button
            onClick={onDownloadPDF}
            className="button-full-width"
            style={{
              background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            }}
          >
            📥 Download PDF Report
          </button>
        </div>
      )}

      {result.final_report && (
        <div className="section">
          <strong className="section-header">🎯 Final Report</strong>
          <div className="final-report">
            <div className="report-section success">
              <h4>✅ What Worked</h4>
              <p>{result.final_report.what_worked}</p>
            </div>
            <div className="report-section failure">
              <h4>❌ What Failed</h4>
              <p>{result.final_report.what_failed}</p>
            </div>
            <div className="report-section analysis">
              <h4>🔬 Why It Happened</h4>
              <p>{result.final_report.why_it_happened}</p>
            </div>
            <div className="report-section improvement">
              <h4>🚀 How to Improve</h4>
              <p>{result.final_report.how_to_improve}</p>
            </div>
          </div>
        </div>
      )}

      {result.factors && result.factors.length > 0 && (
        <div className="section">
          <strong className="section-header">🔍 Extracted Factors</strong>
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
          <strong className="section-header">💬 Debate Analysis</strong>
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
                      <h5>👍 Support Arguments</h5>
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
                      <h5>👎 Counter Arguments</h5>
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
                        )
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
