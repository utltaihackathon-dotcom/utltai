/*!
 * UTLT.ai Assistant - drop-in floating AI widget (bottom-right) with a search bar.
 * Pure JavaScript, no libraries, no API keys. Works on GitHub Pages.
 * Uses Shadow DOM, so it will not clash with your site's CSS.
 *
 * Usage:  <script src="utlt-ai.js" defer></script>
 *
 * Optional config (put BEFORE the script tag):
 *   <script>window.UTLT_AI = { esp32Url: "http://192.168.1.50/data" };</script>
 *   ESP32 should return JSON like {"weight": 21.4, "burner": true}
 *   (browsers block http:// calls from https:// pages - serve your ESP32 over https or run the page locally)
 *
 * Demo helpers in the console:  UTLT_AI_API.simulateLeak(true)  |  UTLT_AI_API.refill()
 */
(function () {
  "use strict";

  const cfg = Object.assign({
    esp32Url: null,        // null = built-in simulator
    tareKg: 15.3,          // empty cylinder weight
    gasFullKg: 14.2,       // gas in a full cylinder
    lowPct: 20,
    emergency: "1906",     // India LPG emergency line - change for your region
    tickMs: 1500,
    hoursPerTick: 1 / 6,   // simulator: 1 tick = 10 simulated minutes
    title: "UTLT.ai Assistant",
    placeholder: "Ask UTLT.ai anything…",
  }, window.UTLT_AI || {});

  /* ---------------------------------------------------------------- sensor */
  const sensor = {
    t: 0, gas: cfg.gasFullKg * 0.62, burner: false, leak: false,
    async read() {
      this.t += cfg.hoursPerTick;
      if (cfg.esp32Url) {
        try {
          const r = await fetch(cfg.esp32Url, { cache: "no-store" });
          const d = await r.json();
          this.gas = Math.max(0, Number(d.weight) - cfg.tareKg);
          this.burner = !!d.burner;
          return [this.t, this.gas, this.burner];
        } catch (e) { /* board unreachable -> fall back to simulation */ }
      }
      if (Math.random() < 0.10) this.burner = !this.burner;
      let use = this.burner ? (0.25 + Math.random() * 0.2) * cfg.hoursPerTick : 0;
      if (this.leak) use += 0.04;
      this.gas = Math.max(0, this.gas - use + (Math.random() - 0.5) * 0.006);
      return [this.t, this.gas, this.burner];
    },
  };

  /* ----------------------------------------------------------------- brain */
  const pick = (a) => a[Math.floor(Math.random() * a.length)];

  function lev(a, b) {
    const m = a.length, n = b.length, d = Array.from({ length: m + 1 }, (_, i) => [i]);
    for (let j = 1; j <= n; j++) d[0][j] = j;
    for (let i = 1; i <= m; i++)
      for (let j = 1; j <= n; j++)
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    return d[m][n];
  }
  const sim = (a, b) => 1 - lev(a, b) / Math.max(a.length, b.length, 1);

  const INTENTS = {
    level:  ["gas level", "how much gas", "remaining", "left", "percentage", "status", "cylinder", "full"],
    days:   ["how long", "days", "last", "run out", "empty", "predict", "forecast", "when"],
    leak:   ["leak", "smell", "safe", "safety", "danger", "gas smell", "check leak"],
    weight: ["weight", "kg", "load cell", "hx711", "reading"],
    book:   ["book", "order", "refill", "new cylinder", "buy"],
    how:    ["how does", "work", "explain", "esp32", "project", "utlt", "about"],
    tips:   ["tip", "tips", "save", "efficient", "reduce", "advice"],
    help:   ["help", "what can you do", "commands", "options"],
    hello:  ["hi", "hello", "hey", "yo", "good morning", "good evening"],
    thanks: ["thanks", "thank you", "cool", "great", "nice"],
  };

  const brain = {
    history: [], // [time_h, gas_kg, burner]
    feed(t, g, b) { this.history.push([t, g, b]); if (this.history.length > 90) this.history.shift(); },
    get gas() { const h = this.history[this.history.length - 1]; return h ? h[1] : 0; },
    get pct() { return Math.max(0, Math.min(100, (this.gas / cfg.gasFullKg) * 100)); },

    burnRate() { // kg/hour: least-squares slope of gas vs time
      const h = this.history, n = h.length;
      if (n < 8) return null;
      const mt = h.reduce((s, x) => s + x[0], 0) / n, mg = h.reduce((s, x) => s + x[1], 0) / n;
      const den = h.reduce((s, x) => s + (x[0] - mt) ** 2, 0);
      if (!den) return null;
      return Math.max(0, -h.reduce((s, x) => s + (x[0] - mt) * (x[1] - mg), 0) / den);
    },
    daysLeft() { const r = this.burnRate(); return !r || r < 1e-4 ? null : this.gas / r / 24; },
    leakSuspected() {
      const h = this.history.slice(-4);
      if (h.length < 4) return false;
      const drops = [0, 1, 2].map((i) => h[i][1] - h[i + 1][1]);
      return h.every((x) => !x[2]) && drops.every((d) => d > 0.02);
    },
    leakAlert() {
      return "🚨 **LEAK SUSPECTED** - weight is dropping while the burner is off.\n" +
        "1. No switches or flames\n2. Open doors and windows\n3. Close the regulator\n" +
        `4. Leave and call **${cfg.emergency}**`;
    },

    intent(text) {
      text = text.toLowerCase();
      const words = text.match(/[a-z']+/g) || [];
      let best = null, bestScore = 0;
      for (const [name, keys] of Object.entries(INTENTS)) {
        let score = 0;
        for (const k of keys) {
          if (new RegExp("\\b" + k + "\\b").test(text)) score += 2 * k.split(" ").length;
          else score += words.filter((w) => w.length > 3 && k.split(" ").some((kw) => sim(w, kw) >= 0.8)).length;
        }
        if (score > bestScore) { best = name; bestScore = score; }
      }
      return bestScore >= 1.5 || best === "hello" ? best : null;
    },

    reply(text) {
      const i = this.intent(text), g = this.gas, p = this.pct;
      switch (i) {
        case "hello": return pick(["Hey! I'm watching your cylinder 24/7. Ask me anything.", "Hi there! Want a quick status check?"]);
        case "level": return `**${g.toFixed(2)} kg** of gas left (**${p.toFixed(0)}%**) - ` + (p > cfg.lowPct ? "all good ✅" : "running low, time to reorder ⚠️");
        case "days": {
          const d = this.daysLeft(), r = this.burnRate();
          if (d == null) return "Still learning your usage pattern - give me a few more readings.";
          return `At your current usage (~${(r * 1000).toFixed(0)} g/hour) the gas lasts about **${d.toFixed(1)} days**. I'd reorder at around ${Math.max(1, d * 0.2).toFixed(1)} days left.`;
        }
        case "leak":
          return this.leakSuspected() ? this.leakAlert()
            : "No leak signature right now: weight is stable while the burner is off. If you ever smell gas, ventilate and close the regulator first - don't wait for software.";
        case "weight": return `Total weight **${(g + cfg.tareKg).toFixed(2)} kg** (cylinder ${cfg.tareKg} kg + gas ${g.toFixed(2)} kg).`;
        case "book": return "Booking isn't wired to a provider in this demo. Hook your distributor's API into `brain.reply` and I'll auto-order at 20%.";
        case "how": return "**UTLT.ai:** 4 load cells → HX711 amplifier → ESP32 → dashboard. I turn raw weight into level, burn rate, forecasts and leak alerts.";
        case "tips": return pick([
          "Keep lids on pots - it can cut gas use by around 20%.",
          "Soak dal and rice first; shorter cooking means less gas.",
          "Flame tips should be blue. Yellow means poor burning - clean the burner.",
          "Turn the regulator off at night - the best safety habit."]);
        case "help": return "Try: *gas level*, *days left*, *check for leaks*, *weight*, *tips*, *how does this work*.";
        case "thanks": return "Anytime! 🙌";
      }
      const keys = Object.values(INTENTS).flat();
      let m = null, ms = 0.5;
      for (const k of keys) { const s = sim(text.toLowerCase().trim(), k); if (s > ms) { ms = s; m = k; } }
      return "I didn't quite get that." + (m ? ` Did you mean *${m}*?` : "") + " Type **help** for options.";
    },
  };

  /* -------------------------------------------------------------------- UI */
  const host = document.createElement("div");
  host.id = "utlt-ai-root";
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
  <style>
    :host { all: initial; }
    * { box-sizing: border-box; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .wrap { position: fixed; right: 24px; bottom: 24px; z-index: 2147483000; color: #e8eefc; }

    /* collapsed search pill */
    .pill { display: flex; align-items: center; gap: 8px; width: 300px; max-width: calc(100vw - 32px);
      background: #161d33; border: 1px solid #2a3556; border-radius: 999px; padding: 6px 6px 6px 14px;
      box-shadow: 0 8px 28px rgba(0,0,0,.4); transition: border-color .2s, box-shadow .2s; }
    .pill:focus-within { border-color: #3b82f6; box-shadow: 0 8px 28px rgba(59,130,246,.35); }
    .pill input { flex: 1; min-width: 0; background: transparent; border: 0; outline: 0; color: #e8eefc; font-size: 14px; }
    .pill input::placeholder { color: #8b97b5; }
    .go { position: relative; width: 38px; height: 38px; border-radius: 50%; border: 0; cursor: pointer;
      background: #3b82f6; color: #fff; font-weight: 700; font-size: 13px; flex: none; }
    .go.low  { background: #f59e0b; animation: pulse 1s infinite; --c: #f59e0b; }
    .go.leak { background: #ef4444; animation: pulse 1s infinite; --c: #ef4444; }
    @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent); }
                       50% { box-shadow: 0 0 0 10px transparent; } }

    /* chat panel */
    .panel { display: none; flex-direction: column; width: 380px; max-width: calc(100vw - 32px); height: 520px;
      max-height: calc(100vh - 48px); background: #0f1424; border: 1px solid #2a3556; border-radius: 18px;
      overflow: hidden; box-shadow: 0 16px 48px rgba(0,0,0,.5); }
    .open .panel { display: flex; animation: pop .18s ease-out; }
    .open .pill { display: none; }
    @keyframes pop { from { opacity: 0; transform: translateY(10px) scale(.98); } to { opacity: 1; transform: none; } }
    header { display: flex; align-items: center; gap: 8px; padding: 12px 14px; background: #161d33; }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: #22c55e; }
    header b { font-size: 14px; }
    .st { font-size: 12px; color: #8b97b5; margin-left: 4px; }
    .x { margin-left: auto; background: none; border: 0; color: #8b97b5; font-size: 16px; cursor: pointer; }
    .msgs { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
    .m { max-width: 85%; padding: 9px 12px; border-radius: 14px; font-size: 14px; line-height: 1.4; word-wrap: break-word; }
    .bot { background: #1f2a44; border-bottom-left-radius: 4px; align-self: flex-start; }
    .user { background: #3b82f6; color: #fff; border-bottom-right-radius: 4px; align-self: flex-end; }
    .alert { background: #4a1d1d; color: #ffd7d7; align-self: flex-start; }
    .typing { display: inline-flex; gap: 4px; }
    .typing i { width: 6px; height: 6px; border-radius: 50%; background: #8b97b5; animation: bl 1s infinite; }
    .typing i:nth-child(2) { animation-delay: .15s; } .typing i:nth-child(3) { animation-delay: .3s; }
    @keyframes bl { 0%,80%,100% { opacity: .25; } 40% { opacity: 1; } }
    .chips { display: flex; gap: 6px; padding: 0 12px 8px; flex-wrap: wrap; }
    .chip { background: #161d33; color: #e8eefc; border: 1px solid #2a3556; border-radius: 999px;
      padding: 4px 10px; font-size: 12px; cursor: pointer; }
    .chip:hover { border-color: #3b82f6; }
    form { display: flex; gap: 8px; padding: 10px 12px 12px; background: #0f1424; }
    form input { flex: 1; background: #161d33; border: 1px solid #2a3556; border-radius: 999px; outline: 0;
      color: #e8eefc; padding: 10px 14px; font-size: 14px; }
    form input:focus { border-color: #3b82f6; }
    form button { width: 40px; border-radius: 50%; border: 0; background: #3b82f6; color: #fff; cursor: pointer; font-size: 15px; }
  </style>

  <div class="wrap" id="wrap">
    <form class="pill" id="pill" autocomplete="off">
      <input id="pillq" placeholder="${cfg.placeholder}" aria-label="Ask UTLT.ai" />
      <button class="go" id="go" type="submit" aria-label="Ask">AI</button>
    </form>

    <section class="panel" role="dialog" aria-label="${cfg.title}">
      <header>
        <span class="dot" id="dot"></span><b>${cfg.title}</b><span class="st" id="st"></span>
        <button class="x" id="x" aria-label="Close">✕</button>
      </header>
      <div class="msgs" id="msgs"></div>
      <div class="chips" id="chips"></div>
      <form id="form" autocomplete="off">
        <input id="q" placeholder="${cfg.placeholder}" aria-label="Your question" />
        <button type="submit" aria-label="Send">➤</button>
      </form>
    </section>
  </div>`;

  const $ = (id) => root.getElementById(id);
  const wrap = $("wrap"), msgs = $("msgs"), go = $("go");
  let alertState = null, alertedLeak = false, alertedLow = false;

  const fmt = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>")
    .replace(/`(.+?)`/g, "<code>$1</code>").replace(/\n/g, "<br>");

  function add(text, cls) {
    const el = document.createElement("div");
    el.className = "m " + cls;
    el.innerHTML = fmt(text);
    msgs.appendChild(el);
    msgs.scrollTop = msgs.scrollHeight;
    return el;
  }

  function setOpen(v) {
    wrap.classList.toggle("open", v);
    if (v) { alertState = null; go.className = "go"; setTimeout(() => $("q").focus(), 0); }
  }

  function ask(text) {
    text = text.trim();
    if (!text) return;
    setOpen(true);
    add(text, "user");
    const t = add('<span class="typing"><i></i><i></i><i></i></span>', "bot");
    t.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    setTimeout(() => { t.innerHTML = fmt(brain.reply(text)); msgs.scrollTop = msgs.scrollHeight; }, 400 + Math.random() * 400);
  }

  [["Gas level", "gas level"], ["Days left", "how many days left"], ["Leaks?", "check for leaks"], ["Tips", "tips"]]
    .forEach(([label, q]) => {
      const b = document.createElement("button");
      b.className = "chip"; b.textContent = label; b.onclick = () => ask(q);
      $("chips").appendChild(b);
    });

  $("pill").addEventListener("submit", (e) => { e.preventDefault(); const i = $("pillq"); const v = i.value; i.value = ""; v.trim() ? ask(v) : setOpen(true); });
  $("form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("q"); const v = i.value; i.value = ""; ask(v); });
  $("x").onclick = () => setOpen(false);
  host.addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });

  function raise(kind, text) {
    alertState = kind;
    add(text, "alert");
    if (!wrap.classList.contains("open")) go.className = "go " + kind;
  }

  async function tick() {
    brain.feed(...(await sensor.read()));
    const p = brain.pct, leak = brain.leakSuspected();
    $("st").textContent = `${p.toFixed(0)}% • ${brain.gas.toFixed(1)} kg`;
    $("dot").style.background = leak ? "#ef4444" : p <= cfg.lowPct ? "#f59e0b" : "#22c55e";
    if (leak && !alertedLeak) { alertedLeak = true; raise("leak", brain.leakAlert()); }
    if (!leak) alertedLeak = false;
    if (p <= cfg.lowPct && !alertedLow) { alertedLow = true; raise("low", `⚠️ Heads up: only **${p.toFixed(0)}%** gas left. Time to book a refill.`); }
    if (p > cfg.lowPct + 5) alertedLow = false;
  }

  function start() {
    document.body.appendChild(host);
    add("Hi! I'm the **UTLT.ai** assistant. I'm monitoring your cylinder live. Ask me anything.", "bot");
    (async () => { for (let i = 0; i < 12; i++) brain.feed(...(await sensor.read())); await tick(); setInterval(tick, cfg.tickMs); })();
  }

  window.UTLT_AI_API = {
    simulateLeak(v = true) { sensor.leak = !!v; },
    refill() { sensor.gas = cfg.gasFullKg; alertedLow = false; },
    ask,
  };

  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
})();
