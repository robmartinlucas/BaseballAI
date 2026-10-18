"""Matchup-driven, explicitly heuristic add/drop and trade watchlists.

No projected stats or invented remaining acquisition counts. Yahoo supplies
actual category values and roster ownership; an optional ESPN scoreboard feed
supplies upcoming NBA games, which are not guaranteed fantasy starts.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
import math
import re
import time
from typing import Any, Dict, List, Optional

import requests

from .fantasy_data import FantasyDashboardClient


ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
TEAM_ALIASES = {
    "GSW": "GS", "GS": "GS", "PHX": "PHO", "PHO": "PHO",
    "SAS": "SA", "SA": "SA", "NYK": "NY", "NY": "NY",
    "NOP": "NO", "NO": "NO", "BKN": "BKN", "BRK": "BKN",
    "UTA": "UTA", "UTAH": "UTA", "WSH": "WAS", "WAS": "WAS",
}
INJURY_WARNING = {"inj", "out", "o", "susp", "suspended", "il", "ir", "pup"}
DAY_TO_DAY = {"gtd", "dtd", "q", "questionable", "doubtful"}


def numeric(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", "").strip())
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def low_is_good(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in {"to", "tov", "turnovers", "turnover"}


def is_percentage(name: str) -> bool:
    n = name.lower()
    return "%" in n or "percentage" in n or n in {"fgp", "ftp"}


def bucket(ownership_type: str) -> str:
    normalized = (ownership_type or "").strip().lower()
    if normalized in {"freeagents", "freeagent", "fa"}:
        return "free_agent"
    if normalized in {"waivers", "waiver", "w"}:
        return "waivers"
    if normalized in {"team", "owned", "t"}:
        return "rostered"
    return "unknown"


def risk(player: Dict[str, Any]) -> str:
    state = (player.get("injury_status") or "").lower().strip()
    if state in INJURY_WARNING:
        return "out"
    if state in DAY_TO_DAY:
        return "questionable"
    return "none"


def matchup_categories(categories: List[Dict[str, str]],
                       matchup: Optional[Dict[str, Any]],
                       my_key: str) -> List[Dict[str, Any]]:
    if not matchup:
        return []
    own = next((t for t in matchup["teams"] if t["team_key"] == my_key), None)
    other = next((t for t in matchup["teams"] if t["team_key"] != my_key), None)
    if not own or not other:
        return []

    table = []
    ids = list(dict.fromkeys([c["id"] for c in categories] +
                             list(own.get("stats", {})) + list(other.get("stats", {}))))
    meta = {c["id"]: c for c in categories}
    for sid in ids:
        label = meta.get(sid, {}).get("name", "Stat " + sid)
        mine = numeric(own.get("stats", {}).get(sid))
        theirs = numeric(other.get("stats", {}).get(sid))
        available = mine is not None and theirs is not None
        direction = -1 if low_is_good(label) else 1
        edge = (mine - theirs) * direction if available else 0
        # Rates: 0.010 equals one FG/FT percentage point when fractional.
        if available:
            if is_percentage(label):
                divisor = 100.0 if max(abs(mine), abs(theirs)) > 1 else 1.0
                relative_gap = abs(mine - theirs) / divisor
                close = relative_gap <= 0.025
            else:
                denom = max(abs(mine), abs(theirs), 1.0)
                close = abs(mine - theirs) / denom <= 0.20
            state = "winning" if edge > 0 else ("losing" if edge < 0 else "tied")
        else:
            close, state = False, "unknown"
        table.append({
            "id": sid, "name": label,
            "mine": own.get("stats", {}).get(sid, "—"),
            "theirs": other.get("stats", {}).get(sid, "—"),
            "state": state, "close": close,
            "priority": (0 if available and mine == 0 and theirs == 0 else
                         3 if state == "losing" and close else
                         2 if state == "tied" else
                         1 if state == "losing" else 0),
        })
    return table


def schedule_window(matchup: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    today = date.today()
    start, end = today, today + timedelta(days=6)
    verified = False
    if matchup:
        try:
            start = max(today, date.fromisoformat(matchup["week_start"][:10]))
            end = date.fromisoformat(matchup["week_end"][:10])
            verified = True
        except (ValueError, TypeError, KeyError):
            pass
    if end < start:
        return {"start": start, "end": end, "verified": verified, "dates": []}
    end = min(end, today + timedelta(days=8))
    return {
        "start": start,
        "end": end,
        "verified": verified,
        "dates": [start + timedelta(days=i) for i in range((end - start).days + 1)],
    }


def _schedule_one_day(day: date) -> Counter:
    response = requests.get(
        ESPN_SCOREBOARD, params={"dates": day.strftime("%Y%m%d"), "limit": 100},
        timeout=7,
    )
    response.raise_for_status()
    result = Counter()
    for event in response.json().get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        state = ((event.get("status") or {}).get("type") or {}).get("state", "")
        if state not in {"pre", "in", ""}:
            continue
        # Count upcoming contests only. Already-started games cannot be added
        # retroactively, so exclude "in" as well.
        if state == "in":
            continue
        for competitor in competitions[0].get("competitors", []):
            code = competitor.get("team", {}).get("abbreviation", "").upper()
            if code:
                result[TEAM_ALIASES.get(code, code)] += 1
    return result


def remaining_games(window: Dict[str, Any]) -> Dict[str, Any]:
    days = window["dates"]
    if not days:
        return {"available": False, "games": {}, "label": "Matchup week has ended"}
    try:
        counts = Counter()
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_schedule_one_day, d) for d in days]
            for future in as_completed(futures):
                counts.update(future.result())
        return {"available": True, "games": dict(counts),
                "label": "Upcoming NBA games from ESPN (not guaranteed fantasy starts)"}
    except (requests.RequestException, ValueError, TypeError):
        return {"available": False, "games": {},
                "label": "Upcoming NBA schedule temporarily unavailable"}


def decorate_schedule(players: List[Dict[str, Any]], schedule: Dict[str, Any]) -> None:
    for player in players:
        code = (player.get("nba_team") or "").upper()
        code = TEAM_ALIASES.get(code, code)
        player["games_remaining"] = schedule["games"].get(code, 0) if schedule["available"] else None
        player["risk"] = risk(player)


def category_signal(player: Dict[str, Any],
                    categories: List[Dict[str, Any]],
                    population: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rank season totals/rates among observed players, not future projections."""
    stats = player.get("stats") or {}
    improved = []
    scores = []
    for cat in categories:
        if cat["priority"] <= 0:
            continue
        value = numeric(stats.get(cat["id"]))
        if value is None:
            continue
        pool = [numeric(p.get("stats", {}).get(cat["id"])) for p in population]
        pool = [n for n in pool if n is not None]
        if len(pool) < 4:
            continue
        direction = -1 if low_is_good(cat["name"]) else 1
        rank = sum(direction * value > direction * v for v in pool) / len(pool)
        if rank > 0.55:
            improved.append(cat["name"])
            scores.append(rank * cat["priority"])
    return {"categories": improved[:3], "score": round(sum(scores), 2)}


