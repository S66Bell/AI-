"use strict";

// ── Tiny state + helpers ───────────────────────────────────────────────
const TOKEN_KEY = "jarvis_token";
let token = localStorage.getItem(TOKEN_KEY) || "";
let sending = false;
let historyLoaded = false;
let speechLang = "";
let ttsEnabled = localStorage.getItem("jarvis_tts") === "1";

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
    speechLang = info.speech_lang || "";
  } catch (e) {
    $("backend-info").textContent = "offline — is the server running?";
  }
}

// ── Past conversation ──────────────────────────────────────────────────
async function loadHistory() {
  if (historyLoaded) return;
  try {
    const res = await fetch("/api/history", { headers: authHeaders() });
    if (!res.ok) return; // e.g. 401 before a token is set — retry after Save
    const data = await res.json();
    const msgs = data.messages || [];
    historyLoaded = true;
    if (!msgs.length) return;
    for (const m of msgs) addMessage(m.role, m.text);
    const divider = document.createElement("div");
    divider.className = "history-divider";
    divider.textContent = "ここから現在の会話";
    messagesEl.appendChild(divider);
    scrollToBottom();
  } catch (e) {
    /* ignore — chat still works without past history */
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
    let replyText = "";
    if (bubble) {
      bubble.classList.remove("streaming");
      replyText = bubble.textContent;
    }
    sending = false;
    $("send").disabled = false;
    scrollToBottom();
    onReplyComplete(replyText);
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
    case "speak":
      toggleSpeak();
      break;
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
  loadHistory();
}

// ── Conversation threads ────────────────────────────────────────────────
function renderMessages(list) {
  messagesEl.innerHTML = "";
  for (const m of list || []) addMessage(m.role, m.text);
  historyLoaded = true;
  scrollToBottom();
}

async function openThreads() {
  $("threads-overlay").classList.remove("hidden");
  $("thread-search").value = "";
  await loadThreadList();
}
function closeThreads() {
  $("threads-overlay").classList.add("hidden");
}

async function loadThreadList() {
  try {
    const res = await fetch("/api/threads", { headers: authHeaders() });
    if (!res.ok) return;
    const data = await res.json();
    renderThreadRows(data.threads || [], data.current);
  } catch (e) {
    /* ignore */
  }
}

function threadRow(opts) {
  const row = document.createElement("div");
  row.className = "thread-row" + (opts.current ? " current" : "");
  const main = document.createElement("div");
  main.className = "t-main";
  const title = document.createElement("div");
  title.className = "t-title";
  title.textContent = opts.title || "新しい会話";
  const prev = document.createElement("div");
  prev.className = "t-preview";
  prev.textContent = opts.preview || "";
  main.appendChild(title);
  main.appendChild(prev);
  row.appendChild(main);
  if (opts.onDelete) {
    const del = document.createElement("button");
    del.className = "t-del";
    del.textContent = "🗑";
    del.setAttribute("aria-label", "削除");
    del.addEventListener("click", (ev) => {
      ev.stopPropagation();
      opts.onDelete();
    });
    row.appendChild(del);
  }
  row.addEventListener("click", opts.onOpen);
  return row;
}

function renderThreadRows(threads, current) {
  const list = $("thread-list");
  list.innerHTML = "";
  if (!threads.length) {
    const e = document.createElement("div");
    e.className = "thread-empty";
    e.textContent = "会話がありません";
    list.appendChild(e);
    return;
  }
  for (const t of threads) {
    list.appendChild(
      threadRow({
        title: t.title,
        preview: t.preview,
        current: t.id === current,
        onOpen: () => switchThread(t.id),
        onDelete: () => deleteThread(t.id),
      })
    );
  }
}

async function switchThread(id) {
  try {
    const res = await fetch("/api/threads/switch", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ id }),
    });
    if (!res.ok) return;
    const data = await res.json();
    renderMessages(data.messages);
    closeThreads();
  } catch (e) {
    /* ignore */
  }
}

async function newThread() {
  try {
    const res = await fetch("/api/threads/new", {
      method: "POST",
      headers: authHeaders(),
    });
    if (!res.ok) return;
    renderMessages([]);
    closeThreads();
  } catch (e) {
    /* ignore */
  }
}

async function deleteThread(id) {
  try {
    const res = await fetch("/api/threads/delete", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ id }),
    });
    if (!res.ok) return;
    const data = await res.json();
    renderMessages(data.messages); // reflect whatever thread is current now
    await loadThreadList(); // refresh list, keep drawer open
  } catch (e) {
    /* ignore */
  }
}

async function searchThreads(q) {
  try {
    const res = await fetch("/api/threads/search?q=" + encodeURIComponent(q), {
      headers: authHeaders(),
    });
    if (!res.ok) return;
    const data = await res.json();
    const list = $("thread-list");
    list.innerHTML = "";
    const results = data.results || [];
    if (!results.length) {
      const e = document.createElement("div");
      e.className = "thread-empty";
      e.textContent = "一致する会話がありません";
      list.appendChild(e);
      return;
    }
    for (const r of results) {
      list.appendChild(
        threadRow({
          title: r.title,
          preview: r.snippet,
          onOpen: () => switchThread(r.thread_id),
        })
      );
    }
  } catch (e) {
    /* ignore */
  }
}

// ── Voice: mic input, read-aloud, and hands-free conversation ───────────
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let handsFree = false;
let gestureArmed = false;
let ttsBeforeHandsFree = false;
// idle | listening | thinking | speaking
let voiceState = "idle";
let intentionalStop = false; // set when WE stop recognition (vs. a silence timeout)

