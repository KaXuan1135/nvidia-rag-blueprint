const conversation = document.querySelector("#conversation");
const welcome = document.querySelector("#welcome");
const composer = document.querySelector("#composer");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");
const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");
const chatPanel = document.querySelector("#chat-panel");
const chatLauncher = document.querySelector("#chat-launcher");
const closeChatButton = document.querySelector("#close-chat");

let messages = [];
let busy = false;

const openChat = () => {
  chatPanel.hidden = false;
  chatLauncher.hidden = true;
  chatLauncher.setAttribute("aria-expanded", "true");
  input.focus();
  scrollToLatest();
};

const closeChat = () => {
  chatPanel.hidden = true;
  chatLauncher.hidden = false;
  chatLauncher.setAttribute("aria-expanded", "false");
  chatLauncher.focus();
};

const scrollToLatest = () => {
  conversation.scrollTop = conversation.scrollHeight;
};

const setBusy = (value) => {
  busy = value;
  input.disabled = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "Sending" : "Send";
};

const escapeHtml = (value) =>
  value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const renderInlineMarkdown = (value) => {
  const codeSpans = [];
  let html = escapeHtml(value).replace(/\`([^\`\n]+)\`/g, (_, code) => {
    const token = `@@CODE_SPAN_${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });

  html = html
    .replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    )
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");

  return html.replace(/@@CODE_SPAN_(\d+)@@/g, (_, index) => codeSpans[Number(index)]);
};

const splitTableRow = (line) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());

const isTableSeparator = (line) => {
  const cells = splitTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
};

const isBlockStart = (line) =>
  /^\s*(?:#{1,4}\s+|[-*+]\s+|\d+\.\s+|>\s?|\`\`\`|---+$)/.test(line);

const renderMarkdown = (content) => {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*\`\`\`([\w-]*)\s*$/);
    if (fence) {
      const code = [];
      index += 1;
      while (index < lines.length && !/^\s*\`\`\`\s*$/.test(lines[index])) {
        code.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const language = fence[1]
        ? ` class="language-${escapeHtml(fence[1])}"`
        : "";
      blocks.push(`<pre><code${language}>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    if (
      index + 1 < lines.length &&
      line.includes("|") &&
      isTableSeparator(lines[index + 1])
    ) {
      const headers = splitTableRow(line);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      const headerHtml = headers
        .map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`)
        .join("");
      const bodyHtml = rows
        .map(
          (row) =>
            `<tr>${headers
              .map((_, cellIndex) => `<td>${renderInlineMarkdown(row[cellIndex] ?? "")}</td>`)
              .join("")}</tr>`
        )
        .join("");
      blocks.push(`<table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table>`);
      continue;
    }

    const heading = line.match(/^\s*(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 1, 5);
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^\s*---+\s*$/.test(line)) {
      blocks.push("<hr>");
      index += 1;
      continue;
    }

    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unordered) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(`<li>${renderInlineMarkdown(item[1])}</li>`);
        index += 1;
      }
      blocks.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (ordered) {
      const items = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*\d+\.\s+(.+)$/);
        if (!item) break;
        items.push(`<li>${renderInlineMarkdown(item[1])}</li>`);
        index += 1;
      }
      blocks.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    if (/^\s*>/.test(line)) {
      const quote = [];
      while (index < lines.length) {
        const quotedLine = lines[index].match(/^\s*>\s?(.*)$/);
        if (!quotedLine) break;
        quote.push(quotedLine[1]);
        index += 1;
      }
      blocks.push(`<blockquote>${renderInlineMarkdown(quote.join("\n")).replaceAll("\n", "<br>")}</blockquote>`);
      continue;
    }

    const paragraph = [line.trim()];
    index += 1;
    while (
      index < lines.length &&
      lines[index].trim() &&
      !isBlockStart(lines[index]) &&
      !(
        index + 1 < lines.length &&
        lines[index].includes("|") &&
        isTableSeparator(lines[index + 1])
      )
    ) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
    blocks.push(
      `<p>${renderInlineMarkdown(paragraph.join("\n")).replaceAll("\n", "<br>")}</p>`
    );
  }

  return blocks.join("");
};

const renderAssistantAnswer = (bubble, content) => {
  bubble.innerHTML = renderMarkdown(content);
};

const addMessage = (role, content = "") => {
  welcome.hidden = true;
  const row = document.createElement("article");
  row.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  row.appendChild(bubble);
  conversation.appendChild(row);
  scrollToLatest();
  return { row, bubble };
};

const extractSources = (payload) => {
  const results =
    payload.citations?.results ??
    payload.sources?.results ??
    payload.choices?.[0]?.message?.citations ??
    payload.choices?.[0]?.message?.sources ??
    [];

  if (!Array.isArray(results)) return [];
  return results
    .map((item) => item.document_name || item.source || item.title)
    .filter(Boolean);
};

const appendSources = (row, sources) => {
  const unique = [...new Set(sources)];
  if (!unique.length) return;
  const sourceLine = document.createElement("div");
  sourceLine.className = "sources";
  sourceLine.textContent = `Sources: ${unique.join(", ")}`;
  row.querySelector(".bubble").appendChild(sourceLine);
};

const parseStream = async (response, onChunk) => {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed with status ${response.status}`);
  }
  if (!response.body) throw new Error("The server returned an empty response.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") return;
      onChunk(JSON.parse(data));
    }
  }
};