def score_free_agents(players: List[Dict[str, Any]],
                      categories: List[Dict[str, Any]],
                      schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    population = list(players)
    for p in players:
        signal = category_signal(p, categories, population)
        p["helps_categories"] = signal["categories"]
        p["signal_score"] = signal["score"]
        # Upcoming games favor usable streamers, but not a fantasy projection.
        games = p.get("games_remaining")
        game_score = float(games or 0) * 1.2 if schedule.get("rankable") else 0
        # The Yahoo overall-rank sort is a strength proxy before Week 1;
        # show its *sort position*, not a misleading exact league ranking.
        order = p.get("yahoo_sort_position")
        quality_score = max(0, 700 - order) / 20 if order else 0
        injury_penalty = 25 if p["risk"] == "out" else 4 if p["risk"] == "questionable" else 0
        p["rank_score"] = round(
            quality_score + game_score + signal["score"] - injury_penalty, 2
        )
        reason = []
        if order:
            reason.append("Yahoo overall-rank sort position #{}".format(order))
        if games is not None:
            reason.append("{} upcoming NBA game{}{}".format(
                games, "" if games == 1 else "s",
                "" if schedule.get("rankable") else " (fantasy-scoring week not verified)"
            ))
        if signal["categories"]:
            reason.append("Season-stat strengths in {}".format(", ".join(signal["categories"])))
        if not reason:
            reason.append("Availability confirmed; statistical fit not established")
        if p["risk"] != "none":
            reason.append("Injury status: " + (p.get("injury_status") or "check"))
        p["reason"] = "; ".join(reason)
    return sorted(players, key=lambda p: (-p["rank_score"], p["name"]))


def drop_watchlist(roster: List[Dict[str, Any]],
                   schedule: Dict[str, Any]) -> List[Dict[str, Any]]:
    ranked = []
    for p in roster:
        reasons = []
        games = p.get("games_remaining")
        if p["risk"] == "out":
            reasons.append("Injury/availability concern; verify timeline and IL eligibility")
        elif p["risk"] == "questionable":
            reasons.append("Day-to-day; monitor pregame status")
        if games == 0 and schedule.get("rankable"):
            reasons.append("No upcoming NBA games found in this window")
        if reasons:
            item = dict(p)
            item["reason"] = "; ".join(reasons)
            item["risk_score"] = (2 if p["risk"] == "out" else 1 if p["risk"] == "questionable" else 0) + (1 if games == 0 else 0)
            ranked.append(item)
    return sorted(ranked, key=lambda p: -p["risk_score"])[:8]


def trade_candidates(players: List[Dict[str, Any]],
                     categories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for p in players:
        signal = category_signal(p, categories, players)
        p["helps_categories"] = signal["categories"]
        p["signal_score"] = signal["score"]
        order = p.get("yahoo_sort_position")
        p["rank_score"] = (signal["score"] +
                           (max(0, 700 - order) / 20 if order else 0) -
                           (25 if p["risk"] == "out" else 0))
        p["reason"] = (
            "Season-stat fit: " + ", ".join(signal["categories"])
            if signal["categories"] else
            ("Yahoo overall-rank sort position #{}; trade value not assessed".format(order)
             if order else "Owned player; category fit and trade value not yet assessed")
        )
    if any(p.get("yahoo_sort_position") for p in players) or (
        categories and any(p.get("stats") for p in players)
    ):
        players.sort(key=lambda p: (-p["rank_score"], p["name"]))
        # Keep the radar multi-manager, rather than listing an entire star-
        # studded lineup from just one manager.
        per_owner = {}
        top = []
        for p in players:
            owner = p.get("owner_team_key") or p.get("owner_team_name")
            if per_owner.get(owner, 0) >= 3:
                continue
            per_owner[owner] = per_owner.get(owner, 0) + 1
            top.append(p)
            if len(top) >= 12:
                break
        return top

    # Without relevant production data, do not present arbitrary alphabetic
    # players from just one owner as a ranked trade recommendation. Show a
    # cross-league sample, explicitly without a computed category fit.
    by_owner: Dict[str, List[Dict[str, Any]]] = {}
    for p in sorted(players, key=lambda x: x["name"]):
        by_owner.setdefault(p["owner_team_name"], []).append(p)
    sample = []
    while by_owner and len(sample) < 12:
        for owner in list(sorted(by_owner)):
            if not by_owner[owner]:
                del by_owner[owner]
                continue
            sample.append(by_owner[owner].pop(0))
            if len(sample) >= 12:
                break
    return sample


class DashboardService:
    """Small in-process cache to limit Yahoo and schedule requests."""

    def __init__(self, yahoo: FantasyDashboardClient) -> None:
        self.yahoo = yahoo
        self._cache: Dict[str, Any] = {}

    def get(self, league_key: str, *, scan: int = 100,
            trades: bool = False, refresh: bool = False) -> Dict[str, Any]:
        scan = 500 if scan >= 500 else 300
        cache_key = "{}:{}:{}".format(league_key, scan, trades)
        cached = self._cache.get(cache_key)
        if not refresh and cached and time.time() - cached["timestamp"] < 300:
            return cached["data"]
        value = self._build(league_key, scan=scan, trades=trades)
        self._cache[cache_key] = {"timestamp": time.time(), "data": value}
        return value

    def _build(self, league_key: str, *, scan: int, trades: bool) -> Dict[str, Any]:
        notices = []
        def optional(description, fn, default):
            try:
                return fn()
            except Exception as exc:
                notices.append("{} unavailable: {}".format(description, str(exc)[:180]))
                return default

        game_key = league_key.split(".l.")[0]
        all_teams = optional("League teams", lambda: self.yahoo.league_teams(league_key), [])
        my_teams = optional("My Yahoo teams", lambda: self.yahoo.user_teams(game_key), [])
        mine = next((t for t in my_teams if t["team_key"].startswith(league_key + ".t.")), None)
        if not mine:
            mine = next((t for t in all_teams if t["is_mine"]), None)

        settings = optional("Scoring settings", lambda: self.yahoo.league_settings(league_key), {})
        board = optional("Current matchup", lambda: self.yahoo.league_scoreboard(league_key),
                         {"week": "", "matchups": []})
        matchup = next(
            (m for m in board["matchups"] if mine and any(
                t["team_key"] == mine["team_key"] for t in m["teams"])), None
        )
        opponent = next(
            (t for t in matchup["teams"] if t["team_key"] != mine["team_key"]),
            None
        ) if matchup and mine else None
        category_rows = matchup_categories(settings.get("categories", []), matchup,
                                           mine["team_key"] if mine else "")
        window = schedule_window(matchup)
        schedule = optional("NBA schedule", lambda: remaining_games(window),
                            {"available": False, "games": {}, "label": "Schedule unavailable"})
        # Do not infer valid fantasy starts from preseason/other non-scoring
        # dates when Yahoo has not confirmed the matchup week boundaries.
        schedule["rankable"] = bool(schedule["available"] and window["verified"])

        roster = optional("My roster", lambda: self.yahoo.roster(mine["team_key"]), []) if mine else []
        decorate_schedule(roster, schedule)

        roster_keys = [p["player_key"] for p in roster if p.get("player_key")]
        recent = optional(
            "Recent seven-day player stats",
            lambda: self.yahoo.player_recent_stats(league_key, roster_keys),
            {},
        ) if roster_keys else {}
        for player in roster:
            player["recent_stats"] = recent.get(player["player_key"], {})
            player["recent_highlights"] = [
                {"name": c["name"], "value": player["recent_stats"][c["id"]]}
                for c in settings.get("categories", [])
                if c["id"] in player["recent_stats"]
            ][:5]

        available = []
        scanned = 0
        rank_by_key: Dict[str, int] = {}
        used_yahoo_rank_sort = True
        # Yahoo has documented sort=OR for overall-rank sorting. Scanning only
        # the first 100 unsorted names had returned alphabetic, weak pickup
        # candidates. Scan more *ranked* players, then use ownership to decide
        # who is actually available. Retain a safe unsorted fallback.
        for offset in range(0, scan, 25):
            try:
                page = self.yahoo.league_player_page(
                    league_key, offset, 25, ranked=used_yahoo_rank_sort
                )
            except Exception as exc:
                if used_yahoo_rank_sort:
                    used_yahoo_rank_sort = False
                    rank_by_key.clear()
                    available.clear()
                    scanned = 0
                    notices.append(
                        "Yahoo overall-rank sorting unavailable; using unranked player pages: {}".format(str(exc)[:150])
                    )
                    break
                notices.append("Yahoo player scan interrupted: {}".format(str(exc)[:150]))
                break

            if not page:
                break
            scanned += len(page)
            for p in page:
                if used_yahoo_rank_sort and p.get("yahoo_sort_position"):
                    rank_by_key[p["player_key"]] = p["yahoo_sort_position"]
                if bucket(p.get("ownership_type", "")) in {"free_agent", "waivers"}:
                    available.append(p)
            if len(page) < 25:
                break

        if not used_yahoo_rank_sort:
            for offset in range(0, scan, 25):
                page = optional(
                    "Yahoo unranked player page starting at {}".format(offset),
                    lambda pos=offset: self.yahoo.league_player_page(league_key, pos, 25),
                    [],
                )
                if not page:
                    break
                scanned += len(page)
                available.extend(
                    p for p in page if bucket(p.get("ownership_type", "")) in {"free_agent", "waivers"}
                )
                if len(page) < 25:
                    break

        stats_keys = [p["player_key"] for p in available if p["player_key"]]
        if stats_keys:
            stats = optional("Available player season stats",
                             lambda: self.yahoo.player_season_stats(league_key, stats_keys), {})
            for p in available:
                p["stats"] = stats.get(p["player_key"], {})
        decorate_schedule(available, schedule)
        adds = score_free_agents(available, category_rows, schedule)

        other_rosters = []
        if trades:
            for team in all_teams:
                if mine and team["team_key"] == mine["team_key"]:
                    continue
                if not team["team_key"]:
                    continue
                other = optional(
                    "Roster for {}".format(team["name"]),
                    lambda key=team["team_key"]: self.yahoo.roster(key),
                    [],
                )
                for p in other:
                    p["owner_team_name"] = team["name"]
                    p["owner_team_key"] = team["team_key"]
                    if p["player_key"] in rank_by_key:
                        p["yahoo_sort_position"] = rank_by_key[p["player_key"]]
                other_rosters.extend(other)
            decorate_schedule(other_rosters, schedule)
        target_board = trade_candidates(other_rosters, category_rows)

        return {
            "league_key": league_key,
            "my_team": mine, "opponent": opponent, "matchup": matchup,
            "scoring": settings, "categories": category_rows,
            "roster": roster, "adds": adds[:15],
            "free_agents_found": sum(bucket(p["ownership_type"]) == "free_agent"
                                     for p in available),
            "waivers_found": sum(bucket(p["ownership_type"]) == "waivers"
                                 for p in available),
            "scanned": scanned, "requested_scan": scan,
            "ranked_scan": used_yahoo_rank_sort,
            "drop_watchlist": drop_watchlist(roster, schedule),
            "trades_loaded": trades, "trade_targets": target_board,
            "schedule": schedule, "window": window, "notices": notices,
            "generated_at": datetime.now().astimezone().strftime("%Y-%m-%d %I:%M %p %Z"),
        }
