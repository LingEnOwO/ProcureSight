"use client";

import { api } from "@/lib/apiClient";
import { useState } from "react";

type UploadStatus =
  | "idle"
  | "uploading"
  | "uploaded"
  | "extracting"
  | "complete"
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

      const ingestRes = await api.POST("/api/ingest", {
        body: ingestFormData as any,
      });

      if (ingestRes.error) {
        setStatus("error");
        setErrorMessage(
          `Upload failed: ${JSON.stringify(ingestRes.error)}`
        );
        return;
      }

      setStatus("uploaded");
      setStatusMessage("File uploaded successfully");

      // Step 2: Extract based on file type
      const fileExt = file.name.split(".").pop()?.toLowerCase();
      const isPdf = fileExt === "pdf";
      const extractEndpoint = isPdf
        ? "/extract/unstructured"
        : "/extract/structured";

      setStatus("extracting");
      setStatusMessage(
        isPdf ? "Extracting from PDF..." : "Extracting structured data..."
      );

      const extractFormData = new FormData();
      extractFormData.append("file", file);

      const extractRes = await api.POST(extractEndpoint as any, {
        body: extractFormData as any,
      });

      if (extractRes.error) {
        setStatus("error");
        setErrorMessage(
          `Extraction failed: ${JSON.stringify(extractRes.error)}`
        );
        return;
      }

      // Success!
      setStatus("complete");
      setStatusMessage("Processing complete");
      setResultData(extractRes.data);
    } catch (err: any) {
      setStatus("error");
      setErrorMessage(`Unexpected error: ${err.message || String(err)}`);
    }
  };

  const isProcessing = status === "uploading" || status === "extracting";

  return (
    <main style={{ padding: 24 }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 6 }}>
          Uploads
        </h1>
        <div style={{ fontSize: 13, opacity: 0.75 }}>
          Upload files for ingestion and extraction
        </div>
      </header>

      {/* File selection */}
      <section
        style={{
          border: "1px solid #e5e7eb",
          borderRadius: 12,
          padding: 20,
          marginBottom: 16,
        }}
      >
        <div style={{ marginBottom: 12 }}>
          <label
            htmlFor="file-input"
            style={{
              display: "block",
              fontWeight: 600,
              marginBottom: 8,
              fontSize: 14,
            }}
          >
            Select a file
          </label>
          <input
            id="file-input"
            type="file"
            accept=".pdf,.csv,.json"
            onChange={handleFileChange}
            disabled={isProcessing}
            style={{
              display: "block",
              width: "100%",
              padding: 8,
              border: "1px solid #d1d5db",
              borderRadius: 6,
              fontSize: 14,
            }}
          />
          <div style={{ fontSize: 12, opacity: 0.7, marginTop: 6 }}>
            Supported formats: PDF, CSV, JSON
          </div>
        </div>

        {file && (
          <div style={{ fontSize: 13, marginBottom: 12 }}>
            <strong>Selected:</strong> {file.name} ({(file.size / 1024).toFixed(1)} KB)
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!file || isProcessing}
          style={{
            padding: "10px 20px",
            backgroundColor: !file || isProcessing ? "#d1d5db" : "#3b82f6",
            color: "white",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: !file || isProcessing ? "not-allowed" : "pointer",
          }}
        >
          {isProcessing ? "Processing..." : "Upload"}
        </button>
      </section>

      {/* Status display */}
      {statusMessage && (
        <section
          style={{
            border: "1px solid #e5e7eb",
            borderRadius: 12,
            padding: 14,
            marginBottom: 16,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 14 }}>
            Status
          </div>
          <div style={{ fontSize: 13 }}>
            {status === "uploading" && "📤 Uploading file..."}
            {status === "uploaded" && "✅ File uploaded successfully"}
            {status === "extracting" && "⚙️ Extracting data..."}
            {status === "complete" && "✅ Processing complete"}
          </div>
        </section>
      )}

      {/* Success message */}
      {status === "complete" && (
        <section
          style={{
            border: "1px solid #86efac",
            background: "#f0fdf4",
            borderRadius: 12,
            padding: 14,
            marginBottom: 16,
          }}
        >
          <div style={{ fontWeight: 700, color: "#166534", marginBottom: 6 }}>
            Success!
          </div>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            File <strong>{file?.name}</strong> has been uploaded and processed.
          </div>
          {resultData && (
            <details style={{ fontSize: 12, marginTop: 10 }}>
              <summary
                style={{ cursor: "pointer", fontWeight: 600, opacity: 0.85 }}
              >
                View result data
              </summary>
              <pre
                style={{
                  marginTop: 8,
                  padding: 8,
                  background: "white",
                  borderRadius: 4,
                  overflow: "auto",
                  maxHeight: 200,
                }}
              >
                {JSON.stringify(resultData, null, 2)}
              </pre>
            </details>
          )}
        </section>
      )}

      {/* Error message */}
      {status === "error" && errorMessage && (
        <section
          style={{
            border: "1px solid #fecaca",
            background: "#fff1f2",
            borderRadius: 12,
            padding: 14,
          }}
        >
          <div style={{ fontWeight: 700, color: "#9f1239", marginBottom: 6 }}>
            Error
          </div>
          <pre
            style={{
              fontSize: 12,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {errorMessage}
          </pre>
        </section>
      )}
    </main>
  );
}
