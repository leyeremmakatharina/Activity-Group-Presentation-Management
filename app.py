"""
Chip game for the presentation about "Cultural diversity, helping behaviour and shared team identity"
(based on the minimal group paradigm, Tajfel et al., 1971)

Flow for every participant (all on their own phone):
  1. Join       -> app assigns one of 4 colours (a purely visible, outward feature) and one of 9 tables
  2. Round 1    -> split 5 chips between two ANONYMOUS participants (same colour vs. different colour)
                   + 1 question on how connected they feel to their colour group
  3. Team time  -> go to the assigned table (one person per colour), find something you share in your
                   leisure time, choose a team name based on it (= shared team identity)
  4. Round 2    -> split 5 chips between (same colour, other team) and (someone from your own team)
                   + 1 question on how connected they feel to their team
  5. Done       -> thank-you screen
The HOST starts every step for everybody (dashboard > Live > Host control), so nobody finishes early.

Host dashboard: open the app URL with  ?admin=1  and enter the password
(set ADMIN_PASSWORD in the settings block below).
"""

import html
import json
import math
import os
import random
import statistics
import threading
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------------------------
N_CHIPS = 5
BASELINE = N_CHIPS / 2  # 2.5 chips = no preference
AUTO_TABLES = True  # True: app assigns the table (guarantees one person per colour at each table)
N_TABLES = 9  # number of tables/teams: 9 tables x 4 colours = 36 people (35 to 37 people work fine)
CONTROL_CONDITION = False  # True: even tables get a control version of round 2
DATA_FILE = Path("chip_game_data.json")
STAGE_FILE = Path("chip_game_stage.json")
STAGES = ["r1", "team", "r2"]  # the host moves everybody from one step to the next

COLOURS = {  # name: (background, text colour)
    "Red": ("#e74c3c", "#ffffff"),
    "Blue": ("#3498db", "#ffffff"),
    "Green": ("#27ae60", "#ffffff"),
    "Yellow": ("#f1c40f", "#222222"),
}  # 4 colours -> every table of about 4 people has one person per colour
COLOUR_NAMES = list(COLOURS)

ADMIN_PASSWORD = "MGTCB2300"  # <- CHANGE THIS: your password for the host dashboard (?admin=1)

st.set_page_config(page_title="Chip Game", page_icon="🪙", layout="centered")


# ----------------------------------------------------------------------------------------------
# Shared storage: one store for all phones, saved to a JSON file in case the app restarts.
# Every change happens under a lock; readers always work on a copy (snapshot), so many people
# can join and play at the same time without errors.
# ----------------------------------------------------------------------------------------------
@st.cache_resource
def get_store():
    store = {"lock": threading.RLock(), "participants": {}, "stage": "r1", "seq": 0}
    if DATA_FILE.exists():
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            loaded = {int(k): v for k, v in raw.items()}
            # ignore an old backup that was made with other settings (e.g. another colour set)
            if all(v.get("colour") in COLOURS for v in loaded.values()):
                store["participants"] = loaded
        except Exception:
            pass
    try:
        meta = json.loads(STAGE_FILE.read_text(encoding="utf-8"))
        if meta.get("stage") in STAGES:
            store["stage"] = meta["stage"]
        store["seq"] = int(meta.get("seq", 0))
    except Exception:
        pass
    return store


store = get_store()


def _save():  # call only while holding the lock
    try:
        tmp = DATA_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(store["participants"], ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, DATA_FILE)  # atomic: the file is never half-written
    except Exception:
        pass


def snapshot():
    with store["lock"]:
        return [dict(p) for p in store["participants"].values()]


def update(p, **fields):
    with store["lock"]:
        p.update(fields)
        _save()


def submit_once(p, flag, **fields):
    """Save an answer only once (protects against double taps)."""
    with store["lock"]:
        if flag in p:
            return False
        p.update(fields)
        _save()
        return True


