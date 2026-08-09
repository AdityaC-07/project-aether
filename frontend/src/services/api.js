const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const GROQ_FLAG = String(import.meta.env.VITE_GROQ_BACKEND ?? "1").toLowerCase();
export const isGroqBackend = ["1", "true", "yes", "on"].includes(GROQ_FLAG);
export const ENGINE_LABEL = isGroqBackend ? "Groq" : "Gemini";
export const STATUS_POLL_MS = isGroqBackend ? 3000 : 8000;

const RETRYABLE_STATUS = new Set([429, 502, 503, 504]);

async function parseError(res) {
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    payload = null;
  }
  const detail = payload?.detail ?? payload;
  const message =
    typeof detail === "string"
      ? detail
      : detail?.message || payload?.message || `Request failed with status ${res.status}`;
  const err = new Error(message);
  err.status = res.status;
  err.detail = payload;
  err.requestId = detail?.request_id || payload?.request_id || null;
  err.traceId = detail?.trace_id || payload?.trace_id || null;
  err.retryable = RETRYABLE_STATUS.has(res.status);
  err.degraded = res.status === 503;
  return err;
}

async function request(path, options) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) throw await parseError(res);
  return res;
}

export const analyzePdf = async (file) => {
  const formData = new FormData();
  formData.append("file", file);

  const res = await request("/analyze-pdf", {
    method: "POST",
    body: formData,
  });

  return res.json();
};

export const analyzePdfReport = async (file) => {
  const formData = new FormData();
  formData.append("file", file);

  const res = await request("/analyze-pdf-report", {
    method: "POST",
    body: formData,
  });

  const blob = await res.blob();
  return {
    blob,
    filename:
      res.headers
        .get("content-disposition")
        ?.split("filename=")[1]
        ?.replace(/"/g, "") || "AETHER_Report.pdf",
  };
};

export const analyzeContext = async (context) => {
  const res = await request("/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(context),
  });

  return res.json();
};

export const analyzeContextWithFactors = async (context, factors) => {
  const res = await request("/analyze-with-factors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context, factors }),
  });

  return res.json();
};

export const suggestFactors = async (context, customFactors = []) => {
  const res = await request("/factors/advise", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context, custom_factors: customFactors }),
  });

  return res.json();
};

export const suggestFactorsPdf = async (file) => {
  const formData = new FormData();
  formData.append("file", file);

  const res = await request("/factors/advise-pdf", {
    method: "POST",
    body: formData,
  });

  return res.json();
};

export const analyzeContextReport = async (context) => {
  const res = await request("/analyze-report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(context),
  });

  const blob = await res.blob();
  return {
    blob,
    filename: "Analysis_Report.pdf",
  };
};

export const downloadReport = async (format = "pdf") => {
  const res = await request(`/download-report?format=${encodeURIComponent(format)}`);

  const blob = await res.blob();
  return {
    blob,
    filename:
      res.headers
        .get("content-disposition")
        ?.split("filename=")[1]
        ?.replace(/"/g, "") || "AETHER_Report",
  };
};

export const emailReport = async (email, format = "pdf") => {
  const res = await request("/send-report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, format }),
  });
  return res.json();
};

export const getStatus = async () => {
  const res = await request("/status");
  return res.json();
};

export const getMetrics = async () => {
  const res = await request("/metrics");
  return res.json();
};

export const getHistory = async (limit = 50, offset = 0) => {
  const res = await request(`/history?limit=${limit}&offset=${offset}`);
  return res.json();
};

export const getAnalysis = async (analysisId) => {
  const res = await request(`/history/${encodeURIComponent(analysisId)}`);
  return res.json();
};

export const compareAnalyses = async (ids) => {
  const res = await request("/history/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });

  return res.json();
};

export const getHistoryTimeline = async (limit = 100) => {
  const res = await request(`/history/trends/timeline?limit=${limit}`);
  return res.json();
};

export const getConsistentFactors = async (minOccurrences = 2) => {
  const res = await request(`/history/trends/factors?min_occurrences=${minOccurrences}`);
  return res.json();
};

export const deleteAnalysis = async (analysisId) => {
  const res = await request(`/history/${encodeURIComponent(analysisId)}`, {
    method: "DELETE",
  });

  return res.json();
};

export const downloadFile = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};
