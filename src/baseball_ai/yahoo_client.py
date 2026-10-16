"""Yahoo Fantasy OAuth and read-only API client.

The application intentionally implements read operations only. OAuth tokens are
stored locally outside source control and refreshed automatically when possible.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import quote, urlencode
import xml.etree.ElementTree as ET

import requests


API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


class YahooAuthError(RuntimeError):
    """Raised when Yahoo OAuth credentials or tokens are unavailable."""


@dataclass(frozen=True)
class YahooConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> "YahooConfig":
        missing = [
            name
            for name in ("YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET", "YAHOO_REDIRECT_URI")
            if not os.getenv(name)
        ]
        if missing:
            raise YahooAuthError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        return cls(
            client_id=os.environ["YAHOO_CLIENT_ID"],
            client_secret=os.environ["YAHOO_CLIENT_SECRET"],
            redirect_uri=os.environ["YAHOO_REDIRECT_URI"],
        )


class TokenStore:
    """Small local JSON token cache.

    The default path is under instance/, which is ignored by git.
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, token: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(token, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class YahooOAuth:
    def __init__(self, config: YahooConfig) -> None:
        self.config = config

    def authorization_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.config.client_id,
                "redirect_uri": self.config.redirect_uri,
                "response_type": "code",
                "language": "en-us",
                "state": state,
            }
        )
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = requests.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "redirect_uri": self.config.redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
        return _normalize_token(token)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        response = requests.post(
            TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "redirect_uri": self.config.redirect_uri,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json()
        if "refresh_token" not in token:
            token["refresh_token"] = refresh_token
        return _normalize_token(token)


class TokenManager:
    def __init__(self, oauth: YahooOAuth, store: TokenStore) -> None:
        self.oauth = oauth
        self.store = store

    def connected(self) -> bool:
        token = self.store.load()
        return bool(token.get("access_token") or token.get("refresh_token"))

    def save(self, token: dict[str, Any]) -> None:
        self.store.save(_normalize_token(token))

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        token = self.store.load()
        if not token:
            raise YahooAuthError("Yahoo is not connected yet.")

        expires_at = float(token.get("expires_at", 0))
        needs_refresh = force_refresh or not token.get("access_token") or time.time() >= expires_at - 60

        if needs_refresh:
            refresh_token = token.get("refresh_token")
            if not refresh_token:
                raise YahooAuthError("Yahoo session expired. Connect Yahoo again.")
            token = self.oauth.refresh(refresh_token)
            self.store.save(token)

        access_token = token.get("access_token")
        if not access_token:
            raise YahooAuthError("Yahoo did not return an access token.")
        return str(access_token)


def _normalize_token(token: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(token)
    expires_in = int(normalized.get("expires_in", 3600))
    normalized["expires_at"] = int(time.time()) + expires_in
    return normalized


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_descendant(element: ET.Element, name: str) -> Optional[ET.Element]:
    for child in element.iter():
        if _local_name(child.tag) == name:
            return child
    return None


def _text(element: ET.Element, name: str, default: str = "") -> str:
    child = _first_descendant(element, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def _parse_xml(response: requests.Response) -> ET.Element:
    try:
        return ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise RuntimeError("Yahoo returned an unreadable XML response.") from exc


class YahooFantasyClient:
    """Authenticated read-only client for Yahoo Fantasy Sports."""

    def __init__(self, tokens: TokenManager) -> None:
        self.tokens = tokens
        self.session = requests.Session()

    def get(self, resource: str) -> requests.Response:
        url = f"{API_BASE}/{resource.lstrip('/')}"
        token = self.tokens.get_access_token()

        response = self.session.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/xml",
            },
            timeout=30,
        )

        if response.status_code == 401:
            token = self.tokens.get_access_token(force_refresh=True)
            response = self.session.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/xml",
                },
                timeout=30,
            )

        response.raise_for_status()
        return response

    def current_nba_game(self) -> dict[str, str]:
        root = _parse_xml(self.get("game/nba"))
        game = _first_descendant(root, "game")
        if game is None:
            raise RuntimeError("Yahoo did not return the current NBA fantasy game.")

        return {
            "game_key": _text(game, "game_key"),
            "name": _text(game, "name"),
            "season": _text(game, "season"),
        }

    def user_leagues(self, game_key: str) -> list[dict[str, str]]:
        root = _parse_xml(
            self.get(f"users;use_login=1/games;game_keys={quote(game_key)}/leagues")
        )
        leagues: list[dict[str, str]] = []

        for element in root.iter():
            if _local_name(element.tag) != "league":
                continue
            league_key = _text(element, "league_key")
            if not league_key:
                continue
            leagues.append(
                {
                    "league_key": league_key,
                    "league_id": _text(element, "league_id"),
                    "name": _text(element, "name"),
                    "season": _text(element, "season"),
                    "draft_status": _text(element, "draft_status"),
                }
            )

        # Yahoo's XML can contain repeated league structures in nested responses.
        unique: dict[str, dict[str, str]] = {}
        for league in leagues:
            unique[league["league_key"]] = league
        return list(unique.values())

    def players_with_ownership(
        self,
        league_key: str,
        *,
        start: int = 0,
        count: int = 25,
    ) -> list[dict[str, str]]:
        # We intentionally do not use ;status=A or ;status=FA. In testing,
        # Yahoo's current service can hang on those filters. Ownership is
        # requested as a player subresource and filtered/displayed locally.
        safe_count = max(1, min(count, 50))
        safe_start = max(0, start)
        resource = (
            f"league/{quote(league_key)}/players;"
            f"start={safe_start};count={safe_count}/ownership"
        )
        root = _parse_xml(self.get(resource))
        players: list[dict[str, str]] = []

        for element in root.iter():
            if _local_name(element.tag) != "player":
                continue

            player_key = _text(element, "player_key")
            if not player_key:
                continue

            name_element = _first_descendant(element, "name")
            full_name = _text(name_element, "full") if name_element is not None else ""

            ownership_element = _first_descendant(element, "ownership")
            ownership_type = (
                _text(ownership_element, "ownership_type")
                if ownership_element is not None
                else ""
            )

            players.append(
                {
                    "player_key": player_key,
                    "name": full_name,
                    "nba_team": _text(element, "editorial_team_abbr"),
                    "positions": _text(element, "display_position"),
                    "injury_status": _text(element, "status"),
                    "ownership_type": ownership_type,
                    "owner_team_name": (
                        _text(ownership_element, "owner_team_name")
                        if ownership_element is not None
                        else ""
                    ),
                    "owner_team_key": (
                        _text(ownership_element, "owner_team_key")
                        if ownership_element is not None
                        else ""
                    ),
                    "waiver_date": (
                        _text(ownership_element, "waiver_date")
                        if ownership_element is not None
                        else ""
                    ),
                }
            )

        # De-duplicate in case Yahoo repeats player nodes in nested XML.
        unique: dict[str, dict[str, str]] = {}
        for player in players:
            unique[player["player_key"]] = player
        return list(unique.values())
