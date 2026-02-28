import { useEffect, useRef, useState } from "react";

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function parseInlineMarkdown(text) {
  const codeTokens = [];
  let html = escapeHtml(text);

  html = html.replace(/`([^`]+)`/g, (_, codeText) => {
    const token = `__CODE_TOKEN_${codeTokens.length}__`;
    codeTokens.push(`<code>${codeText}</code>`);
    return token;
  });

  html = html.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (_, label, href) => `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
  );
  html = html.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");
  html = html.replace(/(^|[\s(])_([^_\n]+)_(?=[\s).,!?:;]|$)/g, "$1<em>$2</em>");

  codeTokens.forEach((tokenHtml, index) => {
    html = html.replace(`__CODE_TOKEN_${index}__`, tokenHtml);
  });

  return html.replace(/\n/g, "<br />");
}

function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line);
}

function parseTableRow(line) {
  let normalized = line.trim();
  if (normalized.startsWith("|")) normalized = normalized.slice(1);
  if (normalized.endsWith("|")) normalized = normalized.slice(0, -1);
  return normalized.split("|").map((cell) => cell.trim());
}

function markdownToHtml(markdownText) {
  const source = String(markdownText ?? "").replace(/\r\n?/g, "\n");
  const lines = source.split("\n");
  const blocks = [];
  let index = 0;

  const isUnorderedList = (line) => /^\s*[-*+]\s+/.test(line);
  const isOrderedList = (line) => /^\s*\d+\.\s+/.test(line);
  const isHeading = (line) => /^\s{0,3}#{1,6}\s+/.test(line);
  const isBlockquote = (line) => /^\s*>\s?/.test(line);
  const isHorizontalRule = (line) => /^\s*(\*{3,}|-{3,}|_{3,})\s*$/.test(line);
  const isFence = (line) => /^\s*```/.test(line);

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (isFence(line)) {
      const language = trimmed.slice(3).trim();
      index += 1;
      const codeLines = [];
      while (index < lines.length && !isFence(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length && isFence(lines[index])) {
        index += 1;
      }
      const langClass = language ? ` class="language-${escapeHtml(language)}"` : "";
      blocks.push(`<pre><code${langClass}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
      continue;
    }

    if (isHeading(line)) {
      const match = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
      if (match) {
        const level = match[1].length;
        blocks.push(`<h${level}>${parseInlineMarkdown(match[2].trim())}</h${level}>`);
      }
      index += 1;
      continue;
    }

    if (isHorizontalRule(line)) {
      blocks.push("<hr />");
      index += 1;
      continue;
    }

    if (isBlockquote(line)) {
      const quoteLines = [];
      while (index < lines.length && isBlockquote(lines[index])) {
        quoteLines.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push(`<blockquote>${parseInlineMarkdown(quoteLines.join("\n"))}</blockquote>`);
      continue;
    }

    if (
      line.includes("|")
      && index + 1 < lines.length
      && isTableSeparator(lines[index + 1])
    ) {
      const headerCells = parseTableRow(line);
      index += 2; // skip header + separator
      const bodyRows = [];
      while (index < lines.length && lines[index].includes("|")) {
        bodyRows.push(parseTableRow(lines[index]));
        index += 1;
      }
      const headHtml = headerCells
        .map((cell) => `<th>${parseInlineMarkdown(cell)}</th>`)
        .join("");
      const bodyHtml = bodyRows
        .map(
          (row) => `<tr>${row.map((cell) => `<td>${parseInlineMarkdown(cell)}</td>`).join("")}</tr>`
        )
        .join("");
      blocks.push(`<table><thead><tr>${headHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`);
      continue;
    }

    if (isUnorderedList(line)) {
      const items = [];
      while (index < lines.length && isUnorderedList(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*+]\s+/, ""));
        index += 1;
      }
      blocks.push(`<ul>${items.map((item) => `<li>${parseInlineMarkdown(item)}</li>`).join("")}</ul>`);
      continue;
    }

    if (isOrderedList(line)) {
      const items = [];
      while (index < lines.length && isOrderedList(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(`<ol>${items.map((item) => `<li>${parseInlineMarkdown(item)}</li>`).join("")}</ol>`);
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (index < lines.length) {
      const nextLine = lines[index];
      const nextTrimmed = nextLine.trim();
      if (
        !nextTrimmed
        || isFence(nextLine)
        || isHeading(nextLine)
        || isHorizontalRule(nextLine)
        || isBlockquote(nextLine)
        || isUnorderedList(nextLine)
        || isOrderedList(nextLine)
        || (
          nextLine.includes("|")
          && index + 1 < lines.length
          && isTableSeparator(lines[index + 1])
        )
      ) {
        break;
      }
      paragraphLines.push(nextLine);
      index += 1;
    }
    blocks.push(`<p>${parseInlineMarkdown(paragraphLines.join("\n"))}</p>`);
  }

  return blocks.join("");
}

export default function AskMapChat({
  assistantInput,
  assistantMessages,
  assistantLoading,
  scrollSignal,
  compactLayout = false,
  onAssistantInputChange,
  onAssistantSubmit,
  onOpenProfile,
}) {
  const messagesContainerRef = useRef(null);
  const [isMinimized, setIsMinimized] = useState(false);
  const panelToggleButtonStyle = {
    position: "absolute",
    top: 8,
    right: 8,
    width: 24,
    height: 24,
    borderRadius: 6,
    border: "1px solid #cbd5e1",
    background: "#ffffff",
    color: "#334155",
    fontWeight: 700,
    cursor: "pointer",
    lineHeight: "20px",
    textAlign: "center",
    padding: 0,
  };

  useEffect(() => {
    if (!messagesContainerRef.current) return;
    messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
  }, [assistantMessages, assistantLoading, scrollSignal]);

  return (
    <div
      style={{
        position: "absolute",
        left: 16,
        right: compactLayout ? 16 : "auto",
        bottom: compactLayout ? 92 : 16,
        width: compactLayout ? "auto" : 360,
        maxHeight: isMinimized ? "none" : (compactLayout ? "34vh" : "46vh"),
        background: "white",
        borderRadius: 10,
        boxShadow: "0 8px 24px rgba(15, 23, 42, 0.16)",
        padding: 12,
        display: "grid",
        gap: 8,
        zIndex: 2100,
      }}
    >
      <button
        type="button"
        aria-label={isMinimized ? "Expand Ask the map" : "Minimize Ask the map"}
        onClick={() => setIsMinimized((current) => !current)}
        style={panelToggleButtonStyle}
      >
        {isMinimized ? "+" : "\u2212"}
      </button>
      <div style={{ fontWeight: 700, fontSize: 13, paddingRight: 30 }}>Ask the map</div>
      {!isMinimized ? (
        <>
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
                <>
                  <div
                    style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}
                    dangerouslySetInnerHTML={{ __html: markdownToHtml(message.text) }}
                  />
                  {message.profileId ? (
                    <button
                      type="button"
                      onClick={() => {
                        if (typeof onOpenProfile === "function") {
                          onOpenProfile(message.profileId);
                        }
                      }}
                      style={{
                        marginTop: 8,
                        padding: "6px 8px",
                        borderRadius: 6,
                        border: "1px solid #1d4ed8",
                        background: "#eff6ff",
                        color: "#1e40af",
                        fontWeight: 600,
                        fontSize: 11,
                        cursor: "pointer",
                      }}
                    >
                      Open full profile
                    </button>
                  ) : null}
                </>
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
        </>
      ) : null}
    </div>
  );
}
