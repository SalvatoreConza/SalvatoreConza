"""Generate Codewars and Kaggle activity heatmap cards for the profile README.

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

CODEWARS_USER = "SalvatoreConza"
KAGGLE_USER = "salvatoreangeloconza"

OUT_DIR = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (profile-heatmaps; +https://github.com/SalvatoreConza/SalvatoreConza)"

# Theme, copied from leetcard's dark theme.
BG, BORDER, TEXT, MUTED = "#101010", "#404040", "#f0f0f0", "#9a9a9a"
FONT = "Inter, 'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"

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


# ---------------------------------------------------------------- fetching

def get_json(url, opener=None, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with (opener or urllib.request.build_opener()).open(req, timeout=30) as r:
        return json.load(r)


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


def heatmap(counts, today, accent):
    """52-week grid of 7 rows (Sun..Sat); returns svg parts and the first date."""
    first_sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7) - dt.timedelta(weeks=52)
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


def card(platform, accent, user, pill, pill_color, top_stats, counts, today):
    grid, start = heatmap(counts, today, accent)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="320" viewBox="0 0 500 320" '
        f'font-family="{FONT}">',
        f'<title>{esc(platform)} activity for {esc(user)}</title>',
        f'<rect x="0.5" y="0.5" width="499" height="319" rx="4" fill="{BG}" stroke="{BORDER}"/>',
        text(20, 34, platform, 13, accent, 700),
        text(20, 60, user, 22, TEXT, 700),
    ]
    pill_w = 14 + 7.2 * len(pill)
    parts += [
        f'<rect x="{480 - pill_w:.1f}" y="30" width="{pill_w:.1f}" height="24" rx="12" '
        f'fill="none" stroke="{pill_color}" stroke-width="1.5"/>',
        text(480 - pill_w / 2, 46, pill, 12, pill_color, 700, "middle"),
    ]
    parts += stat_row(top_stats, 105)
    parts += stat_row(activity_stats(counts, today, start), 155)
    parts += [
        f'<line x1="10" y1="200" x2="490" y2="200" stroke="{BORDER}"/>',
        text(20, 220, "Heatmap (Last 52 Weeks)", 14, TEXT),
        *grid,
        text(20, 310, start.isoformat(), 10, TEXT),
        text(480, 310, today.isoformat(), 10, TEXT, 400, "end"),
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


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
    return card("CODEWARS", CODEWARS_RED, profile["username"], rank["name"],
                CODEWARS_RANK_COLORS.get(rank["color"], MUTED), top, counts, today)


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
    return card("KAGGLE", KAGGLE_BLUE, profile.get("displayName") or KAGGLE_USER, tier.title(),
                KAGGLE_TIER_COLORS.get(tier, MUTED), top, counts, today)


def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    failed = False
    for name, build in (("codewars", codewars_card), ("kaggle", kaggle_card)):
        try:
            (OUT_DIR / f"{name}.svg").write_text(build(today), encoding="utf-8")
            print(f"{name}: ok")
        except Exception as e:  # keep the previous SVG if a source is down
            failed = True
            print(f"{name}: failed: {e!r}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
