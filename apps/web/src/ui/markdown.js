/**
 * Lightweight Zero-dependency Markdown Formatter (`@deepseek-ai/dsh-client-ui-renderer`)
 * 100% Compatible with Windows 7 legacy browsers.
 */

export function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

export function formatMarkdown(text) {
  if (!text) return "";
  let html = escapeHtml(text);

  // Fenced Code Blocks ```lang ... ```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, function (match, lang, code) {
    const langLabel = lang ? lang.toUpperCase() : "CODE";
    return `
      <pre class="code-block-wrap">
        <div class="code-block-header">
          <span class="code-lang-tag">${langLabel}</span>
          <button class="btn-copy-code" onclick="navigator.clipboard.writeText(this.closest('.code-block-wrap').querySelector('code').textContent)">复制</button>
        </div>
        <code>${code}</code>
      </pre>
    `;
  });

  // Inline Code `...`
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Headers
  html = html.replace(/^### (.*$)/gim, "<h3>$1</h3>");
  html = html.replace(/^## (.*$)/gim, "<h2>$1</h2>");
  html = html.replace(/^# (.*$)/gim, "<h1>$1</h1>");

  // Bold & Italic
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

  // Bullet Lists
  html = html.replace(/^\s*[-*]\s+(.*$)/gim, "<li>$1</li>");

  // Paragraphs
  html = html.replace(/\n\n/g, "</p><p>");
  html = "<p>" + html + "</p>";

  return html;
}
