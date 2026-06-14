import { useState, Fragment } from "react";
import { LogOut, ArrowRight, UserPlus, LogIn, Award } from "lucide-react";
import { Step1Upload, Step2Peers, Step3Download, Step4UploadXlsx, Step5Report } from "./components/WizardSteps";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

function App() {
  const [token, setToken] = useState<string>(localStorage.getItem("token") || "");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [authError, setAuthError] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  // Wizard state machine
  const [step, setStep] = useState<number>(1);
  // Ticker persists across refresh and is shared by every step, so you can jump
  // straight to a later step (e.g. Read-back) without redoing earlier ones.
  const [ticker, setTickerState] = useState<string>(localStorage.getItem("ticker") || "");
  const setTicker = (t: string) => {
    setTickerState(t);
    localStorage.setItem("ticker", t);
  };
  const [jobId, setJobId] = useState<string>("");

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError("");
    setAuthLoading(true);

    try {
      const endpoint = isRegister ? "/api/auth/register" : "/api/auth/token";
      const options: RequestInit = {
        method: "POST",
      };

      if (isRegister) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify({ email, password });
      } else {
        const formData = new URLSearchParams();
        formData.append("username", email);
        formData.append("password", password);
        options.body = formData;
      }

      const response = await fetch(`${API_BASE}${endpoint}`, options);
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Authentication failed.");
      }

      if (isRegister) {
        // Automatically log in after registration
        setIsRegister(false);
        setAuthLoading(false);
        // Trigger login call
        const loginData = new URLSearchParams();
        loginData.append("username", email);
        loginData.append("password", password);
        const loginResp = await fetch(`${API_BASE}/api/auth/token`, {
          method: "POST",
          body: loginData,
        });
        const tokObj = await loginResp.json();
        setToken(tokObj.access_token);
        localStorage.setItem("token", tokObj.access_token);
      } else {
        const data = await response.json();
        setToken(data.access_token);
        localStorage.setItem("token", data.access_token);
      }
    } catch (err: any) {
      setAuthError(err.message || "Something went wrong.");
    } finally {
      setAuthLoading(false);
    }
  };

  const logout = () => {
    setToken("");
    localStorage.removeItem("token");
    setStep(1);
    setTicker("");
    setJobId("");
  };

  const nextStep = () => setStep(prev => Math.min(prev + 1, 5));
  const prevStep = () => setStep(prev => Math.max(prev - 1, 1));

  // If not authenticated, render login panel
  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 relative">
        <div className="glowing-bg" style={{ top: "10%", left: "10%" }} />
        <div className="glowing-bg" style={{ bottom: "10%", right: "10%" }} />

        <div className="w-full max-w-md glass-panel p-8 relative z-10">
          <div className="flex flex-col items-center mb-8 text-center">
            <Award className="text-cyan-400 mb-2" size={40} />
            <h1 className="text-3xl font-bold tracking-tight text-gradient">FinAuto</h1>
            <p className="text-gray-400 text-sm mt-1">Autonomous Valuation & Equity Research</p>
          </div>

          <h2 className="text-xl font-bold mb-4 text-gray-200">
            {isRegister ? "Create Analyst Account" : "Access Platform"}
          </h2>

          {authError && (
            <div className="bg-red-950/40 border border-red-900/60 p-3 rounded-lg mb-4 text-red-400 text-xs">
              {authError}
            </div>
          )}

          <form onSubmit={handleAuth} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Email Address</label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="analyst@firm.com"
                className="form-input"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Password</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="form-input"
              />
            </div>

            <button type="submit" disabled={authLoading} className="btn-primary w-full mt-2 flex items-center justify-center gap-2">
              {authLoading ? (
                <div className="spinner" style={{ width: "16px", height: "16px" }} />
              ) : isRegister ? (
                <>
                  <UserPlus size={16} />
                  Register
                </>
              ) : (
                <>
                  <LogIn size={16} />
                  Authenticate
                </>
              )}
            </button>
          </form>

          <div className="mt-6 text-center text-xs text-gray-500">
            {isRegister ? (
              <p>
                Already have an account?{" "}
                <button onClick={() => setIsRegister(false)} className="text-cyan-400 font-semibold hover:underline">
                  Sign in
                </button>
              </p>
            ) : (
              <p>
                New analyst?{" "}
                <button onClick={() => setIsRegister(true)} className="text-cyan-400 font-semibold hover:underline">
                  Create an account
                </button>
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  const stepsList = [
    "1. Ingestion",
    "2. Competitors",
    "3. Spreadsheet",
    "4. Read-back",
    "5. Equity Report"
  ];

  return (
    <div className="min-h-screen flex flex-col relative">
      {/* Background decoration */}
      <div className="glowing-bg" style={{ top: "0", left: "20%" }} />

      {/* Header bar */}
      <header className="glass-panel mx-4 mt-4 px-6 py-4 flex items-center justify-between border-white/5 relative z-20">
        <div className="flex items-center gap-3">
          <Award className="text-cyan-400" size={24} />
          <div>
            <span className="font-bold tracking-tight text-gradient text-lg">FinAuto SaaS</span>
            <span className="text-xs text-gray-500 font-mono ml-2">v0.1.0</span>
          </div>
        </div>

        <button onClick={logout} className="flex items-center gap-2 py-1.5 px-3 rounded-lg text-xs font-semibold text-gray-400 bg-white/5 border border-white/5 hover:text-red-400 hover:bg-red-500/10 transition-all">
          <LogOut size={14} />
          Sign Out
        </button>
      </header>

      {/* Shared ticker + free step navigation */}
      <div className="max-w-7xl w-full mx-auto px-4 mt-8">
        <div className="glass-panel p-4 mb-4 flex flex-wrap items-center gap-3">
          <label className="text-xs font-semibold uppercase tracking-wider text-cyan-400">Ticker</label>
          <input
            type="text"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="e.g. BIMAS.IS"
            className="form-input"
            style={{ maxWidth: "200px" }}
          />
          <span className="text-xs text-gray-500">
            Shared by every step. Click any step below to jump — e.g. go straight to Read‑back if you already have an edited Excel.
          </span>
        </div>

        <div className="glass-panel p-4 flex justify-between items-center overflow-x-auto gap-4">
          {stepsList.map((label, idx) => {
            const stepNum = idx + 1;
            const isCompleted = stepNum < step;
            const isActive = stepNum === step;
            return (
              <Fragment key={label}>
                <button
                  type="button"
                  onClick={() => setStep(stepNum)}
                  title={`Go to ${label}`}
                  className="flex items-center gap-2 shrink-0 cursor-pointer bg-transparent border-0 p-0"
                >
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm border transition-all ${
                    isActive
                      ? "bg-cyan-500/20 border-cyan-400 text-cyan-300 shadow-[0_0_12px_rgba(6,182,212,0.3)]"
                      : isCompleted
                        ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-400"
                        : "bg-white/5 border-white/10 text-gray-400 hover:border-cyan-400/50 hover:text-cyan-300"
                  }`}>
                    {stepNum}
                  </div>
                  <span className={`text-xs font-semibold uppercase tracking-wider ${
                    isActive ? "text-cyan-300" : isCompleted ? "text-emerald-400" : "text-gray-500"
                  }`}>
                    {label.split(". ")[1]}
                  </span>
                </button>
                {idx < stepsList.length - 1 && <ArrowRight size={14} className="text-gray-600 mx-2 shrink-0" />}
              </Fragment>
            );
          })}
        </div>
      </div>

      {/* Main wizard workspace */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 my-8 relative z-10">
        {step === 1 && (
          <Step1Upload
            token={token}
            ticker={ticker}
            setTicker={setTicker}
            nextStep={nextStep}
            prevStep={prevStep}
            jobId={jobId}
            setJobId={setJobId}
          />
        )}
        {step === 2 && (
          <Step2Peers
            token={token}
            ticker={ticker}
            setTicker={setTicker}
            nextStep={nextStep}
            prevStep={prevStep}
            jobId={jobId}
            setJobId={setJobId}
          />
        )}
        {step === 3 && (
          <Step3Download
            token={token}
            ticker={ticker}
            setTicker={setTicker}
            nextStep={nextStep}
            prevStep={prevStep}
            jobId={jobId}
            setJobId={setJobId}
          />
        )}
        {step === 4 && (
          <Step4UploadXlsx
            token={token}
            ticker={ticker}
            setTicker={setTicker}
            nextStep={nextStep}
            prevStep={prevStep}
            jobId={jobId}
            setJobId={setJobId}
          />
        )}
        {step === 5 && (
          <Step5Report
            token={token}
            ticker={ticker}
            setTicker={setTicker}
            nextStep={nextStep}
            prevStep={prevStep}
            jobId={jobId}
            setJobId={setJobId}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="text-center py-6 text-xs text-gray-600 relative z-10">
        &copy; {new Date().getFullYear()} FinAuto. All rights reserved. Grounded Financial Intelligence.
      </footer>
    </div>
  );
}

export default App;
