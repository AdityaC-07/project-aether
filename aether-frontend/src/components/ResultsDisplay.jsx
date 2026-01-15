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
					Upload a PDF or paste text content to begin the analysis. The system will extract factors,
					generate debates between support and opposition agents, and synthesize a comprehensive report.
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
						style={{ background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)" }}
					>
						📥 Download PDF Report
					</button>
				</div>
			)}

			{result.final_report && (
				<div className="section">
					<strong className="section-header">🎯 Final Report</strong>
					<pre>{JSON.stringify(result.final_report, null, 2)}</pre>
				</div>
			)}

			{result.factors && result.factors.length > 0 && (
				<div className="section">
					<strong className="section-header">🔍 Extracted Factors</strong>
					<ul className="factor-list">
						{result.factors.map((factor, idx) => (
							<li
								key={idx}
								className={`domain-${factor.domain?.toLowerCase() || "unknown"}`}
							>
								<div className="factor-id">F{idx + 1}</div>
								<div>
									<div className="factor-desc">{factor.description}</div>
									<div className="factor-domain">
										{factor.domain} {factor.importance && `• ${factor.importance}`}
									</div>
								</div>
							</li>
						))}
					</ul>
				</div>
			)}

			{result.debate_logs && (
				<div className="section">
					<strong className="section-header">💬 Debate Analysis</strong>
					<pre>{JSON.stringify(result.debate_logs, null, 2)}</pre>
				</div>
			)}
		</div>
	);
};

export default ResultsDisplay;
