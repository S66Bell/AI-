"use strict";

// ── Tiny state + helpers ───────────────────────────────────────────────
const TOKEN_KEY = "jarvis_token";
let token = localStorage.getItem(TOKEN_KEY) || "";
let sending = false;

const $ = (id) => document.getElementById(id);
const messagesEl = $("messages");

function authHeaders(extra) {
  const h = Object.assign({ "Content-Type": "application/json" }, extra || {});
  if (token) h["X-Jarvis-Token"] = token;
  return h;
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text || "";
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  scrollToBottom();
  return bubble;
}

function addStatus(text) {
  const el = document.createElement("div");
  el.className = "status-chip";
  el.textContent = `· ${text}`;
  messagesEl.appendChild(el);
  scrollToBottom();
}

function addError(text) {
  const el = document.createElement("div");
  el.className = "error-line";
  el.textContent = `⚠ ${text}`;
  messagesEl.appendChild(el);
  scrollToBottom();
}

// ── Server info / banner ───────────────────────────────────────────────
async function loadInfo() {
  try {
    const res = await fetch("/api/info", { headers: authHeaders() });
    if (res.status === 401) {
      $("backend-info").textContent = "token required — open Settings";
      return;
    }
    const info = await res.json();
    $("assistant-name").textContent = info.assistant_name;
    $("backend-info").textContent = info.backend;
    document.title = info.assistant_name;
  } catch (e) {
    $("backend-info").textContent = "offline — is the server running?";
  }
}

// ── Confirmation dialog ────────────────────────────────────────────────
function askConfirm(id, question) {
  return new Promise((resolve) => {
    const overlay = $("confirm-overlay");
    $("confirm-text").textContent = question;
    overlay.classList.remove("hidden");
    const cleanup = () => {
      overlay.classList.add("hidden");
      $("confirm-approve").onclick = null;
      $("confirm-deny").onclick = null;
    };
    const answer = async (approved) => {
      cleanup();
      try {
        await fetch("/api/confirm", {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({ id, approved }),
        });
      } catch (e) {
        /* stream will error out on its own */
      }
      resolve();
    };
    $("confirm-approve").onclick = () => answer(true);
    $("confirm-deny").onclick = () => answer(false);
  });
}

// ── Streaming chat ─────────────────────────────────────────────────────
async function sendMessage(text) {
  if (sending) return;
  sending = true;
  $("send").disabled = true;

  addMessage("user", text);
  let bubble = null; // created lazily on first text chunk

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ message: text }),
    });
    if (res.status === 401) {
      addError("Access denied. Set your token in Settings.");
      return;
    }
    if (!res.ok || !res.body) {
      addError(`Server error (${res.status}).`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        let evt;
        try {
          evt = JSON.parse(line);
        } catch (e) {
          continue;
        }
        await handleEvent(evt, () => {
          if (!bubble) {
            bubble = addMessage("assistant", "");
            bubble.classList.add("streaming");
          }
          return bubble;
        });
      }
    }
  } catch (e) {
    addError("Connection lost.");
  } finally {
    if (bubble) bubble.classList.remove("streaming");
    sending = false;
    $("send").disabled = false;
    scrollToBottom();
  }
}

async function handleEvent(evt, getBubble) {
  switch (evt.type) {
    case "text": {
      const b = getBubble();
      b.textContent += evt.data;
      scrollToBottom();
      break;
    }
    case "status":
      addStatus(evt.data);
      break;
    case "thinking": {
      let t = messagesEl.querySelector(".thinking:last-of-type");
      const last = messagesEl.lastElementChild;
      if (!t || !last || !last.classList.contains("thinking")) {
        t = document.createElement("div");
        t.className = "thinking";
        messagesEl.appendChild(t);
      }
      t.textContent += evt.data;
      scrollToBottom();
      break;
    }
    case "confirm":
      await askConfirm(evt.id, evt.data);
      break;
    case "error":
      addError(evt.data);
      break;
    case "done":
      break;
  }
}

// ── Menu actions ───────────────────────────────────────────────────────
async function apiPost(path) {
  const res = await fetch(path, { method: "POST", headers: authHeaders() });
  return res.json().catch(() => ({}));
}

async function handleMenu(action) {
  $("menu").classList.add("hidden");
  switch (action) {
    case "reset":
      await apiPost("/api/reset");
      addStatus("conversation context cleared");
      break;
    case "memory": {
      const res = await fetch("/api/memory", { headers: authHeaders() });
      const data = await res.json().catch(() => ({ facts: [] }));
      const facts = (data.facts || []).map((f) => `• ${f.fact}`).join("\n");
      addMessage("assistant", facts || "Nothing remembered yet.");
      break;
    }
    case "thinking": {
      const data = await apiPost("/api/thinking");
      addStatus(`reasoning display ${data.show_thinking ? "on" : "off"}`);
      break;
    }
    case "clear-history": {
      const data = await apiPost("/api/clear-history");
      addStatus(data.message || "history cleared");
      break;
    }
    case "settings":
      openSettings();
      break;
  }
}

// ── Settings ───────────────────────────────────────────────────────────
function openSettings() {
  $("token-input").value = token;
  $("settings-overlay").classList.remove("hidden");
}
function closeSettings() {
  $("settings-overlay").classList.add("hidden");
}
function saveSettings() {
  token = $("token-input").value.trim();
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
  closeSettings();
  loadInfo();
}

// ── Wiring ─────────────────────────────────────────────────────────────
const input = $("input");

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}
input.addEventListener("input", autosize);

$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || sending) return;
  input.value = "";
  autosize();
  sendMessage(text);
});

// Enter sends; Shift+Enter newline (desktop). On-screen keyboards use the form.
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});

$("menu-btn").addEventListener("click", () => $("menu").classList.toggle("hidden"));
document.addEventListener("click", (e) => {
  if (!$("menu").contains(e.target) && e.target !== $("menu-btn")) {
    $("menu").classList.add("hidden");
  }
});
document.querySelectorAll(".menu-item").forEach((btn) =>
  btn.addEventListener("click", () => handleMenu(btn.dataset.action))
);

$("settings-close").addEventListener("click", closeSettings);
$("settings-save").addEventListener("click", saveSettings);

// ── PWA service worker ─────────────────────────────────────────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  });
}

loadInfo();
