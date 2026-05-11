"use client";

import { useState } from "react";

type UploadStatus =
  | "idle"
  | "uploading"
  | "uploaded"
  | "extracting"
  | "complete"
  | "duplicate"
  | "error";

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<UploadStatus>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [resultData, setResultData] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState("");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] || null;
    setFile(selectedFile);
    setStatus("idle");
    setStatusMessage("");
    setResultData(null);
    setErrorMessage("");
  };

  const handleUpload = async () => {
    if (!file) {
      setErrorMessage("Please select a file first");
      return;
    }

    try {
      // Step 1: Ingest
      setStatus("uploading");
      setStatusMessage("Uploading file...");
      setErrorMessage("");

      const ingestFormData = new FormData();
      ingestFormData.append("file", file);

      const ingestRes = await fetch("/api/ingest", {
        method: "POST",
        body: ingestFormData,
      });

      if (!ingestRes.ok) {
        const errorData = await ingestRes
          .json()
          .catch(() => ({ detail: "Upload failed" }));
        setStatus("error");
        setErrorMessage(
          `Upload failed: ${errorData.detail || ingestRes.statusText}`
        );
        return;
      }

      const ingestData = await ingestRes.json();
      const rawDocId = ingestData.raw_doc_id;

      if (ingestData.duplicate) {
        setStatus("duplicate");
        setStatusMessage(
          `Upload skipped: this exact file was already uploaded (raw_doc_id=${rawDocId})`
        );
        return;
      }

      setStatus("uploaded");
      setStatusMessage("File uploaded successfully");

      // Step 2: Extract based on file type
      const fileExt = file.name.split(".").pop()?.toLowerCase();
      const isPdf = fileExt === "pdf";
      const extractEndpoint = isPdf
        ? `/api/extract/unstructured?raw_doc_id=${rawDocId}`
        : `/api/extract/structured?raw_doc_id=${rawDocId}`;

      setStatus("extracting");
      setStatusMessage(
        isPdf ? "Extracting from PDF..." : "Extracting structured data..."
      );

      const extractRes = await fetch(extractEndpoint, {
        method: "POST",
      });

      if (!extractRes.ok) {
        const errorData = await extractRes
          .json()
          .catch(() => ({ detail: "Extraction failed" }));
        setStatus("error");
        setErrorMessage(
          `Extraction failed: ${errorData.detail || extractRes.statusText}`
        );
        return;
      }

      const extractData = await extractRes.json();

      setStatus("complete");
      setStatusMessage("Extraction job queued");
      setResultData(extractData);
    } catch (err: any) {
      setStatus("error");
      setErrorMessage(`Unexpected error: ${err.message || String(err)}`);
    }
  };

  const isProcessing = status === "uploading" || status === "extracting";
  const isTerminal = status === "complete" || status === "duplicate" || status === "error";

  const steps: { key: UploadStatus | "uploaded"; label: string }[] = [
    { key: "uploading", label: "Upload" },
    { key: "extracting", label: "Extract" },
    { key: "complete", label: "Done" },
  ];

  function getStepState(stepKey: string) {
    if (status === "complete") return "done";
    if (status === "error") return "error";
    if (stepKey === "uploading" && (status === "uploading" || status === "uploaded" || status === "extracting")) return "done";
    if (stepKey === "extracting" && status === "extracting") return "active";
    return "pending";
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Uploads</h1>
        <p className="page-subtitle">
          Upload and extract data from invoices and documents
        </p>
      </div>

      {/* Upload card */}
      <div className="upload-card">
        <label
          htmlFor="file-input"
          className={`upload-drop-zone${file ? " has-file" : ""}`}
          style={{ display: "block" }}
        >
          <div
            style={{
              color: "var(--text-muted)",
              marginBottom: "0.625rem",
              display: "flex",
              justifyContent: "center",
            }}
          >
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="8" fill="var(--brand-light)" />
              <path
                d="M16 20V11M16 11L12 15M16 11L20 15"
                stroke="var(--brand)"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M10 23h12"
                stroke="var(--brand)"
                strokeWidth="1.75"
                strokeLinecap="round"
                opacity="0.5"
              />
            </svg>
          </div>

          {file ? (
            <div>
              <div
                style={{
                  fontWeight: 600,
                  fontSize: "0.9375rem",
                  color: "var(--brand-dark)",
                  marginBottom: "0.25rem",
                }}
              >
                {file.name}
              </div>
              <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                {(file.size / 1024).toFixed(1)} KB &middot; Click to change
              </div>
            </div>
          ) : (
            <div>
              <div
                style={{
                  fontWeight: 600,
                  fontSize: "0.9375rem",
                  color: "var(--text-secondary)",
                  marginBottom: "0.25rem",
                }}
              >
                Click to select a file
              </div>
              <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
                PDF, CSV, or JSON &mdash; up to any size
              </div>
            </div>
          )}
        </label>

        <input
          id="file-input"
          type="file"
          accept=".pdf,.csv,.json"
          onChange={handleFileChange}
          disabled={isProcessing}
          style={{ display: "none" }}
        />

        <button
          onClick={handleUpload}
          disabled={!file || isProcessing}
          className="btn-primary"
          style={{ width: "100%", justifyContent: "center" }}
        >
          {isProcessing && <span className="spinner" />}
          {isProcessing
            ? status === "uploading"
              ? "Uploading..."
              : "Extracting..."
            : "Upload & Extract"}
        </button>
      </div>

      {/* Status steps */}
      {status !== "idle" && (
        <div
          className="card"
          style={{ marginBottom: "1.25rem" }}
        >
          <div className="card-body">
            <div
              style={{
                fontSize: "0.8125rem",
                fontWeight: 600,
                color: "var(--text-secondary)",
                marginBottom: "1rem",
              }}
            >
              Processing status
            </div>
            <div className="status-steps">
              {steps.map((step, idx) => {
                const state = getStepState(step.key);
                return (
                  <div key={step.key} style={{ display: "contents" }}>
                    <div
                      className={`status-step${state === "active" ? " active" : state === "done" ? " done" : ""}`}
                    >
                      {state === "done" ? (
                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ color: "#16a34a" }}>
                          <circle cx="7" cy="7" r="6" fill="#dcfce7" />
                          <path d="M4.5 7l2 2 3-3" stroke="#16a34a" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      ) : state === "active" ? (
                        <span className="spinner" style={{ color: "var(--brand)" }} />
                      ) : (
                        <div className="status-dot" style={{ opacity: 0.3 }} />
                      )}
                      {step.label}
                    </div>
                    {idx < steps.length - 1 && (
                      <div className="status-divider" />
                    )}
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
              {statusMessage}
            </div>
          </div>
        </div>
      )}

      {/* Duplicate */}
      {status === "duplicate" && (
        <div className="alert-banner warning">
          <div className="alert-title">Already uploaded</div>
          <div style={{ fontSize: "0.8125rem" }}>
            <strong>{file?.name}</strong> was not re-processed — this exact file
            already exists in the system. No extraction or scoring will run.
          </div>
        </div>
      )}

      {/* Success */}
      {status === "complete" && (
        <div className="alert-banner success">
          <div className="alert-title">Processing complete</div>
          <div style={{ fontSize: "0.8125rem", marginBottom: resultData ? "0.75rem" : 0 }}>
            <strong>{file?.name}</strong> has been uploaded. Extraction is
            running in the background — check the Invoices page shortly.
          </div>
          {resultData && (
            <details style={{ marginTop: "0.5rem" }}>
              <summary
                style={{
                  cursor: "pointer",
                  fontWeight: 600,
                  fontSize: "0.8125rem",
                  opacity: 0.85,
                  userSelect: "none",
                }}
              >
                View extracted data
              </summary>
              <pre
                style={{
                  marginTop: "0.625rem",
                  padding: "0.75rem",
                  background: "white",
                  borderRadius: "var(--r-sm)",
                  overflow: "auto",
                  maxHeight: 240,
                  fontSize: "0.75rem",
                  lineHeight: 1.5,
                  color: "var(--text-primary)",
                  border: "1px solid #bbf7d0",
                }}
              >
                {JSON.stringify(resultData, null, 2)}
              </pre>
            </details>
          )}
        </div>
      )}

      {/* Error */}
      {status === "error" && errorMessage && (
        <div className="alert-banner error">
          <div className="alert-title">Upload failed</div>
          <pre
            style={{
              fontSize: "0.8125rem",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              margin: 0,
              fontFamily: "inherit",
            }}
          >
            {errorMessage}
          </pre>
        </div>
      )}
    </div>
  );
}