def clear_all():
    """Delete all participants and answers and go back to Round 1. The id counter is NOT reset,
    so a phone that is still open from before can never be mixed up with a new participant."""
    with store["lock"]:
        store["seq"] = max(store["seq"], max(store["participants"], default=0))
        store["participants"].clear()
        _save()
        set_stage("r1")


def _save_meta():  # call only while holding the lock
    try:
        STAGE_FILE.write_text(
            json.dumps({"stage": store["stage"], "seq": store["seq"]}), encoding="utf-8")
    except Exception:
        pass


def get_stage():
    with store["lock"]:
        return store["stage"]


def set_stage(stage):
    with store["lock"]:
        store["stage"] = stage
        _save_meta()


def team_info(p):
    """Team name of p's table. Any ONE team member can enter it; it then counts for all of them."""
    with store["lock"]:
        for q in store["participants"].values():
            if q.get("table") == p.get("table") and q.get("team_name"):
                if not p.get("team_name"):  # e.g. somebody who joined the table later
                    p["team_name"], p["team_common"] = q["team_name"], q.get("team_common", "")
                    _save()
                return {"name": q["team_name"], "common": q.get("team_common", "")}
    return None


def team_label(p):
    info = team_info(p)
    return info["name"] if info else f"Team {p.get('table')}"


def submit_team(p, common, name):
    """The first member of a table who confirms sets the team name for the whole table."""
    with store["lock"]:
        if team_info(p) is not None:
            return False
        for q in store["participants"].values():
            if q.get("table") == p.get("table"):
                q["team_common"], q["team_name"] = common, name
        _save()
        return True


def state_sig(p):
    """Everything that decides which screen a participant should see."""
    with store["lock"]:
        q = store["participants"].get(p["id"])
        if q is None:
            return None
        info = team_info(q)
        return (store["stage"], "r1_to_same" in q, info["name"] if info else None,
                "r2_to_same" in q)


@st.fragment(run_every=3)
def watch(pid, sig):
    """Invisible: every 3 seconds checks if the screen has to change (host moved on, or a
    team member entered the team name) and then reloads the page for this participant."""
    with store["lock"]:
        q = store["participants"].get(pid)
    if q is None or state_sig(q) != sig:
        st.rerun()


def new_code(used):
    while True:
        code = f"P-{random.randint(100, 999)}"
        if code not in used:
            return code


def join():
    with store["lock"]:
        ps = store["participants"]
        pid = max(max(ps, default=0), store["seq"]) + 1
        store["seq"] = pid
        _save_meta()
        colour = COLOUR_NAMES[(pid - 1) % len(COLOUR_NAMES)]  # round robin -> balanced colours
        table = None
        if AUTO_TABLES:
            # k-th person of a colour sits at table k -> every table has one person of each colour.
            # More people than tables x colours simply start again at table 1 (a table of 5).
            k = sum(1 for q in ps.values() if q["colour"] == colour) + 1
            table = (k - 1) % N_TABLES + 1
        p = {
            "id": pid,
            "code": new_code({q["code"] for q in ps.values()}),
            "colour": colour,
            "table": table,
        }
        ps[pid] = p
        _save()
    return p


def find_by_code(code):
    code = code.strip().upper()
    with store["lock"]:
        for q in store["participants"].values():
            if q["code"].upper() == code:
                return q
    return None


def current_participant():
    pid = st.session_state.get("pid")
    if pid is None:
        raw = st.query_params.get("pid")
        if raw and str(raw).isdigit():
            pid = int(raw)
    with store["lock"]:
        p = store["participants"].get(pid)
    if p is not None:
        st.session_state["pid"] = pid
    elif pid is not None:  # this phone belongs to an old game (after a reset): start fresh
        st.session_state.pop("pid", None)
        if "pid" in st.query_params:
            del st.query_params["pid"]
    return p


