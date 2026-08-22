"""Minimal Yahoo Fantasy API client foundation.

Write operations are intentionally not implemented here. They should only be
added if Yahoo grants the application the required permissions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests


API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"


@dataclass(frozen=True)
class YahooConfig:
    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_env(cls) -> "YahooConfig":
        return cls(
            client_id=os.environ["YAHOO_CLIENT_ID"],
            client_secret=os.environ["YAHOO_CLIENT_SECRET"],
            redirect_uri=os.environ["YAHOO_REDIRECT_URI"],
        )


class YahooFantasyClient:
    """Small authenticated HTTP client for Yahoo Fantasy endpoints."""

    def __init__(self, access_token: str) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/xml",
            }
        )

    def get(self, resource: str) -> requests.Response:
        """Fetch an authorized Yahoo Fantasy resource."""
        url = f"{API_BASE}/{resource.lstrip('/')}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response
