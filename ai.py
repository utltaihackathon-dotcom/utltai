"""
UTLT.ai Assistant (Streamlit edition)
A floating AI chat bubble pinned to the bottom-right of the page, plus a live
LPG cylinder dashboard. Pure Python, no API keys.

Install:  pip install "streamlit>=1.39"
Run:      streamlit run utlt_ai_streamlit.py

Real hardware: set ESP32_URL to an endpoint returning {"weight": 21.4, "burner": true}
"""
import difflib
import json
import random
import re
import urllib.request
from collections import deque

import pandas as pd
import streamlit as st

# ------------------------------------------------------------------ config
ESP32_URL = None            # e.g. "http://192.168.1.50/data"  (None = simulator)
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
        "tips": ["tip", "save", "efficient", "reduce", "advice"],
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
                if k in text:
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
            return ("**UTLT.ai:** 4 load cells -> HX711 amplifier -> ESP32 -> dashboard. "
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
        m = difflib.get_close_matches(text.lower(), keys, n=1, cutoff=0.5)
        return "I didn't quite get that." + (f" Did you mean *{m[0]}*?" if m else "") + " Type **help** for options."


# ------------------------------------------------------------------ state
ss = st.session_state
if "sensor" not in ss:
    ss.sensor, ss.brain = Sensor(), Brain()
    ss.log = deque(maxlen=200)          # chart rows
    ss.chat = [("assistant", "Hi! I'm the **UTLT.ai** assistant. I'm monitoring your cylinder live. Ask me anything.")]
    ss.alert = None                     # "leak" | "low" | None (unread)
    ss.alerted_leak = ss.alerted_low = False
    for _ in range(12):                 # warm-up so predictions work immediately
        ss.brain.feed(*ss.sensor.read())


def ask(text):
    ss.chat.append(("user", text))
    ss.chat.append(("assistant", ss.brain.reply(text)))
    ss.alert = None


# ------------------------------------------------------------------ floating widget CSS
pulse = {"leak": "#ef4444", "low": "#f59e0b"}.get(ss.alert, "#3b82f6")
st.markdown(f"""
<style>
.st-key-ai_widget {{ position: fixed; bottom: 24px; right: 24px; z-index: 9999; width: auto; }}
.st-key-ai_widget button {{
    width: 64px; height: 64px; border-radius: 50%; border: none; color: white; font-weight: 700;
    font-size: 18px; background: {pulse}; box-shadow: 0 6px 20px rgba(0,0,0,.35);
    {"animation: utltpulse 1s infinite;" if ss.alert else ""}
}}
.st-key-ai_widget button:hover {{ transform: scale(1.06); }}
@keyframes utltpulse {{ 0%,100% {{ box-shadow: 0 0 0 0 {pulse}99; }} 50% {{ box-shadow: 0 0 0 14px {pulse}00; }} }}
div[data-testid="stPopoverBody"] {{ width: 390px; max-width: 92vw; border-radius: 16px; }}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ dashboard (live)
st.title("🔥 UTLT.ai Smart LPG Monitor")


@st.fragment(run_every=TICK_SECONDS)
def dashboard():
    brain, sensor = ss.brain, ss.sensor
    t, gas, burner = sensor.read()
    brain.feed(t, gas, burner)
    ss.log.append({"time (h)": round(t, 2), "gas (kg)": round(gas, 3)})

    leak, p = brain.leak_suspected(), brain.pct
    if leak and not ss.alerted_leak:
        ss.alerted_leak, ss.alert = True, "leak"
        ss.chat.append(("assistant", brain.leak_alert()))
        st.toast("Possible gas leak detected! Open the assistant.", icon="🚨")
    if not leak:
        ss.alerted_leak = False
    if p <= LOW_GAS_PCT and not ss.alerted_low:
        ss.alerted_low = True
        ss.alert = ss.alert or "low"
        ss.chat.append(("assistant", f"⚠️ Heads up: only **{p:.0f}%** gas left. Time to book a refill."))
        st.toast(f"Only {p:.0f}% gas left", icon="⚠️")
    if p > LOW_GAS_PCT + 5:
        ss.alerted_low = False

    d = brain.days_left()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Gas left", f"{brain.gas:.2f} kg", f"{p:.0f}%")
    c2.metric("Total weight", f"{brain.gas + TARE_KG:.2f} kg")
    c3.metric("Days left (forecast)", f"{d:.1f}" if d else "learning…")
    c4.metric("Burner", "ON 🔥" if burner else "OFF")
    st.progress(int(p) / 100, text="Cylinder level")
    if leak:
        st.error("Possible leak: weight is falling while the burner is off.")
    st.line_chart(pd.DataFrame(ss.log), x="time (h)", y="gas (kg)", height=280)


dashboard()

with st.sidebar:
    st.subheader("Demo controls")
    ss.sensor.leak = st.toggle("Simulate a gas leak", value=ss.sensor.leak)
    if st.button("Refill cylinder"):
        ss.sensor.gas = GAS_FULL_KG
        ss.alerted_low = False
    st.caption("Using ESP32 at " + ESP32_URL if ESP32_URL else "Using built-in simulator.")

# ------------------------------------------------------------------ floating chat bubble (bottom-right)
with st.container(key="ai_widget"):
    with st.popover("AI"):
        st.markdown("**UTLT.ai Assistant**")
        box = st.container(height=320)
        with box:
            for role, msg in ss.chat:
                with st.chat_message(role):
                    st.markdown(msg)
        cols = st.columns(4)
        for col, label in zip(cols, ["Level", "Days left", "Leaks?", "Tips"]):
            if col.button(label, use_container_width=True, key=f"chip_{label}"):
                ask({"Level": "gas level", "Days left": "how many days left",
                     "Leaks?": "check for leaks", "Tips": "tips"}[label])
                st.rerun()
        with st.form("ask_form", clear_on_submit=True, border=False):
            q = st.text_input("Ask me anything", label_visibility="collapsed", placeholder="Ask me anything…")
            if st.form_submit_button("Send", use_container_width=True) and q.strip():
                ask(q.strip())
                st.rerun()
