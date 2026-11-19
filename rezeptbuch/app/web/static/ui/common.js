/* HA-Rezeptbuch – gemeinsame Bausteine der Oberfläche (Modul 10, docs/dashboard.md, K10-2).
   Adresse der Schnittstelle aus der eigenen Adresse (HA-Ingress-sicher), Live-Kanal mit Neuaufbau,
   eigene Dialoge statt alert/confirm, Zahlenfeld, Meldeleiste. Daten nur als Text einfügen. */
"use strict";

(function () {
  // Basis: alles vor /station/…, /admin… bzw. die Startseite selbst (Ingress-Präfix bleibt erhalten)
  const BASE = location.pathname.replace(/\/(station\/[^\/]*|admin(\/[^\/]*)?)?\/?$/, "/");
  const API = BASE + "api/v1/";

  function el(tag, text, cls) {
    const e = document.createElement(tag);
    if (text !== undefined && text !== null) e.textContent = String(text);
    if (cls) e.className = cls;
    return e;
  }

  function grams(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    return Math.round(v).toLocaleString("de-DE") + " g";
  }

  function kg(v) {
    if (v === null || v === undefined) return "–";
    return (v / 1000).toLocaleString("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 3 }) + " kg";
  }

  // Gerätespeicher: kann fehlen oder werfen (Kiosk, privater Modus) – dann ohne Speicher weiter
  const store = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* ohne Speicher */ } },
    del(key) { try { localStorage.removeItem(key); } catch (e) { /* ohne Speicher */ } },
  };

  // ------------------------------------------------------------ Schnittstelle
  const listeners = [];
  async function api(path, options) {
    const opts = options || {};
    const headers = {};
    let token = null;
    try { token = sessionStorage.getItem("rezeptbuch_admin_session"); } catch (e) { token = null; }
    if (token) headers["X-Rezeptbuch-Session"] = token;
    if (opts.body !== undefined) headers["Content-Type"] = "application/json";
    let res;
    try {
      res = await fetch(API + path, { method: opts.method || "GET", headers: headers, cache: "no-store",
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined });
    } catch (e) {
      const err = new Error("Keine Verbindung zum Rezeptserver."); err.status = 0; err.data = {};
      listeners.forEach((f) => f(err)); throw err;
    }
    let data = null;
    if (res.status !== 204) { try { data = await res.json(); } catch (e) { data = null; } }
    if (!res.ok) {
      const err = new Error((data && typeof data.detail === "string") ? data.detail : "Fehler " + res.status);
      err.status = res.status; err.data = data || {}; err.code = err.data.code;
      listeners.forEach((f) => f(err));
      throw err;
    }
    listeners.forEach((f) => f(null));
    return data;
  }
  function onApiResult(f) { listeners.push(f); }

  // ------------------------------------------------------------ Live-Kanal
  // Neuaufbau nach 1, 2, 5, 10 s; nach 40 s ohne Nachricht gilt die Verbindung als getrennt (Herzschlag 15 s)
  function live(onMessage, onState) {
    const delays = [1000, 2000, 5000, 10000];
    let attempt = 0, ws = null, lastAt = 0, connected = false, timer = null;
    function setState(v) { if (v !== connected) { connected = v; onState(v); } }
    function connect() {
      try {
        ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + API + "live");
      } catch (e) { retry(); return; }
      ws.onopen = () => { attempt = 0; lastAt = Date.now(); setState(true); };
      ws.onmessage = (ev) => {
        lastAt = Date.now();
        let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
        onMessage(m);
      };
      ws.onclose = () => { ws = null; setState(false); retry(); };
      ws.onerror = () => { try { ws.close(); } catch (e) { /* egal */ } };
    }
    function retry() {
      if (timer) return;
      const d = delays[Math.min(attempt, delays.length - 1)];
      attempt += 1;
      timer = setTimeout(() => { timer = null; connect(); }, d);
    }
    setInterval(() => {
      if (ws && connected && Date.now() - lastAt > 40000) {
        setState(false);
        try { ws.close(); } catch (e) { /* egal */ }
      }
    }, 5000);
    onState(false);
    connect();
  }

  // ------------------------------------------------------------ Dialoge (keine Browser-Dialoge, iOS-App)
  // buttons: [{label, value, kind}] → Promise mit dem value der getippten Taste
  function dialog(opts) {
    return new Promise((resolve) => {
      const back = el("div", null, "dlg-back");
      const box = el("div", null, "dlg");
      if (opts.title) box.appendChild(el("h2", opts.title));
      if (opts.text) box.appendChild(el("p", opts.text));
      if (opts.content) box.appendChild(opts.content);
      const row = el("div", null, "btns");
      (opts.buttons || [{ label: "OK", value: true, kind: "primary" }]).forEach((b) => {
        const btn = el("button", b.label, (b.kind || "") + " keep");
        btn.type = "button";
        btn.addEventListener("click", () => {
          if (b.check && !b.check()) return;
          back.remove(); resolve(b.value);
        });
        row.appendChild(btn);
      });
      box.appendChild(row);
      back.appendChild(box);
      document.body.appendChild(back);
    });
  }

  // Zahlenfeld: Promise mit dem eingegebenen Text oder null (Abbrechen)
  function numpad(opts) {
    let value = opts.value !== undefined && opts.value !== null ? String(opts.value) : "";
    const wrap = el("div");
    const show = el("div", null, "pad-show num");
    function paint() { show.textContent = (opts.secret ? "•".repeat(value.length) : value) + (opts.unit && !opts.secret ? " " + opts.unit : ""); }
    wrap.appendChild(show);
    const pad = el("div", null, "pad");
    ["7", "8", "9", "4", "5", "6", "1", "2", "3", opts.decimal ? "," : "", "0", "⌫"].forEach((k) => {
      const b = el("button", k, "keep");
      b.type = "button";
      if (!k) { b.disabled = true; b.style.visibility = "hidden"; }
      b.addEventListener("click", () => {
        if (k === "⌫") value = value.slice(0, -1);
        else if (k === "," && value.includes(",")) return;
        else if (value.length < (opts.max || 8)) value += k;
        paint();
      });
      pad.appendChild(b);
    });
    wrap.appendChild(pad);
    paint();
    return dialog({ title: opts.title, text: opts.text, content: wrap, buttons: [
      { label: "Abbrechen", value: null },
      { label: "OK", value: "ok", kind: "primary" },
    ] }).then((r) => (r === "ok" ? value : null));
  }

  // ------------------------------------------------------------ Meldeleiste
  // Stufen: rot (4) > grau (3) > orange (2) > blau (1); die höchste wird gezeigt
  const LEVEL = { red: 4, grey: 3, orange: 2, blue: 1 };
  const notices = {};
  let noticeBox = null;
  function paintNotice() {
    if (!noticeBox) return;
    let best = null;
    Object.keys(notices).forEach((k) => {
      const n = notices[k];
      if (!best || LEVEL[n.level] > LEVEL[best.level]) best = n;
    });
    noticeBox.className = "notice" + (best ? " " + best.level : " hidden");
    noticeBox.textContent = best ? best.text : "";
  }
  const notice = {
    attach(box) { noticeBox = box; paintNotice(); },
    set(key, level, text, seconds) {
      notices[key] = { level: level, text: text };
      if (seconds) setTimeout(() => { if (notices[key] && notices[key].text === text) notice.clear(key); }, seconds * 1000);
      paintNotice();
    },
    clear(key) { if (notices[key]) { delete notices[key]; paintNotice(); } },
    has(key) { return Boolean(notices[key]); },
  };

  // ------------------------------------------------------------ iOS-App: erstes Zeichnen erzwingen
  function repaint() { document.body.style.display = "none"; void document.body.offsetHeight; document.body.style.display = ""; }
  window.addEventListener("load", function () { repaint(); requestAnimationFrame(repaint); setTimeout(repaint, 150); });
  window.addEventListener("pageshow", repaint);

  window.RB = { BASE: BASE, API: API, el: el, grams: grams, kg: kg, store: store, api: api, onApiResult: onApiResult,
                live: live, dialog: dialog, numpad: numpad, notice: notice };
})();