# ----------------------------------------------------------------------------------------------
# Recipients: anonymous (code + colour only), chosen randomly by the app
# ----------------------------------------------------------------------------------------------
def pick_recipient(me, same_colour, other_team_only=False):
    candidates = [
        q
        for q in snapshot()
        if q["id"] != me["id"]
        and ((q["colour"] == me["colour"]) == same_colour)
        and (not other_team_only or q.get("table") != me.get("table"))
    ]
    if candidates:
        q = random.choice(candidates)
        return {"code": q["code"], "colour": q["colour"]}
    # fallback (e.g. for the first people who join): invent an anonymous code
    colour = me["colour"] if same_colour else random.choice(
        [c for c in COLOUR_NAMES if c != me["colour"]]
    )
    return {"code": f"P-{random.randint(100, 999)}", "colour": colour}


def get_rec(p, prefix):
    return {"code": p[prefix + "_code"], "colour": p[prefix + "_colour"]}


def set_rec(prefix, rec):
    return {prefix + "_code": rec["code"], prefix + "_colour": rec["colour"]}


# ----------------------------------------------------------------------------------------------
# Small UI helpers
# ----------------------------------------------------------------------------------------------
def banner(p):
    bg, fg = COLOURS[p["colour"]]
    team = f" &nbsp;|&nbsp; Team: <b>{html.escape(p['team_name'])}</b>" if p.get("team_name") else ""
    st.markdown(
        f"<div style='background:{bg};color:{fg};padding:14px 18px;border-radius:12px;"
        f"text-align:center;font-size:1.05rem;'>Your colour: <b>{p['colour']}</b>"
        f" &nbsp;|&nbsp; Your code: <b>{p['code']}</b>{team}</div>",
        unsafe_allow_html=True,
    )
    st.write("")


def recipient_card(title, rec=None, text=None, note=""):
    if rec is not None:
        bg, fg = COLOURS[rec["colour"]]
        body = (
            f"<div style='font-size:1.3rem;font-weight:700;margin-bottom:6px;'>{rec['code']}</div>"
            f"<span style='background:{bg};color:{fg};padding:4px 14px;border-radius:999px;"
            f"font-weight:600;'>{rec['colour']}</span>"
            f"<div style='color:#777;margin-top:8px;font-size:0.9rem;'>{note}</div>"
        )
    else:
        body = f"<div style='font-size:1.05rem;font-weight:600;'>{text}</div>"
    st.markdown(
        f"<div style='border:2px solid #bbb;border-radius:12px;padding:14px;text-align:center;"
        f"margin-bottom:8px;'><div style='color:#777;margin-bottom:6px;'>{title}</div>{body}</div>",
        unsafe_allow_html=True,
    )


def _link(src, dst):
    """When one person's chips are chosen, the other person automatically gets the rest."""
    v = st.session_state.get(src)
    if v is not None:
        st.session_state[dst] = N_CHIPS - v


def chips_ui(prefix, card1, card2):
    """Two cards, each with its own 'How many chips would you give to Person X?' question.
    Returns the number of chips given to Person 1 (None until the participant has chosen)."""
    k1, k2 = f"{prefix}_p1", f"{prefix}_p2"
    options = list(range(N_CHIPS + 1))
    c1, c2 = st.columns(2)
    with c1:
        card1()
        st.radio("How many chips would you give to Person 1?", options, index=None,
                 horizontal=True, key=k1, on_change=_link, args=(k1, k2))
    with c2:
        card2()
        st.radio("How many chips would you give to Person 2?", options, index=None,
                 horizontal=True, key=k2, on_change=_link, args=(k2, k1))
    a = st.session_state.get(k1)
    if a is None:
        st.caption("Choose a number under one of the two persons. "
                   "The remaining chips automatically go to the other person.")
    else:
        st.info(f"Person 1 gets **{a}** 🪙 and Person 2 gets **{N_CHIPS - a}** 🪙. "
                "The rest of your chips automatically goes to the other person.")
    return a


