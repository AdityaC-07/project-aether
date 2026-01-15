import React from "react";

const FactorsList = ({ factors = [] }) => {
	if (!factors.length) {
		return (
			<div className="card">
				<h3>🔍 Factors</h3>
				<p style={{ color: "#64748b" }}>No factors extracted yet. Analyze content to view results.</p>
			</div>
		);
	}

	return (
		<div className="card">
			<h3>🔍 Extracted Factors</h3>
			<ul className="factor-list">
				{factors.map((f) => (
					<li key={f.factor_id} className={`domain-${f.domain?.toLowerCase()}`}>
						<div className="factor-id">{f.factor_id}</div>
						<div className="factor-body">
							<div className="factor-desc">{f.description}</div>
							<div className="factor-domain">
								<strong>{f.domain}</strong>
								{f.importance && ` • ${f.importance}`}
							</div>
						</div>
					</li>
				))}
			</ul>
		</div>
	);
};

export default FactorsList;
