const conversation = document.querySelector("#conversation");
const welcome = document.querySelector("#welcome");
const composer = document.querySelector("#composer");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");
const statusDot = document.querySelector("#status-dot");
const statusText = document.querySelector("#status-text");

let messages = [];
let busy = false;

const scrollToLatest = () => {
  conversation.scrollTop = conversation.scrollHeight;
};

const setBusy = (value) => {
  busy = value;
  input.disabled = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "Sending" : "Send";
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

      if (answer) {
        assistant.bubble.classList.remove("thinking");
        assistant.bubble.textContent = answer;
      }
      scrollToLatest();
    });

    if (!answer) {
      answer = "Sorry, I could not produce an answer. Please try again.";
      assistant.bubble.classList.remove("thinking");
      assistant.bubble.textContent = answer;
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
    input.focus();
    scrollToLatest();
  }
};

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
