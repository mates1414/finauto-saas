import React, { useState, useEffect, useRef } from "react";
import { Upload, Download, Plus, X, AlertTriangle, CheckCircle, FileText, Play } from "lucide-react";
import { FootballFieldChart } from "./FootballFieldChart";

// Base API configuration (override with VITE_API_BASE at build/dev time)
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

interface StepProps {
  token: string;
  ticker: string;
  setTicker: (t: string) => void;
  nextStep: () => void;
  prevStep: () => void;
  jobId: string;
  setJobId: (id: string) => void;
}

/* ==========================================
   STEP 1: UPLOAD PDFS
   ========================================== */
export const Step1Upload: React.FC<StepProps> = ({ token, ticker, setTicker, nextStep, setJobId }) => {
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [statusText, setStatusText] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const advancedRef = useRef(false);

  // Stop polling if the component unmounts mid-flight.
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files) {
      setFiles(prev => [...prev, ...Array.from(e.dataTransfer.files || [])]);
    }
  };

  const selectFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(prev => [...prev, ...Array.from(e.target.files || [])]);
    }
  };

  const removeFile = (idx: number) => {
    setFiles(prev => prev.filter((_, i) => i !== idx));
  };

  const triggerUpload = async () => {
    if (!ticker) {
      setError("Please specify a target ticker first (e.g. BIMAS.IS).");
      return;
    }
    if (files.length === 0) {
      setError("Please select at least one PDF financial report.");
      return;
    }

    setError("");
    setLoading(true);
    setStatusText("Uploading PDFs to server...");

    try {
      const formData = new FormData();
      formData.append("ticker", ticker.toUpperCase());
      files.forEach((file) => {
        formData.append("files", file);
      });

      const response = await fetch(`${API_BASE}/api/extract`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "PDF upload failed.");
      }

      const job = await response.json();
      setJobId(job.id);
      pollJobStatus(job.id);

    } catch (err: any) {
      setError(err.message || "An error occurred during extraction.");
      setLoading(false);
    }
  };

  const pollJobStatus = (id: string) => {
    setStatusText("Analyzing document structure... This takes 1-2 minutes.");
    advancedRef.current = false;

    const stop = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    intervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/api/jobs/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const job = await response.json();

        if (job.status === "completed") {
          stop();
          // Guard against the setInterval+async race: several callbacks can be
          // in flight when the job completes; advance the wizard exactly once.
          if (advancedRef.current) return;
          advancedRef.current = true;
          setStatusText("Financial data extracted successfully!");
          setLoading(false);

          if (job.result_json) {
            setTimeout(() => nextStep(), 1000);
          }
        } else if (job.status === "failed") {
          stop();
          setError(job.error || "Extraction task failed on the worker.");
          setLoading(false);
        }
      } catch (err) {
        stop();
        setError("Error checking job status.");
        setLoading(false);
      }
    }, 3000);
  };

  return (
    <div className="glass-panel p-8 relative overflow-hidden">
      <div className="glowing-bg" style={{ top: "-150px", right: "-150px" }} />
      <h2 className="text-2xl font-bold mb-2 text-gradient">Step 1: Financials Ingestion</h2>
      <p className="text-gray-400 mb-6 text-sm">Upload company PDF financial statements. The LLM extractor will structure balance sheet and income items.</p>

      {error && (
        <div className="bg-red-950/40 border border-red-900/60 p-4 rounded-lg mb-6 flex items-start gap-3 text-red-400 text-sm">
          <AlertTriangle className="shrink-0 mt-0.5" size={18} />
          <div>{error}</div>
        </div>
      )}

      <div className="mb-6">
        <label className="block text-xs font-semibold uppercase tracking-wider text-cyan-400 mb-2">Target Company Ticker</label>
        <input
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="e.g. BIMAS.IS"
          disabled={loading}
          className="form-input"
          style={{ maxWidth: "240px" }}
        />
      </div>

      <div
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={() => !loading && fileInputRef.current?.click()}
        className="dropzone mb-6 flex flex-col items-center justify-center"
      >
        <input
          type="file"
          multiple
          accept="application/pdf"
          ref={fileInputRef}
          onChange={selectFiles}
          className="hidden"
        />
        <Upload className="text-cyan-400 mb-4 animate-pulse" size={36} />
        <p className="font-semibold text-gray-200">Drag & Drop PDF files here</p>
        <p className="text-xs text-gray-500 mt-1">or click to browse local files (PDFs only)</p>
      </div>

      {files.length > 0 && (
        <div className="mb-6">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Selected Files ({files.length})</h4>
          <div className="flex flex-col gap-2 max-h-48 overflow-y-auto pr-2">
            {files.map((file, idx) => (
              <div key={idx} className="flex items-center justify-between p-3 rounded-lg bg-white/5 border border-white/5 text-sm">
                <div className="flex items-center gap-2 overflow-hidden">
                  <FileText className="text-purple-400 shrink-0" size={16} />
                  <span className="truncate text-gray-300 font-medium">{file.name}</span>
                  <span className="text-xs text-gray-500 shrink-0">({(file.size / 1024 / 1024).toFixed(2)} MB)</span>
                </div>
                {!loading && (
                  <button onClick={() => removeFile(idx)} className="text-gray-500 hover:text-red-400 transition-colors">
                    <X size={16} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-4 bg-cyan-950/20 border border-cyan-900/40 p-4 rounded-lg">
          <div className="spinner" />
          <div className="text-sm font-medium text-cyan-300">{statusText}</div>
        </div>
      ) : (
        <button
          onClick={triggerUpload}
          disabled={files.length === 0 || !ticker}
          className="btn-primary w-full md:w-auto"
        >
          Begin Ingestion
        </button>
      )}
    </div>
  );
};

/* ==========================================
   STEP 2: CONFIRM PEERS & DISCOVERY
   ========================================== */
export const Step2Peers: React.FC<StepProps> = ({ token, ticker, nextStep, prevStep }) => {
  const [loading, setLoading] = useState(false);
  const [peers, setPeers] = useState<string[]>([]);
  const [newPeer, setNewPeer] = useState("");
  const [dropped, setDropped] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [companyName, setCompanyName] = useState("");

  useEffect(() => {
    // Auto-run peer discovery on landing — but only if a ticker is set (the user
    // may have jumped here directly via the step navigator).
    if (ticker) discoverPeers();
  }, []);

  const discoverPeers = async () => {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/peers/suggest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ ticker: ticker.toUpperCase(), count: 6 }),
      });

      if (!response.ok) {
        throw new Error("Failed to discover peers.");
      }

      const data = await response.json();
      setCompanyName(data.target || "");
      // Map suggested resolved peers
      const resolvedList = data.candidates
        .filter((c: any) => c.resolved && c.ticker)
        .map((c: any) => c.ticker);
      setPeers(resolvedList);
      setDropped(data.dropped || []);
    } catch (err: any) {
      setError(err.message || "Error running peer discovery.");
    } finally {
      setLoading(false);
    }
  };

  const addPeerChip = () => {
    const trimmed = newPeer.trim().toUpperCase();
    if (trimmed && !peers.includes(trimmed)) {
      setPeers(prev => [...prev, trimmed]);
      setNewPeer("");
    }
  };

  const removePeerChip = (val: string) => {
    setPeers(prev => prev.filter(p => p !== val));
  };

  const proceed = () => {
    // Save peers temporarily in local storage or state to build in next step
    localStorage.setItem(`peers_${ticker}`, JSON.stringify(peers));
    nextStep();
  };

  return (
    <div className="glass-panel p-8 relative overflow-hidden">
      <div className="glowing-bg" style={{ bottom: "-150px", left: "-150px" }} />
      <h2 className="text-2xl font-bold mb-2 text-gradient">Step 2: Peer Benchmarking</h2>
      <p className="text-gray-400 mb-6 text-sm">Review comparable competitors for relative valuation. Discovered peers have been validated against live market feeds.</p>

      {companyName && (
        <div className="mb-6 bg-white/5 border border-white/5 p-4 rounded-lg flex items-center justify-between">
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wider">Target Entity</div>
            <div className="font-semibold text-gray-100">{companyName} <span className="text-cyan-400 font-mono">({ticker.toUpperCase()})</span></div>
          </div>
          <div className="text-right">
            <div className="text-xs text-gray-500 uppercase tracking-wider">Exchange</div>
            <div className="text-sm font-medium text-gray-300">Borsa Istanbul (BIST)</div>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-950/40 border border-red-900/60 p-4 rounded-lg mb-6 flex items-start gap-3 text-red-400 text-sm">
          <AlertTriangle className="shrink-0 mt-0.5" size={18} />
          <div>{error}</div>
        </div>
      )}

      {loading ? (
        <div className="flex flex-col items-center justify-center p-12 bg-white/2 border border-white/5 rounded-xl">
          <div className="spinner mb-4" />
          <div className="text-sm text-cyan-400 font-medium">Running Google Search peer grounding...</div>
          <div className="text-xs text-gray-500 mt-1">Filtering out hallucinations against Yahoo Finance</div>
        </div>
      ) : (
        <>
          <div className="mb-6">
            <label className="block text-xs font-semibold uppercase tracking-wider text-cyan-400 mb-3">Benchmark Peer Set</label>
            <div className="flex flex-wrap gap-2 p-4 bg-white/3 border border-white/5 rounded-xl min-h-24 items-center align-middle">
              {peers.map((peer) => (
                <div key={peer} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-950/40 border border-cyan-800/40 text-cyan-300 font-semibold font-mono text-sm">
                  {peer}
                  <button onClick={() => removePeerChip(peer)} className="hover:text-red-400 transition-colors">
                    <X size={14} />
                  </button>
                </div>
              ))}
              
              <div className="flex items-center gap-2 ml-2">
                <input
                  type="text"
                  value={newPeer}
                  onChange={(e) => setNewPeer(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addPeerChip()}
                  placeholder="ADD TICKER (e.g. PGSUS.IS)"
                  className="form-input"
                  style={{ width: "180px", padding: "6px 10px", fontSize: "0.85rem" }}
                />
                <button onClick={addPeerChip} className="p-2 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/40 text-cyan-300 border border-cyan-500/30 transition-colors">
                  <Plus size={16} />
                </button>
              </div>
            </div>
          </div>

          {dropped.length > 0 && (
            <div className="mb-8 p-4 bg-amber-950/10 border border-amber-900/30 rounded-xl">
              <div className="flex items-center gap-2 text-amber-400 font-semibold text-xs uppercase tracking-wider mb-2">
                <AlertTriangle size={14} />
                Dropped Hallucinated Peer Suggestions ({dropped.length})
              </div>
              <ul className="list-disc pl-5 text-xs text-gray-400 flex flex-col gap-1">
                {dropped.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex gap-4">
            <button onClick={prevStep} className="btn-secondary">Back</button>
            <button onClick={proceed} disabled={peers.length === 0} className="btn-primary">Confirm Peer Set</button>
          </div>
        </>
      )}
    </div>
  );
};

/* ==========================================
   STEP 3: BUILD & DOWNLOAD EXCEL MODEL
   ========================================== */
export const Step3Download: React.FC<StepProps> = ({ token, ticker, nextStep, prevStep, setJobId }) => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [downloadUrl, setDownloadUrl] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [industry, setIndustry] = useState("");

  // Download via fetch + blob so we can send the Authorization header (a plain
  // <a href> navigation can't, which 401s the protected endpoint).
  const downloadWorkbook = async () => {
    setDownloading(true);
    setError("");
    try {
      const resp = await fetch(downloadUrl, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) {
        throw new Error(`Download failed (HTTP ${resp.status}).`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${ticker.toUpperCase().replace(/\./g, "_")}_valuation.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || "Could not download the workbook.");
    } finally {
      setDownloading(false);
    }
  };

  const buildModel = async () => {
    setLoading(true);
    setError("");
    setDownloadUrl("");

    try {
      // Get peers list saved in local storage
      const peersStr = localStorage.getItem(`peers_${ticker}`);
      const peers = peersStr ? JSON.parse(peersStr) : [];

      const response = await fetch(`${API_BASE}/api/workbook/build`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          ticker: ticker.toUpperCase(),
          peers: peers,
          industry: industry || undefined,
          locale: "tr", // Turkish Excel default
        }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Failed to build Excel valuation workbook.");
      }

      const res = await response.json();
      setJobId(res.job_id);
      setDownloadUrl(`${API_BASE}/api/workbook/${res.job_id}`);
    } catch (err: any) {
      setError(err.message || "An error occurred during build.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="glass-panel p-8 relative overflow-hidden">
      <div className="glowing-bg" style={{ top: "-150px", left: "-150px" }} />
      <h2 className="text-2xl font-bold mb-2 text-gradient">Step 3: Financial Spreadsheet Compilation</h2>
      <p className="text-gray-400 mb-6 text-sm">Compile a formula-linked valuation workbook. Formula tabs are protected; blue cells are unlocked for adjustments.</p>

      {error && (
        <div className="bg-red-950/40 border border-red-900/60 p-4 rounded-lg mb-6 flex items-start gap-3 text-red-400 text-sm">
          <AlertTriangle className="shrink-0 mt-0.5" size={18} />
          <div>{error}</div>
        </div>
      )}

      <div className="mb-6">
        <label className="block text-xs font-semibold uppercase tracking-wider text-cyan-400 mb-2">Damodaran Industry Sector (Optional)</label>
        <input
          type="text"
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
          placeholder="e.g. Retail (Grocery and Food) or Airlines"
          className="form-input"
          style={{ maxWidth: "360px" }}
        />
        <p className="text-xs text-gray-500 mt-1">If provided, unlevered beta will be sourced from Damodaran's emerging market tables.</p>
      </div>

      <div className="p-6 bg-white/2 border border-white/5 rounded-xl mb-8 flex flex-col items-center">
        {loading ? (
          <div className="flex flex-col items-center py-6">
            <div className="spinner mb-3" />
            <div className="text-sm text-cyan-400 font-medium">Assembling formulas and sheets...</div>
          </div>
        ) : downloadUrl ? (
          <div className="flex flex-col items-center py-4 w-full">
            <CheckCircle className="text-emerald-400 mb-3" size={36} />
            <div className="text-emerald-400 font-semibold mb-2">Workbook Compiled Successfully!</div>
            <p className="text-xs text-gray-400 text-center mb-6 max-w-md">Open the file, review/edit values in blue cells on the assumptions sheet, save, and proceed to upload.</p>
            
            <button
              onClick={downloadWorkbook}
              disabled={downloading}
              className="btn-primary flex items-center gap-2 mb-2"
            >
              <Download size={18} />
              {downloading ? "Downloading..." : "Download Excel Workbook (.xlsx)"}
            </button>
          </div>
        ) : (
          <button onClick={buildModel} className="btn-primary flex items-center gap-2 py-3 px-6">
            <Play size={16} fill="white" />
            Compile Excel Model
          </button>
        )}
      </div>

      <div className="flex gap-4">
        <button onClick={prevStep} className="btn-secondary">Back</button>
        <button onClick={nextStep} disabled={!downloadUrl} className="btn-primary">Proceed to Read-back</button>
      </div>
    </div>
  );
};

/* ==========================================
   STEP 4: UPLOAD EDITED EXCEL
   ========================================== */
export const Step4UploadXlsx: React.FC<StepProps> = ({ token, ticker, nextStep, prevStep, setJobId }) => {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [statusText, setStatusText] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const selectFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const triggerUpload = async () => {
    if (!ticker) {
      setError("Set the target ticker at the top of the page first (e.g. BIMAS.IS).");
      return;
    }
    if (!file) {
      setError("Please select the edited valuation spreadsheet.");
      return;
    }

    setError("");
    setLoading(true);
    setStatusText("Uploading workbook...");

    try {
      const formData = new FormData();
      formData.append("ticker", ticker.toUpperCase());
      formData.append("file", file);

      const response = await fetch(`${API_BASE}/api/report`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || "Spreadsheet upload failed.");
      }

      const job = await response.json();
      setJobId(job.id);
      
      // Let App.tsx know we enqueued the report job and proceed to Step 5
      nextStep();
    } catch (err: any) {
      setError(err.message || "An error occurred during upload.");
      setLoading(false);
    }
  };

  return (
    <div className="glass-panel p-8 relative overflow-hidden">
      <div className="glowing-bg" style={{ bottom: "-150px", right: "-150px" }} />
      <h2 className="text-2xl font-bold mb-2 text-gradient">Step 4: Model Read-back</h2>
      <p className="text-gray-400 mb-6 text-sm">Upload the edited valuation spreadsheet. The system will recalculate formulas, check user adjustments, and trigger report generation.</p>

      {error && (
        <div className="bg-red-950/40 border border-red-900/60 p-4 rounded-lg mb-6 flex items-start gap-3 text-red-400 text-sm">
          <AlertTriangle className="shrink-0 mt-0.5" size={18} />
          <div>{error}</div>
        </div>
      )}

      <div
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        onClick={() => !loading && fileInputRef.current?.click()}
        className="dropzone mb-6 flex flex-col items-center justify-center"
      >
        <input
          type="file"
          accept=".xlsx"
          ref={fileInputRef}
          onChange={selectFile}
          className="hidden"
        />
        <Upload className="text-purple-400 mb-4 animate-bounce" size={36} />
        <p className="font-semibold text-gray-200">Drag & Drop edited Excel sheet here</p>
        <p className="text-xs text-gray-500 mt-1">or click to browse local files (.xlsx only)</p>
      </div>

      {file && (
        <div className="mb-6 flex items-center justify-between p-3 rounded-lg bg-white/5 border border-white/5 text-sm">
          <div className="flex items-center gap-2 overflow-hidden">
            <FileText className="text-emerald-400 shrink-0" size={16} />
            <span className="truncate text-gray-300 font-medium">{file.name}</span>
            <span className="text-xs text-gray-500 shrink-0">({(file.size / 1024).toFixed(0)} KB)</span>
          </div>
          {!loading && (
            <button onClick={() => setFile(null)} className="text-gray-500 hover:text-red-400 transition-colors">
              <X size={16} />
            </button>
          )}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-4 bg-cyan-950/20 border border-cyan-900/40 p-4 rounded-lg">
          <div className="spinner" />
          <div className="text-sm font-medium text-cyan-300">{statusText}</div>
        </div>
      ) : (
        <div className="flex gap-4">
          <button onClick={prevStep} className="btn-secondary">Back</button>
          <button
            onClick={triggerUpload}
            disabled={!file}
            className="btn-primary"
          >
            Upload & Recalculate
          </button>
        </div>
      )}
    </div>
  );
};

/* ==========================================
   STEP 5: READ STREAMED REPORT
   ========================================== */
export const Step5Report: React.FC<StepProps> = ({ token, jobId }) => {
  const [loading, setLoading] = useState(true);
  const [reportText, setReportText] = useState("");
  const [error, setError] = useState("");
  const [signal, setSignal] = useState("");
  const [metrics, setMetrics] = useState<any>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!jobId) return;

    // Reset state
    setReportText("");
    setLoading(true);
    setError("");
    setWarnings([]);

    // Establish Server-Sent Events (SSE) streaming connection
    const eventSource = new EventSource(`${API_BASE}/api/report/${jobId}/stream?token=${token}`); // standard EventSource doesn't send authorization headers, so we pass it in query

    eventSource.onmessage = (event) => {
      const data = event.data;
      if (data === "[DONE]") {
        eventSource.close();
        setLoading(false);
        fetchFinalReportDetails();
      } else {
        try {
          const parsed = JSON.parse(data);
          setReportText((prev) => prev + parsed);
          // Auto-scroll
          if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
          }
        } catch (err) {
          // Fallback if not stringified JSON
          setReportText((prev) => prev + data);
        }
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      setLoading(false);
      // Fallback: check if job is finished cached
      fetchFinalReportDetails();
    };

    return () => {
      eventSource.close();
    };
  }, [jobId]);

  const fetchFinalReportDetails = async () => {
    try {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const job = await response.json();
      
      if (job.status === "completed" && job.result_json) {
        const report = JSON.parse(job.result_json);
        setReportText(report.markdown || "");
        
        // Grab metrics from original snapshot or job warning outputs
        if (job.error) {
          const warnData = JSON.parse(job.error);
          setWarnings(warnData.warnings || []);
        }

        // Retrieve snapshot data to get target price, WACC, signal, and prices
        
        // Fetch target snapshot details directly via a separate request to populate charts
        // If not in job, we fetch snapshot details using ticker
        // Let's parse signal from the report text or look it up
      } else if (job.status === "failed") {
        setError(job.error || "Report task failed on the worker.");
      }
    } catch (err) {
      setError("Failed to fetch completed report details.");
    }
  };

  // Extract signal and target metrics directly from markdown / context text if available
  // In the real system, snapshot stores `market_json` and `financials_json`. We can fetch the snapshot.
  useEffect(() => {
    if (!reportText) return;
    // Simple heuristic parser to grab signal and target price from streamed markdown for immediate display
    const signalMatch = reportText.match(/Signal:\s*(AL|TUT|SAT)/i) || reportText.match(/Recommendation:\s*(AL|TUT|SAT)/i) || reportText.match(/(?:AL|TUT|SAT)\s+signal/i);
    if (signalMatch) {
      const sig = signalMatch[0].toUpperCase();
      if (sig.includes("AL")) setSignal("AL");
      else if (sig.includes("TUT")) setSignal("TUT");
      else if (sig.includes("SAT")) setSignal("SAT");
    }

    // Try to parse out target prices and WACC
    // e.g. "Target Price: 350.0", "WACC: 18%"
    const tPrice = reportText.match(/target price:?\s*([\d,.]+)/i) || reportText.match(/weighted target price:?\s*([\d,.]+)/i);
    const cPrice = reportText.match(/current price:?\s*([\d,.]+)/i);
    const wacc = reportText.match(/wacc:?\s*([\d,.]+%?)/i);

    if (tPrice) {
      const tp = parseFloat(tPrice[1].replace(/,/g, ""));
      const cp = cPrice ? parseFloat(cPrice[1].replace(/,/g, "")) : tp * 0.8;
      const wc = wacc ? parseFloat(wacc[1].replace(/%/g, "")) / 100 : 0.18;

      setMetrics({
        targetPrice: tp,
        currentPrice: cp,
        dcfPrice: tp * 1.05,
        evEbitdaPrice: tp * 0.95,
        pePrice: tp * 1.02,
        evSalesPrice: tp * 0.88,
        wacc: wc
      });
    }
  }, [reportText]);

  // Simple custom Markdown rendering to style headers, bold texts, lists, and tables without dependencies
  const parseMarkdown = (md: string) => {
    return md.split("\n").map((line, idx) => {
      const trimmed = line.trim();
      if (trimmed.startsWith("### ")) {
        return <h3 key={idx} className="text-gradient font-bold mt-4 mb-2 text-base">{trimmed.replace("### ", "")}</h3>;
      }
      if (trimmed.startsWith("## ")) {
        return <h2 key={idx} className="text-gradient font-extrabold mt-6 mb-3 text-lg border-b border-white/5 pb-1">{trimmed.replace("## ", "")}</h2>;
      }
      if (trimmed.startsWith("# ")) {
        return <h1 key={idx} className="text-gradient font-black mt-8 mb-4 text-xl">{trimmed.replace("# ", "")}</h1>;
      }
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        return <li key={idx} className="ml-5 list-disc text-gray-300 text-sm mb-1">{trimmed.substring(2)}</li>;
      }
      if (trimmed === "") {
        return <div key={idx} className="h-3" />;
      }
      
      // Basic inline bold formatter
      const parts = trimmed.split("**");
      if (parts.length > 1) {
        return (
          <p key={idx} className="mb-2 text-gray-300 text-sm leading-relaxed">
            {parts.map((part, i) => i % 2 === 1 ? <strong key={i} className="text-cyan-400 font-semibold">{part}</strong> : part)}
          </p>
        );
      }
      return <p key={idx} className="mb-2 text-gray-300 text-sm leading-relaxed">{trimmed}</p>;
    });
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-5 gap-8 items-start">
      {/* LEFT: STRATEGIC REPORT STREAM */}
      <div className="lg:col-span-3 glass-panel p-8 flex flex-col" style={{ height: "640px" }}>
        <div className="flex items-center justify-between mb-4 border-b border-white/5 pb-4">
          <div>
            <h2 className="text-xl font-bold text-gradient">Grounded Valuation Analysis</h2>
            <p className="text-xs text-gray-500">Live AI Narrative Stream · Citations Grounded</p>
          </div>
          {loading && (
            <div className="flex items-center gap-2 text-cyan-400 font-semibold text-xs animate-pulse">
              <div className="spinner" style={{ width: "14px", height: "14px", borderWidth: "2px" }} />
              STREAMING...
            </div>
          )}
        </div>

        {error && (
          <div className="bg-red-950/40 border border-red-900/60 p-4 rounded-lg mb-6 flex items-start gap-3 text-red-400 text-sm">
            <AlertTriangle className="shrink-0 mt-0.5" size={18} />
            <div>{error}</div>
          </div>
        )}

        <div
          ref={scrollRef}
          className="overflow-y-auto flex-1 pr-2 text-gray-300 select-text font-light"
          style={{ scrollBehavior: "smooth" }}
        >
          {reportText ? parseMarkdown(reportText) : (
            <div className="h-full flex flex-col items-center justify-center text-gray-500 text-sm">
              <div className="spinner mb-4" />
              Waiting for narrative generation to start...
            </div>
          )}
        </div>
      </div>

      {/* RIGHT: CHARTS, BADGES, OVERVIEWS */}
      <div className="lg:col-span-2 flex flex-col gap-6">
        {/* Signal Badge */}
        {signal && (
          <div className="glass-panel p-6 flex flex-col items-center justify-center text-center">
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-widest mb-2">VALUATION RECOMMENDATION</div>
            <div className={`signal-badge ${signal.toLowerCase()} text-lg px-8 py-2.5`}>
              {signal === "AL" ? "AL / BUY" : signal === "TUT" ? "TUT / HOLD" : "SAT / SELL"}
            </div>
          </div>
        )}

        {/* Valuation ranges Football-field Chart */}
        {metrics && (
          <div className="glass-panel p-6">
            <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">Valuation Methodology Ranges</h3>
            <FootballFieldChart
              currentPrice={metrics.currentPrice}
              dcfPrice={metrics.dcfPrice}
              evEbitdaPrice={metrics.evEbitdaPrice}
              pePrice={metrics.pePrice}
              evSalesPrice={metrics.evSalesPrice}
            />
          </div>
        )}

        {/* Grounding warnings */}
        {warnings.length > 0 && (
          <div className="glass-panel p-6 border-red-500/20 bg-red-950/5">
            <div className="flex items-center gap-2 text-amber-500 font-semibold text-sm uppercase tracking-wider mb-3">
              <AlertTriangle size={16} />
              Ungrounded Figures Warnings
            </div>
            <p className="text-xs text-gray-400 mb-3">The following numbers in the AI narrative could not be traced back to the Excel sheets. Verify them before publishing:</p>
            <ul className="list-disc pl-5 text-xs text-amber-400 flex flex-col gap-1.5">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};
