"""Yahoo fantasy data helpers for the read-only matchup dashboard."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote
import xml.etree.ElementTree as ET

from .yahoo_client import (
    YahooFantasyClient,
    _first_descendant,
    _local_name,
    _parse_xml,
    _text,
)


def direct_children(node: Optional[ET.Element], name: str) -> List[ET.Element]:
    if node is None:
        return []
    return [c for c in node if _local_name(c.tag) == name]


def direct_child(node: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    return next(iter(direct_children(node, name)), None)


def child_text(node: Optional[ET.Element], name: str, default: str = "") -> str:
    child = direct_child(node, name)
    return (child.text or "").strip() if child is not None else default


def parse_stats(node: Optional[ET.Element]) -> Dict[str, str]:
    """Extract stat_id -> value from one player_stats or team_stats subtree."""
    if node is None:
        return {}
    stats = direct_child(node, "stats")
    if stats is None:
        stats = _first_descendant(node, "stats")
    data = {}
    for stat in direct_children(stats, "stat"):
        sid = child_text(stat, "stat_id")
        value = child_text(stat, "value")
        if sid and value not in ("", "-"):
            data[sid] = value
    return data


def parse_player(node: ET.Element) -> Dict[str, Any]:
    name = direct_child(node, "name")
    ownership = direct_child(node, "ownership")
    stats = direct_child(node, "player_stats")
    return {
        "player_key": child_text(node, "player_key"),
        "name": child_text(name, "full"),
        "nba_team": child_text(node, "editorial_team_abbr"),
        "positions": child_text(node, "display_position"),
        "injury_status": child_text(node, "status"),
        "status_full": child_text(node, "status_full"),
        "ownership_type": child_text(ownership, "ownership_type"),
        "owner_team_name": child_text(ownership, "owner_team_name"),
        "owner_team_key": child_text(ownership, "owner_team_key"),
        "waiver_date": child_text(ownership, "waiver_date"),
        "stats": parse_stats(stats),
    }


def player_nodes(root: ET.Element) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for node in root.iter():
        if _local_name(node.tag) != "player":
            continue
        player = parse_player(node)
        if player["player_key"] and player["player_key"] not in seen:
            seen.add(player["player_key"])
            result.append(player)
    return result


def parse_team(node: ET.Element) -> Dict[str, Any]:
    managers = direct_child(node, "managers")
    manager = direct_child(managers, "manager")
    return {
        "team_key": child_text(node, "team_key"),
        "name": child_text(node, "name"),
        "is_mine": child_text(node, "is_owned_by_current_login") == "1",
        "manager": child_text(manager, "nickname"),
        "stats": parse_stats(direct_child(node, "team_stats")),
    }


class FantasyDashboardClient(YahooFantasyClient):
    def user_teams(self, game_key: str) -> List[Dict[str, Any]]:
        resource = "users;use_login=1/games;game_keys={}/teams".format(quote(game_key, safe=""))
        root = _parse_xml(self.get(resource))
        return [parse_team(n) for n in root.iter() if _local_name(n.tag) == "team"
                and child_text(n, "team_key")]

    def league_teams(self, league_key: str) -> List[Dict[str, Any]]:
        root = _parse_xml(self.get("league/{}/teams".format(quote(league_key, safe=""))))
        return [parse_team(n) for n in root.iter() if _local_name(n.tag) == "team"
                and child_text(n, "team_key")]

    def league_settings(self, league_key: str) -> Dict[str, Any]:
        root = _parse_xml(self.get("league/{}/settings".format(quote(league_key, safe=""))))
        settings = _first_descendant(root, "settings")
        categories = []
        cat_root = direct_child(settings, "stat_categories")
        stats_root = direct_child(cat_root, "stats")
        for stat in direct_children(stats_root, "stat"):
            sid = child_text(stat, "stat_id")
            # Exclude informational stats if Yahoo labels them display-only.
            if not sid or child_text(stat, "is_only_display_stat") == "1":
                continue
            if child_text(stat, "enabled") == "0":
                continue
            name = child_text(stat, "display_name") or child_text(stat, "name") or "Stat " + sid
            categories.append({"id": sid, "name": name, "long_name": child_text(stat, "name")})
        # Some Yahoo responses nest stat_categories deeper.
        if not categories and settings is not None:
            cats = _first_descendant(settings, "stat_categories")
            for stat in direct_children(_first_descendant(cats, "stats"), "stat"):
                sid = child_text(stat, "stat_id")
                if sid and child_text(stat, "is_only_display_stat") != "1":
                    categories.append({
                        "id": sid,
                        "name": child_text(stat, "display_name") or child_text(stat, "name") or sid,
                        "long_name": child_text(stat, "name"),
                    })
        return {
            "categories": categories,
            "max_adds": child_text(settings, "max_adds"),
            "weekly_add_limit": (
                child_text(settings, "weekly_add_limit")
                or child_text(settings, "max_adds_per_week")
            ),
            "scoring_type": child_text(settings, "scoring_type"),
            "waiver_type": child_text(settings, "waiver_type"),
        }

    def league_scoreboard(self, league_key: str) -> Dict[str, Any]:
        root = _parse_xml(self.get("league/{}/scoreboard".format(quote(league_key, safe=""))))
        scoreboard = _first_descendant(root, "scoreboard")
        matches = []
        for matchup in root.iter():
            if _local_name(matchup.tag) != "matchup":
                continue
            teams_root = direct_child(matchup, "teams")
            competitors = [parse_team(node) for node in direct_children(teams_root, "team")]
            if len(competitors) < 2:
                continue
            matches.append({
                "week": child_text(matchup, "week") or child_text(scoreboard, "week"),
                "week_start": child_text(matchup, "week_start"),
                "week_end": child_text(matchup, "week_end"),
                "status": child_text(matchup, "status"),
                "teams": competitors,
            })
        return {"week": child_text(scoreboard, "week"), "matchups": matches}

    def roster(self, team_key: str) -> List[Dict[str, Any]]:
        team_path = "team/{}/roster/players".format(quote(team_key, safe=""))
        # Yahoo can reject an expanded stats subresource for some leagues.
        try:
            root = _parse_xml(self.get(team_path + "/stats"))
        except Exception:
            root = _parse_xml(self.get(team_path))
        players = player_nodes(root)
        if players and not any(p["stats"] for p in players):
            # Not fatal when season stats aren't ready.
            try:
                stats_root = _parse_xml(self.get(team_path + "/stats"))
                by_key = {p["player_key"]: p["stats"] for p in player_nodes(stats_root)}
                for player in players:
                    player["stats"] = by_key.get(player["player_key"], {})
            except Exception:
                pass
        return players

    def league_player_page(self, league_key: str, start: int, count: int = 25) -> List[Dict[str, Any]]:
        resource = "league/{}/players;start={};count={}/ownership".format(
            quote(league_key, safe=""), max(0, start), min(25, max(1, count))
        )
        root = _parse_xml(self.get(resource))
        return player_nodes(root)

    def player_recent_stats(self, league_key: str, keys: List[str]) -> Dict[str, Dict[str, str]]:
        """Yahoo recent 7-day player totals. Best-effort; not a projection."""
        if not keys:
            return {}
        result = {}
        for offset in range(0, len(keys), 25):
            sub_keys = keys[offset:offset + 25]
            resource = "league/{}/players;player_keys={}/stats;type=lastweek".format(
                quote(league_key, safe=""), ",".join(quote(k, safe=".") for k in sub_keys)
            )
            root = _parse_xml(self.get(resource))
            for player in player_nodes(root):
                result[player["player_key"]] = player["stats"]
        return result

    def player_season_stats(self, league_key: str, keys: List[str]) -> Dict[str, Dict[str, str]]:
        if not keys:
            return {}
        result = {}
        for offset in range(0, len(keys), 25):
            sub_keys = keys[offset:offset + 25]
            resource = "league/{}/players;player_keys={}/stats".format(
                quote(league_key, safe=""), ",".join(quote(k, safe=".") for k in sub_keys)
            )
            root = _parse_xml(self.get(resource))
            for player in player_nodes(root):
                result[player["player_key"]] = player["stats"]
        return result
