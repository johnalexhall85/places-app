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
  openSignal = 0,
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
    borderRadius: 999,
    border: "1px solid #BFD0E1",
    background: "#ffffff",
    color: "#3576BA",
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

  useEffect(() => {
    setIsMinimized(false);
  }, [openSignal]);

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
        borderRadius: 18,
        border: "1px solid #D7E2EE",
        boxShadow: "0 14px 32px rgba(18, 50, 71, 0.09)",
        padding: 14,
        display: "grid",
        gap: 8,
        zIndex: 2100,
      }}
    >
      <button
        type="button"
        aria-label={
          isMinimized
            ? "Expand CHIP analysis assistant"
            : "Minimize CHIP analysis assistant"
        }
        onClick={() => setIsMinimized((current) => !current)}
        style={panelToggleButtonStyle}
      >
        {isMinimized ? "+" : "\u2212"}
      </button>
      <div style={{ fontWeight: 700, fontSize: 13, paddingRight: 30, color: "#123247" }}>
        CHIP analysis assistant
      </div>
      {!isMinimized ? (
        <>
      <div
        ref={messagesContainerRef}
        style={{
          border: "1px solid #D7E2EE",
          borderRadius: 14,
          padding: 8,
          minHeight: 120,
          maxHeight: "28vh",
          overflowY: "auto",
          display: "grid",
          gap: 8,
          background: "#F7FAFD",
        }}
      >
        {assistantMessages.length === 0 ? (
          <div style={{ color: "#627A90", fontSize: 12, lineHeight: 1.5 }}>
            Ask a place-based question about the current geography. CHIP summarizes modeled and administrative signals using the active data layer and source context.
          </div>
        ) : (
          assistantMessages.map((message, index) => (
            <div
              key={`assistant-message-${index}`}
              style={{
                justifySelf: message.role === "user" ? "end" : "start",
                maxWidth: "95%",
                background: message.role === "user" ? "#F2F6FB" : "white",
                border: "1px solid #D7E2EE",
                borderRadius: 14,
                padding: "8px 10px",
                fontSize: 12,
              }}
            >
              <div style={{ fontWeight: 700, marginBottom: 4 }}>
                {message.role === "user" ? "You" : "Assistant"}
              </div>
              {message.role === "assistant" ? (
                <>
                  {message.contextSummary && typeof message.contextSummary === "object" ? (
                    <div style={{ display: "grid", gap: 6, marginBottom: message.text ? 8 : 0 }}>
                      {message.contextSummary.context_chip ? (
                        <div
                          style={{
                            justifySelf: "start",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            background: "#F2F6FB",
                            border: "1px solid #D7E2EE",
                            color: "#123247",
                            borderRadius: 999,
                            fontSize: 11,
                            lineHeight: 1.2,
                            padding: "3px 10px",
                            fontWeight: 600,
                          }}
                        >
                          Context: {String(message.contextSummary.context_chip)}
                        </div>
                      ) : null}

                      {message.contextSummary.title ? (
                        <div style={{ fontWeight: 700, color: "#123247" }}>
                          {String(message.contextSummary.title)}
                        </div>
                      ) : null}

                      {Array.isArray(message.contextSummary.stats) && message.contextSummary.stats.length > 0 ? (
                        <div style={{ display: "grid", gap: 2 }}>
                          {message.contextSummary.stats.map((entry, statIndex) => (
                            <div key={`summary-stat-${index}-${statIndex}`} style={{ color: "#1f2937" }}>
                              <strong>{String(entry?.label ?? "Stat")}:</strong>{" "}
                              {String(entry?.value ?? "Not available")}
                            </div>
                          ))}
                        </div>
                      ) : null}

                      {Array.isArray(message.contextSummary.bullets) && message.contextSummary.bullets.length > 0 ? (
                        <ul style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 2 }}>
                          {message.contextSummary.bullets.map((entry, bulletIndex) => (
                            <li key={`summary-bullet-${index}-${bulletIndex}`}>
                              {String(entry)}
                            </li>
                          ))}
                        </ul>
                      ) : null}

                      {message.contextSummary.methodology ? (
                        <div style={{ color: "#627A90", fontSize: 11 }}>
                          Methodology: {String(message.contextSummary.methodology)}
                        </div>
                      ) : null}

                      {Array.isArray(message.contextSummary.suggestedQuestions)
                      && message.contextSummary.suggestedQuestions.length > 0 ? (
                        <div style={{ display: "grid", gap: 4 }}>
                          <div style={{ fontWeight: 600, color: "#334155" }}>
                            Suggested follow-ups
                          </div>
                          <ol style={{ margin: 0, paddingLeft: 18, display: "grid", gap: 2 }}>
                            {message.contextSummary.suggestedQuestions.slice(0, 3).map((entry, followupIndex) => (
                              <li key={`summary-followup-${index}-${followupIndex}`}>
                                {String(entry)}
                              </li>
                            ))}
                          </ol>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {String(message.text ?? "").trim() ? (
                    <div
                      style={{ whiteSpace: "pre-wrap", lineHeight: 1.4 }}
                      dangerouslySetInnerHTML={{ __html: markdownToHtml(message.text) }}
                    />
                  ) : null}
                  {message.profileId ? (
                    <button
                      type="button"
                      onClick={() => {
                        if (typeof onOpenProfile === "function") {
                          onOpenProfile(message.profileId);
                        }
                      }}
                      className="chip-secondary-btn"
                      style={{
                        marginTop: 8,
                        fontSize: 11,
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
          <div style={{ color: "#627A90", fontSize: 12 }}>Reviewing the current data context...</div>
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
        <textarea
          placeholder="e.g., Summarize the main signals for Fulton County, Georgia."
          value={assistantInput}
          onChange={(event) => onAssistantInputChange(event.target.value)}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
              event.preventDefault();
              if (typeof onAssistantSubmit === "function") {
                onAssistantSubmit();
              }
            }
          }}
          disabled={assistantLoading}
          rows={3}
          aria-label="Ask the CHIP analysis assistant"
          style={{
            padding: "8px 10px",
            borderRadius: 14,
            border: "1px solid #BFD0E1",
            fontSize: 12,
            width: "100%",
            minHeight: 74,
            resize: "vertical",
            fontFamily: "inherit",
          }}
        />
        <button
          type="submit"
          disabled={assistantLoading || assistantInput.trim().length === 0}
          className="chip-primary-btn"
          style={{
            borderRadius: 999,
            padding: "8px 10px",
            fontWeight: 700,
            fontSize: 12,
          }}
        >
          {assistantLoading ? "Analyzing..." : "Ask"}
        </button>
      </form>
        </>
      ) : null}
    </div>
  );
}