def scale_question(key, label):
    return st.radio(
        label + "  \n(1 = not at all, 7 = very much)",
        options=list(range(1, 8)),
        index=None,
        horizontal=True,
        key=key,
    )


# ----------------------------------------------------------------------------------------------
# Participant screens
# ----------------------------------------------------------------------------------------------
def screen_welcome():
    st.title("🪙 Chip Game")
    st.write(
        "Welcome! In this short game you will make a few quick decisions with **chips**. "
        "There are no right or wrong answers, and everything is anonymous."
    )
    if st.button("Join the game", type="primary"):
        p = join()
        st.session_state["pid"] = p["id"]
        st.query_params["pid"] = str(p["id"])  # keeps you in the game if the page reloads
        st.rerun()
    with st.expander("Already joined? Continue where you stopped"):
        code = st.text_input("Your code (e.g. P-123)", key="resume_code")
        if st.button("Continue"):
            q = find_by_code(code)
            if q is None:
                st.error("Code not found. Please check it or join as a new participant.")
            else:
                st.session_state["pid"] = q["id"]
                st.query_params["pid"] = str(q["id"])
                st.rerun()


def screen_round1(p):
    banner(p)
    st.caption(
        "Your colour is a visible, outward feature. It says nothing about your personality or your interests."
    )
    st.header("Round 1")
    st.write(
        f"You have **{N_CHIPS} chips**. Give them to two other participants in this room: "
        "all to one of them, or split them any way you like. "
        "Participants are anonymous and identified only by a code and a colour."
    )

    if "r1_same_code" not in p:  # choose recipients once, so they stay stable
        update(
            p,
            **set_rec("r1_same", pick_recipient(p, same_colour=True)),
            **set_rec("r1_diff", pick_recipient(p, same_colour=False)),
            r1_first_same=random.random() < 0.5,  # random position (left/right)
        )

    same, diff = get_rec(p, "r1_same"), get_rec(p, "r1_diff")
    first, second = (same, diff) if p["r1_first_same"] else (diff, same)
    a = chips_ui("r1", lambda: recipient_card("Person 1", first), lambda: recipient_card("Person 2", second))
    st.write("")
    conn = scale_question("r1_conn", "How connected do you feel to the other participants with your colour?")

    if st.button("Submit Round 1", type="primary", disabled=a is None or conn is None):
        to_same = a if p["r1_first_same"] else N_CHIPS - a
        submit_once(p, "r1_to_same", r1_to_same=to_same, r1_conn=conn)
        st.rerun()


def screen_team(p):
    banner(p)
    st.header("Team time")
    if AUTO_TABLES:
        st.success(f"Please go to **table {p['table']}** now. You will meet your team there.")
    st.write(
        "At your table you will find people with **all different colours**. Introduce yourselves and "
        "find something you **all have in common regarding your leisure time**, for example a "
        "favourite food, movie, music, hobby, ...  \n"
        "Your colours are only outward features. What you find now is something you **really share**, "
        "and it makes you a team. **What you share is your team name**, so just type it in below."
    )
    common = st.text_input("What do you all have in common? (this is your team name)",
                           max_chars=40, key="team_common")
    name = " ".join(common.split())
    name = name[:1].upper() + name[1:]
    table = p.get("table")
    if not AUTO_TABLES:
        table = st.number_input("Your table number", min_value=1, max_value=99, step=1, key="table_no")

    if st.button("Confirm team name", type="primary", disabled=not name):
        if not AUTO_TABLES:
            update(p, table=int(table))
        submit_team(p, name, name)  # the first entry of a table counts, later ones are ignored
        st.rerun()
    st.caption("Only ONE person per table needs to do this. If several people enter something, "
               "the first entry is used. The host moves everybody on to Round 2.")


