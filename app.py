import html
import io
import json
import os
import random
import secrets
import threading
from pathlib import Path

import pandas as pd
import qrcode
import streamlit as st

st.set_page_config(page_title="Chip Game", page_icon="🎲")

COLORS = [("Red", "#e5484d"), ("Blue", "#3b82f6"), ("Green", "#22a06b"),
          ("Yellow", "#f5c518"), ("Purple", "#8b5cf6")]
TEAMS, NCOL, CHIPS = 16, 5, 5
PHASES = ["round1", "table", "round2", "results"]
PHASE_LABEL = {
    "round1": "1. Round 1 (same vs. different color)",
    "table": "2. Show table numbers",
    "round2": "3. Round 2 (teammate vs. same color)",
    "results": "4. Close game",
}
POLL_SECONDS = 4
STATE_FILE = Path(__file__).with_name("state.json")

try:
    ADMIN_PIN = str(st.secrets["ADMIN_PIN"])
    PIN_IS_DEFAULT = False
except Exception:
    ADMIN_PIN = "1234"
    PIN_IS_DEFAULT = True


@st.cache_resource
def get_store():
    # One shared object for every visitor of this app. It is also backed up to
    # a file, so a crash or restart of the app process does not lose the game.
    store = {"lock": threading.RLock(), "phase": "round1",
             "order": random.sample(range(TEAMS), TEAMS), "people": {}}
    try:
        data = json.loads(STATE_FILE.read_text())
        store.update(phase=data["phase"], order=data["order"], people=data["people"])
    except Exception:
        pass
    return store


S = get_store()


def save_state():
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"phase": S["phase"], "order": S["order"],
                                   "people": S["people"]}))
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def join(name):
    with S["lock"]:
        n = len(S["people"])
        r, p = divmod(n, TEAMS)
        pid = secrets.token_hex(4)
        # Teams are filled one person at a time in a shuffled order; the color
        # shifts every round, so each team gets one person per color and colors
        # stay balanced even if fewer than 80 people join. More than 80 people
        # simply makes some teams bigger.
        S["people"][pid] = {"name": name, "team": S["order"][p],
                            "color": (p + r) % NCOL, "r1": None, "r2": None}
        save_state()
        return pid


def answer(pid, key, value):
    with S["lock"]:
        if S["people"][pid][key] is None:
            S["people"][pid][key] = value
            save_state()


def set_phase(ph):
    with S["lock"]:
        S["phase"] = ph
        save_state()


def teammate(pid):
    me = S["people"][pid]
    mates = [q for k, q in S["people"].items() if k != pid and q["team"] == me["team"]]
    if not mates:
        return None
    return sorted(mates, key=lambda q: (q["color"] - me["color"]) % NCOL)[0]


def banner(ci, text):
    hexc = COLORS[ci][1]
    fg = "#000" if ci == 3 else "#fff"
    st.markdown(
        f'<div style="background:{hexc};color:{fg};padding:26px;border-radius:14px;'
        f'text-align:center;font-size:2rem;font-weight:800">{text}</div>',
        unsafe_allow_html=True)


def chip_choice(key, label_a, label_b):
    ka, kb = f"{key}_a", f"{key}_b"
    options = list(range(CHIPS + 1))

    def sync(src, dst):
        v = st.session_state.get(src)
        if v is not None:
            st.session_state[dst] = CHIPS - v

    st.write(f"You have **{CHIPS} chips**. Give all of them away, split between two people.")
    st.markdown(f"**A:** {label_a}")
    st.radio("How many chips go to A?", options, index=None, horizontal=True,
             key=ka, on_change=sync, args=(ka, kb))
    st.markdown(f"**B:** {label_b}")
    st.radio("How many chips go to B?", options, index=None, horizontal=True,
             key=kb, on_change=sync, args=(kb, ka))
    st.caption(f"The two numbers always add up to {CHIPS}.")
    if st.button("Submit", type="primary", key=f"{key}_submit"):
        a = st.session_state.get(ka)
        if a is None:
            st.error("Please choose how many chips go to A or B.")
        else:
            return int(a)
    return None


@st.fragment(run_every=POLL_SECONDS)
def play(pid):
    p = S["people"].get(pid)
    if p is None:
        st.warning("The game was reset. Please reload this page to join again.")
        return
    phase = S["phase"]
    cname = COLORS[p["color"]][0]
    banner(p["color"], f"You are {cname}")
    st.write("")

    if p["r1"] is None and phase in ("round1", "table"):
        st.subheader("Round 1")
        a = chip_choice(f"r1_{pid}", f"someone with your color ({cname})",
                        "someone with a different color")
        if a is not None:
            answer(pid, "r1", a)
            st.rerun()
        return

    if phase == "round1":
        st.success("Thanks! Please wait for the next step.")
    elif phase == "table":
        st.subheader("Your table")
        st.markdown(
            f'<div style="text-align:center;font-size:4rem;font-weight:800">{p["team"] + 1}</div>',
            unsafe_allow_html=True)
        st.write("Go to this table. Your team will play a game together.")
    elif phase == "round2":
        st.caption(f"Your table: {p['team'] + 1}")
        if p["r2"] is None:
            st.subheader("Round 2")
            tm = teammate(pid)
            label_b = (f"**{html.escape(tm['name'])}**, your teammate ({COLORS[tm['color']][0]})"
                       if tm else "a teammate from your table")
            a = chip_choice(f"r2_{pid}",
                            f"someone with your color ({cname}) from a different team",
                            label_b)
            if a is not None:
                answer(pid, "r2", a)
                st.rerun()
        else:
            st.success("Thanks! Please wait for the results.")
    else:
        st.success("Thank you for playing! Look at the screen for the results.")


