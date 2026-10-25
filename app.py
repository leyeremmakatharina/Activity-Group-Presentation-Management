import html
import io
import json
import os
import random
import re
import secrets
import threading
from pathlib import Path

import altair as alt
import pandas as pd
import qrcode
import streamlit as st

st.set_page_config(page_title="Chip Game", page_icon="🎲")

COLORS = [("Red", "#e5484d"), ("Blue", "#3b82f6"), ("Green", "#22a06b"),
          ("Yellow", "#f5c518"), ("Purple", "#8b5cf6")]
TEAMS, NCOL, CHIPS = 16, 5, 5
PHASES = ["round1", "table", "task", "round2", "results"]
PHASE_LABEL = {
    "round1": "1. Round 1: chips (same color vs. different color)",
    "table": "2. Show table numbers",
    "task": "3. Team task: best food at the university",
    "round2": "4. Round 2: chips (own team vs. same color)",
    "results": "5. Close game",
}
TEAM_TEMPLATES = ["Team {f}", "The {f} Crew", "{f} Squad", "{f} United",
                  "The Mighty {f}", "{f} Legends"]
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
             "order": random.sample(range(TEAMS), TEAMS), "people": {}, "teams": {}}
    try:
        data = json.loads(STATE_FILE.read_text())
        store.update(phase=data["phase"], order=data["order"], people=data["people"],
                     teams=data.get("teams", {}))
    except Exception:
        pass
    return store


S = get_store()


def save_state():
    try:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"phase": S["phase"], "order": S["order"],
                                   "people": S["people"], "teams": S["teams"]}))
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


def clean_food(text):
    text = re.sub(r"[^\w\s\-&'.]|_", "", text or "")
    text = " ".join(text.split())[:30]
    return text[:1].upper() + text[1:]


def make_team_name(food):
    # Always returns a name that no other team has, even if several teams pick
    # the same food.
    used = {t["name"].lower() for t in S["teams"].values()}
    for tpl in TEAM_TEMPLATES:
        name = tpl.format(f=food)
        if name.lower() not in used:
            return name
    i = 2
    while f"Team {food} {i}".lower() in used:
        i += 1
    return f"Team {food} {i}"


def submit_team(pid, food):
    with S["lock"]:
        key = str(S["people"][pid]["team"])
        if key not in S["teams"]:  # the first submission of a team counts
            S["teams"][key] = {"food": food, "name": make_team_name(food),
                               "by": S["people"][pid]["name"]}
            save_state()
        return S["teams"][key]


def team_name(p):
    t = S["teams"].get(str(p["team"]))
    return t["name"] if t else f"Team {p['team'] + 1}"


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


def team_task(pid):
    p = S["people"][pid]
    t = S["teams"].get(str(p["team"]))
    st.subheader("Team task")
    if t is None:
        st.write("Discuss with your team for **1 to 2 minutes**: what is the **best food "
                 "you can buy at the university?** Agree on one answer and type it in. "
                 "Only one person per team needs to submit.")
        food = st.text_input("Best food at the university", max_chars=30,
                             placeholder="e.g. Currywurst", key=f"food_{pid}")
        if st.button("Submit for our team", type="primary", key=f"food_btn_{pid}"):
            clean = clean_food(food)
            if not clean:
                st.error("Please enter a food.")
            else:
                submit_team(pid, clean)
                st.rerun()
    else:
        st.write(f"Your team chose **{html.escape(t['food'])}**. Your team name is:")
        st.markdown(
            f'<div style="background:#14202b;color:#fff;padding:24px;border-radius:14px;'
            f'text-align:center;font-size:1.8rem;font-weight:800">{html.escape(t["name"])}</div>',
            unsafe_allow_html=True)
        st.write("")
        st.write("Please wait for the next step.")


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
        st.write("Go to this table and wait for the next step.")
    elif phase == "task":
        st.caption(f"Your table: {p['team'] + 1}")
        team_task(pid)
    elif phase == "round2":
        tname = team_name(p)
        st.caption(f"Your table: {p['team'] + 1}  |  Your team: {html.escape(tname)}")
        if p["r2"] is None:
            st.subheader("Round 2")
            a = chip_choice(f"r2_{pid}",
                            f"someone with your color ({cname}) from a different team",
                            f"someone from your team **“{html.escape(tname)}”**")
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


COLS = ["name", "table", "team_name", "color", "r1_same_color", "r1_different_color",
        "r2_own_team", "r2_same_color_other_team"]


def get_df():
    with S["lock"]:
        people = list(S["people"].values())
    rows = []
    for q in people:
        r1, r2 = q["r1"], q["r2"]
        rows.append({"name": q["name"], "table": q["team"] + 1, "team_name": team_name(q),
                     "color": COLORS[q["color"]][0],
                     "r1_same_color": r1,
                     "r1_different_color": None if r1 is None else CHIPS - r1,
                     "r2_own_team": None if r2 is None else CHIPS - r2,
                     "r2_same_color_other_team": r2})
    df = pd.DataFrame(rows, columns=COLS)
    for c in COLS[4:]:
        df[c] = pd.to_numeric(df[c])
    return df


