import React, { useState } from "react";

const defaultContext = {
	narrative: "",
	extracted_facts: [],
	metrics: [],
	assumptions: [],
	limitations: [],
};

const JsonInput = ({ onSubmit, loading }) => {
	const [context, setContext] = useState(defaultContext);

	const handleChange = (field) => (e) => {
		setContext({ ...context, [field]: e.target.value });
	};

	const parseList = (text) =>
		text
			.split("\n")
			.map((s) => s.trim())
			.filter(Boolean);

	const handleFormSubmit = (e) => {
		e.preventDefault();
		onSubmit({
			narrative: context.narrative,
			extracted_facts: parseList(context.extracted_facts || ""),
			metrics: [],
			assumptions: parseList(context.assumptions || ""),
			limitations: parseList(context.limitations || ""),
		});
	};

	return (
		<div className="card">
			<h3>📝 Analyze Text</h3>
			<form onSubmit={handleFormSubmit}>
				<div className="form-group">
					<label>Narrative</label>
					<textarea
						rows={6}
						value={context.narrative}
						onChange={handleChange("narrative")}
						placeholder="Paste your report or narrative text here..."
					/>
				</div>

				<div className="form-group">
					<label>Extracted Facts (one per line)</label>
					<textarea
						rows={4}
						value={context.extracted_facts}
						onChange={handleChange("extracted_facts")}
						placeholder="Fact 1&#10;Fact 2&#10;Fact 3..."
					/>
				</div>

				<div className="form-group">
					<label>Assumptions (one per line)</label>
					<textarea
						rows={3}
						value={context.assumptions}
						onChange={handleChange("assumptions")}
						placeholder="Assumption 1&#10;Assumption 2..."
					/>
				</div>

				<div className="form-group">
					<label>Limitations (one per line)</label>
					<textarea
						rows={3}
						value={context.limitations}
						onChange={handleChange("limitations")}
						placeholder="Limitation 1&#10;Limitation 2..."
					/>
				</div>

				<div className="form-actions">
					<button type="submit" disabled={loading} className="button-full-width">
						{loading ? (
							<span className="loading-state">
								<span className="loading-spinner"></span>
								Analyzing...
							</span>
						) : (
							"Analyze Text"
						)}
					</button>
				</div>
			</form>
			<p className="hint">✨ Sends your context to the analysis engine for processing.</p>
		</div>
	);
};

export default JsonInput;
