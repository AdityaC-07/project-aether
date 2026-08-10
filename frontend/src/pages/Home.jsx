import React, { useEffect, useState } from "react";
import { Brain } from "lucide-react";
import PdfUpload from "../components/PdfUpload";
import JsonInput from "../components/JsonInput";
import ResultsDisplay from "../components/ResultsDisplay";
import FactorSelector from "../components/FactorSelector";
import HistoryPanel from "../components/HistoryPanel";
import {
  downloadReport,
  emailReport,
  getMetrics,
  getStatus,
  STATUS_POLL_MS,
  suggestFactors,
  suggestFactorsPdf,
} from "../services/api";

const Home = () => {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastInput, setLastInput] = useState(null);
  const [lastInputType, setLastInputType] = useState(null);
  const [status, setStatus] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [emailState, setEmailState] = useState({ status: "idle", message: "" });
  const [factorPlan, setFactorPlan] = useState(null);
  const [factorContext, setFactorContext] = useState(null);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  const refreshMetrics = async () => {
    try {
      setMetrics(await getMetrics());
    } catch {
      setMetrics(null);
    }
  };

  const handleSuggestPdf = async (file) => {
    try {
      setLoading(true);
      setError(null);
      setStatus(null);
      setMetrics(null);
      setResult(null);
      const data = await suggestFactorsPdf(file);
      setFactorPlan(data);
      setFactorContext(data.context);
      setLastInput(file);
      setLastInputType("pdf");
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSuggestJson = async (context) => {
    try {
      setLoading(true);
      setError(null);
      setStatus(null);
      setMetrics(null);
      setResult(null);
      const data = await suggestFactors(context);
      setFactorPlan(data);
      setFactorContext(data.context || context);
      setLastInput(context);
      setLastInputType("context");
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleFactorRunComplete = (data) => {
    setResult(data);
    setFactorPlan(null);
    setFactorContext(null);
    setLastInputType("context");
    refreshMetrics();
    setHistoryRefreshKey((k) => k + 1);
  };

  const handleFactorBack = () => {
    setFactorPlan(null);
    setFactorContext(null);
  };

  const handleDownload = async (format = "pdf") => {
    try {
      setLoading(true);
      setStatus(null);
      const reportData = await downloadReport(format);
      const urlObject = URL.createObjectURL(reportData.blob);
      const a = document.createElement("a");
      a.href = urlObject;
      a.download = reportData.filename || `Aether_Report.${format}`;
      a.click();
      URL.revokeObjectURL(urlObject);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  const handleEmail = async (recipient, format = "pdf") => {
    setEmailState({ status: "sending", message: "" });
    try {
      const res = await emailReport(recipient, format);
      setEmailState({
        status: "success",
        message: res.message || "Report sent successfully.",
      });
    } catch (err) {
      setEmailState({
        status: "error",
        message: err.message || "Failed to send report.",
      });
    }
  };

  const handleRetry = () => {
    if (lastInputType === "pdf" && lastInput) return handleSuggestPdf(lastInput);
    if (lastInputType === "context" && lastInput) return handleSuggestJson(lastInput);
    return null;
  };

  useEffect(() => {
    let intervalId;
    let cancelled = false;

    const pollStatus = async () => {
      try {
        const data = await getStatus();
        if (!cancelled) {
          setStatus(data);
        }
      } catch (err) {
        if (!cancelled) {
          setStatus(null);
        }
      }
    };

    if (loading) {
      pollStatus();
      intervalId = setInterval(pollStatus, STATUS_POLL_MS);
    } else {
      setStatus(null);
    }

    return () => {
      cancelled = true;
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [loading]);

  return (
    <div className="layout">
      <header className="header">
        <h1>PROJECT AETHER</h1>
        <p>AI-Powered Debate & Synthesis System for Comprehensive Analysis</p>
      </header>

      <div className="grid">
        <PdfUpload onUpload={handleSuggestPdf} loading={loading} />
        <JsonInput onSubmit={handleSuggestJson} loading={loading} />
      </div>

      {factorPlan ? (
        <FactorSelector
          plan={factorPlan}
          context={factorContext}
          onComplete={handleFactorRunComplete}
          onBack={handleFactorBack}
        />
      ) : (
        <ResultsDisplay
          result={result}
          error={error}
          loading={loading}
          status={status}
          metrics={metrics}
          emailState={emailState}
          onRetry={handleRetry}
          onDownload={result ? handleDownload : null}
          onEmail={result ? handleEmail : null}
        />
      )}

      <HistoryPanel refreshKey={historyRefreshKey} />
    </div>
  );
};

export default Home;