def participant():
    pid = st.query_params.get("p")
    if pid and pid in S["people"]:
        play(pid)
        return
    st.title("🎲 Chip Game")
    if pid:
        st.warning("We could not find your earlier session. Please enter your name again.")
    st.write("Enter your name to join.")
    with st.form("join"):
        name = st.text_input("Your name", max_chars=30)
        ok = st.form_submit_button("Join", type="primary")
    if ok:
        name = name.strip()
        if not name:
            st.error("Please enter your name.")
            return
        st.query_params["p"] = join(name)
        st.rerun()


def get_df():
    with S["lock"]:
        people = list(S["people"].values())
    rows = [{"name": q["name"], "team": q["team"] + 1, "color": COLORS[q["color"]][0],
             "round1_chips_same_color": q["r1"], "round2_chips_same_color_other_team": q["r2"]}
            for q in people]
    cols = ["name", "team", "color", "round1_chips_same_color",
            "round2_chips_same_color_other_team"]
    df = pd.DataFrame(rows, columns=cols)
    for c in cols[3:]:
        df[c] = pd.to_numeric(df[c])
    return df


@st.fragment(run_every=POLL_SECONDS)
def stats_view():
    df = get_df()
    c1, c2, c3 = st.columns(3)
    c1.metric("Joined", len(df))
    c2.metric("Round 1 done", int(df["round1_chips_same_color"].notna().sum()))
    c3.metric("Round 2 done", int(df["round2_chips_same_color_other_team"].notna().sum()))


@st.fragment(run_every=POLL_SECONDS)
def results_view():
    df = get_df()
    r1 = df["round1_chips_same_color"].dropna()
    r2 = df["round2_chips_same_color_other_team"].dropna()
    if r1.empty:
        st.info("No answers yet.")
        return
    both = df.dropna(subset=["round1_chips_same_color", "round2_chips_same_color_other_team"])
    diff = both["round2_chips_same_color_other_team"] - both["round1_chips_same_color"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Round 1: avg chips to same color", f"{r1.mean():.2f}", help=f"n = {len(r1)}")
    c2.metric("Round 2: avg chips to same color", f"{r2.mean():.2f}" if len(r2) else "–",
              help=f"n = {len(r2)}")
    c3.metric("Change per person", f"{diff.mean():+.2f}" if len(diff) else "–",
              help=f"{int((diff < 0).sum())} of {len(diff)} gave less to the same color")
    st.caption(f"Neutral would be {CHIPS / 2:.1f} of {CHIPS} chips.")
    chart = pd.DataFrame({"Avg chips to same color": [r1.mean(), r2.mean() if len(r2) else 0]},
                         index=["Round 1", "Round 2"])
    st.bar_chart(chart, y_label="Chips (of 5)")
    if len(r2):
        st.write(f"Round 2: on average **{CHIPS - r2.mean():.2f}** chips went to the teammate.")


def admin():
    st.title("Admin")
    pin = st.sidebar.text_input("Admin PIN", type="password")
    if pin != ADMIN_PIN:
        st.info("Enter the admin PIN in the sidebar.")
        return
    if PIN_IS_DEFAULT:
        st.warning("You are using the default PIN. Set ADMIN_PIN in the app secrets.")
    t_qr, t_ctl, t_res = st.tabs(["QR code", "Control", "Results"])

    with t_qr:
        url = st.text_input("Public app URL", placeholder="https://your-app.streamlit.app")
        if url.strip():
            buf = io.BytesIO()
            qrcode.make(url.strip()).save(buf, format="PNG")
            st.image(buf.getvalue(), width=420)
            st.caption("Show this on the projector. Everyone scans it with their phone.")

    with t_ctl:
        st.write(f"Current step: **{PHASE_LABEL[S['phase']]}**")
        for ph in PHASES:
            if st.button(PHASE_LABEL[ph], key=f"ph_{ph}",
                         type="primary" if ph == S["phase"] else "secondary"):
                set_phase(ph)
                st.rerun()
        stats_view()
        st.divider()
        st.write("**Testing**")
        if st.button("Add 20 test players with random answers"):
            for i in range(20):
                pid = join(f"Test {len(S['people']) + 1}")
                answer(pid, "r1", random.randint(0, CHIPS))
                answer(pid, "r2", random.randint(0, CHIPS))
            st.rerun()
        if st.checkbox("I want to reset the game (deletes all players and answers)"):
            if st.button("Reset now"):
                with S["lock"]:
                    S["people"].clear()
                    S["phase"] = "round1"
                    random.shuffle(S["order"])
                    save_state()
                st.rerun()

    with t_res:
        results_view()
        df = get_df()
        st.download_button("Download CSV", df.to_csv(index=False), "chip_game_results.csv",
                           "text/csv")
        with st.expander("All players"):
            st.dataframe(df.sort_values(["team", "color"]))


if st.query_params.get("admin") is not None:
    admin()
else:
    participant()
