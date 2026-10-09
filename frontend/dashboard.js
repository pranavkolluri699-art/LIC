/**
 * Insura Customer Dashboard — Controller
 *
 * Architecture
 * ------------
 *  - Single-page application driven by a sidebar nav.
 *  - Each nav item shows one <section class="panel"> and hides the rest.
 *  - All API calls go through the central api() helper which injects the
 *    X-Username header automatically.
 *  - State lives in the DashboardState object — no globals scattered around.
 *  - Each panel has its own loader function: loadOverview(), loadProfile(), …
 *  - Tables support client-side sort and search where the dataset is small;
 *    chat history uses server-side pagination because it can grow large.
 *
 * Auth model
 * ----------
 *  Same as existing pages: username stored in localStorage under "username".
 *  If absent the user is redirected to login.html immediately.
 */

"use strict";

/* ==========================================================================
   Constants
   ========================================================================== */

const API_BASE = window.location.origin;

/* ==========================================================================
   Central state
   ========================================================================== */

const DashboardState = {
  username:     "",
  profile:      {},
  stats:        {},
  policies:     [],
  recommendations: [],
  notifications: [],
  documents:    [],
  chatHistory:  { total: 0, page: 1, per_page: 30, items: [] },
  chatSearch:   "",
  activePanel:  "overview",
  notifUnread:  0,
};

/* ==========================================================================
   Bootstrap — runs on DOMContentLoaded
   ========================================================================== */

document.addEventListener("DOMContentLoaded", async () => {
  // ── Auth guard ──────────────────────────────────────────────────────────
  const username = localStorage.getItem("username");
  if (!username) {
    window.location.href = "/login";
    return;
  }
  DashboardState.username = username;

  // ── Wire sidebar nav items ───────────────────────────────────────────────
  document.querySelectorAll(".nav-item[data-panel]").forEach(el => {
    el.addEventListener("click", () => navigateTo(el.dataset.panel));
  });

  // ── Wire mobile sidebar toggle ────────────────────────────────────────────
  document.getElementById("sidebarToggle")
    .addEventListener("click", openSidebar);
  document.getElementById("sidebarOverlay")
    .addEventListener("click", closeSidebar);

  // ── Wire topbar search (delegates to active panel's search) ───────────────
  document.getElementById("topbarSearch")
    .addEventListener("input", e => handleTopbarSearch(e.target.value));

  // ── Wire notification bell ────────────────────────────────────────────────
  document.getElementById("btnNotifBell")
    .addEventListener("click", () => navigateTo("notifications"));

  // ── Show username in topbar ───────────────────────────────────────────────
  document.getElementById("topbarUsername").textContent =
    _capitalize(username);

  // ── Check backend is reachable before first load ─────────────────────────
  try {
    const health = await fetch(`${API_BASE}/health`, { method: "GET" });
    if (!health.ok) throw new Error("Backend returned " + health.status);
  } catch (err) {
    _showBackendError();
    return;
  }

  // ── Initial load ─────────────────────────────────────────────────────────
  navigateTo("overview");
});

/* ==========================================================================
   Navigation
   ========================================================================== */

function navigateTo(panelName) {
  // Update sidebar active state
  document.querySelectorAll(".nav-item[data-panel]").forEach(el => {
    el.classList.toggle("active", el.dataset.panel === panelName);
  });

  // Show/hide panels
  document.querySelectorAll(".panel").forEach(p => {
    p.classList.toggle("active", p.id === `panel-${panelName}`);
  });

  DashboardState.activePanel = panelName;
  closeSidebar();

  // Load panel data
  const loaders = {
    overview:        loadOverview,
    profile:         loadProfile,
    policies:        loadPolicies,
    recommendations: loadRecommendations,
    "chat-history":  loadChatHistory,
    documents:       loadDocuments,
    notifications:   loadNotifications,
    calculators:     loadCalculators,
  };

  if (loaders[panelName]) loaders[panelName]();
}

/* ==========================================================================
   API helper
   ========================================================================== */

/**
 * Central fetch wrapper.
 * @param {string} path   - e.g. "/dashboard/stats"
 * @param {object} opts   - fetch options (method, body, etc.)
 * @returns {Promise<any>} parsed JSON
 */