def screen_round2(p):
    banner(p)
    st.header("Round 2")
    control = CONTROL_CONDITION and int(p["table"]) % 2 == 0
    st.write(
        f"Again you have **{N_CHIPS} chips**. Give them to two other participants: "
        "all to one of them, or split them any way you like."
    )

    if "r2_same_code" not in p:
        fields = set_rec("r2_same", pick_recipient(p, same_colour=True, other_team_only=True))
        if control:
            fields.update(set_rec("r2_other", pick_recipient(p, same_colour=False, other_team_only=True)))
        update(p, r2_condition="control" if control else "team",
               r2_first_same=random.random() < 0.5, **fields)

    same = get_rec(p, "r2_same")

    def same_card(title):
        recipient_card(title, same, note="from another team")

    if p["r2_condition"] == "control":
        other = get_rec(p, "r2_other")

        def other_card(title):
            recipient_card(title, other, note="from another team")
    else:
        team = html.escape(team_label(p))

        def other_card(title):
            recipient_card(title, text=f"Someone from your own team<br>“{team}”")

    first_same = p["r2_first_same"]
    one = same_card if first_same else other_card
    two = other_card if first_same else same_card
    a = chips_ui("r2", lambda: one("Person 1"), lambda: two("Person 2"))
    st.write("")
    conn = scale_question("r2_conn", "How connected do you feel to your team?")

    if st.button("Submit Round 2", type="primary", disabled=a is None or conn is None):
        to_same = a if first_same else N_CHIPS - a
        submit_once(p, "r2_to_same", r2_to_same=to_same, r2_conn=conn)
        st.rerun()


def screen_done(p):
    banner(p)
    st.header("Thank you! 🎉")
    st.write("You are done. Thank you for taking part!")


def screen_wait(p, text, show_team=False):
    banner(p)
    if show_team:
        st.success(f"Your team: **{html.escape(team_label(p))}** (table {p.get('table')})")
    st.info(text)


# ----------------------------------------------------------------------------------------------
# Statistics helpers
# ----------------------------------------------------------------------------------------------
def values(df, col):
    return df[col].dropna().astype(float).tolist() if col in df else []


def mean_ci(xs):
    m = statistics.mean(xs)
    if len(xs) < 2:
        return m, m, m
    se = statistics.stdev(xs) / math.sqrt(len(xs))
    return m, m - 1.96 * se, m + 1.96 * se


# ----------------------------------------------------------------------------------------------
# Host dashboard (?admin=1)
# ----------------------------------------------------------------------------------------------
def stage_controls():
    st.subheader("Host control")
    cur = get_stage()
    labels = {"r1": "1️⃣ Round 1", "team": "2️⃣ Team time", "r2": "3️⃣ Round 2"}
    cols = st.columns(len(STAGES))
    for col, s in zip(cols, STAGES):
        if col.button(labels[s], key=f"stage_{s}", type="primary" if s == cur else "secondary"):
            set_stage(s)
            st.rerun()
    st.caption("Everybody sees the step you select here. People who are finished wait on a waiting "
               "screen until you start the next step. Start the next step when most people are done "
               "(see the numbers below).")


def reset_controls(key):
    if st.session_state.pop("reset_done", False):
        st.success("The game was reset. All participants and answers are deleted.")
    with st.expander("🗑 Reset game (delete all participants)"):
        st.write("Deletes **all participants and answers** and sets the game back to Round 1. "
                 "All phones go back to the start page. Download the data first if you still "
                 "need it (tab Data).")
        sure = st.checkbox("Yes, delete everything", key=f"reset_ok_{key}")
        if st.button("Reset game now", key=f"reset_btn_{key}", type="primary", disabled=not sure):
            clear_all()
            st.session_state["reset_done"] = True
            st.rerun()


