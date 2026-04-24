import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import pdoObservatoryMark from "../assets/brand/pdo-observatory-mark.png";
import { API_BASE } from "../config/apiBase";
import { APP_NAME, PRIMARY_BRAND } from "../branding/pdoBrand";
import {
  fetchDemoAccessSession,
  logoutDemoAccess,
  validateDemoAccessCode,
} from "./api";

const DemoAccessContext = createContext({
  hasAccess: false,
  session: null,
  logout: async () => {},
  refreshSession: async () => {},
});

export function useDemoAccess() {
  return useContext(DemoAccessContext);
}

function AccessGateLoading() {
  return (
    <main className="demo-access-page">
      <section className="demo-access-panel" aria-live="polite">
        <img src={pdoObservatoryMark} alt="" className="demo-access-logo" />
        <p className="demo-access-kicker">Demo access required</p>
        <h1>Checking Access</h1>
      </section>
    </main>
  );
}

function AccessCodeScreen({ error, isSubmitting, onSubmit }) {
  const [accessCode, setAccessCode] = useState("");

  const handleSubmit = (event) => {
    event.preventDefault();
    onSubmit(accessCode);
  };

  return (
    <main className="demo-access-page">
      <section className="demo-access-panel" aria-labelledby="demo-access-title">
        <img src={pdoObservatoryMark} alt="" className="demo-access-logo" />
        <p className="demo-access-brand">{PRIMARY_BRAND}</p>
        <h1 id="demo-access-title">Enter Access Code</h1>
        <p className="demo-access-kicker">Demo access required</p>
        <form className="demo-access-form" onSubmit={handleSubmit}>
          <label htmlFor="demo-access-code">Access code</label>
          <input
            id="demo-access-code"
            type="text"
            value={accessCode}
            autoComplete="one-time-code"
            spellCheck="false"
            autoFocus
            onChange={(event) => setAccessCode(event.target.value)}
            placeholder="CHIP-XXXX-XXXX-XXXX"
            disabled={isSubmitting}
          />
          {error ? <p className="demo-access-error">{error}</p> : null}
          <button type="submit" disabled={isSubmitting || !accessCode.trim()}>
            {isSubmitting ? "Validating..." : "Continue"}
          </button>
        </form>
        <p className="demo-access-footnote">{APP_NAME}</p>
      </section>
    </main>
  );
}

export default function DemoAccessGate({ children }) {
  const [status, setStatus] = useState("checking");
  const [session, setSession] = useState(null);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const refreshSession = useCallback(async ({ signal } = {}) => {
    const payload = await fetchDemoAccessSession({ apiBase: API_BASE, signal });
    if (payload?.has_access) {
      setSession(payload);
      setStatus("granted");
      setError("");
      return payload;
    }
    setSession(null);
    setStatus("blocked");
    return payload;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refreshSession({ signal: controller.signal }).catch((sessionError) => {
      if (controller.signal.aborted) return;
      console.warn("Demo access session check failed:", sessionError);
      setSession(null);
      setStatus("blocked");
    });
    return () => controller.abort();
  }, [refreshSession]);

  const handleSubmit = useCallback(async (accessCode) => {
    const trimmedCode = accessCode.trim();
    if (!trimmedCode) return;
    setIsSubmitting(true);
    setError("");
    try {
      await validateDemoAccessCode(trimmedCode, { apiBase: API_BASE });
      await refreshSession();
    } catch (validationError) {
      setError(validationError?.message || "That access code did not work.");
      setStatus("blocked");
      setSession(null);
    } finally {
      setIsSubmitting(false);
    }
  }, [refreshSession]);

  const handleLogout = useCallback(async () => {
    try {
      await logoutDemoAccess({ apiBase: API_BASE });
    } catch (logoutError) {
      console.warn("Demo access logout failed:", logoutError);
    } finally {
      setSession(null);
      setStatus("blocked");
      setError("");
    }
  }, []);

  const contextValue = useMemo(() => ({
    hasAccess: status === "granted",
    session,
    logout: handleLogout,
    refreshSession,
  }), [handleLogout, refreshSession, session, status]);

  if (status === "checking") {
    return <AccessGateLoading />;
  }

  if (status !== "granted") {
    return (
      <AccessCodeScreen
        error={error}
        isSubmitting={isSubmitting}
        onSubmit={handleSubmit}
      />
    );
  }

  return (
    <DemoAccessContext.Provider value={contextValue}>
      {children}
    </DemoAccessContext.Provider>
  );
}