async function api(path, opts = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Username":   DashboardState.username,
    ...(opts.headers || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, { ...opts, headers });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }

  return response.json();
}

/* ==========================================================================
   PANEL: Overview
   ========================================================================== */

async function loadOverview() {
  try {
    const stats = await api("/dashboard/stats");
    DashboardState.stats = stats;

    _setText("stat-total-policies",   stats.total_policies   ?? 0);
    _setText("stat-active-policies",  stats.active_policies  ?? 0);
    _setText("stat-premium-due",      `${stats.premium_due ?? 0} due soon`);
    _setText("stat-recommendations",  stats.recommendations_count ?? 0);
    _setText("stat-unread-notifs",    stats.unread_notifications  ?? 0);
    _setText("stat-chat-count",       stats.chat_count       ?? 0);

    // Update notification badge in sidebar + topbar
    _updateNotifBadge(stats.unread_notifications ?? 0);

    // Greet user
    const greeting = _greetingWord();
    _setText("overview-greeting",
      `${greeting}, ${_capitalize(stats.customer_name || DashboardState.username)}! 👋`);
    _setText("overview-sub",
      `Here's a summary of your insurance portfolio.`);

  } catch (err) {
    console.error("[Overview] Failed to load stats:", err);
    showToast("Could not load dashboard stats.", "error");
  }
}

/* ==========================================================================
   PANEL: Profile
   ========================================================================== */

async function loadProfile() {
  try {
    const profile = await api("/dashboard/profile");
    DashboardState.profile = profile;
    _renderProfile(profile);
  } catch (err) {
    console.error("[Profile] Load error:", err);
    showToast("Could not load profile.", "error");
  }
}

function _renderProfile(p) {
  // Hero section
  _setText("profile-display-name",
    p.name || _capitalize(DashboardState.username));
  _setText("profile-display-username", `@${DashboardState.username}`);

  // Form fields (read-only mode)
  _setVal("profile-name",  p.name  || "");
  _setVal("profile-age",   p.age   || "");
  _setVal("profile-phone", p.phone || "");
  _setVal("profile-email", p.email || "");

  setProfileReadOnly(true);
}

/** Toggle the profile form between read-only and edit mode. */
function setProfileReadOnly(readOnly) {
  ["profile-name", "profile-age", "profile-phone", "profile-email"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.readOnly = readOnly;
  });

  _show("btn-profile-edit",   readOnly);
  _show("btn-profile-save",  !readOnly);
  _show("btn-profile-cancel",!readOnly);
}

function profileEditMode()   { setProfileReadOnly(false); }
function profileCancelEdit() {
  _renderProfile(DashboardState.profile);
  setProfileReadOnly(true);
}

async function profileSave() {
  const payload = {
    name:  _getVal("profile-name").trim(),
    age:   _getVal("profile-age").trim(),
    phone: _getVal("profile-phone").trim(),
    email: _getVal("profile-email").trim(),
  };

  if (!payload.name) { showToast("Name cannot be empty.", "warning"); return; }

  try {
    const updated = await api("/dashboard/profile", {
      method: "PUT",
      body:   JSON.stringify(payload),
    });
    DashboardState.profile = updated;
    _renderProfile(updated);
    setProfileReadOnly(true);
    showToast("Profile updated successfully.", "success");

    // Refresh overview greeting
    loadOverview();
  } catch (err) {
    console.error("[Profile] Save error:", err);
    showToast("Could not save profile.", "error");
  }
}

/* ==========================================================================
   PANEL: Policies
   ========================================================================== */

async function loadPolicies() {
  const tbody = document.getElementById("policies-tbody");
  tbody.innerHTML = _loadingRow(6);

  try {
    const policies = await api("/dashboard/policies");
    DashboardState.policies = policies;
    _renderPoliciesTable(policies);
  } catch (err) {
    console.error("[Policies] Load error:", err);
    tbody.innerHTML = _errorRow(6, "Could not load policies.");
  }
}