const sendMessage = async (text) => {
  const userMessage = { role: "user", content: text };
  messages.push(userMessage);
  addMessage("user", text);

  const assistant = addMessage("assistant", "Thinking...");
  assistant.bubble.classList.add("thinking");
  let answer = "";
  let sources = [];
  setBusy(true);

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages,
        use_knowledge_base: true,
        enable_citations: true,
        enable_reranker: true,
        agentic: false
      })
    });

    await parseStream(response, (payload) => {
      const choice = payload.choices?.[0];
      const delta = choice?.delta ?? {};
      const eventType =
        delta.event_type ?? choice?.message?.event_type ?? payload.event_type;
      const content = typeof delta.content === "string" ? delta.content : "";

      if (!eventType || eventType === "final_answer" || eventType === "error") {
        answer += content;
      }
      sources = [...sources, ...extractSources(payload)];

      const visibleAnswer = answer.trimStart();
      if (visibleAnswer) {
        assistant.bubble.classList.remove("thinking");
        renderAssistantAnswer(assistant.bubble, visibleAnswer);
      }
      scrollToLatest();
    });

    answer = answer.trim();
    if (!answer) {
      answer = "Sorry, I could not produce an answer. Please try again.";
      assistant.bubble.classList.remove("thinking");
      assistant.bubble.textContent = answer;
    } else {
      renderAssistantAnswer(assistant.bubble, answer);
    }
    appendSources(assistant.row, sources);
    messages.push({ role: "assistant", content: answer });
  } catch (error) {
    messages.pop();
    assistant.bubble.classList.remove("thinking");
    assistant.bubble.textContent =
      "We could not reach customer care just now. Please try again shortly.";
    console.error(error);
  } finally {
    setBusy(false);
    if (!chatPanel.hidden) input.focus();
    scrollToLatest();
  }
};

chatLauncher.addEventListener("click", openChat);
closeChatButton.addEventListener("click", closeChat);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !chatPanel.hidden) closeChat();
});

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  input.style.height = "auto";
  sendMessage(text);
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

newChatButton.addEventListener("click", () => {
  if (busy) return;
  messages = [];
  conversation.querySelectorAll(".message").forEach((node) => node.remove());
  welcome.hidden = false;
  input.focus();
});

fetch("/api/health")
  .then((response) => {
    if (!response.ok) throw new Error("offline");
    statusDot.classList.add("online");
    statusText.textContent = "Online";
  })
  .catch(() => {
    statusDot.classList.add("offline");
    statusText.textContent = "Unavailable";
  });
