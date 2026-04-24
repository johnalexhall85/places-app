import { useCallback, useEffect, useMemo, useState } from "react";
import pdoObservatoryMark from "../assets/brand/pdo-observatory-mark.png";
import { API_BASE } from "../config/apiBase";
import {
  createDemoAccessCode,
  fetchDemoAccessCodes,
  fetchDemoAccessEvents,
  updateDemoAccessCode,
} from "../demoAccess/api";

const ADMIN_SECRET_STORAGE_KEY = "chip_demo_access_admin_secret";

const EMPTY_CREATE_FORM = {
  code_label: "",
  recipient_name: "",
  recipient_email: "",
  organization: "",
  notes: "",
  max_uses: "",
  expires_at: "",
};

function formatDateTime(value) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Never";
  return date.toLocaleString();
}

function nullableText(value) {
  const text = String(value ?? "").trim();
  return text || "-";
}

function toCreatePayload(form) {
  const payload = {
    code_label: form.code_label.trim(),
    recipient_name: form.recipient_name.trim() || null,
    recipient_email: form.recipient_email.trim() || null,
    organization: form.organization.trim() || null,
    notes: form.notes.trim() || null,
  };
  if (form.max_uses) {
    payload.max_uses = Number(form.max_uses);
  }
  if (form.expires_at) {
    payload.expires_at = new Date(form.expires_at).toISOString();
  }
  return payload;
}