function _renderPoliciesTable(policies) {
  const tbody = document.getElementById("policies-tbody");

  if (!policies.length) {
    tbody.innerHTML = _emptyRow(6,
      "No policies yet",
      "Enroll in a policy by talking to the AI Agent.");
    return;
  }

  tbody.innerHTML = policies.map(p => `
    <tr>
      <td><code>${_esc(p.policy_number)}</code></td>
      <td><strong>${_esc(p.policy_name)}</strong></td>
      <td>${_fmtDate(p.enrollment_date)}</td>
      <td><span class="badge ${_statusBadge(p.status)}">${_esc(p.status)}</span></td>
      <td>${_esc(p.min_sum_assured || '—')}</td>
      <td>${_esc(p.payment_frequency || '—')}</td>
      <td>${_fmtDate(p.next_due_date)}</td>
    </tr>
  `).join("");
}

// Sort state for policies table
let _policiesSort = { col: null, dir: 1 };

function sortPolicies(col) {
  const policies = [...DashboardState.policies];
  if (_policiesSort.col === col) {
    _policiesSort.dir *= -1;
  } else {
    _policiesSort.col = col;
    _policiesSort.dir = 1;
  }
  policies.sort((a, b) => {
    const av = a[col] ?? "";
    const bv = b[col] ?? "";
    return av < bv ? -_policiesSort.dir : av > bv ? _policiesSort.dir : 0;
  });
  _renderPoliciesTable(policies);
  _markSortHeader("policies-thead", col, _policiesSort.dir);
}

function searchPolicies(q) {
  const lower = q.toLowerCase();
  const filtered = DashboardState.policies.filter(p =>
    p.policy_name.toLowerCase().includes(lower) ||
    p.policy_number.toLowerCase().includes(lower) ||
    p.status.toLowerCase().includes(lower)
  );
  _renderPoliciesTable(filtered);
}

/* ==========================================================================
   PANEL: Recommendations
   ========================================================================== */

async function loadRecommendations() {
  const container = document.getElementById("rec-grid");
  container.innerHTML = `<div style="padding:20px"><div class="spinner"></div></div>`;

  try {
    const recs = await api("/dashboard/recommendations");
    DashboardState.recommendations = recs;
    _renderRecommendations(recs);
  } catch (err) {
    console.error("[Recommendations] Load error:", err);
    container.innerHTML = _emptyStateHTML("📋",
      "Could not load recommendations", "Please try again later.");
  }
}

function _renderRecommendations(recs) {
  const container = document.getElementById("rec-grid");

  if (!recs.length) {
    container.innerHTML = _emptyStateHTML("🤖",
      "No recommendations yet",
      "Ask the AI Agent about policies that suit your needs.");
    return;
  }

  container.innerHTML = recs.map(r => `
    <div class="rec-card">
      <div class="rec-card-header">
        <div class="rec-icon">📋</div>
        <div class="rec-name">${_esc(r.policy_name)}</div>
      </div>
      <div class="rec-reason">${_esc(r.reason || "Recommended based on your profile.")}</div>
      <div class="rec-date">Recommended on ${_fmtDate(r.recommended_at)}</div>
    </div>
  `).join("");
}

/* ==========================================================================
   PANEL: Chat History
   ========================================================================== */

async function loadChatHistory(page = 1) {
  const container = document.getElementById("chat-history-container");
  container.innerHTML = `<div class="empty-state"><div class="spinner"></div></div>`;

  const q = DashboardState.chatSearch;

  try {
    const data = await api(
      `/dashboard/chat-history?page=${page}&per_page=30${q ? `&q=${encodeURIComponent(q)}` : ""}`
    );
    DashboardState.chatHistory = data;
    _renderChatHistory(data);
  } catch (err) {
    console.error("[ChatHistory] Load error:", err);
    container.innerHTML = _emptyStateHTML("💬",
      "Could not load chat history", "Please try again later.");
  }
}

function _renderChatHistory(data) {
  const container = document.getElementById("chat-history-container");

  if (!data.items.length) {
    container.innerHTML = _emptyStateHTML("💬",
      "No conversations yet",
      "Start chatting with the AI Agent to see your history here.");
    _renderChatPagination(data);
    return;
  }

  // Group turns by session_id
  const sessions = {};
  data.items.forEach(turn => {
    const sid = turn.session_id || "default";
    if (!sessions[sid]) sessions[sid] = [];
    sessions[sid].push(turn);
  });

  container.innerHTML = Object.entries(sessions).map(([sid, turns]) => {
    const firstDate = _fmtDateTime(turns[turns.length - 1]?.created_at);
    return `
      <div class="chat-session-group">
        <div class="chat-session-label">Session · ${firstDate}</div>
        ${turns.map(turn => `
          <div class="chat-turn ${turn.role === "user" ? "user-turn" : "bot-turn"}">
            <div class="chat-turn-avatar">
              ${turn.role === "user" ? "👤" : "🛡️"}
            </div>
            <div class="chat-turn-content">
              <div class="chat-turn-meta">
                <span class="chat-turn-role">${_esc(turn.role)}</span>
                <span class="chat-turn-time">${_fmtDateTime(turn.created_at)}</span>
              </div>
              <div class="chat-turn-msg">${_esc(turn.message)}</div>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }).join("");

  _renderChatPagination(data);
}

