"""
UTLT.ai Assistant - Python only (Streamlit).
A floating search bar in the bottom-right that opens a chat panel. It knows your water data
(status, goal, forecasts, patterns, leaks) and your LPG cylinder. No API keys.

Files (keep them in the same folder):
    ai.py            <- this file (the UI)
    utlt_brain.py    <- the analytics + prediction brain
    readings.json    <- OPTIONAL: your real readings (see below). Without it, demo data is used.
requirements.txt:    streamlit>=1.39

Run:  streamlit run ai.py

Using your REAL app data: in the UTLT.ai web app, open the browser console (F12) and run
    copy(JSON.stringify(UTLT.getState().readings))
then paste the result into a file named readings.json next to ai.py.
(A list like [{"recordedAt": "...+05:30", "litres": 12.5, "category": "Bath"}, ...] is what it reads.)
"""
import os

import streamlit as st

from utlt_brain import Assistant, load_file

TICK_SECONDS = 2.0
DEMO_NIGHT_LEAK = False   # True = demo an overnight water leak for the judges
HERE = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="UTLT.ai", page_icon="💧", layout="wide")

# ------------------------------------------------------------------ state
ss = st.session_state
if "ai" not in ss:
    readings = load_file(os.path.join(HERE, "readings.json"))
    ss.ai = Assistant(readings=readings or None, demo_night_leak=DEMO_NIGHT_LEAK)
    ss.chat = [("assistant", "Hi! I'm the **UTLT.ai** assistant. I've read your data - here's where things stand:\n\n"
                             + ss.ai.greeting())]
    ss.open = False
    ss.alert = None  # "leak" | "warn" | None (unread)


def ask(text):
    ss.chat.append(("user", text))
    ss.chat.append(("assistant", ss.ai.reply(text)))
    ss.alert = None
    ss.open = True


# ------------------------------------------------------------------ styling
st.markdown("""
<style>
#MainMenu, footer { visibility: hidden; }

.st-key-ai_widget { position: fixed; bottom: 24px; right: 24px; z-index: 9999; width: 400px; max-width: 92vw; }
.st-key-ai_widget, .st-key-ai_widget p, .st-key-ai_widget li, .st-key-ai_widget span,
.st-key-ai_widget label, .st-key-ai_widget strong { color: #e8eefc; }
.st-key-ai_widget [data-testid="stForm"] { border: 0; padding: 0; }
.st-key-ai_widget input { background: #161d33; color: #e8eefc; border-radius: 999px; }
.st-key-ai_widget input::placeholder { color: #8b97b5; }
.st-key-ai_widget [data-baseweb="input"], .st-key-ai_widget [data-baseweb="base-input"] {
    background: #161d33; border-radius: 999px; border: 1px solid #2a3556; }
.st-key-ai_widget [data-baseweb="input"]:focus-within { border-color: #3b82f6; }

/* collapsed: search pill */
.st-key-ai_pill { background: #0f1424; border: 1px solid #2a3556; border-radius: 999px;
    padding: 6px 8px; box-shadow: 0 8px 28px rgba(0,0,0,.4); width: 330px; margin-left: auto; }

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
    ai = ss.ai
    ai.tick()
    for _key, kind, text in ai.alerts():
        ss.chat.append(("assistant", text))
        ss.alert = "leak" if kind == "leak" else (ss.alert or "warn")
        st.toast(text.split("\n")[0].replace("**", "")[:120], icon="🚨" if kind == "leak" else "⚠️")

    color = {"leak": "#ef4444", "warn": "#f59e0b"}.get(ss.alert)
    if color:  # pulse the AI button while an alert is unread
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
            w = ss.ai.w
            h1, h2 = st.columns([6, 1], vertical_alignment="center")
            h1.markdown(f"**UTLT.ai Assistant** &nbsp; <small>💧 {w.so_far:.0f}/{ss.ai.goal} L today</small>",
                        unsafe_allow_html=True)
            if h2.button("✕", key="ai_close"):
                ss.open = False
                st.rerun()

            with st.container(height=360, border=False):
                for role, msg in ss.chat[-6:]:
                    with st.chat_message(role):
                        st.markdown(msg)

            chips = [("Status", "status"), ("Predict", "predict the next 7 days"),
                     ("Patterns", "my patterns"), ("Tips", "tips")]
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
