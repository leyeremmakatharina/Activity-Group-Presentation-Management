"""
Chip game for the presentation "Cultural diversity, helping behaviour and shared team identity"
(based on the minimal group paradigm, Tajfel et al., 1971)

Flow for every participant (all on their own phone):
  1. Join            -> app assigns a colour (a purely visible, outward feature) and a table
  2. Round 1         -> split 5 chips between two ANONYMOUS participants (same colour vs. different colour)
                        + 1 question on how connected they feel to their colour group
  3. Team time       -> go to the assigned table (one person per colour), find something you share in your
                        leisure time, choose a team name based on it (= shared team identity)
  4. Round 2         -> split 5 chips between (same colour, other team) and (someone from your own team)
                        + 1 question on how connected they feel to their team
  5. Done            -> host opens the dashboard with ?admin=1

Host dashboard: open the app URL with  ?admin=1  and enter the password
(set ADMIN_PASSWORD in the Streamlit Cloud secrets, default: "admin").
"""

import html
import json
import math
import random
import statistics
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------------------------
N_CHIPS = 5
BASELINE = N_CHIPS / 2  # 2.5 chips = no preference
AUTO_TABLES = True  # True: app assigns the table (guarantees one person per colour at each table)
CONTROL_CONDITION = False  # True: even tables get a control version of round 2 (see README text)
DATA_FILE = Path("chip_game_data.json")

COLOURS = {  # name: (background, text colour)
    "Red": ("#e74c3c", "#ffffff"),
    "Blue": ("#3498db", "#ffffff"),
    "Green": ("#27ae60", "#ffffff"),
    "Yellow": ("#f1c40f", "#222222"),
    "Purple": ("#8e44ad", "#ffffff"),
}
COLOUR_NAMES = list(COLOURS)

try:
    ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin")
except Exception:
    ADMIN_PASSWORD = "admin"

st.set_page_config(page_title="Chip Game", page_icon="🪙", layout="centered")


# ----------------------------------------------------------------------------------------------
# Shared storage (one store for all phones, saved to a JSON file in case the app restarts)
# ----------------------------------------------------------------------------------------------
@st.cache_resource
def get_store():
    store = {"lock": threading.Lock(), "participants": {}}
    if DATA_FILE.exists():
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            store["participants"] = {int(k): v for k, v in raw.items()}
        except Exception:
            pass
    return store


store = get_store()