@st.fragment(run_every=5)
def live_counts():
    """Updates itself every 5 seconds, so you can watch the room finish each step."""
    df = pd.DataFrame(snapshot())
    if df.empty:
        st.info("Nobody has joined yet.")
        return
    a, b, c, d = st.columns(4)
    a.metric("Joined", len(df))
    b.metric("Round 1 done", len(values(df, "r1_to_same")))
    n_tables = int(df["table"].nunique()) if "table" in df else 0
    named = int(df.loc[df["team_name"].notna(), "table"].nunique()) if "team_name" in df else 0
    c.metric("Teams named", f"{named} of {n_tables}")
    d.metric("Round 2 done", len(values(df, "r2_to_same")))
    st.caption("This view refreshes automatically every 5 seconds.")


def results_chart(r1, r2):
    order = [
        "Round 1: same colour",
        "Round 1: different colour",
        "Round 2: same colour (other team)",
        "Round 2: own team",
    ]
    rows = []
    for label, kind, xs in [
        (order[0], "Same colour", r1),
        (order[1], "Different colour", [N_CHIPS - x for x in r1]),
        (order[2], "Same colour", r2),
        (order[3], "Own team", [N_CHIPS - x for x in r2]),
    ]:
        m, lo, hi = mean_ci(xs)
        rows.append({"label": label, "kind": kind, "mean": m, "lo": max(lo, 0), "hi": min(hi, N_CHIPS)})
    data = pd.DataFrame(rows)

    y = alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelLimit=260))
    colour = alt.Color(
        "kind:N",
        scale=alt.Scale(domain=["Same colour", "Different colour", "Own team"],
                        range=["#e67e22", "#95a5a6", "#27ae60"]),
        legend=alt.Legend(title=None, orient="bottom"),
    )
    bars = alt.Chart(data).mark_bar(size=34).encode(
        y=y, x=alt.X("mean:Q", scale=alt.Scale(domain=[0, N_CHIPS]), title="Average chips (of 5)"),
        color=colour)
    errs = alt.Chart(data).mark_rule(color="#333", strokeWidth=2).encode(y=y, x="lo:Q", x2="hi:Q")
    labels = alt.Chart(data).mark_text(align="left", dx=6, fontSize=15, fontWeight="bold").encode(
        y=y, x="hi:Q", text=alt.Text("mean:Q", format=".1f"))
    base = alt.Chart(pd.DataFrame({"x": [BASELINE]})).mark_rule(
        strokeDash=[5, 5], color="#000").encode(x="x:Q")
    return (bars + errs + labels + base).properties(height=230, width="container")


