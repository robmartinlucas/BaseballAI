"""Offline parser and recommendation tests; no Yahoo credentials required."""

import unittest
import xml.etree.ElementTree as ET
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from baseball_ai.fantasy_data import FantasyDashboardClient, parse_player, parse_team, parse_stats
from baseball_ai.strategy import (
    bucket,
    category_signal,
    drop_watchlist,
    matchup_categories,
    numeric,
    risk,
    schedule_window,
    score_free_agents,
)


class ParserTests(unittest.TestCase):
    def test_player_and_owner(self):
        node = ET.fromstring("""
        <player>
          <player_key>478.p.99</player_key>
          <name><full>Example Guard</full></name>
          <editorial_team_abbr>LAL</editorial_team_abbr>
          <display_position>PG,SG</display_position>
          <status>GTD</status>
          <ownership>
            <ownership_type>freeagents</ownership_type>
          </ownership>
          <player_stats><stats>
            <stat><stat_id>12</stat_id><value>102</value></stat>
          </stats></player_stats>
        </player>
        """)
        player = parse_player(node)
        self.assertEqual(player["name"], "Example Guard")
        self.assertEqual(player["stats"], {"12": "102"})
        self.assertEqual(bucket(player["ownership_type"]), "free_agent")
        self.assertEqual(risk(player), "questionable")

    def test_ranked_scan_uses_yahoo_overall_rank_sort(self):
        xml = b"""<fantasy_content><league><players>
            <player><player_key>478.p.5</player_key>
            <name><full>Example</full></name>
            <ownership><ownership_type>freeagents</ownership_type></ownership>
            </player>
        </players></league></fantasy_content>"""
        client = object.__new__(FantasyDashboardClient)
        client.get = Mock(return_value=SimpleNamespace(content=xml))
        result = client.league_player_page("478.l.123", 25, 25, ranked=True)
        url = client.get.call_args[0][0]
        self.assertIn(";sort=OR;start=25;count=25/ownership", url)
        self.assertEqual(result[0]["yahoo_sort_position"], 26)
        self.assertEqual(result[0]["ownership_type"], "freeagents")

    def test_team_scores(self):
        node = ET.fromstring("""
        <team>
          <team_key>478.l.123.t.2</team_key>
          <name>Team Two</name>
          <team_stats><stats>
            <stat><stat_id>12</stat_id><value>234</value></stat>
          </stats></team_stats>
        </team>
        """)
        team = parse_team(node)
        self.assertEqual(team["stats"]["12"], "234")
        self.assertEqual(team["name"], "Team Two")


class DecisionTests(unittest.TestCase):
    def test_category_edges_and_turnovers(self):
        matchup = {
            "teams": [
                {"team_key": "a", "stats": {"12": "100", "19": "40", "5": ".450"}},
                {"team_key": "b", "stats": {"12": "105", "19": "45", "5": ".457"}},
            ]
        }
        cats = [
            {"id": "12", "name": "PTS"},
            {"id": "19", "name": "TO"},
            {"id": "5", "name": "FG%"},
        ]
        by_name = {x["name"]: x for x in matchup_categories(cats, matchup, "a")}
        self.assertEqual(by_name["PTS"]["state"], "losing")
        self.assertTrue(by_name["PTS"]["close"])
        self.assertEqual(by_name["TO"]["state"], "winning")
        self.assertEqual(by_name["FG%"]["state"], "losing")

    def test_absent_matchup_not_fabricated(self):
        self.assertEqual(matchup_categories([], None, "a"), [])
        self.assertEqual(numeric("—"), None)

    def test_rank_availability_and_injuries(self):
        candidates = [
            {"name": "A", "stats": {}, "risk": "none", "games_remaining": 4},
            {"name": "B", "stats": {}, "risk": "out", "injury_status": "INJ",
             "games_remaining": 4},
        ]
        ranked = score_free_agents(candidates, [], {"available": True})
        self.assertEqual(ranked[0]["name"], "A")
        self.assertTrue("upcoming NBA game" in ranked[0]["reason"])

    def test_yahoo_overall_rank_beats_one_extra_game(self):
        candidates = [
            {"name": "Higher ranked", "stats": {}, "risk": "none", "games_remaining": 3,
             "yahoo_sort_position": 170},
            {"name": "Lower ranked", "stats": {}, "risk": "none", "games_remaining": 4,
             "yahoo_sort_position": 280},
        ]
        ranked = score_free_agents(candidates, [], {"available": True, "rankable": True})
        self.assertEqual(ranked[0]["name"], "Higher ranked")
        self.assertIn("Yahoo overall-rank sort position", ranked[0]["reason"])

    def test_risk_is_watchlist_not_drop_automation(self):
        roster = [
            {"name": "Injured", "risk": "out", "injury_status": "INJ", "games_remaining": 3},
            {"name": "Healthy", "risk": "none", "injury_status": "", "games_remaining": 3},
        ]
        flagged = drop_watchlist(roster, {"available": True})
        self.assertEqual([p["name"] for p in flagged], ["Injured"])

    def test_schedule_fallback_is_unverified(self):
        window = schedule_window(None)
        self.assertFalse(window["verified"])
        self.assertEqual(window["start"], date.today())


if __name__ == "__main__":
    unittest.main()