function _renderChatPagination(data) {
  const el = document.getElementById("chat-pagination");
  if (!el) return;

  const totalPages = Math.ceil(data.total / data.per_page) || 1;
  const cur        = data.page;

  if (totalPages <= 1) { el.innerHTML = ""; return; }

  let html = `
    <button class="pg-btn" onclick="loadChatHistory(${cur - 1})"
      ${cur === 1 ? "disabled" : ""}>‹</button>
  `;

  for (let p = 1; p <= totalPages; p++) {
    if (
      p === 1 || p === totalPages ||
      (p >= cur - 1 && p <= cur + 1)
    ) {
      html += `<button class="pg-btn ${p === cur ? "active" : ""}"
        onclick="loadChatHistory(${p})">${p}</button>`;
    } else if (p === cur - 2 || p === cur + 2) {
      html += `<span style="color:var(--text-muted);padding:0 4px">…</span>`;
    }
  }

  html += `
    <button class="pg-btn" onclick="loadChatHistory(${cur + 1})"
      ${cur === totalPages ? "disabled" : ""}>›</button>
  `;

  el.innerHTML = html;
}

function chatHistorySearch(q) {
  DashboardState.chatSearch = q.trim();
  loadChatHistory(1);
}

/* ==========================================================================
   PANEL: Documents
   ========================================================================== */

async function loadDocuments() {
  const grid = document.getElementById("doc-grid");
  grid.innerHTML = `<div style="padding:20px"><div class="spinner"></div></div>`;

  try {
    const docs = await api("/dashboard/documents");
    DashboardState.documents = docs;
    _renderDocuments(docs);
  } catch (err) {
    console.error("[Documents] Load error:", err);
    grid.innerHTML = _emptyStateHTML("📁",
      "Could not load documents", "Please try again later.");
  }
}

function _renderDocuments(docs) {
  const grid = document.getElementById("doc-grid");

  if (!docs.length) {
    grid.innerHTML = _emptyStateHTML("📁",
      "No documents yet",
      "Policy documents will appear here after enrollment.");
    return;
  }

  grid.innerHTML = docs.map(d => `
    <div class="doc-card" onclick="downloadDoc(${d.id}, '${_esc(d.filename)}')">
      <div class="doc-icon">${_docIcon(d.filename)}</div>
      <div class="doc-name">${_esc(d.filename)}</div>
      <div class="doc-label">${_esc(d.label)}</div>
      <div class="doc-date">${_fmtDate(d.uploaded_at)}</div>
      <span class="badge badge-info btn-sm">⬇ Download</span>
    </div>
  `).join("");
}

function downloadDoc(id, filename) {
  // Documents are served from /audio equivalent path in future;
  // for now show a toast indicating the feature is available.
  showToast(`Preparing download: ${filename}`, "success");
}

/* ==========================================================================
   PANEL: Notifications
   ========================================================================== */

async function loadNotifications() {
  const list = document.getElementById("notif-list");
  list.innerHTML = `<div class="empty-state"><div class="spinner"></div></div>`;

  try {
    const data = await api("/dashboard/notifications");
    DashboardState.notifications  = data.items;
    DashboardState.notifUnread    = data.unread;
    _renderNotifications(data.items);
    _updateNotifBadge(data.unread);
  } catch (err) {
    console.error("[Notifications] Load error:", err);
    list.innerHTML = _emptyStateHTML("🔔",
      "Could not load notifications", "Please try again later.");
  }
}

