import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  Play,
  RotateCcw,
  Sparkles,
  Swords,
} from "lucide-react";
import { ENGINE_LABEL, isGroqBackend } from "../services/api";
import { argConfidence, factorConfidence } from "../utils/debate";

const REVEAL_MS = 750;

const SupportCard = ({ arg, revealed }) => (
  <div className={`arena-arg support-arg ${revealed ? "in" : ""}`}>
    <div className="arena-arg-title">{arg.claim}</div>
    <div className="arena-arg-text">
      <strong>Evidence:</strong> {arg.evidence}
    </div>
    {arg.assumption && (
      <div className="arena-arg-text">
        <strong>Assumption:</strong> {arg.assumption}
      </div>
    )}
    <div className="arena-confidence-label">Strength</div>
    <div className="arena-bar">
      <div
        className="arena-bar-fill support"
        style={{ width: revealed ? `${arg.confidence}%` : "0%" }}
      />
    </div>
    <div className="arena-confidence-value">
      {revealed ? `${arg.confidence}%` : ""}
    </div>
  </div>
);

const OppositionCard = ({ arg, revealed }) => (
  <div className={`arena-arg opposition-arg ${revealed ? "in" : ""}`}>
    {arg.target_claim && (
      <div className="arena-responds">
        Responding to: {arg.target_claim}
      </div>
    )}
    <div className="arena-arg-title">{arg.challenge}</div>
    {arg.risk && (
      <div className="arena-arg-text">
        <strong>Risk:</strong> {arg.risk}
      </div>
    )}
    <div className="arena-confidence-label">Strength</div>
    <div className="arena-bar">
      <div
        className="arena-bar-fill opposition"
        style={{ width: revealed ? `${arg.confidence}%` : "0%" }}
      />
    </div>
    <div className="arena-confidence-value">
      {revealed ? `${arg.confidence}%` : ""}
    </div>
  </div>
);

const LiveArena = ({ status }) => {
  const phase = status?.phase || "starting";
  const factorIndex = status?.factor_index || 0;
  const factorTotal = status?.factor_total || 0;
  const activeCol =
    phase === "opposition"
      ? "opposition"
      : phase === "synthesizing"
        ? "synthesis"
        : "support";
  const skeletonCount = Math.max(1, Math.min(factorTotal || 3, 4));

  return (
    <div className="arena arena-live">
      <div className="arena-header">
        <span className="arena-title">
          <Swords className="icon" aria-hidden="true" />
          Live Debate
        </span>
        <span
          className={`engine-badge ${isGroqBackend ? "groq" : "gemini"}`}
        >
          {ENGINE_LABEL}
        </span>
        <span className="arena-phase">
          {status?.message || "Starting analysis"}
        </span>
        {factorTotal > 0 && (
          <span className="arena-progress">
            {Math.min(factorIndex, factorTotal)}/{factorTotal}
          </span>
        )}
      </div>

      <div className="arena-grid">
        <div className="arena-col arena-col-factor">
          <div className="arena-col-title">Factors</div>
          {Array.from({ length: skeletonCount }).map((_, i) => (
            <div
              key={i}
              className={`arena-skeleton ${
                i < factorIndex ? "arena-skeleton-filled" : ""
              }`}
            />
          ))}
        </div>

        <div
          className={`arena-col arena-col-support ${
            activeCol === "support" ? "arena-active" : ""
          }`}
        >
          <div className="arena-col-title">Support</div>
          <div className="arena-working">
            <Activity className="icon" aria-hidden="true" />
            Generating support arguments...
          </div>
        </div>

        <div
          className={`arena-col arena-col-synthesis ${
            activeCol === "synthesis" ? "arena-active" : ""
          }`}
        >
          <div className="arena-col-title">Synthesis</div>
          <div className="arena-working">
            <Sparkles className="icon" aria-hidden="true" />
            Forming consensus...
          </div>
        </div>

        <div
          className={`arena-col arena-col-opposition ${
            activeCol === "opposition" ? "arena-active" : ""
          }`}
        >
          <div className="arena-col-title">Opposition</div>
          <div className="arena-working">
            <Swords className="icon" aria-hidden="true" />
            Preparing counter-arguments...
          </div>
        </div>
      </div>
    </div>
  );
};

