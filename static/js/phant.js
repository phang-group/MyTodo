/*
 * phant.js — PHANT global widget
 *
 * Handles:
 *   - Panel open/close toggle
 *   - Tab switching (Brief / Ask / Signals)
 *   - Brief loading  → GET  /phant/brief/daily
 *   - Signal loading → GET  /phant/signals/{type}
 *   - Chat messaging → POST /phant/chat
 *
 * No external dependencies. Vanilla JS.
 * Loaded once via <script src="/static/js/phant.js"> in base.html.
 */

(function () {
  "use strict";

  /* ── State ─────────────────────────────────────────────────────────────── */
  let _open          = false;
  let _briefLoaded   = false;
  let _signalsLoaded = {};
  let _sessionId     = null;

  /* ── Panel toggle ───────────────────────────────────────────────────────── */
  window.togglePhantPanel = function () {
    _open = !_open;
    const panel = document.getElementById("phant-panel");
    if (!panel) return;
    panel.classList.toggle("panel-open",   _open);
    panel.classList.toggle("panel-closed", !_open);
    panel.setAttribute("aria-hidden", String(!_open));
    if (_open && !_briefLoaded) _loadBrief();
  };

  /* ── Tab switching ──────────────────────────────────────────────────────── */
  window.switchTab = function (tab) {
    const briefTab = document.getElementById("phant-brief-tab");
    const askTab   = document.getElementById("phant-ask-tab");
    const btnBrief = document.getElementById("tab-brief");
    const btnAsk   = document.getElementById("tab-ask");
    if (!briefTab || !askTab) return;

    const isBrief = tab === "brief";
    briefTab.classList.toggle("hidden", !isBrief);
    askTab.classList.toggle("hidden",    isBrief);

    [btnBrief, btnAsk].forEach((btn, i) => {
      const active = (i === 0) === isBrief;
      btn?.classList.toggle("text-gray-900",      active);
      btn?.classList.toggle("border-gray-900",    active);
      btn?.classList.toggle("text-gray-400",      !active);
      btn?.classList.toggle("border-transparent", !active);
    });

    if (!isBrief) {
      document.getElementById("phant-input")?.focus();
    }
  };

  /* ── Brief loading ──────────────────────────────────────────────────────── */
  async function _loadBrief() {
    _briefLoaded = true;
    try {
      const res  = await fetch("/phant/brief/daily");
      const data = await res.json();
      const loading = document.getElementById("phant-brief-loading");
      const content = document.getElementById("phant-brief-content");
      if (loading) loading.classList.add("hidden");
      if (content) {
        content.classList.remove("hidden");
        content.innerHTML = _fmt(data.brief || "No brief available.");
      }
      // Render stats badge row
      if (data.stats) {
        const statsEl = document.getElementById("phant-brief-stats");
        if (statsEl) {
          const s = data.stats;
          statsEl.innerHTML =
            `<span class="phant-stat">${s.active_risks} risks</span>` +
            `<span class="phant-stat">${s.open_decisions} open decisions</span>` +
            `<span class="phant-stat">${s.divergences} divergences</span>`;
          statsEl.classList.remove("hidden");
        }
      }
    } catch (e) {
      const el = document.getElementById("phant-brief-loading");
      if (el) el.textContent = "Unable to load brief.";
    }

    // Load signal sections
    _loadSignals("risks");
    _loadSignals("divergences");
    _loadSignals("goals");
  }

  /* ── Signal loading ─────────────────────────────────────────────────────── */
  async function _loadSignals(type) {
    if (_signalsLoaded[type]) return;
    _signalsLoaded[type] = true;

    const el = document.getElementById("phant-signals-" + type);
    if (!el) return;

    try {
      const res  = await fetch("/phant/signals/" + type);
      const data = await res.json();
      _renderSignals(el, data.items || []);
    } catch (_) {
      el.innerHTML = '<span class="phant-signals-loading">Unavailable.</span>';
    }
  }

  function _renderSignals(container, items) {
    if (!items.length) {
      container.innerHTML = '<span class="phant-signals-loading">None active.</span>';
      return;
    }
    container.innerHTML = items.slice(0, 5).map(function (item) {
      // Memories have memory_type + confidence; divergences have divergence_type + severity
      const typeLabel = item.memory_type || item.divergence_type || "signal";
      const conf = item.confidence != null
        ? `<span class="phant-conf">${Math.round(item.confidence * 100)}%</span>`
        : "";
      const dotClass = item.severity >= 0.7 || (item.confidence && item.confidence < 0.5)
        ? "phant-dot-critical"
        : "phant-dot-warning";

      return (
        '<div class="phant-signal-item">' +
          '<div class="phant-signal-row">' +
            '<span class="' + dotClass + '">&#9679;</span>' +
            '<span class="phant-signal-type">' + _esc(typeLabel) + '</span>' +
            conf +
          "</div>" +
          '<div class="phant-signal-desc">' + _esc((item.content || item.description || "").slice(0, 100)) + "</div>" +
        "</div>"
      );
    }).join("");
  }

  /* ── Chat (Ask PHANT) ───────────────────────────────────────────────────── */
  window.sendPhantMessage = async function () {
    const input = document.getElementById("phant-input");
    const msg   = input?.value.trim();
    if (!msg) return;
    input.value = "";

    const container = document.getElementById("phant-chat-messages");
    if (!container) return;

    container.insertAdjacentHTML(
      "beforeend",
      '<div class="flex justify-end">' +
        '<div class="bg-gray-900 text-white text-sm px-3 py-2 rounded-2xl rounded-br-sm max-w-[85%]">' +
          _esc(msg) +
        "</div></div>"
    );
    container.scrollTop = container.scrollHeight;

    const typingId = "phant-typing-" + Date.now();
    container.insertAdjacentHTML(
      "beforeend",
      '<div id="' + typingId + '" class="flex justify-start">' +
        '<div class="bg-gray-100 text-gray-500 text-xs px-3 py-2 rounded-2xl">...</div>' +
      "</div>"
    );
    container.scrollTop = container.scrollHeight;

    try {
      const body = { message: msg };
      if (_sessionId) body.session_id = _sessionId;

      const res  = await fetch("/phant/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(body),
      });
      const data = await res.json();
      if (data.session_id) _sessionId = data.session_id;

      document.getElementById(typingId)?.remove();
      container.insertAdjacentHTML(
        "beforeend",
        '<div class="flex justify-start">' +
          '<div class="bg-white border border-gray-200 text-gray-800 text-sm px-3 py-2 rounded-2xl rounded-bl-sm max-w-[85%]">' +
            _fmt(data.response || "No response.") +
          "</div>" +
          (data.mode ? '<span class="phant-mode-badge">' + _esc(data.mode) + '</span>' : '') +
        "</div>"
      );
    } catch (_) {
      document.getElementById(typingId)?.remove();
      container.insertAdjacentHTML(
        "beforeend",
        '<div class="flex justify-start">' +
          '<div class="bg-red-50 text-red-600 text-xs px-3 py-2 rounded-xl">Request failed.</div>' +
        "</div>"
      );
    }
    container.scrollTop = container.scrollHeight;
  };

  /* ── Utilities ──────────────────────────────────────────────────────────── */
  function _esc(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function _fmt(text) {
    return String(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g,     "<em>$1</em>")
      .replace(/\n/g,            "<br/>");
  }
})();