function _renderNotifications(items) {
  const list = document.getElementById("notif-list");

  _setText("notif-unread-count",
    DashboardState.notifUnread
      ? `${DashboardState.notifUnread} unread`
      : "All read");

  if (!items.length) {
    list.innerHTML = _emptyStateHTML("🔔",
      "No notifications", "You're all caught up!");
    return;
  }

  list.innerHTML = items.map(n => `
    <div class="notif-item ${n.is_read ? "read" : "unread"}"
         onclick="markNotifRead(${n.id}, this)">
      <div class="notif-icon ${n.type}">
        ${_notifIcon(n.type)}
      </div>
      <div class="notif-body">
        <div class="notif-title">${_esc(n.title)}</div>
        <div class="notif-text">${_esc(n.body)}</div>
        <div class="notif-time">${_fmtDateTime(n.created_at)}</div>
      </div>
      <div class="notif-dot"></div>
    </div>
  `).join("");
}

async function markNotifRead(id, rowEl) {
  try {
    await api(`/dashboard/notifications/${id}/read`, { method: "PUT" });
    rowEl.classList.remove("unread");
    rowEl.classList.add("read");
    rowEl.querySelector(".notif-dot").style.visibility = "hidden";

    DashboardState.notifUnread = Math.max(0, DashboardState.notifUnread - 1);
    _updateNotifBadge(DashboardState.notifUnread);
    _setText("notif-unread-count",
      DashboardState.notifUnread ? `${DashboardState.notifUnread} unread` : "All read");
  } catch (err) {
    console.error("[Notifications] Mark read error:", err);
  }
}

async function markAllNotifRead() {
  try {
    await api("/dashboard/notifications/read-all", { method: "PUT" });
    DashboardState.notifUnread = 0;
    _updateNotifBadge(0);
    // Re-render list as all-read
    DashboardState.notifications.forEach(n => n.is_read = 1);
    _renderNotifications(DashboardState.notifications);
    showToast("All notifications marked as read.", "success");
  } catch (err) {
    console.error("[Notifications] Mark all read error:", err);
    showToast("Could not update notifications.", "error");
  }
}

/* ==========================================================================
   Topbar search  (delegates to the active panel)
   ========================================================================== */

function handleTopbarSearch(q) {
  const panel = DashboardState.activePanel;
  if (panel === "policies")      searchPolicies(q);
  if (panel === "chat-history")  chatHistorySearch(q);
}

/* ==========================================================================
   Sidebar helpers
   ========================================================================== */

function openSidebar() {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sidebarOverlay").classList.add("open");
}

function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebarOverlay").classList.remove("open");
}

/* ==========================================================================
   Toast notifications
   ========================================================================== */

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast     = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  // Trigger transition
  requestAnimationFrame(() => {
    requestAnimationFrame(() => toast.classList.add("show"));
  });

  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 350);
  }, 3200);
}

/* ==========================================================================
   Backend connectivity error
   ========================================================================== */

function _showBackendError() {
  // Replace the entire page content with a clear, actionable error.
  const content = document.querySelector(".page-content");
  if (!content) return;
  content.innerHTML = `
    <div style="
      display:flex; flex-direction:column; align-items:center;
      justify-content:center; height:60vh; gap:18px; text-align:center;
    ">
      <div style="font-size:52px">⚠️</div>
      <h2 style="color:var(--text);font-size:1.3rem">Cannot connect to backend</h2>
      <p style="color:var(--text-muted);max-width:360px;font-size:.9rem">
        The Insura backend at <strong>${API_BASE}</strong> is not responding.<br><br>
        Start it with:<br>
        <code style="
          background:var(--bg);padding:6px 12px;border-radius:6px;
          font-size:.85rem;display:inline-block;margin-top:6px
        ">cd backend &amp;&amp; python app.py</code>
      </p>
      <button class="btn btn-primary" onclick="location.reload()">
        🔄 Retry
      </button>
    </div>
  `;
  // Also update the topbar to indicate offline state
  const topbar = document.querySelector(".topbar");
  if (topbar) {
    topbar.style.borderBottom = "3px solid var(--danger)";
  }
}

/* ==========================================================================
   Logout
   ========================================================================== */

function logout() {
  localStorage.removeItem("username");
  window.location.href = "/login";
}

/* ==========================================================================
   Utility helpers
   ========================================================================== */

function _setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function _setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}

function _getVal(id) {
  const el = document.getElementById(id);
  return el ? el.value : "";
}

