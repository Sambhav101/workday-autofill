// Popup logic: read the active tab, POST its URL to the Workday Autofill queue.
// Server URL + token live in chrome.storage.local (set via the gear section).

const DEFAULT_BASE = "http://localhost:8000";

// URL patterns the agent supports today (Workday) + ATS planned in issue #2.
const SUPPORTED = /(\.myworkdayjobs\.com|boards\.greenhouse\.io|jobs\.lever\.co|jobs\.ashbyhq\.com)/i;

const $ = (id) => document.getElementById(id);

let settings = { baseUrl: DEFAULT_BASE, token: "" };
let currentUrl = "";

async function loadSettings() {
  const s = await chrome.storage.local.get(["baseUrl", "token"]);
  settings.baseUrl = (s.baseUrl || DEFAULT_BASE).replace(/\/+$/, "");
  settings.token = s.token || "";
  $("baseUrl").value = settings.baseUrl;
  $("token").value = settings.token;
}

async function loadTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentUrl = (tab && tab.url) || "";
  $("url").textContent = currentUrl || "(no URL)";
  const ok = SUPPORTED.test(currentUrl);
  $("ats").textContent = ok ? "✓ Supported job page" : "Not a recognized ATS — queued anyway";
  $("ats").className = "ats " + (ok ? "ok" : "no");
  $("addBtn").disabled = !/^https?:\/\//i.test(currentUrl);
}

function setStatus(msg, cls = "") {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + cls;
}

async function addToQueue() {
  if (!currentUrl) return;
  $("addBtn").disabled = true;
  setStatus("Adding…");
  try {
    const headers = { "Content-Type": "application/json" };
    if (settings.token) headers["X-Auth-Token"] = settings.token;
    const resp = await fetch(`${settings.baseUrl}/api/queue/add`, {
      method: "POST",
      headers,
      body: JSON.stringify({ urls: [currentUrl] }),
    });
    if (resp.status === 401) {
      setStatus("Unauthorized — set the auth token in ⚙︎ settings", "err");
      return;
    }
    if (!resp.ok) {
      setStatus(`Server error (${resp.status})`, "err");
      return;
    }
    const data = await resp.json();
    const added = data.added ?? 0;
    setStatus(
      added > 0
        ? `Added ✓  (${data.total_queued} in queue)`
        : `Already queued  (${data.total_queued} in queue)`,
      "ok"
    );
    flashBadge(added > 0 ? "+1" : "•");
  } catch (e) {
    setStatus(`Can't reach server at ${settings.baseUrl}`, "err");
  } finally {
    $("addBtn").disabled = false;
  }
}

function flashBadge(text) {
  try {
    chrome.action.setBadgeBackgroundColor({ color: "#3fb950" });
    chrome.action.setBadgeText({ text });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
  } catch (e) { /* badge is best-effort */ }
}

async function saveSettings() {
  settings.baseUrl = ($("baseUrl").value.trim() || DEFAULT_BASE).replace(/\/+$/, "");
  settings.token = $("token").value.trim();
  await chrome.storage.local.set({ baseUrl: settings.baseUrl, token: settings.token });
  $("saved").textContent = "saved";
  setTimeout(() => ($("saved").textContent = ""), 1500);
}

$("addBtn").addEventListener("click", addToQueue);
$("saveBtn").addEventListener("click", saveSettings);

(async () => {
  await loadSettings();
  await loadTab();
})();
