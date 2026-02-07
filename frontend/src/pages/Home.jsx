import React, { useEffect, useState } from "react";
import { Brain } from "lucide-react";
import PdfUpload from "../components/PdfUpload";
import JsonInput from "../components/JsonInput";
import ResultsDisplay from "../components/ResultsDisplay";
import {
  analyzePdf,
  analyzeContext,
  downloadFile,
  downloadLatestReport,
  getStatus,
} from "../services/api";

const Home = () => {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [lastInput, setLastInput] = useState(null);
  const [lastInputType, setLastInputType] = useState(null);
  const [status, setStatus] = useState(null);

  const handlePdf = async (file) => {
    try {
      setLoading(true);
      setError(null);
      setStatus(null);
      const data = await analyzePdf(file);
      setResult(data);
      setLastInput(file);
      setLastInputType("pdf");
    } catch (err) {
      setError(err.message || "Failed to analyze PDF");
    } finally {
      setLoading(false);
    }
  };

  const handleJson = async (context) => {
    try {
      setLoading(true);
      setError(null);
      setStatus(null);
      const data = await analyzeContext(context);
      setResult(data);
      setLastInput(context);
      setLastInputType("context");
    } catch (err) {
      setError(err.message || "Failed to analyze text");
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadPDF = async () => {
    try {
      setLoading(true);
      setStatus(null);
      const pdfData = await downloadLatestReport();
      downloadFile(pdfData.blob, pdfData.filename);
    } catch (err) {
      setError(err.message || "Failed to download PDF");
    } finally {
      setLoading(false);
    }
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
      intervalId = setInterval(pollStatus, 8000);
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
        <PdfUpload onUpload={handlePdf} loading={loading} />
        <JsonInput onSubmit={handleJson} loading={loading} />
      </div>

      <ResultsDisplay
        result={result}
        error={error}
        loading={loading}
        status={status}
        onDownloadPDF={result ? handleDownloadPDF : null}
      />
    </div>
  );
};

export default Home;
