/*
 * markdown-client.js — SPA 客户端 Markdown 白名单渲染器
 *
 * 与服务端 app/api/public_render.py 同规则（ADR-7② 双层防线的服务端镜像）：
 * 先整篇 HTML 转义（任何内嵌标记失去标记语义），再把白名单语法重组为受控
 * 标签；标签名/属性由本文件字面生成。脚注 [^n] 转文末引用区锚链接。
 * 服务端版本为规则权威，两侧行为一致性由同一语法清单约束。
 */

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function safeHref(url) {
  const trimmed = String(url || "").trim();
  if (/^(https?:\/\/|\/)/i.test(trimmed)) {
    return escapeHtml(trimmed).replace(/"/g, "%22");
  }
  return "";
}

function inline(markupEscaped) {
  let out = markupEscaped;
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
    const href = safeHref(url);
    return href
      ? `<a href="${href}" target="_blank" rel="noopener noreferrer nofollow">${label}</a>`
      : label;
  });
  return out;
}

function footnoteRefs(line) {
  return line.replace(/\[\^([0-9a-zA-Z]+)\]/g,
    '<sup class="fn-ref"><a href="#fn-$1">$1</a></sup>');
}

export function renderMarkdownClient(source) {
  const lines = escapeHtml(source || "").split("\n");
  const out = [];
  const footnotes = [];
  let paragraph = [];
  let listStack = [];
  let inFence = false;
  let fenceLines = [];
  let tableBuffer = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${paragraph.map((p) => footnoteRefs(inline(p))).join("<br>")}</p>`);
      paragraph = [];
    }
  };
  const closeList = () => {
    while (listStack.length) out.push(`</${listStack.pop()}>`);
  };
  const flushTable = () => {
    if (!tableBuffer.length) return;
    const rows = tableBuffer
      .filter((ln) => !/^\|[\s:|-]+\|$/.test(ln.trim()))
      .map((ln) => ln.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
    const head = rows.length ? rows[0].map((c) => `<th>${inline(c)}</th>`).join("") : "";
    const body = rows.slice(1)
      .map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("");
    out.push(`<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`);
    tableBuffer = [];
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");

    if (inFence) {
      if (/^```\s*$/.test(line)) {
        out.push(`<pre><code>${fenceLines.join("\n")}</code></pre>`);
        inFence = false;
        fenceLines = [];
      } else {
        fenceLines.push(line);
      }
      continue;
    }
    const fence = line.match(/^```([0-9a-zA-Z+-]*)\s*$/);
    if (fence) {
      flushParagraph(); closeList(); flushTable();
      inFence = true;
      continue;
    }
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      flushParagraph(); closeList();
      tableBuffer.push(line);
      continue;
    }
    if (tableBuffer.length) flushTable();

    const footnoteDef = line.trim().match(/^\[\^([0-9a-zA-Z]+)\]:\s*(.*)$/);
    if (footnoteDef) {
      flushParagraph(); closeList();
      footnotes.push({ key: footnoteDef[1], text: footnoteDef[2] });
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${footnoteRefs(inline(heading[2]))}</h${level}>`);
      continue;
    }
    if (/^>\s?/.test(line)) {
      flushParagraph(); closeList();
      const quote = footnoteRefs(inline(line.replace(/^>\s?/, "")));
      if (out.length && out[out.length - 1].startsWith("<blockquote>")) {
        out[out.length - 1] = out[out.length - 1].slice(0, -13) + `<p>${quote}</p></blockquote>`;
      } else {
        out.push(`<blockquote><p>${quote}</p></blockquote>`);
      }
      continue;
    }
    const ul = line.match(/^[-*]\s+(.*)$/);
    const ol = line.match(/^\d+[.、]\s+(.*)$/);
    if (ul || ol) {
      flushParagraph();
      const want = ul ? "ul" : "ol";
      if (!listStack.length || listStack[listStack.length - 1] !== want) {
        closeList();
        listStack.push(want);
        out.push(`<${want}>`);
      }
      out.push(`<li>${footnoteRefs(inline((ul || ol)[1]))}</li>`);
      continue;
    }
    if (!line.trim()) {
      flushParagraph(); closeList();
      continue;
    }
    if (listStack.length) {
      out[out.length - 1] = out[out.length - 1].slice(0, -4)
        + footnoteRefs(inline(line.trim())) + "</li>";
      continue;
    }
    paragraph.push(line.trim());
  }
  flushParagraph(); closeList(); flushTable();

  if (footnotes.length) {
    const items = footnotes.map((f) =>
      `<li id="fn-${f.key}">${footnoteRefs(inline(f.text))}</li>`).join("");
    out.push(`<section class="footnotes"><ol>${items}</ol></section>`);
  }
  return out.join("\n");
}