def save():
    try:
        DATA_FILE.write_text(
            json.dumps(store["participants"], ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def update(p, **fields):
    with store["lock"]:
        p.update(fields)
        save()


def new_code(used):
    while True:
        code = f"P-{random.randint(100, 999)}"
        if code not in used:
            return code


def join():
    with store["lock"]:
        ps = store["participants"]
        pid = max(ps, default=0) + 1
        colour = COLOUR_NAMES[(pid - 1) % len(COLOUR_NAMES)]  # round robin -> balanced colours
        table = None
        if AUTO_TABLES:
            # k-th person of a colour sits at table k -> every table has one person of each colour
            table = sum(1 for q in ps.values() if q["colour"] == colour) + 1
        p = {
            "id": pid,
            "code": new_code({q["code"] for q in ps.values()}),
            "colour": colour,
            "table": table,
        }
        ps[pid] = p
        save()
    return p


def current_participant():
    ps = store["participants"]
    pid = st.session_state.get("pid")
    if pid is None:
        raw = st.query_params.get("pid")
        if raw and str(raw).isdigit():
            pid = int(raw)
    if pid in ps:
        st.session_state["pid"] = pid
        return ps[pid]
    return None


# ----------------------------------------------------------------------------------------------
# Recipients: anonymous (code + colour only), chosen randomly by the app
# ----------------------------------------------------------------------------------------------
def pick_recipient(me, same_colour, other_team_only=False):
    ps = store["participants"].values()
    candidates = [
        q
        for q in ps
        if q["id"] != me["id"]
        and ((q["colour"] == me["colour"]) == same_colour)
        and (not other_team_only or q.get("table") != me.get("table"))
    ]
    if candidates:
        q = random.choice(candidates)
        return {"code": q["code"], "colour": q["colour"]}
    # fallback (e.g. the first people to join): invent an anonymous code
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
        f"<div style='border:2px solid #bbb;border-radius:12px;padding:14px;text-align:center;'>"
        f"<div style='color:#777;margin-bottom:6px;'>{title}</div>{body}</div>",
        unsafe_allow_html=True,
    )


def chip_choice(key, label):
    choice = st.radio(
        label, options=list(range(N_CHIPS + 1)), index=None, horizontal=True, key=key
    )
    if choice is not None:
        st.info(f"Person 1: **{choice}** 🪙   |   Person 2: **{N_CHIPS - choice}** 🪙")
    return choice


def scale_question(key, label):
    return st.radio(
        label + "  \n(1 = not at all, 7 = very much)",
        options=list(range(1, 8)),
        index=None,
        horizontal=True,
        key=key,
    )


# ----------------------------------------------------------------------------------------------
# Screens
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
    c1, c2 = st.columns(2)
    with c1:
        recipient_card("Person 1", first)
    with c2:
        recipient_card("Person 2", second)
    st.write("")

    choice = chip_choice("r1_choice", "How many chips do you give to Person 1? (Person 2 gets the rest.)")
    conn = scale_question("r1_conn", "How connected do you feel to the other participants with your colour?")

    if st.button("Submit Round 1", type="primary", disabled=choice is None or conn is None):
        to_same = choice if p["r1_first_same"] else N_CHIPS - choice
        update(p, r1_to_same=to_same, r1_conn=conn)
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
        "and it makes you a team. Give your team a name based on it."
    )
    common = st.text_input("What do you all have in common?", max_chars=60, key="team_common")
    team_name = st.text_input("Your team name", max_chars=30, key="team_name_input")
    table = p.get("table")
    if not AUTO_TABLES:
        table = st.number_input("Your table number", min_value=1, max_value=99, step=1, key="table_no")

    ready = bool(common.strip()) and bool(team_name.strip())
    if st.button("Continue to Round 2", type="primary", disabled=not ready):
        update(p, team_common=common.strip(), team_name=team_name.strip(), table=int(table))
        st.rerun()


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
        team = html.escape(p["team_name"])

        def other_card(title):
            recipient_card(title, text=f"Someone from your own team<br>“{team}”")

    first_same = p["r2_first_same"]
    c1, c2 = st.columns(2)
    with c1:
        (same_card if first_same else other_card)("Person 1")
    with c2:
        (other_card if first_same else same_card)("Person 2")
    st.write("")

    choice = chip_choice("r2_choice", "How many chips do you give to Person 1? (Person 2 gets the rest.)")
    conn = scale_question("r2_conn", "How connected do you feel to your team?")

    if st.button("Submit Round 2", type="primary", disabled=choice is None or conn is None):
        to_same = choice if first_same else N_CHIPS - choice
        update(p, r2_to_same=to_same, r2_conn=conn)
        st.rerun()


def screen_done(p):
    banner(p)
    st.header("Thank you! 🎉")
    st.write("You are done. Please look up to the front: the results will be shown in a moment.")


# ----------------------------------------------------------------------------------------------
# Host dashboard (?admin=1)
# ----------------------------------------------------------------------------------------------
def values(df, col):
    return df[col].dropna().astype(float).tolist() if col in df else []


def normal_p(t):
    return 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))


def one_sample(xs, mu=BASELINE):
    if len(xs) < 2 or statistics.stdev(xs) == 0:
        return None
    t = (statistics.mean(xs) - mu) / (statistics.stdev(xs) / math.sqrt(len(xs)))
    return t, normal_p(t)


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    se = math.sqrt(statistics.variance(a) / len(a) + statistics.variance(b) / len(b))
    if se == 0:
        return None
    t = (statistics.mean(a) - statistics.mean(b)) / se
    return t, normal_p(t)


def stat_text(res, n):
    if res is None:
        return f"n = {n}"
    t, p = res
    return f"n = {n}, t = {t:.2f}, p ≈ {p:.3f} (normal approximation)"