@st.fragment(run_every=POLL_SECONDS)
def stats_view():
    df = get_df()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Joined", len(df))
    c2.metric("Round 1 done", int(df["r1_same_color"].notna().sum()))
    c3.metric("Teams with name", len(S["teams"]))
    c4.metric("Round 2 done", int(df["r2_same_color_other_team"].notna().sum()))


def pct(x):
    return f"{x / CHIPS * 100:.0f}%"


def result_chart(m1, m2_team, m2_color):
    rows = [{"round": "Round 1", "choice": "Same color", "chips": m1,
             "group": "in-group", "label": f"{m1:.1f}"},
            {"round": "Round 1", "choice": "Different color", "chips": CHIPS - m1,
             "group": "other", "label": f"{CHIPS - m1:.1f}"}]
    if m2_team is not None:
        rows += [{"round": "Round 2", "choice": "Own team", "chips": m2_team,
                  "group": "in-group", "label": f"{m2_team:.1f}"},
                 {"round": "Round 2", "choice": "Same color, other team", "chips": m2_color,
                  "group": "other", "label": f"{m2_color:.1f}"}]
    df = pd.DataFrame(rows)
    x = alt.X("choice:N", title=None, sort=None,
              axis=alt.Axis(labelAngle=0, labelLimit=110, labelFontSize=13))
    y = alt.Y("chips:Q", title="Average chips (of 5)",
              scale=alt.Scale(domain=[0, CHIPS]))
    color = alt.Color("group:N", legend=None,
                      scale=alt.Scale(domain=["in-group", "other"],
                                      range=["#2f6fdd", "#b8c0cc"]))
    bars = alt.Chart().mark_bar(size=70).encode(x=x, y=y, color=color)
    text = alt.Chart().mark_text(dy=-8, fontSize=18, fontWeight="bold").encode(
        x=x, y=y, text="label:N")
    chart = (alt.layer(bars, text, data=df).properties(width=230, height=300)
             .facet(column=alt.Column("round:N", title=None, sort=None,
                                      header=alt.Header(labelFontSize=18))))
    st.altair_chart(chart)


@st.fragment(run_every=POLL_SECONDS)
def results_view():
    df = get_df()
    r1 = df["r1_same_color"].dropna()
    r2c = df["r2_same_color_other_team"].dropna()
    r2t = df["r2_own_team"].dropna()
    if r1.empty:
        st.info("No answers yet.")
        return
    m1 = float(r1.mean())
    has2 = len(r2t) > 0
    m2t = float(r2t.mean()) if has2 else None
    m2c = float(r2c.mean()) if has2 else None

    st.subheader("Where did the chips go?")
    result_chart(m1, m2t, m2c)
    st.caption("Blue bars: the option that favors people like me "
               "(same color in Round 1, own team in Round 2). 5 chips per person.")

    both = df.dropna(subset=["r1_same_color", "r2_own_team"])
    more_team = int((both["r2_own_team"] > both["r1_same_color"]).sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Round 1: chips to same color", f"{m1:.1f} of {CHIPS}", help=f"n = {len(r1)}")
    c2.metric("Round 2: chips to own team", f"{m2t:.1f} of {CHIPS}" if has2 else "–",
              help=f"n = {len(r2t)}")
    c3.metric("Gave more to team than to same color",
              f"{more_team} of {len(both)}" if has2 else "–",
              help="Per person: chips to own team in Round 2 compared with chips "
                   "to the same color in Round 1.")
    st.write(f"**Round 1:** {pct(m1)} of all chips went to someone with the same color.")
    if has2:
        st.write(f"**Round 2:** {pct(m2t)} of all chips went to someone from the own team, "
                 f"only {pct(m2c)} to the same color on another team.")


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
            foods = ["Pizza", "Pizza", "Currywurst", "Pasta", "Doener", "Schnitzel"]
            for i in range(20):
                pid = join(f"Test {len(S['people']) + 1}")
                answer(pid, "r1", random.randint(0, CHIPS))
                answer(pid, "r2", random.randint(0, CHIPS))
                submit_team(pid, random.choice(foods))
            st.rerun()
        if st.checkbox("I want to reset the game (deletes all players and answers)"):
            if st.button("Reset now"):
                with S["lock"]:
                    S["people"].clear()
                    S["teams"].clear()
                    S["phase"] = "round1"
                    random.shuffle(S["order"])
                    save_state()
                st.rerun()

    with t_res:
        results_view()
        df = get_df()
        st.download_button("Download CSV", df.to_csv(index=False), "chip_game_results.csv",
                           "text/csv")
        with st.expander("Team names"):
            with S["lock"]:
                trows = [{"table": int(k) + 1, "food": v["food"], "team_name": v["name"],
                          "entered_by": v["by"]} for k, v in S["teams"].items()]
            if trows:
                st.dataframe(pd.DataFrame(trows).sort_values("table"))
            else:
                st.write("No team has entered a food yet.")
        with st.expander("All players"):
            st.dataframe(df.sort_values(["table", "color"]))


if st.query_params.get("admin") is not None:
    admin()
else:
    participant()