function _show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? "" : "none";
}

/** Escape text for safe innerHTML insertion. */
function _esc(str) {
  const d = document.createElement("div");
  d.textContent = str ?? "";
  return d.innerHTML;
}

function _capitalize(s) {
  if (!s) return "";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function _fmt(num) {
  return Number(num).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}

function _fmtDate(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleDateString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
    });
  } catch { return dateStr; }
}

function _fmtDateTime(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Date(dateStr).toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return dateStr; }
}

function _greetingWord() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function _statusBadge(status) {
  const map = {
    Active:    "badge-success",
    Expired:   "badge-danger",
    Pending:   "badge-warning",
    Cancelled: "badge-neutral",
  };
  return map[status] ?? "badge-neutral";
}

function _notifIcon(type) {
  return { success: "✅", warning: "⚠️", info: "ℹ️" }[type] ?? "🔔";
}

function _docIcon(filename) {
  const ext = (filename || "").split(".").pop().toLowerCase();
  return { pdf: "📄", xlsx: "📊", xls: "📊", doc: "📝",
           docx: "📝", png: "🖼️", jpg: "🖼️" }[ext] ?? "📁";
}

function _updateNotifBadge(count) {
  ["notif-sidebar-badge", "notif-topbar-badge"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = count;
    el.style.display = count > 0 ? "" : "none";
  });
}

/** HTML for a full-width loading row inside a <tbody>. */
function _loadingRow(cols) {
  return `<tr class="loading-row"><td colspan="${cols}">
    <div class="spinner"></div> Loading…
  </td></tr>`;
}

/** HTML for a full-width error row inside a <tbody>. */
function _errorRow(cols, msg) {
  return `<tr><td colspan="${cols}" style="text-align:center;padding:28px;color:var(--danger)">
    ⚠️ ${_esc(msg)}
  </td></tr>`;
}

/** HTML for a full-width empty-state row inside a <tbody>. */
function _emptyRow(cols, title, body = "") {
  return `<tr><td colspan="${cols}">
    <div class="empty-state">
      <div class="empty-state-icon">📭</div>
      <div class="empty-state-title">${_esc(title)}</div>
      ${body ? `<div class="empty-state-body">${_esc(body)}</div>` : ""}
    </div>
  </td></tr>`;
}

/** Standalone empty-state block (used outside tables). */
function _emptyStateHTML(icon, title, body = "") {
  return `<div class="empty-state">
    <div class="empty-state-icon">${icon}</div>
    <div class="empty-state-title">${_esc(title)}</div>
    ${body ? `<div class="empty-state-body">${_esc(body)}</div>` : ""}
  </div>`;
}

/** Update sort-arrow classes on a thead row. */
function _markSortHeader(theadId, activeCol, dir) {
  document.querySelectorAll(`#${theadId} th[data-col]`).forEach(th => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.col === activeCol) {
      th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
    }
  });
}

/* ==========================================================================
   PANEL: Calculators
   ========================================================================== */

/** Called when the Calculators panel is first opened. */
function loadCalculators() {
  // Run all calculators once so results are visible immediately
  calcPremium();
  calcMaturity();
  calcSurrender();
  calcSIP();
  calcFD();
}

/** Switch between the five calculator tabs. */
function switchCalc(name) {
  document.querySelectorAll(".calc-tab").forEach(t => {
    t.classList.toggle("active", t.dataset.calc === name);
  });
  document.querySelectorAll(".calc-pane").forEach(p => {
    p.classList.toggle("active", p.id === `calc-${name}`);
  });
}

/* --------------------------------------------------------------------------
   Helper: format Indian-style currency
   -------------------------------------------------------------------------- */
