import { useEffect, useRef } from "react";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function markdownToHtml(markdownText) {
  return escapeHtml(markdownText)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>")
    .replace(/\n/g, "<br />");
}

export default function AskMapChat({
  assistantInput,
  assistantMessages,
  assistantLoading,
  scrollSignal,
  onAssistantInputChange,
  onAssistantSubmit,
}) {
  const messagesContainerRef = useRef(null);

  useEffect(() => {
    if (!messagesContainerRef.current) return;
    messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
  }, [assistantMessages, assistantLoading, scrollSignal]);

  return (
    <div
      style={{
        position: "absolute",
        left: 16,
        bottom: 16,
        width: 360,
        maxHeight: "46vh",
        background: "white",
        borderRadius: 10,
        boxShadow: "0 8px 24px rgba(15, 23, 42, 0.16)",
        padding: 12,
        display: "grid",
        gap: 8,
        zIndex: 2100,
      }}
    >
      <div style={{ fontWeight: 700, fontSize: 13 }}>Ask the map</div>
      <div
        ref={messagesContainerRef}
        style={{
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          padding: 8,
          minHeight: 120,
          maxHeight: "28vh",
          overflowY: "auto",
          display: "grid",
          gap: 8,
          background: "#f8fafc",
        }}
      >
        {assistantMessages.length === 0 ? (
          <div style={{ color: "#64748b", fontSize: 12 }}>
            Ask for a county comparison and the map will move/highlight automatically.
          </div>
        ) : (
          assistantMessages.map((message, index) => (
            <div
              key={`assistant-message-${index}`}
              style={{
                justifySelf: message.role === "user" ? "end" : "start",
                maxWidth: "95%",
                background: message.role === "user" ? "#dbeafe" : "white",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                padding: "8px 10px",
                fontSize: 12,
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: 4 }}>
                {message.role === "user" ? "You" : "Assistant"}
              </div>
              {message.role === "assistant" ? (
                <div
                  style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}
                  dangerouslySetInnerHTML={{ __html: markdownToHtml(message.text) }}
                />
              ) : (
                <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}>
                  {message.text}
                </div>
              )}
            </div>
          ))
        )}

        {assistantLoading ? (
          <div style={{ color: "#64748b", fontSize: 12 }}>Thinking...</div>
        ) : null}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (typeof onAssistantSubmit === "function") {
            onAssistantSubmit();
          }
        }}
        style={{ display: "grid", gap: 8 }}
      >
        <input
          type="text"
          placeholder="e.g., What is arthritis in Fulton County GA?"
          value={assistantInput}
          onChange={(event) => onAssistantInputChange(event.target.value)}
          disabled={assistantLoading}
          style={{
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid #cbd5e1",
            fontSize: 12,
          }}
        />
        <button
          type="submit"
          disabled={assistantLoading || assistantInput.trim().length === 0}
          style={{
            padding: "8px 10px",
            borderRadius: 8,
            border: "1px solid #1d4ed8",
            background: assistantLoading ? "#93c5fd" : "#2563eb",
            color: "white",
            cursor: assistantLoading ? "wait" : "pointer",
            fontWeight: 700,
            fontSize: 12,
          }}
        >
          {assistantLoading ? "Asking..." : "Ask"}
        </button>
      </form>
    </div>
  );
}
