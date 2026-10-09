export type InlineToken = { kind: "text" | "code" | "link"; value: string; label?: string };

function linkLabel(value: string): string {
  const url = new URL(value);
  const parts = url.pathname.split("/").filter(Boolean);
  if (url.hostname === "github.com" && parts.length >= 4) {
    if (parts[2] === "pull") return `${parts[1]} #${parts[3]}`;
    if (parts[2] === "commit") return `${parts[1]} · ${parts[3].slice(0, 8)}`;
    if (parts[2] === "actions" && parts[3] === "runs" && parts[4]) return `${parts[1]} · Run ${parts[4]}`;
  }
  return url.hostname + (url.pathname === "/" ? "" : url.pathname);
}

export function inlineTokens(value: string): InlineToken[] {
  // 只识别明确的技术写法；普通文本交给 React 转义，不执行 HTML 或 Markdown。
  const pattern = /`([^`\n]+)`|https?:\/\/[^\s<>"`，。；：！？（）【】]+|\b[0-9a-f]{40}\b|\b[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)+(?:=-?[\w.]+)?|\b[A-Za-z_][\w]*=-?[\w.]+|\b[A-Z][A-Z_]{3,}\b/g;
  const tokens: InlineToken[] = [];
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const start = match.index!;
    if (start > cursor) tokens.push({ kind: "text", value: value.slice(cursor, start) });
    let raw = match[0];
    if (/^https?:\/\//.test(raw)) {
      raw = raw.replace(/[.,;:!?]+$/, "");
      // 保留 URL 内成对括号，仅移除正文包裹链接的右括号。
      for (const [left, right] of [["(", ")"], ["[", "]"]]) {
        while (raw.endsWith(right) && raw.split(right).length > raw.split(left).length) raw = raw.slice(0, -1);
      }
      try {
        tokens.push({ kind: "link", value: raw, label: linkLabel(raw) });
      } catch {
        tokens.push({ kind: "text", value: raw });
      }
    } else {
      tokens.push({ kind: "code", value: match[1] ?? raw });
    }
    cursor = start + raw.length;
  }
  if (cursor < value.length) tokens.push({ kind: "text", value: value.slice(cursor) });
  return tokens;
}