def admin_view():
    st.title("Host dashboard")
    if st.text_input("Password", type="password") != ADMIN_PASSWORD:
        st.stop()
    st.button("🔄 Refresh")

    df = pd.DataFrame(list(store["participants"].values()))
    if df.empty:
        st.info("Nobody has joined yet.")
        st.stop()

    n_joined = len(df)
    n_r1 = len(values(df, "r1_to_same"))
    n_team = int(df["team_name"].notna().sum()) if "team_name" in df else 0
    n_r2 = len(values(df, "r2_to_same"))
    a, b, c, d = st.columns(4)
    a.metric("Joined", n_joined)
    b.metric("Round 1 done", n_r1)
    c.metric("Team formed", n_team)
    d.metric("Round 2 done", n_r2)

    # ---- Round 1: helping the same colour (visible, outward feature) ----
    st.subheader("Round 1: chips to the same colour")
    r1 = values(df, "r1_to_same")
    if r1:
        m = statistics.mean(r1)
        st.metric(f"Average chips to the same colour (of {N_CHIPS})", f"{m:.2f}",
                  delta=f"{m - BASELINE:+.2f} vs. no preference ({BASELINE})")
        st.caption(stat_text(one_sample(r1), len(r1)))
        dist = pd.Series(r1).astype(int).value_counts().reindex(range(N_CHIPS + 1), fill_value=0)
        st.bar_chart(dist.rename("participants"), x_label="Chips given to the same colour",
                     y_label="Participants")

    # ---- Round 2: team ----
    st.subheader("Round 2: chips to the own team")
    if "r2_condition" in df:
        team = df[(df["r2_condition"] == "team") & df["r2_to_same"].notna()]
        ctrl = df[(df["r2_condition"] == "control") & df["r2_to_same"].notna()]
    else:
        team = ctrl = df.iloc[0:0]
    to_team = [N_CHIPS - x for x in values(team, "r2_to_same")]
    if to_team:
        m2 = statistics.mean(to_team)
        st.metric(f"Average chips to the own team (of {N_CHIPS})", f"{m2:.2f}",
                  delta=f"{m2 - BASELINE:+.2f} vs. no preference ({BASELINE})")
        st.caption(stat_text(one_sample(to_team), len(to_team)))
    if len(ctrl):
        to_other = [N_CHIPS - x for x in values(ctrl, "r2_to_same")]
        st.write(
            f"Control tables (different colour from another team): {statistics.mean(to_other):.2f} chips "
            f"vs. own team: {statistics.mean(to_team) if to_team else float('nan'):.2f} chips. "
            + stat_text(welch(to_team, to_other), len(to_team) + len(to_other))
        )

    # ---- Round 1 vs. round 2: does the favouritism for the same colour shrink? ----
    both = df.dropna(subset=["r1_to_same", "r2_to_same"]) if "r2_to_same" in df else df.iloc[0:0]
    if len(both):
        st.subheader("Same colour: Round 1 vs. Round 2")
        r1b, r2b = values(both, "r1_to_same"), values(both, "r2_to_same")
        chart = pd.DataFrame(
            {"Average chips to same colour": [statistics.mean(r1b), statistics.mean(r2b)]},
            index=["Round 1 (no team yet)", "Round 2 (vs. own team)"],
        )
        st.bar_chart(chart)
        diff = [x - y for x, y in zip(r1b, r2b)]
        st.caption("Paired difference: " + stat_text(one_sample(diff, 0), len(diff)))

    # ---- Connectedness (proxy for social integration) ----
    cc1, cc2 = values(df, "r1_conn"), values(df, "r2_conn")
    if cc1 or cc2:
        st.subheader("Connectedness (1–7)")
        x, y = st.columns(2)
        if cc1:
            x.metric("…to the own colour group (Round 1)", f"{statistics.mean(cc1):.2f}")
        if cc2:
            y.metric("…to the own team (Round 2)", f"{statistics.mean(cc2):.2f}")

    st.divider()
    st.download_button("⬇️ Download raw data (CSV)", df.to_csv(index=False).encode("utf-8"),
                       file_name="chip_game_results.csv", mime="text/csv")
    with st.expander("Danger zone"):
        if st.checkbox("Yes, delete all data") and st.button("Reset game"):
            with store["lock"]:
                store["participants"].clear()
                save()
            st.rerun()


# ----------------------------------------------------------------------------------------------
# Router
# ----------------------------------------------------------------------------------------------
if st.query_params.get("admin") is not None:
    admin_view()
    st.stop()

participant = current_participant()
if participant is None:
    screen_welcome()
elif "r1_to_same" not in participant:
    screen_round1(participant)
elif "team_name" not in participant:
    screen_team(participant)
elif "r2_to_same" not in participant:
    screen_round2(participant)
else:
    screen_done(participant)
