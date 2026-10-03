"""Generate the PokerStars card from the hand histories the desktop client saves locally.

PokerStars has no public API, so this runs on the PC where the client is installed
(Windows Task Scheduler, hourly) instead of in the GitHub Action, and pushes the SVG itself.
Hands are cached outside the repo, so they still count after the client deletes old files.
Standard library only.
"""

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import generate as g

HAND_HISTORY = Path(os.environ.get(
    "POKERSTARS_HH", Path.home() / "AppData/Local/PokerStars.Italy/HandHistory"))
CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "pokerstars-card" / "hands.json"
REPO = g.OUT_DIR.parent
SVG = g.OUT_DIR / "pokerstars.svg"

POKERSTARS_RED = "#e8202a"
# A playing-card spade on a 24x24 viewBox, drawn for this card (Simple Icons has no PokerStars logo).
SPADE = ("M12 1C9.2 5.4 3 8.7 3 13.4 3 16 5 18 7.5 18c1.4 0 2.7-.6 3.5-1.7-.2 2.4-1.1 4.2-2.9 "
         "6.2h7.8c-1.8-2-2.7-3.8-2.9-6.2.8 1.1 2.1 1.7 3.5 1.7 2.5 0 4.5-2 4.5-4.6C21 8.7 14.8 5.4 12 1Z")

HEADER = re.compile(r"^PokerStars (?:[\w&' ]+ )?(?:Hand|Game) #(\d+):")
TOURNEY = re.compile(r"Tournament #(\d+)")
DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2}) \d{1,2}:\d{2}:\d{2}")
DEALT = re.compile(r"^Dealt to (.+?) \[")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- parsing

def split_hands(text):
    hand = []
    for line in text.splitlines():
        if HEADER.match(line) and hand:
            yield hand
            hand = []
        if hand or HEADER.match(line):
            hand.append(line.rstrip())
    if hand:
        yield hand


def parse_hand(lines):
    """One hand -> (hand_id, record, finish, hero) or None if hero wasn't dealt in.

    record = [date, vpip, pfr, went_to_showdown, won_at_showdown, tourney_id]
    """
    hand_id = HEADER.match(lines[0]).group(1)
    date = DATE.search(lines[0])
    hero = next((m.group(1) for m in map(DEALT.match, lines) if m), None)
    if not date or not hero:
        return None
    tourney = TOURNEY.search(lines[0])
    tid = tourney.group(1) if tourney else ""

    preflop, section = [], None
    for line in lines:
        if line.startswith("*** "):
            section = line
        elif section == "*** HOLE CARDS ***" and line.startswith(f"{hero}: "):
            preflop.append(line[len(hero) + 2:])
    vpip = any(a.startswith(("calls", "bets", "raises")) for a in preflop)
    pfr = any(a.startswith(("bets", "raises")) for a in preflop)

    seat = re.compile(rf"^Seat \d+: {re.escape(hero)} ")
    summary = next((l for l in lines if seat.match(l) and ("showed [" in l or "mucked [" in l)), "")
    showdown = bool(summary)
    won = "showed [" in summary and " and won " in summary

    finish = None
    for line in lines:
        if line.startswith(f"{hero} wins the tournament"):
            finish = 1
        elif m := re.match(rf"{re.escape(hero)} finished the tournament in (\d+)", line):
            finish = int(m.group(1))
    day = "-".join(date.groups())
    return hand_id, [day, vpip, pfr, showdown, won, tid], finish, hero


def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"hero": None, "hands": {}, "finishes": {}}


def update_cache():
    cache = load_cache()
    for path in sorted(HAND_HISTORY.rglob("*.txt")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        for lines in split_hands(text):
            parsed = parse_hand(lines)
            if not parsed:
                continue
            hand_id, record, finish, cache["hero"] = parsed
            cache["hands"][hand_id] = record
            if finish:
                cache["finishes"][record[5]] = finish
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    return cache


# ---------------------------------------------------------------- card

def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "—"


def pokerstars_card(cache, today):
    hands = list(cache["hands"].values())
    counts = {}
    for day, *_ in hands:
        counts[day] = counts.get(day, 0) + 1
    showdowns = sum(h[3] for h in hands)
    top = [
        (pct(sum(h[1] for h in hands), len(hands)), "VPIP"),
        (pct(sum(h[2] for h in hands), len(hands)), "PFR"),
        (pct(sum(h[4] for h in hands), showdowns), "Won at Showdown"),
        (f"{len({h[5] for h in hands if h[5]}):,}", "Tournaments"),
    ]
    return g.card("POKERSTARS", POKERSTARS_RED, g.logo(SPADE, POKERSTARS_RED),
                  cache["hero"] or "PokerStars", f"{len(hands):,} Hands", POKERSTARS_RED,
                  g.stats_body(top, counts, today), counts, today)


# ---------------------------------------------------------------- publish

def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True,
                          check=True, creationflags=NO_WINDOW).stdout


def publish():
    if not HAND_HISTORY.exists():
        raise FileNotFoundError(f"Hand history folder not found: {HAND_HISTORY}")
    git("pull", "--rebase", "--autostash", "--quiet")
    cache = update_cache()
    SVG.write_text(pokerstars_card(cache, dt.date.today()), encoding="utf-8")
    if git("status", "--porcelain", "--", str(SVG)).strip():
        git("add", "--", str(SVG))
        git("commit", "--quiet", "-m", "Update PokerStars heatmap")
    # Also retries a commit whose push failed on an earlier run.
    if int(git("rev-list", "--count", "@{u}..HEAD")):
        git("push", "--quiet")
        return f"pushed ({len(cache['hands'])} hands)"
    return f"no changes ({len(cache['hands'])} hands)"


def main():
    # pythonw has no console when run by Task Scheduler, so the outcome goes to a log file.
    log = CACHE.parent / "last-run.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        status = publish()
    except Exception as e:
        status = f"failed: {e!r} {getattr(e, 'stderr', '') or ''}".strip()
    log.write_text(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {status}\n", encoding="utf-8")
    print(f"pokerstars: {status}")
    sys.exit(status.startswith("failed"))


if __name__ == "__main__":
    main()
