import React from "react";
import { Award, Handshake, Minus, Zap } from "lucide-react";
import {
  argConfidence,
  argConfidenceDetails,
  factorConfidence,
  pairArguments,
  strongestArgument,
} from "../utils/debate";

const fmtPct = (v) => `${Math.round(v)}%`;
const clampBar = (v) => Math.max(0, Math.min(100, Number(v) || 0));

const ConfidenceBars = ({ details, confidence, role }) => {
  const main = confidence ?? details?.confidence;
  const evidence = details?.evidence_quality;
  return (
    <div className="arg-bars">
      <div className="arg-bar-row">
        <span className="arg-bar-label">Confidence</span>
        <div className={`strength-bar ${role}`}>
          <div
            className="strength-bar-fill"
            style={{ width: `${clampBar(main)}%` }}
          />
        </div>
        <span className="arg-bar-value">
          {main != null ? fmtPct(main) : "—"}
        </span>
      </div>
      {evidence != null && (
        <div className="arg-bar-row">
          <span className="arg-bar-label">Evidence</span>
          <div className="strength-bar evidence">
            <div
              className="strength-bar-fill"
              style={{ width: `${clampBar(evidence)}%` }}
            />
          </div>
          <span className="arg-bar-value">{fmtPct(evidence)}</span>
        </div>
      )}
      {details?.justification && (
        <div className="arg-justification">{details.justification}</div>
      )}
    </div>
  );
};

const ArgCard = ({ side, arg, index, debate, strongest }) => {
  const details = argConfidenceDetails(debate, side, index, arg);
  const confidence = argConfidence(debate, side, index, arg);
  const isStrongest = strongest && strongest.index === index;
  return (
    <div className={`comparison-arg ${side}`}>
      {isStrongest && (
        <span className="strongest-badge">
          <Award className="icon" aria-hidden="true" />
          Strongest
        </span>
      )}
      <div className="comparison-arg-title">
        {side === "support" ? arg.claim : arg.challenge}
      </div>
      {side === "support" ? (
        <>
          {arg.evidence && (
            <div className="comparison-arg-detail">
              <strong>Evidence:</strong> {arg.evidence}
            </div>
          )}
          {arg.assumption && (
            <div className="comparison-arg-detail">
              <strong>Assumption:</strong> {arg.assumption}
            </div>
          )}
        </>
      ) : (
        <>
          {arg.target_claim && (
            <div className="comparison-arg-detail comparison-target">
              Responds to: {arg.target_claim}
            </div>
          )}
          {arg.risk && (
            <div className="comparison-arg-detail">
              <strong>Risk:</strong> {arg.risk}
            </div>
          )}
        </>
      )}
      <ConfidenceBars
        details={details}
        confidence={confidence}
        role={side === "support" ? "support" : "opposition"}
      />
    </div>
  );
};

const VerdictBadge = ({ type }) => {
  const label =
    type === "contradiction"
      ? "Contradiction"
      : type === "agreement"
        ? "Agreement"
        : "Unmatched";
  const Icon =
    type === "contradiction"
      ? Zap
      : type === "agreement"
        ? Handshake
        : Minus;
  return (
    <span className={`verdict-badge ${type}`}>
      <Icon className="icon" aria-hidden="true" />
      {label}
    </span>
  );
};

const ArgumentComparison = ({ result }) => {
  const debates = result?.debate_logs || [];
  if (!debates.length) return null;

  return (
    <div className="comparison">
      {debates.map((debate, fi) => {
        const { pairs, unmatchedSupport } = pairArguments(debate);
        const strongestSupport = strongestArgument(debate, "support");
        const strongestOpposition = strongestArgument(debate, "opposition");
        const factorConf = factorConfidence(debate);
        const agreement = debate.confidence_data?.support_opposition_agreement;
        const supportCount = debate.support?.support_arguments?.length || 0;
        const oppositionCount =
          debate.opposition?.counter_arguments?.length || 0;

        return (
          <div key={fi} className="comparison-block">
            <div className="comparison-header">
              <div className="comparison-title">
                <span className="factor-badge">Factor {fi + 1}</span>
                <span className="comparison-factor-desc">
                  {debate.factor?.description}
                </span>
              </div>
              <div className="comparison-stats">
                <div className="comparison-stat">
                  <span className="comparison-stat-label">
                    Factor confidence
                  </span>
                  <div className="strength-bar synthesis">
                    <div
                      className="strength-bar-fill"
                      style={{ width: `${clampBar(factorConf)}%` }}
                    />
                  </div>
                  <span className="comparison-stat-value">
                    {fmtPct(factorConf)}
                  </span>
                </div>
                {agreement != null && (
                  <div className="comparison-stat">
                    <span className="comparison-stat-label">Agreement</span>
                    <div className="strength-bar agreement">
                      <div
                        className="strength-bar-fill"
                        style={{ width: `${clampBar(agreement)}%` }}
                      />
                    </div>
                    <span className="comparison-stat-value">
                      {fmtPct(agreement)}
                    </span>
                  </div>
                )}
                <div className="comparison-stat comparison-counts">
                  <span>{supportCount} support</span>
                  <span>{oppositionCount} opposition</span>
                </div>
              </div>
            </div>

            <div className="comparison-rows">
              {pairs.map((pair, ri) => (
                <div key={ri} className="comparison-row">
                  <div className="comparison-cell">
                    {pair.support ? (
                      <ArgCard
                        side="support"
                        arg={pair.support}
                        index={pair.supportIndex}
                        debate={debate}
                        strongest={strongestSupport}
                      />
                    ) : (
                      <div className="comparison-arg-missing">
                        {pair.opposition.target_claim ? (
                          <span>
                            Targets:{" "}
                            <span className="comparison-target">
                              {pair.opposition.target_claim}
                            </span>
                          </span>
                        ) : (
                          <span>No matching support argument</span>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="verdict-cell">
                    <VerdictBadge type={pair.type} />
                  </div>
                  <div className="comparison-cell">
                    <ArgCard
                      side="opposition"
                      arg={pair.opposition}
                      index={pair.oppositionIndex}
                      debate={debate}
                      strongest={strongestOpposition}
                    />
                  </div>
                </div>
              ))}

              {unmatchedSupport.map(({ arg, index }) => (
                <div key={`u-${index}`} className="comparison-row">
                  <div className="comparison-cell">
                    <ArgCard
                      side="support"
                      arg={arg}
                      index={index}
                      debate={debate}
                      strongest={strongestSupport}
                    />
                  </div>
                  <div className="verdict-cell">
                    <span className="verdict-badge none">
                      <Minus className="icon" aria-hidden="true" />
                      No rebuttal
                    </span>
                  </div>
                  <div className="comparison-cell" />
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default ArgumentComparison;