// ── read-aloud (TTS) ────────────────────────────────────────────────────
function updateSpeakLabel() {
  const btn = document.querySelector('.menu-item[data-action="speak"]');
  if (btn) btn.textContent = `音声読み上げ: ${ttsEnabled ? "オン" : "オフ"}`;
}

function toggleSpeak() {
  ttsEnabled = !ttsEnabled;
  localStorage.setItem("jarvis_tts", ttsEnabled ? "1" : "0");
  if (!ttsEnabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
  updateSpeakLabel();
  addStatus(`音声読み上げ ${ttsEnabled ? "オン" : "オフ"}`);
}

function speak(text, onEnd) {
  const done = typeof onEnd === "function" ? onEnd : () => {};
  if (!text || !("speechSynthesis" in window)) {
    done();
    return;
  }
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    if (speechLang) u.lang = speechLang;
    u.onend = done;
    u.onerror = done;
    window.speechSynthesis.speak(u);
  } catch (e) {
    done();
  }
}

// Called when a reply finishes streaming. In hands-free mode JARVIS speaks the
// reply, then resumes listening once it's done talking (so it doesn't hear
// itself). Otherwise it just reads aloud if that toggle is on.
function onReplyComplete(text) {
  if (handsFree) {
    voiceState = "speaking";
    setMicUI();
    speak(text, () => {
      resumeHandsFreeListening();
    });
  } else if (ttsEnabled) {
    speak(text);
  }
}

// ── speech-to-text ──────────────────────────────────────────────────────
function setMicUI() {
  const mic = $("mic");
  mic.classList.toggle("listening", voiceState === "listening");
  mic.classList.toggle("handsfree", handsFree);
}

function startRecognition() {
  if (!SpeechRec || recognition) return;
  const rec = new SpeechRec();
  recognition = rec;
  rec.lang = speechLang || navigator.language || "en-US";
  rec.interimResults = false;
  rec.continuous = handsFree;
  rec.maxAlternatives = 1;

  rec.onresult = (e) => {
    const text = (e.results[e.results.length - 1][0].transcript || "").trim();
    if (!text) return;
    if (handsFree) {
      // Pause listening while we get + speak the reply, to avoid echo.
      intentionalStop = true;
      voiceState = "thinking";
      setMicUI();
      try { rec.stop(); } catch (e) {}
    }
    input.value = text;
    autosize();
    $("composer").requestSubmit();
  };

  rec.onerror = (ev) => {
    if (ev && (ev.error === "not-allowed" || ev.error === "service-not-allowed")) {
      addError("マイクの使用が許可されていません。ブラウザの設定で許可してください。");
      stopHandsFree();
    }
  };

  rec.onend = () => {
    recognition = null;
    if (handsFree && !intentionalStop && voiceState === "listening") {
      // Ended on a silence timeout — keep the conversation open.
      setTimeout(startRecognition, 250);
    } else if (!handsFree) {
      voiceState = "idle";
    }
    intentionalStop = false;
    setMicUI();
  };

  try {
    rec.start();
  } catch (e) {
    recognition = null;
  }
}

// ── always-on listening (mic button toggle) ─────────────────────────────
function startHandsFree() {
  handsFree = true;
  ttsBeforeHandsFree = ttsEnabled;
  ttsEnabled = true; // a spoken conversation needs replies read aloud
  localStorage.setItem("jarvis_tts", "1");
  updateSpeakLabel();
  voiceState = "listening";
  setMicUI();
  addStatus("マイク オン — 常時聞き取り中です");
  startRecognition();
}

function stopHandsFree() {
  handsFree = false;
  voiceState = "idle";
  intentionalStop = true;
  if (recognition) {
    try { recognition.stop(); } catch (e) {}
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  ttsEnabled = ttsBeforeHandsFree; // back to whatever read-aloud was before
  localStorage.setItem("jarvis_tts", ttsEnabled ? "1" : "0");
  updateSpeakLabel();
  setMicUI();
  addStatus("マイク オフ — 通常のチャットに戻りました");
}

// Keep the mic on: (re)start listening, and if the browser requires a user
// gesture to access the mic, begin on the very next tap anywhere.
function resumeHandsFreeListening() {
  if (!handsFree) return;
  voiceState = "listening";
  setMicUI();
  startRecognition();
  if (!recognition) armGestureAutostart();
}

function armGestureAutostart() {
  if (gestureArmed) return;
  gestureArmed = true;
  const handler = () => {
    gestureArmed = false;
    if (handsFree && !recognition && voiceState === "listening") startRecognition();
  };
  document.addEventListener("pointerdown", handler, { once: true });
}

function initVoice() {
  updateSpeakLabel();
  // Start in normal chat mode. Tapping the mic toggles always-on listening;
  // tapping it again returns to normal chat. Recognition isn't everywhere
  // (e.g. iOS Safari), so show the mic only when supported.
  if (SpeechRec) {
    $("mic").classList.remove("hidden");
    $("mic").addEventListener("click", () => {
      if (handsFree) stopHandsFree();
      else startHandsFree();
    });
  }
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

// Threads drawer
$("threads-btn").addEventListener("click", openThreads);
$("threads-close").addEventListener("click", closeThreads);
$("thread-new").addEventListener("click", newThread);
$("threads-overlay").addEventListener("click", (e) => {
  if (e.target === $("threads-overlay")) closeThreads();
});
$("thread-search").addEventListener("input", (e) => {
  const q = e.target.value.trim();
  if (q) searchThreads(q);
  else loadThreadList();
});

// ── PWA service worker ─────────────────────────────────────────────────
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  });
}

initVoice();
loadInfo();
loadHistory();
