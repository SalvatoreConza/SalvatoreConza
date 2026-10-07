"""Generate LeetCode, Codewars, Kaggle, freeCodeCamp and Chess.com activity heatmap cards for the profile README.

Run by .github/workflows/heatmaps.yml once a day. Standard library only.
The cards mimic the dark leetcard.jacoblin.cool heatmap card (500x320).
"""

import datetime as dt
import html
import http.cookiejar
import json
import math
import sys
import urllib.request
from pathlib import Path

import icons

LEETCODE_USER = "Salvatore_Conza_Angelo"
CODEWARS_USER = "SalvatoreConza"
KAGGLE_USER = "salvatoreangeloconza"
FCC_USER = "salvatore_conza_angelo"
CHESSCOM_USER = "salvatore_conza"

OUT_DIR = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (profile-heatmaps; +https://github.com/SalvatoreConza/SalvatoreConza)"

# Theme, copied from leetcard's dark theme.
BG, BORDER, TEXT, MUTED = "#101010", "#404040", "#f0f0f0", "#9a9a9a"
FONT = "Inter, 'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"

LEETCODE_ORANGE = "#ffa116"
LEETCODE_DIFFICULTY_COLORS = {"Easy": "#5cb85c", "Medium": "#f0ad4e", "Hard": "#d9534f"}
CODEWARS_RED = "#b1361e"
CODEWARS_RANK_COLORS = {
    "white": "#e6e6e6", "yellow": "#ecb613", "blue": "#3c7ebb",
    "purple": "#866cc7", "black": "#9a9a9a", "red": "#b1361e",
}
KAGGLE_BLUE = "#20beff"
KAGGLE_TIER_COLORS = {
    "NOVICE": "#5ac995", "CONTRIBUTOR": "#20beff", "EXPERT": "#95628f",
    "MASTER": "#f96517", "GRANDMASTER": "#dca917",
}
FCC_GREEN = "#acd157"
CHESSCOM_GREEN = "#81b64c"


# ---------------------------------------------------------------- fetching

def get_json(url, opener=None, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with (opener or urllib.request.build_opener()).open(req, timeout=30) as r:
        return json.load(r)


def fetch_leetcode(user):
    query = """query($u: String!) {
      allQuestionsCount { difficulty count }
      matchedUser(username: $u) {
        username
        profile { ranking }
        submitStatsGlobal { acSubmissionNum { difficulty count } }
        userCalendar { submissionCalendar }
      }
    }"""
    data = get_json(
        "https://leetcode.com/graphql",
        data=json.dumps({"query": query, "variables": {"u": user}}).encode(),
        headers={"Content-Type": "application/json", "Referer": "https://leetcode.com/"},
    )["data"]
    counts = {}
    for ts, c in json.loads(data["matchedUser"]["userCalendar"]["submissionCalendar"]).items():
        day = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat()
        counts[day] = counts.get(day, 0) + c
    return data, counts


def fetch_codewars(user):
    base = f"https://www.codewars.com/api/v1/users/{user}"
    profile = get_json(base)
    counts, page, pages = {}, 0, 1
    while page < pages:
        chunk = get_json(f"{base}/code-challenges/completed?page={page}")
        pages = chunk["totalPages"]
        for kata in chunk["data"]:
            day = kata["completedAt"][:10]
            counts[day] = counts.get(day, 0) + 1
        page += 1
    return profile, counts


def fetch_kaggle(user):
    # Kaggle's internal web API only needs the anonymous session's XSRF cookie.
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.open(urllib.request.Request(f"https://www.kaggle.com/{user}", headers={"User-Agent": UA}), timeout=30).read()
    xsrf = next((c.value for c in jar if c.name == "XSRF-TOKEN"), None)
    if not xsrf:
        raise RuntimeError("Kaggle did not set an XSRF-TOKEN cookie")

    def call(method):
        return get_json(
            f"https://www.kaggle.com/api/i/users.ProfileService/{method}",
            opener=opener,
            data=json.dumps({"userName": user}).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "Origin": "https://www.kaggle.com", "X-Xsrf-Token": xsrf},
        )

    profile = call("GetProfile")
    counts = {a["date"][:10]: a.get("totalSubmissionsCount", 0) for a in call("GetUserActivity").get("activities", [])}
    return profile, {d: c for d, c in counts.items() if c}


def fetch_freecodecamp(user):
    data = get_json(f"https://api.freecodecamp.org/users/get-public-profile?username={user}")
    profile = data["entities"]["user"][data["result"]]
    counts = {}
    for ts, c in profile.get("calendar", {}).items():
        day = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date().isoformat()
        counts[day] = counts.get(day, 0) + c
    return profile, counts


def fetch_chesscom(user):
    base = f"https://api.chess.com/pub/player/{user}"
    profile, stats = get_json(base), get_json(f"{base}/stats")
    counts = {}
    # Monthly archives of finished games; the last 13 cover the 52-week heatmap.
    for url in get_json(f"{base}/games/archives")["archives"][-13:]:
        for game in get_json(url)["games"]:
            day = dt.datetime.fromtimestamp(game["end_time"], dt.timezone.utc).date().isoformat()
            counts[day] = counts.get(day, 0) + 1
    return profile, stats, counts


# ---------------------------------------------------------------- stats

def streaks(counts, today):
    days = sorted(dt.date.fromisoformat(d) for d in counts)
    longest = run = 0
    prev = None
    for d in days:
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    active = set(days)
    # A streak stays alive until a full day has been missed, like GitHub's.
    cur, d = 0, today if today in active else today - dt.timedelta(days=1)
    while d in active:
        cur += 1
        d -= dt.timedelta(days=1)
    return cur, longest


def activity_stats(counts, today, start):
    window = {d: c for d, c in counts.items() if dt.date.fromisoformat(d) >= start}
    cur, longest = streaks(counts, today)
    return [
        (f"{sum(window.values()):,}", "Past Year"),
        (f"{len(window):,}", "Active Days"),
        (f"{cur:,}", "Current Streak"),
        (f"{longest:,}", "Longest Streak"),
    ]


# ---------------------------------------------------------------- rendering

def esc(s):
    return html.escape(str(s), quote=True)


def text(x, y, s, size, fill, weight=400, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{esc(s)}</text>')


def stat_row(stats, y):
    out, col = [], 460 / len(stats)
    for i, (value, label) in enumerate(stats):
        cx = 20 + col * i + col / 2
        out.append(text(cx, y, value, 18, TEXT, 700, "middle"))
        out.append(text(cx, y + 17, label, 11, MUTED, 400, "middle"))
    return out


def heatmap_start(today):
    """The Sunday 52 weeks before this week's Sunday: the heatmap's first day."""
    return today - dt.timedelta(days=(today.weekday() + 1) % 7) - dt.timedelta(weeks=52)


def heatmap(counts, today, accent):
    """52-week grid of 7 rows (Sun..Sat); returns svg parts and the first date."""
    first_sunday = heatmap_start(today)
    peak = max([c for d, c in counts.items() if dt.date.fromisoformat(d) >= first_sunday] or [1])
    step, size = 8.6, 7.2
    out = []
    for week in range(53):
        for dow in range(7):
            day = first_sunday + dt.timedelta(days=week * 7 + dow)
            if day > today:
                break
            c = counts.get(day.isoformat(), 0)
            opacity = 0.16 if c == 0 else (0.35, 0.55, 0.78, 1.0)[min(3, math.ceil(4 * c / peak) - 1)]
            out.append(f'<rect x="{20 + week * step:.1f}" y="{235 + dow * step:.1f}" width="{size}" '
                       f'height="{size}" rx="1.5" fill="{accent}" fill-opacity="{opacity}"/>')
    return out, first_sunday


def logo(path, color):
    """A Simple Icons path scaled into the 36x36 slot left of the card title."""
    return (f'<svg x="20" y="24" width="36" height="36" viewBox="0 0 24 24">'
            f'<path fill="{color}" d="{path}"/></svg>')


def kaggle_logo():
    # Simple Icons only has Kaggle's wordmark; its favicon is a lowercase "k".
    return text(38, 58, "k", 46, KAGGLE_BLUE, 700, "middle")


def stats_body(top_stats, counts, today):
    return stat_row(top_stats, 105) + stat_row(activity_stats(counts, today, heatmap_start(today)), 155)


def leetcode_body(solved, totals):
    """leetcard-style solved ring on the left, per-difficulty progress bars on the right."""
    cx, cy, r = 80, 132, 40
    circ = 2 * math.pi * r
    frac = solved["All"] / max(totals["All"], 1)
    out = [
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{BORDER}" stroke-width="6"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{LEETCODE_ORANGE}" stroke-width="6" '
        f'stroke-linecap="round" stroke-dasharray="{max(frac * circ, 0.1):.2f} {circ:.2f}" '
        f'transform="rotate(-90 {cx} {cy})"/>',
        text(cx, cy + 4, f"{solved['All']:,}", 24, TEXT, 700, "middle"),
        text(cx, cy + 20, "Solved", 11, MUTED, 400, "middle"),
    ]
    x0, x1 = 160, 480
    for i, level in enumerate(("Easy", "Medium", "Hard")):
        y = 98 + 38 * i
        color = LEETCODE_DIFFICULTY_COLORS[level]
        width = (x1 - x0) * solved[level] / max(totals[level], 1)
        out += [
            text(x0, y, level, 15, TEXT, 700),
            text(x1, y, f"{solved[level]:,} / {totals[level]:,}", 13, TEXT, 700, "end"),
            f'<rect x="{x0}" y="{y + 8}" width="{x1 - x0}" height="4" rx="2" fill="{BORDER}"/>',
            f'<rect x="{x0}" y="{y + 8}" width="{max(width, 4):.1f}" height="4" rx="2" fill="{color}"/>',
        ]
    return out


def card(platform, accent, icon, user, pill, pill_color, body, counts, today):
    grid, start = heatmap(counts, today, accent)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="320" viewBox="0 0 500 320" '
        f'font-family="{FONT}">',
        f'<title>{esc(platform)} activity for {esc(user)}</title>',
        f'<rect x="0.5" y="0.5" width="499" height="319" rx="4" fill="{BG}" stroke="{BORDER}"/>',
        icon,
        text(68, 34, platform, 13, accent, 700),
        text(68, 60, user, 22, TEXT, 700),
    ]
    pill_w = 14 + 7.2 * len(pill)
    parts += [
        f'<rect x="{480 - pill_w:.1f}" y="30" width="{pill_w:.1f}" height="24" rx="12" '
        f'fill="none" stroke="{pill_color}" stroke-width="1.5"/>',
        text(480 - pill_w / 2, 46, pill, 12, pill_color, 700, "middle"),
    ]
    parts += body
    parts += [
        f'<line x1="10" y1="200" x2="490" y2="200" stroke="{BORDER}"/>',
        text(20, 220, "Heatmap (Last 52 Weeks)", 14, TEXT),
        *grid,
        text(20, 310, start.isoformat(), 10, TEXT),
        text(480, 310, today.isoformat(), 10, TEXT, 400, "end"),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def leetcode_card(today):
    data, counts = fetch_leetcode(LEETCODE_USER)
    user = data["matchedUser"]
    totals = {q["difficulty"]: q["count"] for q in data["allQuestionsCount"]}
    solved = {q["difficulty"]: q["count"] for q in user["submitStatsGlobal"]["acSubmissionNum"]}
    return card("LEETCODE", LEETCODE_ORANGE, logo(icons.LEETCODE, LEETCODE_ORANGE), user["username"],
                f"#{user['profile']['ranking']:,}", LEETCODE_ORANGE, leetcode_body(solved, totals),
                counts, today)


def codewars_card(today):
    profile, counts = fetch_codewars(CODEWARS_USER)
    rank = profile["ranks"]["overall"]
    pos = profile.get("leaderboardPosition")
    top = [
        (f"{profile.get('honor', 0):,}", "Honor"),
        (f"{profile['codeChallenges']['totalCompleted']:,}", "Kata Solved"),
        (f"#{pos:,}" if pos else "—", "Leaderboard"),
        (f"{len(profile['ranks'].get('languages', {}))}", "Languages"),
    ]
    return card("CODEWARS", CODEWARS_RED, logo(icons.CODEWARS, CODEWARS_RED), profile["username"],
                rank["name"], CODEWARS_RANK_COLORS.get(rank["color"], MUTED),
                stats_body(top, counts, today), counts, today)


def kaggle_card(today):
    profile, counts = fetch_kaggle(KAGGLE_USER)
    tier = profile.get("performanceTier", "NOVICE")
    joined = dt.date.fromisoformat(profile["userJoinDate"][:10])
    last = dt.date.fromisoformat(profile["userLastActive"][:10])
    top = [
        (f"{sum(counts.values()):,}", "Submissions"),
        (f"{len(profile.get('badges', [])):,}", "Badges"),
        (joined.strftime("%b %Y"), "Joined"),
        (last.strftime("%b %d").replace(" 0", " "), "Last Active"),
    ]
    return card("KAGGLE", KAGGLE_BLUE, kaggle_logo(), profile.get("displayName") or KAGGLE_USER,
                tier.title(), KAGGLE_TIER_COLORS.get(tier, MUTED), stats_body(top, counts, today),
                counts, today)


def freecodecamp_card(today):
    profile, counts = fetch_freecodecamp(FCC_USER)
    certs = sum(1 for k, v in profile.items() if k.startswith("is") and "Cert" in k and v is True)
    joined = dt.date.fromisoformat(profile["joinDate"][:10])
    last = max(counts) if counts else None
    top = [
        (f"{len(profile.get('completedChallenges', [])):,}", "Challenges"),
        (f"{profile.get('points', 0):,}", "Points"),
        (joined.strftime("%b %Y"), "Joined"),
        (dt.date.fromisoformat(last).strftime("%b %d").replace(" 0", " ") if last else "—", "Last Active"),
    ]
    return card("FREECODECAMP", FCC_GREEN, logo(icons.FREECODECAMP, FCC_GREEN),
                profile.get("usernameDisplay") or profile["username"], f"{certs} Cert{'s' * (certs != 1)}",
                FCC_GREEN if certs else MUTED, stats_body(top, counts, today), counts, today)


def chesscom_card(today):
    profile, stats, counts = fetch_chesscom(CHESSCOM_USER)
    modes = ("rapid", "blitz", "bullet", "daily")
    ratings = {m: stats.get(f"chess_{m}", {}).get("last", {}).get("rating") for m in modes}
    record = {k: sum(stats.get(f"chess_{m}", {}).get("record", {}).get(k, 0) for m in modes)
              for k in ("win", "loss", "draw")}
    top = [(f"{ratings[m]:,}" if ratings[m] else "—", m.title()) for m in modes]
    return card("CHESS.COM", CHESSCOM_GREEN, logo(icons.CHESSCOM, CHESSCOM_GREEN),
                profile["url"].rsplit("/", 1)[-1],
                f"{record['win']}W {record['loss']}L {record['draw']}D", CHESSCOM_GREEN,
                stats_body(top, counts, today), counts, today)


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    failed = False
    for name, build in (("leetcode", leetcode_card), ("codewars", codewars_card),
                        ("kaggle", kaggle_card), ("freecodecamp", freecodecamp_card),
                        ("chesscom", chesscom_card)):
        try:
            (OUT_DIR / f"{name}.svg").write_text(build(today), encoding="utf-8")
            print(f"{name}: ok")
        except Exception as e:  # keep the previous SVG if a source is down
            failed = True
            print(f"{name}: failed: {e!r}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
