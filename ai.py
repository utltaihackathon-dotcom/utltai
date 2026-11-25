"""
UTLT.ai Assistant - Python only (Streamlit).
Just the AI: a search bar pinned to the bottom-right that opens a chat panel.
No dashboard, no API keys.

requirements.txt:   streamlit>=1.39
Run:                streamlit run ai.py

Put your own page content where it says YOUR PAGE CONTENT at the bottom.
"""
import difflib
import json
import random
import re
import urllib.request
from collections import deque

import streamlit as st

# ------------------------------------------------------------------ config
ESP32_URL = None            # e.g. "http://192.168.1.50/data" (None = simulator)
TARE_KG = 15.3              # empty cylinder weight
GAS_FULL_KG = 14.2          # gas in a full cylinder
LOW_GAS_PCT = 20
EMERGENCY_NUMBER = "1906"   # India LPG emergency line - change for your region
HOURS_PER_TICK = 1 / 6      # simulator: 1 tick = 10 simulated minutes
TICK_SECONDS = 1.5

st.set_page_config(page_title="UTLT.ai", page_icon="🔥", layout="wide")


# ------------------------------------------------------------------ sensor
class Sensor:
    def __init__(self):
        self.t, self.gas = 0.0, GAS_FULL_KG * 0.62
        self.burner, self.leak = False, False

    def read(self):
        self.t += HOURS_PER_TICK
        if ESP32_URL:
            try:
                with urllib.request.urlopen(ESP32_URL, timeout=1.5) as r:
                    d = json.loads(r.read().decode())
                self.gas = max(0.0, float(d["weight"]) - TARE_KG)
                self.burner = bool(d.get("burner", False))
                return self.t, self.gas, self.burner
            except Exception:
                pass  # board unreachable -> fall back to simulation
        if random.random() < 0.10:
            self.burner = not self.burner
        use = random.uniform(0.25, 0.45) * HOURS_PER_TICK if self.burner else 0
        if self.leak:
            use += 0.04
        self.gas = max(0.0, self.gas - use + random.uniform(-0.003, 0.003))
        return self.t, self.gas, self.burner