export default function DemoAccessAdmin() {
  const [adminSecret, setAdminSecret] = useState(() => (
    typeof window === "undefined"
      ? ""
      : window.sessionStorage.getItem(ADMIN_SECRET_STORAGE_KEY) || ""
  ));
  const [secretInput, setSecretInput] = useState(adminSecret);
  const [codes, setCodes] = useState([]);
  const [events, setEvents] = useState([]);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE_FORM);
  const [newPlaintextCode, setNewPlaintextCode] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState("");

  const hasSecret = adminSecret.trim().length > 0;

  const loadAdminData = useCallback(async (secret, { signal } = {}) => {
    if (!secret) return;
    setIsLoading(true);
    setError("");
    try {
      const [codePayload, eventPayload] = await Promise.all([
        fetchDemoAccessCodes(secret, { apiBase: API_BASE, signal }),
        fetchDemoAccessEvents(secret, { apiBase: API_BASE, signal, limit: 100 }),
      ]);
      setCodes(Array.isArray(codePayload?.items) ? codePayload.items : []);
      setEvents(Array.isArray(eventPayload?.items) ? eventPayload.items : []);
    } catch (loadError) {
      if (signal?.aborted) return;
      setError(loadError?.message || "Could not load demo access admin data.");
    } finally {
      if (!signal?.aborted) {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    if (!hasSecret) return undefined;
    const controller = new AbortController();
    loadAdminData(adminSecret, { signal: controller.signal });
    return () => controller.abort();
  }, [adminSecret, hasSecret, loadAdminData]);

  const activeCount = useMemo(
    () => codes.filter((code) => code.is_active).length,
    [codes]
  );

  const handleSecretSubmit = (event) => {
    event.preventDefault();
    const trimmed = secretInput.trim();
    setAdminSecret(trimmed);
    if (typeof window !== "undefined") {
      if (trimmed) {
        window.sessionStorage.setItem(ADMIN_SECRET_STORAGE_KEY, trimmed);
      } else {
        window.sessionStorage.removeItem(ADMIN_SECRET_STORAGE_KEY);
      }
    }
  };

  const handleCreateChange = (field, value) => {
    setCreateForm((current) => ({ ...current, [field]: value }));
  };

  const handleCreate = async (event) => {
    event.preventDefault();
    if (!createForm.code_label.trim()) return;
    setIsCreating(true);
    setError("");
    setNewPlaintextCode("");
    try {
      const payload = await createDemoAccessCode(
        toCreatePayload(createForm),
        adminSecret,
        { apiBase: API_BASE }
      );
      setNewPlaintextCode(payload?.plaintext_access_code || "");
      setCreateForm(EMPTY_CREATE_FORM);
      await loadAdminData(adminSecret);
    } catch (createError) {
      setError(createError?.message || "Could not create access code.");
    } finally {
      setIsCreating(false);
    }
  };

  const handleToggleActive = async (code) => {
    setError("");
    try {
      await updateDemoAccessCode(
        code.id,
        { is_active: !code.is_active },
        adminSecret,
        { apiBase: API_BASE }
      );
      await loadAdminData(adminSecret);
    } catch (updateError) {
      setError(updateError?.message || "Could not update access code.");
    }
  };

  return (
    <main className="demo-admin-page">
      <header className="demo-admin-header">
        <div className="demo-admin-title">
          <img src={pdoObservatoryMark} alt="" className="demo-admin-logo" />
          <div>
            <p>CHIP Demo Access</p>
            <h1>Access Code Admin</h1>
          </div>
        </div>
        <form className="demo-admin-secret-form" onSubmit={handleSecretSubmit}>
          <label htmlFor="demo-admin-secret">Admin secret</label>
          <input
            id="demo-admin-secret"
            type="password"
            value={secretInput}
            onChange={(event) => setSecretInput(event.target.value)}
            placeholder="Required"
          />
          <button type="submit">Use Secret</button>
        </form>
      </header>

      {error ? <p className="demo-admin-error">{error}</p> : null}

      <section className="demo-admin-summary" aria-live="polite">
        <div>
          <span>{codes.length}</span>
          <p>Total codes</p>
        </div>
        <div>
          <span>{activeCount}</span>
          <p>Active codes</p>
        </div>
        <div>
          <span>{events.length}</span>
          <p>Recent events</p>
        </div>
      </section>

      <section className="demo-admin-section">
        <div className="demo-admin-section-heading">
          <h2>Create Code</h2>
          {newPlaintextCode ? (
            <p className="demo-admin-new-code">
              New code: <strong>{newPlaintextCode}</strong>
            </p>
          ) : null}
        </div>
        <form className="demo-admin-create-form" onSubmit={handleCreate}>
          <label>
            Label
            <input
              value={createForm.code_label}
              onChange={(event) => handleCreateChange("code_label", event.target.value)}
              required
            />
          </label>
          <label>
            Recipient
            <input
              value={createForm.recipient_name}
              onChange={(event) => handleCreateChange("recipient_name", event.target.value)}
            />
          </label>
          <label>
            Email
            <input
              type="email"
              value={createForm.recipient_email}
              onChange={(event) => handleCreateChange("recipient_email", event.target.value)}
            />
          </label>
          <label>
            Organization
            <input
              value={createForm.organization}
              onChange={(event) => handleCreateChange("organization", event.target.value)}
            />
          </label>
          <label>
            Max uses
            <input
              type="number"
              min="1"
              value={createForm.max_uses}
              onChange={(event) => handleCreateChange("max_uses", event.target.value)}
            />
          </label>
          <label>
            Expires
            <input
              type="datetime-local"
              value={createForm.expires_at}
              onChange={(event) => handleCreateChange("expires_at", event.target.value)}
            />
          </label>
          <label className="demo-admin-wide">
            Notes
            <textarea
              value={createForm.notes}
              onChange={(event) => handleCreateChange("notes", event.target.value)}
              rows="3"
            />
          </label>
          <button type="submit" disabled={!hasSecret || isCreating}>
            {isCreating ? "Creating..." : "Create Code"}
          </button>
        </form>
      </section>

      <section className="demo-admin-section">
        <div className="demo-admin-section-heading">
          <h2>Codes</h2>
          <button type="button" onClick={() => loadAdminData(adminSecret)} disabled={!hasSecret || isLoading}>
            {isLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
        <div className="demo-admin-table-wrap">
          <table className="demo-admin-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Recipient</th>
                <th>Organization</th>
                <th>Uses</th>
                <th>Last Used</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {codes.map((code) => (
                <tr key={code.id}>
                  <td>{code.code_label}</td>
                  <td>
                    <strong>{nullableText(code.recipient_name)}</strong>
                    <span>{nullableText(code.recipient_email)}</span>
                  </td>
                  <td>{nullableText(code.organization)}</td>
                  <td>{code.current_use_count}{code.max_uses ? ` / ${code.max_uses}` : ""}</td>
                  <td>{formatDateTime(code.last_used_at)}</td>
                  <td>{code.is_active ? "Active" : "Disabled"}</td>
                  <td>
                    <button type="button" onClick={() => handleToggleActive(code)}>
                      {code.is_active ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
              {codes.length === 0 ? (
                <tr>
                  <td colSpan="7">No access codes loaded.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="demo-admin-section">
        <div className="demo-admin-section-heading">
          <h2>Recent Events</h2>
        </div>
        <div className="demo-admin-table-wrap">
          <table className="demo-admin-table demo-admin-events-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>Code</th>
                <th>Success</th>
                <th>Reason</th>
                <th>IP</th>
                <th>Path</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{formatDateTime(event.occurred_at)}</td>
                  <td>{event.event_type}</td>
                  <td>
                    <strong>{nullableText(event.code_label)}</strong>
                    <span>{nullableText(event.recipient_name || event.organization)}</span>
                  </td>
                  <td>{event.success ? "Yes" : "No"}</td>
                  <td>{nullableText(event.failure_reason)}</td>
                  <td>{nullableText(event.ip_address)}</td>
                  <td>{nullableText(event.request_path)}</td>
                </tr>
              ))}
              {events.length === 0 ? (
                <tr>
                  <td colSpan="7">No events loaded.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

