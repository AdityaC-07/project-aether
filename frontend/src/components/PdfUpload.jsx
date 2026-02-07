import React, { useState } from "react";
import { FileText, Upload } from "lucide-react";

const PdfUpload = ({ onUpload, loading }) => {
  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!file) return;
    onUpload(file);
  };

  const handleDragEnter = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files?.[0];
    if (droppedFile?.type === "application/pdf") {
      setFile(droppedFile);
    }
  };

  return (
    <div className="card">
      <h3>
        <FileText className="icon" aria-hidden="true" />
        Analyze PDF
      </h3>
      <form onSubmit={handleSubmit}>
        <div
          className={`upload-container ${isDragging ? "dragging" : ""}`}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            style={{ display: "none" }}
            id="pdf-input"
          />
          <label htmlFor="pdf-input">
            <div className="upload-icon">
              <Upload className="icon-xl" aria-hidden="true" />
            </div>
            <div className={file ? "upload-file-name" : "upload-title"}>
              {file ? file.name : "Drag and drop your PDF or click to browse"}
            </div>
            <div className="upload-hint">Supports PDF files up to 50MB</div>
          </label>
        </div>
        <div className="form-actions">
          <button
            type="submit"
            disabled={!file || loading}
            className="button-full-width"
          >
            {loading ? (
              <span className="loading-state">
                <span className="loading-spinner"></span>
                Uploading...
              </span>
            ) : (
              "Analyze PDF"
            )}
          </button>
        </div>
      </form>
      <p className="hint">
        Uploads the PDF and runs the full analysis pipeline.
      </p>
    </div>
  );
};

export default PdfUpload;
