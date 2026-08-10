export const hashScore = (text = "") => {
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = (h * 31 + text.charCodeAt(i)) >>> 0;
  }
  return 55 + (h % 44);
};

export const argConfidenceDetails = (debate, role, index) => {
  const entry = debate.confidence_data?.arguments?.find(
    (a) => a.role === role && a.argument_index === index + 1,
  );
  return entry || null;
};

export const argConfidence = (debate, role, index, arg) => {
  const entry = argConfidenceDetails(debate, role, index);
  if (entry?.confidence != null) return entry.confidence;
  return hashScore(arg.claim || arg.target_claim || "");
};

export const factorConfidence = (debate) => {
  if (debate.confidence_data?.confidence != null) {
    return debate.confidence_data.confidence;
  }
  const scores = (debate.support?.support_arguments || []).map((arg, i) =>
    argConfidence(debate, "support", i, arg),
  );
  return scores.length ? Math.max(...scores) : 0;
};

const normalize = (s = "") =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

export const similarity = (a, b) => {
  const A = normalize(a)
    .split(" ")
    .filter((w) => w.length > 2);
  const B = normalize(b)
    .split(" ")
    .filter((w) => w.length > 2);
  if (!A.length || !B.length) return 0;
  const setB = new Set(B);
  const intersection = A.filter((w) => setB.has(w)).length;
  return intersection / Math.min(A.length, B.length);
};

const PAIR_THRESHOLD = 0.25;
const AGREEMENT_THRESHOLD = 0.3;

export const pairArguments = (debate) => {
  const support = debate.support?.support_arguments || [];
  const opposition = debate.opposition?.counter_arguments || [];
  const used = new Set();

  const pairs = opposition.map((oppositionArg, oi) => {
    let best = -1;
    let bestScore = 0;
    support.forEach((sup, si) => {
      if (used.has(si)) return;
      const score = similarity(oppositionArg.target_claim || "", sup.claim || "");
      if (score > bestScore) {
        bestScore = score;
        best = si;
      }
    });
    if (best >= 0 && bestScore >= PAIR_THRESHOLD) {
      used.add(best);
      return {
        type: "contradiction",
        supportIndex: best,
        support: support[best],
        oppositionIndex: oi,
        opposition: oppositionArg,
        score: bestScore,
      };
    }

    let agree = -1;
    let agreeScore = 0;
    support.forEach((sup, si) => {
      const score = similarity(
        `${sup.claim || ""} ${sup.evidence || ""}`,
        `${oppositionArg.challenge || ""} ${oppositionArg.risk || ""}`,
      );
      if (score > agreeScore) {
        agreeScore = score;
        agree = si;
      }
    });
    if (agree >= 0 && agreeScore >= AGREEMENT_THRESHOLD) {
      used.add(agree);
      return {
        type: "agreement",
        supportIndex: agree,
        support: support[agree],
        oppositionIndex: oi,
        opposition: oppositionArg,
        score: agreeScore,
      };
    }

    return {
      type: "standalone",
      supportIndex: -1,
      support: null,
      oppositionIndex: oi,
      opposition: oppositionArg,
      score: 0,
    };
  });

  const unmatchedSupport = support
    .map((arg, index) => ({ arg, index }))
    .filter(({ index }) => !used.has(index));

  return { pairs, unmatchedSupport };
};

export const strongestArgument = (debate, role) => {
  const args =
    role === "support"
      ? debate.support?.support_arguments || []
      : debate.opposition?.counter_arguments || [];
  if (!args.length) return null;
  let best = 0;
  args.forEach((arg, i) => {
    if (
      argConfidence(debate, role, i, arg) >
      argConfidence(debate, role, best, args[best])
    ) {
      best = i;
    }
  });
  return {
    index: best,
    arg: args[best],
    confidence: argConfidence(debate, role, best, args[best]),
  };
};