def render_results(df):
    both = df.dropna(subset=["r1_to_same", "r2_to_same"]) if (
        "r1_to_same" in df and "r2_to_same" in df) else df.iloc[0:0]
    main = both[both["r2_condition"] == "team"] if len(both) else both
    ctrl = both[both["r2_condition"] == "control"] if len(both) else both

    if len(main) == 0:
        st.info("Results appear as soon as the first participants have finished both rounds.")
        return

    r1 = main["r1_to_same"].astype(int).tolist()  # chips to the same colour in round 1
    r2 = main["r2_to_same"].astype(int).tolist()  # chips to the same colour (other team) in round 2
    n = len(r1)

    # With 5 chips there are no ties: 3 or more chips = "preferred this person"
    fav_col_r1 = [x >= 3 for x in r1]
    fav_team_r2 = [x <= 2 for x in r2]
    n_col = sum(fav_col_r1)
    b = sum(1 for f1, t2 in zip(fav_col_r1, fav_team_r2) if f1 and t2)  # colour -> team
    c = sum(1 for f1, t2 in zip(fav_col_r1, fav_team_r2) if (not f1) and (not t2))  # other -> colour
    pct1, pct2 = 100 * n_col / n, 100 * sum(fav_team_r2) / n

    st.caption(f"Based on {n} participants who finished both rounds.")
    m1, m2 = st.columns(2)
    m1.metric("Round 1: favoured their own colour", f"{pct1:.0f}%")
    m2.metric("Round 2: favoured their own team", f"{pct2:.0f}%")

    st.subheader("How the shared identity changes who gets the chips")
    st.altair_chart(results_chart(r1, r2))
    st.caption("Bars show the average number of chips; black lines show the 95% confidence interval; "
               "the dashed line marks 2.5 chips (no preference).")

    st.subheader("Who switched?")
    table = pd.DataFrame(
        {
            "Round 2: gave more to own team": [
                b, sum(1 for f1, t2 in zip(fav_col_r1, fav_team_r2) if (not f1) and t2)],
            "Round 2: gave more to same colour": [
                sum(1 for f1, t2 in zip(fav_col_r1, fav_team_r2) if f1 and (not t2)), c],
        },
        index=["Round 1: gave more to same colour", "Round 1: gave more to different colour"],
    )
    st.table(table)
    st.caption(f"{b} people switched from their colour to their team, {c} switched in the other direction.")

    diff = [x - y for x, y in zip(r1, r2)]
    st.write(f"On average, participants gave **{statistics.mean(diff):.2f} fewer chips** to their own "
             f"colour in Round 2 than in Round 1.")

    st.subheader("Connectedness (1–7)")
    c1, c2 = values(main, "r1_conn"), values(main, "r2_conn")
    if c1 and c2:
        x, y = st.columns(2)
        x.metric("…to the own colour group (Round 1)", f"{statistics.mean(c1):.2f}")
        y.metric("…to the own team (Round 2)", f"{statistics.mean(c2):.2f}",
                 delta=f"{statistics.mean(c2) - statistics.mean(c1):+.2f}")

    if len(ctrl):
        st.subheader("Control tables")
        to_team = [N_CHIPS - x for x in r2]
        to_other = [N_CHIPS - x for x in values(ctrl, "r2_to_same")]
        st.write(
            f"Chips to a person with a different colour from another team: "
            f"**{statistics.mean(to_other):.2f}** (control) vs. to the own team: "
            f"**{statistics.mean(to_team):.2f}**."
        )

    with st.expander("How to read this"):
        st.write(
            "In both rounds participants choose between a person with their own colour and a person "
            "with a different colour. In Round 2 the different-coloured person is a team member. "
            "If chips move from the same colour to the team, the shared identity (something you really "
            "have in common) outweighs the outward category (the colour). The game illustrates the idea "
            "of the model; it does not test it."
        )


def admin_view():
    st.title("Host dashboard")
    if st.text_input("Password", type="password") != ADMIN_PASSWORD:
        st.stop()

    tab_live, tab_results, tab_data = st.tabs(["📡 Live", "📊 Results", "🗂 Data"])
    with tab_live:
        stage_controls()
        reset_controls("live")
        live_counts()
    df = pd.DataFrame(snapshot())
    with tab_results:
        st.button("🔄 Refresh results")
        if df.empty:
            st.info("Nobody has joined yet.")
        else:
            render_results(df)
    with tab_data:
        if df.empty:
            st.info("No data yet.")
        else:
            st.dataframe(df)
            st.download_button("⬇️ Download raw data (CSV)", df.to_csv(index=False).encode("utf-8"),
                               file_name="chip_game_results.csv", mime="text/csv")
        reset_controls("data")


# ----------------------------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------------------------
if st.query_params.get("admin") is not None:
    admin_view()
    st.stop()

def route(p):
    stage = get_stage()
    if "r1_to_same" not in p:  # always finish Round 1 first (also for people who joined late)
        screen_round1(p)
    elif "r2_to_same" in p:
        screen_done(p)
    elif stage == "r1":
        screen_wait(p, "✅ Round 1 is done. Please wait until the host starts the next step.")
    elif stage == "team":
        if team_info(p) is None:
            screen_team(p)
        else:
            screen_wait(p, "✅ Your team is set. Please wait until the host starts Round 2.",
                        show_team=True)
    else:  # stage == "r2"
        screen_round2(p)


participant = current_participant()
if participant is None:
    screen_welcome()
else:
    route(participant)
    watch(participant["id"], state_sig(participant))