const ReplayArena = ({ result }) => {
  const debates = result?.debate_logs || [];

  const timeline = useMemo(() => {
    const items = [];
    let idx = 0;
    debates.forEach((debate, fi) => {
      items.push({ index: idx, type: "factor", fi, debate });
      idx += 1;
      (debate.support?.support_arguments || []).forEach((arg, ai) => {
        items.push({
          index: idx,
          type: "support",
          fi,
          ai,
          arg,
          confidence: argConfidence(debate, "support", ai, arg),
        });
        idx += 1;
      });
      (debate.opposition?.counter_arguments || []).forEach((arg, ai) => {
        items.push({
          index: idx,
          type: "opposition",
          fi,
          ai,
          arg,
          confidence: argConfidence(debate, "opposition", ai, arg),
        });
        idx += 1;
      });
      items.push({ index: idx, type: "consensus", fi, debate });
      idx += 1;
    });
    items.push({ index: idx, type: "synthesis", result });
    return items;
  }, [debates, result]);

  const [revealed, setRevealed] = useState(0);
  const [done, setDone] = useState(false);
  const timerRef = useRef(null);

  const reset = () => {
    setRevealed(0);
    setDone(false);
  };

  useEffect(() => {
    reset();
    if (!timeline.length) return undefined;
    timerRef.current = setInterval(() => {
      setRevealed((n) => {
        if (n >= timeline.length) {
          clearInterval(timerRef.current);
          setDone(true);
          return n;
        }
        return n + 1;
      });
    }, REVEAL_MS);
    return () => clearInterval(timerRef.current);
  }, [timeline]);

  const skip = () => {
    clearInterval(timerRef.current);
    setRevealed(timeline.length);
    setDone(true);
  };

  const revealIndex = (type, fi, ai) => {
    const item = timeline.find(
      (t) =>
        t.type === type &&
        t.fi === fi &&
        (ai === undefined || t.ai === ai),
    );
    return item ? item.index : -1;
  };

  const synthesisConfidence =
    result?.final_report?.confidence_report?.overall_confidence ?? null;
  const synthesisRevealed = timeline.length > 0 && revealed > timeline[timeline.length - 1].index;

  if (!timeline.length) return null;

  return (
    <div className="arena arena-replay">
      <div className="arena-header">
        <span className="arena-title">
          <Swords className="icon" aria-hidden="true" />
          Debate Arena
        </span>
        {!done ? (
          <span className="arena-revealing">
            <Activity className="icon" aria-hidden="true" />
            Revealing debate...
          </span>
        ) : (
          <span className="arena-phase">Complete</span>
        )}
        <span className="arena-controls">
          {!done && (
            <button onClick={skip} title="Skip animation">
              <Play className="icon" aria-hidden="true" />
              Skip
            </button>
          )}
          {done && (
            <button onClick={reset} title="Replay animation">
              <RotateCcw className="icon" aria-hidden="true" />
              Replay
            </button>
          )}
        </span>
      </div>

      {debates.map((debate, fi) => {
        const factorIn = revealIndex("factor", fi) < revealed;
        const consensusIn = revealIndex("consensus", fi) < revealed;
        return (
          <div key={fi} className="arena-debate">
            <div className="arena-grid">
              <div className="arena-col arena-col-factor">
                <div
                  className={`arena-factor ${factorIn ? "in" : ""}`}
                >
                  <span className="factor-badge">Factor {fi + 1}</span>
                  <div className="factor-desc">
                    {debate.factor?.description}
                  </div>
                  <div className="factor-domain">
                    {debate.factor?.domain}
                    {debate.factor?.importance &&
                      ` • ${debate.factor.importance}`}
                  </div>
                </div>
              </div>

              <div className="arena-col arena-col-support">
                <div className="arena-col-title">Support</div>
                {(debate.support?.support_arguments || []).map(
                  (arg, ai) => {
                    const item = timeline.find(
                      (t) =>
                        t.type === "support" &&
                        t.fi === fi &&
                        t.ai === ai,
                    );
                    return (
                      <SupportCard
                        key={ai}
                        arg={{ ...arg, confidence: item?.confidence }}
                        revealed={item && item.index < revealed}
                      />
                    );
                  },
                )}
                {(debate.support?.support_arguments || []).length ===
                  0 && (
                  <div className="arena-empty">No support generated</div>
                )}
              </div>

              <div className="arena-col arena-col-synthesis">
                <div className="arena-col-title">Consensus</div>
                <div
                  className={`arena-consensus ${
                    consensusIn ? "in" : ""
                  }`}
                >
                  <div className="arena-confidence-label">
                    Factor confidence
                  </div>
                  <div className="arena-bar">
                    <div
                      className="arena-bar-fill synthesis"
                      style={{
                        width: consensusIn
                          ? `${factorConfidence(debate)}%`
                          : "0%",
                      }}
                    />
                  </div>
                  <div className="arena-confidence-value">
                    {consensusIn
                      ? `${Math.round(factorConfidence(debate))}%`
                      : ""}
                  </div>
                </div>
              </div>

              <div className="arena-col arena-col-opposition">
                <div className="arena-col-title">Opposition</div>
                {(debate.opposition?.counter_arguments || []).map(
                  (arg, ai) => {
                    const item = timeline.find(
                      (t) =>
                        t.type === "opposition" &&
                        t.fi === fi &&
                        t.ai === ai,
                    );
                    return (
                      <OppositionCard
                        key={ai}
                        arg={{ ...arg, confidence: item?.confidence }}
                        revealed={item && item.index < revealed}
                      />
                    );
                  },
                )}
                {(debate.opposition?.counter_arguments || []).length ===
                  0 && (
                  <div className="arena-empty">
                    No counter-arguments generated
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}

      <div
        className={`arena-synthesis ${synthesisRevealed ? "in" : ""}`}
      >
        <div className="arena-col-title">
          <Sparkles className="icon" aria-hidden="true" />
          Synthesis
        </div>
        {synthesisConfidence != null && (
          <div className="arena-synthesis-row">
            <div className="arena-confidence-label">
              Overall confidence
            </div>
            <div className="arena-bar">
              <div
                className="arena-bar-fill synthesis"
                style={{
                  width: synthesisRevealed
                    ? `${synthesisConfidence}%`
                    : "0%",
                }}
              />
            </div>
            <div className="arena-confidence-value">
              {synthesisRevealed
                ? `${Math.round(synthesisConfidence)}%`
                : ""}
            </div>
          </div>
        )}
        <p className="arena-synthesis-text">
          Synthesis complete. The full verdict is available in the Final
          Report above.
        </p>
      </div>
    </div>
  );
};

const DebateArena = ({ result, status, loading }) => {
  if (loading) return <LiveArena status={status} />;
  if (result?.debate_logs?.length) return <ReplayArena result={result} />;
  return null;
};

export default DebateArena;