function _inr(n) {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

/* --------------------------------------------------------------------------
   1. PREMIUM CALCULATOR
   --------------------------------------------------------------------------
   Uses LIC's publicly available tabular rate approximations:
   Base rate per ₹1,000 SA varies by plan type, age, term, and gender.
   A smoking loading of 15% is applied for smokers.
   GST at 4.5% is added on top (first year GST is 4.5% per LIC norm).
   -------------------------------------------------------------------------- */

/**
 * Base rate tables (per ₹1,000 sum assured per year) — approximate values
 * derived from LIC's published premium charts.
 *
 * Structure: baseRates[planType][ageGroup] = rate
 * Age groups: "young" (<30), "mid" (30-45), "senior" (>45)
 * Term modifier applied separately.
 */
const PREM_BASE_RATES = {
  endowment:  { young: 48, mid: 56, senior: 72 },
  wholelife:  { young: 36, mid: 44, senior: 60 },
  moneyback:  { young: 56, mid: 65, senior: 82 },
  term:       { young:  6, mid:  9, senior: 18 },
};

function calcPremium() {
  const plan    = document.getElementById("prem-plan").value;
  const age     = parseInt(document.getElementById("prem-age").value)   || 30;
  const term    = parseInt(document.getElementById("prem-term").value)  || 20;
  const sa      = parseFloat(document.getElementById("prem-sum").value) || 500000;
  const gender  = document.querySelector('input[name="prem-gender"]:checked')?.value || "male";
  const smoker  = document.querySelector('input[name="prem-smoke"]:checked')?.value  === "yes";

  // Age group
  const ageGroup = age < 30 ? "young" : age <= 45 ? "mid" : "senior";
  let rate = PREM_BASE_RATES[plan][ageGroup];

  // Term modifier: longer term → slightly lower annual premium rate
  const termFactor = term <= 10 ? 1.12 : term <= 20 ? 1.00 : 0.93;
  rate *= termFactor;

  // Gender loading: female 2% lower (LIC standard)
  if (gender === "female") rate *= 0.98;

  // Smoker loading: +15%
  if (smoker) rate *= 1.15;

  // Annual premium before GST (rate is per ₹1,000 SA)
  const netPrem = (rate / 1000) * sa;

  // GST: 4.5% on first-year, 2.25% renewal — using 4.5% as conservative
  const gst  = 0.045;
  const annual    = netPrem * (1 + gst);
  const halfYearly = annual * 0.512;   // LIC applies 1.024 / 2 modal factor
  const quarterly  = annual * 0.260;   // 1.04 / 4
  const monthly    = annual * 0.0875;  // 1.05 / 12 approx
  const daily      = annual / 365;

  document.getElementById("prem-annual").textContent    = _inr(annual);
  document.getElementById("prem-half").textContent      = _inr(halfYearly);
  document.getElementById("prem-quarterly").textContent = _inr(quarterly);
  document.getElementById("prem-monthly").textContent   = _inr(monthly);
  document.getElementById("prem-daily").textContent     = "₹" + Math.round(daily);
}

/* --------------------------------------------------------------------------
   2. MATURITY CALCULATOR
   --------------------------------------------------------------------------
   Maturity = Sum Assured
            + Accrued Reversionary Bonus (bonus rate × SA/1000 × term)
            + Final Addition Bonus (FAB rate × SA/1000)
   -------------------------------------------------------------------------- */

function calcMaturity() {
  const sa    = parseFloat(document.getElementById("mat-sum").value)   || 500000;
  const term  = parseInt(document.getElementById("mat-term").value)    || 20;
  const bonus = parseFloat(document.getElementById("mat-bonus").value) || 45;   // ₹ per ₹1000 SA/yr
  const fab   = parseFloat(document.getElementById("mat-fab").value)   || 600;  // ₹ per ₹1000 SA

  const accBonus    = (bonus / 1000) * sa * term;
  const fabAmount   = (fab   / 1000) * sa;
  const totalMaturity = sa + accBonus + fabAmount;

  // Approximate total premiums paid (using ~5% of SA per year as rough annual premium)
  const approxPremPaid = sa * 0.05 * term;
  const profit = totalMaturity - approxPremPaid;

  document.getElementById("mat-total").textContent     = _inr(totalMaturity);
  document.getElementById("mat-sa").textContent        = _inr(sa);
  document.getElementById("mat-bonus-out").textContent = _inr(accBonus);
  document.getElementById("mat-fab-out").textContent   = _inr(fabAmount);
  document.getElementById("mat-profit").textContent    = _inr(profit);
}

/* --------------------------------------------------------------------------
   3. SURRENDER VALUE CALCULATOR
   --------------------------------------------------------------------------
   LIC surrender formula (simplified):
     Special Surrender Value = Paid-up Value × Surrender Value Factor
     Paid-up Value = SA × (premiums paid / total premiums)
     SVF depends on years paid; LIC publishes an SVF table —
     we approximate: SVF = 30% at 3 yrs, growing to 50% at 7+ yrs.
   -------------------------------------------------------------------------- */

function calcSurrender() {
  const sa         = parseFloat(document.getElementById("sur-sum").value)   || 500000;
  const term       = parseInt(document.getElementById("sur-term").value)    || 20;
  const yearsPaid  = parseInt(document.getElementById("sur-paid").value)    || 5;
  const annualPrem = parseFloat(document.getElementById("sur-prem").value)  || 25000;

  if (yearsPaid < 3) {
    document.getElementById("sur-value").textContent      = "Not eligible";
    document.getElementById("sur-total-paid").textContent = _inr(annualPrem * yearsPaid);
    document.getElementById("sur-factor").textContent     = "0%";
    return;
  }

  // Paid-up value
  const paidUpValue = sa * (yearsPaid / term);

  // Surrender Value Factor: linear from 30% at year 3 → 50% at year 7 → 80% at maturity
  let svf;
  if (yearsPaid <= 7)  svf = 0.30 + (yearsPaid - 3) * 0.05;
  else                 svf = 0.50 + (yearsPaid - 7)  * (0.30 / (term - 7));
  svf = Math.min(svf, 0.85);

  const surrenderValue = paidUpValue * svf;
  const totalPaid      = annualPrem * yearsPaid;

  document.getElementById("sur-value").textContent      = _inr(surrenderValue);
  document.getElementById("sur-total-paid").textContent = _inr(totalPaid);
  document.getElementById("sur-factor").textContent     = (svf * 100).toFixed(1) + "%";
}

/* --------------------------------------------------------------------------
   4. SIP CALCULATOR
   --------------------------------------------------------------------------
   Future Value of SIP = P × [((1 + r)^n - 1) / r] × (1 + r)
   Where:  P = monthly investment
           r = monthly rate = annual_rate / 12 / 100
           n = total months
   -------------------------------------------------------------------------- */

function calcSIP() {
  const monthly  = parseFloat(document.getElementById("sip-amount").value) || 5000;
  const annualR  = parseFloat(document.getElementById("sip-rate").value)   || 12;
  const years    = parseInt(document.getElementById("sip-years").value)    || 10;

  const r = annualR / 12 / 100;
  const n = years * 12;

  const fv       = monthly * (((Math.pow(1 + r, n) - 1) / r) * (1 + r));
  const invested = monthly * n;
  const returns  = fv - invested;
  const pct      = ((returns / invested) * 100).toFixed(1);

  document.getElementById("sip-wealth").textContent   = _inr(returns);
  document.getElementById("sip-invested").textContent = _inr(invested);
  document.getElementById("sip-returns").textContent  = _inr(returns);
  document.getElementById("sip-total").textContent    = _inr(fv);
  document.getElementById("sip-pct").textContent      = pct + "%";
}

/* --------------------------------------------------------------------------
   5. FD CALCULATOR
   --------------------------------------------------------------------------
   Compound Interest: A = P × (1 + r/n)^(n×t)
   Where:  P = principal
           r = annual rate / 100
           n = compounding frequency per year
           t = time in years
   EAR = (1 + r/n)^n - 1
   -------------------------------------------------------------------------- */

function calcFD() {
  const principal = parseFloat(document.getElementById("fd-principal").value) || 100000;
  const annualR   = parseFloat(document.getElementById("fd-rate").value)      || 7;
  const years     = parseInt(document.getElementById("fd-years").value)       || 5;
  const freq      = parseInt(document.getElementById("fd-freq").value)        || 4;

  const r       = annualR / 100;
  const maturity = principal * Math.pow(1 + r / freq, freq * years);
  const interest = maturity - principal;
  const ear      = (Math.pow(1 + r / freq, freq) - 1) * 100;
  const growth   = ((maturity / principal - 1) * 100).toFixed(1);

  document.getElementById("fd-maturity").textContent     = _inr(maturity);
  document.getElementById("fd-principal-out").textContent = _inr(principal);
  document.getElementById("fd-interest").textContent     = _inr(interest);
  document.getElementById("fd-ear").textContent          = ear.toFixed(2) + "%";
  document.getElementById("fd-growth").textContent       = growth + "%";
}