# ------------------------------------------------------------------ brain
class Brain:
    INTENTS = {
        "level": ["gas level", "how much gas", "remaining", "left", "percentage", "status", "cylinder", "full"],
        "days": ["how long", "days", "last", "run out", "empty", "predict", "forecast", "when"],
        "leak": ["leak", "smell", "safe", "safety", "danger", "gas smell", "check leak"],
        "weight": ["weight", "kg", "load cell", "hx711", "reading"],
        "book": ["book", "order", "refill", "new cylinder", "buy"],
        "how": ["how does", "work", "explain", "esp32", "project", "utlt", "about"],
        "tips": ["tip", "tips", "save", "efficient", "reduce", "advice"],
        "help": ["help", "what can you do", "commands", "options"],
        "hello": ["hi", "hello", "hey", "yo", "good morning", "good evening"],
        "thanks": ["thanks", "thank you", "cool", "great", "nice"],
    }

    def __init__(self):
        self.history = deque(maxlen=90)  # (time_h, gas_kg, burner_on)

    def feed(self, t, gas, burner):
        self.history.append((t, gas, burner))

    @property
    def gas(self):
        return self.history[-1][1] if self.history else 0.0

    @property
    def pct(self):
        return max(0.0, min(100.0, self.gas / GAS_FULL_KG * 100))

    def burn_rate(self):
        """kg/hour from least-squares slope of gas vs time."""
        n = len(self.history)
        if n < 8:
            return None
        ts, gs = [h[0] for h in self.history], [h[1] for h in self.history]
        mt, mg = sum(ts) / n, sum(gs) / n
        den = sum((x - mt) ** 2 for x in ts)
        if den == 0:
            return None
        return max(0.0, -sum((x - mt) * (y - mg) for x, y in zip(ts, gs)) / den)

    def days_left(self):
        r = self.burn_rate()
        return None if not r or r < 1e-4 else self.gas / r / 24

    def leak_suspected(self):
        h = list(self.history)[-4:]
        if len(h) < 4:
            return False
        drops = [h[i][1] - h[i + 1][1] for i in range(3)]
        return all(not x[2] for x in h) and all(d > 0.02 for d in drops)

    def intent(self, text):
        text = text.lower()
        words = re.findall(r"[a-z']+", text)
        best, best_score = None, 0.0
        for name, keys in self.INTENTS.items():
            score = 0.0
            for k in keys:
                if re.search(r"\b" + re.escape(k) + r"\b", text):
                    score += 2 * len(k.split())
                else:
                    score += sum(1 for w in words if len(w) > 3
                                 and difflib.get_close_matches(w, k.split(), n=1, cutoff=0.8))
            if score > best_score:
                best, best_score = name, score
        return best if best_score >= 1.5 or best == "hello" else None

    def leak_alert(self):
        return ("🚨 **LEAK SUSPECTED** - weight is dropping while the burner is off.\n\n"
                "1. No switches or flames\n2. Open doors and windows\n3. Close the regulator\n"
                f"4. Leave and call **{EMERGENCY_NUMBER}**")

    def reply(self, text):
        i, g, p = self.intent(text), self.gas, self.pct
        if i == "hello":
            return random.choice(["Hey! I'm watching your cylinder 24/7. Ask me anything.",
                                  "Hi there! Want a quick status check?"])
        if i == "level":
            mood = "all good ✅" if p > LOW_GAS_PCT else "running low, time to reorder ⚠️"
            return f"**{g:.2f} kg** of gas left (**{p:.0f}%**) - {mood}"
        if i == "days":
            d, r = self.days_left(), self.burn_rate()
            if d is None:
                return "Still learning your usage pattern - give me a few more readings."
            return (f"At your current usage (~{r * 1000:.0f} g/hour) the gas lasts about **{d:.1f} days**. "
                    f"I'd reorder at around {max(1, d * 0.2):.1f} days left.")
        if i == "leak":
            if self.leak_suspected():
                return self.leak_alert()
            return ("No leak signature right now: weight is stable while the burner is off. "
                    "If you ever smell gas, ventilate and close the regulator first - don't wait for software.")
        if i == "weight":
            return f"Total weight **{g + TARE_KG:.2f} kg** (cylinder {TARE_KG} kg + gas {g:.2f} kg)."
        if i == "book":
            return ("Booking isn't wired to a provider in this demo. Hook your distributor's API "
                    "into `Brain.reply` and I'll auto-order at 20%.")
        if i == "how":
            return ("**UTLT.ai:** 4 load cells → HX711 amplifier → ESP32 → dashboard. "
                    "I turn raw weight into level, burn rate, forecasts and leak alerts.")
        if i == "tips":
            return random.choice([
                "Keep lids on pots - it can cut gas use by around 20%.",
                "Soak dal and rice first; shorter cooking means less gas.",
                "Flame tips should be blue. Yellow means poor burning - clean the burner.",
                "Turn the regulator off at night - the best safety habit."])
        if i == "help":
            return "Try: *gas level*, *days left*, *check for leaks*, *weight*, *tips*, *how does this work*."
        if i == "thanks":
            return "Anytime! 🙌"
        keys = [k for v in self.INTENTS.values() for k in v]
        m = difflib.get_close_matches(text.lower().strip(), keys, n=1, cutoff=0.5)
        return "I didn't quite get that." + (f" Did you mean *{m[0]}*?" if m else "") + " Type **help** for options."


# ------------------------------------------------------------------ state
ss = st.session_state
if "sensor" not in ss:
    ss.sensor, ss.brain = Sensor(), Brain()
    ss.chat = [("assistant", "Hi! I'm the **UTLT.ai** assistant. I'm monitoring your cylinder live. Ask me anything.")]
    ss.open = False
    ss.alert = None                     # "leak" | "low" | None (unread)
    ss.alerted_leak = ss.alerted_low = False
    for _ in range(12):                 # warm-up so forecasts work immediately
        ss.brain.feed(*ss.sensor.read())


def ask(text):
    ss.chat.append(("user", text))
    ss.chat.append(("assistant", ss.brain.reply(text)))
    ss.alert = None
    ss.open = True


