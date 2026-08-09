import React, { useEffect, useMemo, useState } from "react";
import { Check, ListChecks, Plus, RotateCcw, Sparkles, Trash2, X } from "lucide-react";
import { analyzeContextWithFactors } from "../services/api";

const DOMAINS = ["sales", "statistics", "policy", "organization"];

const pct = (v) => `${Math.round(Number(v) || 0)}%`;

const FactorSelector = ({ plan, context, onComplete, onBack }) => {
  const [extracted, setExtracted] = useState([]);
  const [added, setAdded] = useState([]);
  const [selected, setSelected] = useState([]);
  const [customDescription, setCustomDescription] = useState("");
  const [customDomain, setCustomDomain] = useState(DOMAINS[0]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const validations = useMemo(() => {
    const map = {};
    for (const v of plan?.validations || []) map[v.factor_id] = v;
    return map;
  }, [plan]);

  useEffect(() => {
    setExtracted(plan?.extracted_factors || []);
    setAdded([]);
    const debatable = (plan?.extracted_factors || [])
      .filter((f) => {
        const v = validations[f.factor_id];
        return !v || v.is_debatable;
      })
      .map((f) => f.factor_id);
    setSelected(debatable);
    setError("");
  }, [plan]);

  const allFactors = useMemo(() => {
    const seen = new Set();
    const list = [];
    for (const f of [...extracted, ...added]) {
      const key = f.description.trim().toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      list.push(f);
    }
    return list;
  }, [extracted, added]);

  const toggle = (factorId) => {
    setSelected((prev) =>
      prev.includes(factorId) ? prev.filter((id) => id !== factorId) : [...prev, factorId],
    );
  };

  const addSuggestion = (suggestion) => {
    const factor = {
      factor_id: `A${added.length + 1}`,
      description: suggestion.description,
      domain: suggestion.domain,
    };
    setAdded((prev) => [...prev, factor]);
    setSelected((prev) => [...prev, factor.factor_id]);
  };

  const removeAdded = (factorId) => {
    setAdded((prev) => prev.filter((f) => f.factor_id !== factorId));
    setSelected((prev) => prev.filter((id) => id !== factorId));
  };

  const applyRefinement = (factorId) => {
    const v = validations[factorId];
    if (!v?.refinement) return;
    setAdded((prev) => [
      ...prev,
      {
        factor_id: `A${added.length + 1}`,
        description: v.refinement,
        domain: allFactors.find((f) => f.factor_id === factorId)?.domain || "policy",
      },
    ]);
    setSelected((prev) => [...prev, `A${added.length + 1}`]);
  };

  const addCustom = () => {
    const description = customDescription.trim();
    if (!description) return;
    setAdded((prev) => [...prev, { factor_id: `A${added.length + 1}`, description, domain: customDomain }]);
    setSelected((prev) => [...prev, `A${added.length + 1}`]);
    setCustomDescription("");
  };

  const run = async () => {
    const chosen = allFactors.filter((f) => selected.includes(f.factor_id));
    if (!chosen.length) {
      setError("Select at least one factor to analyze.");
      return;
    }
    setRunning(true);
    setError("");
    try {
      const result = await analyzeContextWithFactors(context, chosen);
      onComplete(result);
    } catch (err) {
      setError(err.message || "Analysis failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="card factor-selector">
      <div className="card-header">
        <h3>
          <ListChecks className="icon" aria-hidden="true" />
          Review factors
        </h3>
        <button className="button ghost" onClick={onBack} disabled={running}>
          <RotateCcw className="icon" aria-hidden="true" />
          Back
        </button>
      </div>
      <p className="factor-selector-hint">
        Select the factors you want debated. Factors marked “not debatable” are excluded from the
        final report but shown for transparency.
      </p>

      {allFactors.length > 0 && (
        <div className="factor-list">
          {allFactors.map((factor) => {
            const v = validations[factor.factor_id];
            const isAdded = factor.factor_id.startsWith("A");
            const debatable = v ? v.is_debatable : true;
            return (
              <div
                key={factor.factor_id}
                className={`factor-item ${selected.includes(factor.factor_id) ? "selected" : ""}`}
              >
                <label className="factor-select">
                  <input
                    type="checkbox"
                    checked={selected.includes(factor.factor_id)}
                    onChange={() => toggle(factor.factor_id)}
                  />
                  <span className="factor-body">
                    <span className="factor-description">{factor.description}</span>
                    <span className="factor-meta">
                      <span className={`domain-chip ${factor.domain}`}>{factor.domain}</span>
                      {isAdded && <span className="added-chip">added</span>}
                      {v && (
                        <span className={`debatability ${debatable ? "yes" : "no"}`}>
                          {debatable ? "debatable" : "not debatable"}
                        </span>
                      )}
                      {v?.quality_score != null && (
                        <span className="quality-chip">quality {pct(v.quality_score)}</span>
                      )}
                    </span>
                    {v?.reason && <span className="factor-reason">{v.reason}</span>}
                    {v?.refinement && (
                      <button
                        type="button"
                        className="refine-link"
                        onClick={() => applyRefinement(factor.factor_id)}
                      >
                        <Sparkles className="icon" aria-hidden="true" />
                        Use clearer wording
                      </button>
                    )}
                  </span>
                </label>
                {isAdded && (
                  <button
                    type="button"
                    className="icon-button"
                    title="Remove"
                    onClick={() => removeAdded(factor.factor_id)}
                  >
                    <Trash2 className="icon" aria-hidden="true" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      {(plan?.suggestions?.length > 0) && (
        <div className="suggestions-section">
          <h4>
            <Sparkles className="icon" aria-hidden="true" />
            Related factors worth adding
          </h4>
          <div className="suggestion-list">
            {plan.suggestions.map((s, i) => {
              const exists = allFactors.some(
                (f) => f.description.trim().toLowerCase() === s.description.trim().toLowerCase(),
              );
              return (
                <div key={i} className="suggestion-item">
                  <div className="suggestion-main">
                    <span className="suggestion-description">{s.description}</span>
                    <span className="suggestion-relation">
                      <span className={`domain-chip ${s.domain}`}>{s.domain}</span> · {s.relation}
                    </span>
                    <span className="suggestion-rationale">{s.rationale}</span>
                  </div>
                  <button
                    type="button"
                    className="button small"
                    disabled={exists}
                    onClick={() => addSuggestion(s)}
                  >
                    {exists ? <Check className="icon" aria-hidden="true" /> : <Plus className="icon" aria-hidden="true" />}
                    {exists ? "Added" : "Add"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="custom-factor-form">
        <input
          type="text"
          placeholder="Add your own factor, e.g. 'Whether the partnership undermines brand autonomy'"
          value={customDescription}
          onChange={(e) => setCustomDescription(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") addCustom();
          }}
        />
        <select value={customDomain} onChange={(e) => setCustomDomain(e.target.value)}>
          {DOMAINS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <button type="button" className="button small" onClick={addCustom}>
          <Plus className="icon" aria-hidden="true" />
          Add factor
        </button>
      </div>

      {error && <div className="email-status error">{error}</div>}

      <div className="factor-selector-footer">
        <span className="selection-count">
          {selected.length} of {allFactors.length} factors selected
        </span>
        <button className="button primary" onClick={run} disabled={running || !allFactors.length}>
          {running ? "Running analysis…" : "Run analysis"}
        </button>
      </div>
    </div>
  );
};

export default FactorSelector;
