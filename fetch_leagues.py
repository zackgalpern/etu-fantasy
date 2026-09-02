"""
ETU Sports Club — fantasy data fetcher.

Pulls standings, rosters, and matchups for both leagues and writes a single
JSON file the front end can fetch.

Both leagues are public, so no credentials are needed. If a league is ever
set back to private, export ESPN_S2 and ESPN_SWID and they'll be picked up
automatically.

Local run:
    pip install espn_api
    python fetch_leagues.py
"""

import datetime
import json
import os
import pathlib

from espn_api.football import League

YEAR = 2026
OUTPUT = pathlib.Path("docs/data.json")

LEAGUES = [
    {"key": "league_a", "name": "ETU League A", "id": 1225572244},
    {"key": "league_b", "name": "ETU League B", "id": None},  # <-- fill in
]

# The cross-league championship has no ESPN equivalent, so it lives here.
# Fill in once both league champions are decided.
SUPER_BOWL = {
    "scheduled": False,
    "league_a_champion": None,
    "league_b_champion": None,
    "league_a_score": None,
    "league_b_score": None,
    "note": "Winners of both leagues meet in the ETU Super Bowl.",
}


def auth():
    """Public leagues need no credentials. If both env vars happen to be set
    they're passed through, which keeps this working if a league is ever
    flipped back to private."""
    s2 = os.environ.get("ESPN_S2")
    swid = os.environ.get("ESPN_SWID")
    if s2 and swid:
        print("Using ESPN credentials from environment")
        return {"espn_s2": s2, "swid": swid}
    print("No credentials set — treating leagues as public")
    return {}


def owner_name(team):
    """espn_api returns owners as dicts in recent versions, strings in older ones."""
    owners = getattr(team, "owners", None) or []
    if not owners:
        return ""
    first = owners[0]
    if isinstance(first, dict):
        parts = [first.get("firstName", ""), first.get("lastName", "")]
        return " ".join(p for p in parts if p).strip()
    return str(first)


def serialize_player(player):
    return {
        "name": player.name,
        "position": player.position,
        "pro_team": getattr(player, "proTeam", ""),
        "slot": getattr(player, "lineupSlot", ""),
        "injury_status": getattr(player, "injuryStatus", ""),
        "acquisition": getattr(player, "acquisitionType", ""),
        "points": getattr(player, "total_points", 0),
        "projected": getattr(player, "projected_total_points", 0),
    }


def serialize_team(team):
    return {
        "id": team.team_id,
        "name": team.team_name,
        "abbrev": getattr(team, "team_abbrev", ""),
        "owner": owner_name(team),
        "logo": getattr(team, "logo_url", ""),
        "wins": team.wins,
        "losses": team.losses,
        "ties": getattr(team, "ties", 0),
        "points_for": round(getattr(team, "points_for", 0), 2),
        "points_against": round(getattr(team, "points_against", 0), 2),
        "standing": getattr(team, "standing", None),
        "streak": f"{getattr(team, 'streak_type', '')} {getattr(team, 'streak_length', '')}".strip(),
        "roster": [serialize_player(p) for p in team.roster],
    }


def matchups_for_week(league, week):
    """Built from team.schedule so this works before Week 1 kicks off,
    unlike box_scores() which needs games to exist."""
    seen = set()
    games = []
    idx = week - 1

    for team in league.teams:
        if idx >= len(team.schedule):
            continue
        opponent = team.schedule[idx]
        pair = frozenset((team.team_id, opponent.team_id))
        if pair in seen:
            continue
        seen.add(pair)

        def score_of(t):
            return round(t.scores[idx], 2) if idx < len(t.scores) else 0.0

        games.append({
            "home": team.team_name,
            "home_id": team.team_id,
            "home_owner": owner_name(team),
            "home_score": score_of(team),
            "away": opponent.team_name,
            "away_id": opponent.team_id,
            "away_owner": owner_name(opponent),
            "away_score": score_of(opponent),
        })

    return games


def dump_league(config, credentials):
    league = League(league_id=config["id"], year=YEAR, **credentials)
    week = league.current_week

    return {
        "key": config["key"],
        "name": config["name"],
        "placeholder": False,
        "espn_name": getattr(league, "settings", None) and league.settings.name,
        "current_week": week,
        "teams": [serialize_team(t) for t in league.teams],
        "matchups": {
            str(w): matchups_for_week(league, w)
            for w in range(1, min(week + 1, 19))
        },
    }


def placeholder_league(config, team_count=12):
    """Same shape as a real league, but empty and flagged.

    This exists so the front end can be designed and built for two leagues
    before the second league_id is available. Drop the id into LEAGUES and
    the placeholder is replaced by real data on the next run — no UI changes.
    """
    teams = [
        {
            "id": i,
            "name": f"Team {i}",
            "abbrev": f"T{i}",
            "owner": "",
            "logo": "",
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "points_for": 0,
            "points_against": 0,
            "standing": i,
            "streak": "",
            "roster": [],
        }
        for i in range(1, team_count + 1)
    ]

    games = [
        {
            "home": teams[i]["name"],
            "home_id": teams[i]["id"],
            "home_owner": "",
            "home_score": 0,
            "away": teams[i + 1]["name"],
            "away_id": teams[i + 1]["id"],
            "away_owner": "",
            "away_score": 0,
        }
        for i in range(0, team_count - 1, 2)
    ]

    return {
        "key": config["key"],
        "name": config["name"],
        "placeholder": True,
        "espn_name": None,
        "current_week": 1,
        "teams": teams,
        "matchups": {"1": games},
    }


def main():
    credentials = auth()
    payload = {
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "season": YEAR,
        "super_bowl": SUPER_BOWL,
        "leagues": [],
    }

    for config in LEAGUES:
        if not config["id"]:
            print(f"{config['name']}: no league_id set — writing placeholder")
            payload["leagues"].append(placeholder_league(config))
            continue
        print(f"Fetching {config['name']}...")
        payload["leagues"].append(dump_league(config, credentials))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