# ------------------------------------------------------------------ styling
st.markdown("""
<style>
#MainMenu, footer { visibility: hidden; }

.st-key-ai_widget { position: fixed; bottom: 24px; right: 24px; z-index: 9999; width: 380px; max-width: 92vw; }
.st-key-ai_widget, .st-key-ai_widget p, .st-key-ai_widget li, .st-key-ai_widget span,
.st-key-ai_widget label { color: #e8eefc; }
.st-key-ai_widget [data-testid="stForm"] { border: 0; padding: 0; }
.st-key-ai_widget input { background: #161d33; color: #e8eefc; border-radius: 999px; }
.st-key-ai_widget input::placeholder { color: #8b97b5; }
.st-key-ai_widget [data-baseweb="input"], .st-key-ai_widget [data-baseweb="base-input"] {
    background: #161d33; border-radius: 999px; border: 1px solid #2a3556; }
.st-key-ai_widget [data-baseweb="input"]:focus-within { border-color: #3b82f6; }

/* collapsed: search pill */
.st-key-ai_pill { background: #0f1424; border: 1px solid #2a3556; border-radius: 999px;
    padding: 6px 8px; box-shadow: 0 8px 28px rgba(0,0,0,.4); width: 320px; margin-left: auto; }

/* open: chat panel */
.st-key-ai_panel { background: #0f1424; border: 1px solid #2a3556; border-radius: 18px; padding: 10px 12px 12px;
    box-shadow: 0 16px 48px rgba(0,0,0,.5); }
.st-key-ai_panel [data-testid="stChatMessage"] { background: #1f2a44; border-radius: 14px; }

/* round buttons */
.st-key-ai_go button, .st-key-ai_send button {
    width: 40px; height: 40px; min-height: 40px; padding: 0; border-radius: 50%; border: 0;
    background: #3b82f6; color: #fff; font-weight: 700; }
.st-key-ai_go button p, .st-key-ai_send button p { color: #fff; }
.st-key-ai_close button { background: transparent; border: 0; color: #8b97b5; }
.st-key-ai_widget [class*="st-key-chip_"] button { background: #161d33; border: 1px solid #2a3556;
    border-radius: 999px; padding: 2px 6px; min-height: 30px; }
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ background monitor (invisible)
@st.fragment(run_every=TICK_SECONDS)
def monitor():
    brain = ss.brain
    brain.feed(*ss.sensor.read())
    p, leak = brain.pct, brain.leak_suspected()
    if leak and not ss.alerted_leak:
        ss.alerted_leak, ss.alert = True, "leak"
        ss.chat.append(("assistant", brain.leak_alert()))
        st.toast("Possible gas leak detected! Open the assistant.", icon="🚨")
    if not leak:
        ss.alerted_leak = False
    if p <= LOW_GAS_PCT and not ss.alerted_low:
        ss.alerted_low, ss.alert = True, ss.alert or "low"
        ss.chat.append(("assistant", f"⚠️ Heads up: only **{p:.0f}%** gas left. Time to book a refill."))
        st.toast(f"Only {p:.0f}% gas left", icon="⚠️")
    if p > LOW_GAS_PCT + 5:
        ss.alerted_low = False

    # pulse the AI button while an alert is unread
    color = {"leak": "#ef4444", "low": "#f59e0b"}.get(ss.alert)
    if color:
        st.markdown(f"""<style>
        .st-key-ai_go button {{ background: {color} !important; animation: utlt 1s infinite; }}
        @keyframes utlt {{ 0%,100% {{ box-shadow: 0 0 0 0 {color}99; }} 50% {{ box-shadow: 0 0 0 10px {color}00; }} }}
        </style>""", unsafe_allow_html=True)


monitor()

# ------------------------------------------------------------------ YOUR PAGE CONTENT
# st.title("My project")   # <- add your own content here; the AI floats on top

# ------------------------------------------------------------------ floating AI (bottom-right)
with st.container(key="ai_widget"):
    if not ss.open:
        # collapsed: just a search bar
        with st.container(key="ai_pill"):
            with st.form("pill_form", clear_on_submit=True, border=False):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                q = c1.text_input("Ask", placeholder="Ask UTLT.ai anything…", label_visibility="collapsed")
                sent = c2.form_submit_button("AI", key="ai_go")
        if sent:
            if q.strip():
                ask(q.strip())
            ss.open, ss.alert = True, None
            st.rerun()
    else:
        with st.container(key="ai_panel"):
            h1, h2 = st.columns([6, 1], vertical_alignment="center")
            h1.markdown(f"**UTLT.ai Assistant** &nbsp; <small>{ss.brain.pct:.0f}% • {ss.brain.gas:.1f} kg</small>",
                        unsafe_allow_html=True)
            if h2.button("✕", key="ai_close"):
                ss.open = False
                st.rerun()

            with st.container(height=300, border=False):
                for role, msg in ss.chat[-8:]:
                    with st.chat_message(role):
                        st.markdown(msg)

            chips = [("Level", "gas level"), ("Days", "how many days left"), ("Leaks?", "check for leaks"), ("Tips", "tips")]
            for col, (label, query) in zip(st.columns(4), chips):
                if col.button(label, key=f"chip_{label}", use_container_width=True):
                    ask(query)
                    st.rerun()

            with st.form("chat_form", clear_on_submit=True, border=False):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                q = c1.text_input("Ask", placeholder="Ask UTLT.ai anything…", label_visibility="collapsed")
                sent = c2.form_submit_button("➤", key="ai_send")
            if sent and q.strip():
                ask(q.strip())
                st.rerun()
