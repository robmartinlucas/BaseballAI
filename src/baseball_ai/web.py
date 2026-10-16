"""Local web application for Yahoo Fantasy Basketball status."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from requests import HTTPError

from .fantasy_data import FantasyDashboardClient
from .strategy import DashboardService

from .yahoo_client import (
    TokenManager,
    TokenStore,
    YahooAuthError,
    YahooConfig,
    YahooFantasyClient,
    YahooOAuth,
)


def create_app() -> Flask:
    load_dotenv(".env", override=True)

    app = Flask(__name__)
    app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)

    config = YahooConfig.from_env()
    token_store = TokenStore(os.getenv("YAHOO_TOKEN_FILE", "instance/yahoo_tokens.json"))
    oauth = YahooOAuth(config)
    tokens = TokenManager(oauth, token_store)
    yahoo = FantasyDashboardClient(tokens)
    dashboard_service = DashboardService(yahoo)

    app.extensions["yahoo_oauth"] = oauth
    app.extensions["yahoo_tokens"] = tokens
    app.extensions["yahoo_client"] = yahoo
    app.extensions["dashboard_service"] = dashboard_service

    @app.get("/")
    def index():
        if not tokens.connected():
            return render_template("index.html", connected=False)

        try:
            game = yahoo.current_nba_game()
            leagues = yahoo.user_leagues(game["game_key"])
            return render_template(
                "index.html",
                connected=True,
                game=game,
                leagues=leagues,
            )
        except Exception as exc:  # show a friendly reconnect/debug path
            return render_template(
                "index.html",
                connected=True,
                error=_friendly_error(exc),
                leagues=[],
            )

    @app.get("/login")
    def login():
        state = secrets.token_urlsafe(32)
        session["oauth_state"] = state
        return redirect(oauth.authorization_url(state))

    @app.get("/oauth/callback")
    def oauth_callback():
        if request.args.get("error"):
            return render_template(
                "error.html",
                message=f"Yahoo authorization failed: {request.args.get('error')}",
            ), 400

        expected_state = session.pop("oauth_state", None)
        received_state = request.args.get("state")
        if not expected_state or received_state != expected_state:
            return render_template(
                "error.html",
                message="OAuth state validation failed. Start the Yahoo connection again.",
            ), 400

        code = request.args.get("code")
        if not code:
            return render_template(
                "error.html",
                message="Yahoo did not return an authorization code.",
            ), 400

        try:
            tokens.save(oauth.exchange_code(code))
        except Exception as exc:
            return render_template("error.html", message=_friendly_error(exc)), 502

        dashboard_service._cache.clear()
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        token_store.clear()
        dashboard_service._cache.clear()
        session.clear()
        return redirect(url_for("index"))

    @app.get("/league/<league_key>/dashboard")
    def league_dashboard(league_key: str):
        if not tokens.connected():
            return redirect(url_for("index"))
        scan = 200 if request.args.get("scan", type=int) == 200 else 100
        trades = request.args.get("trades", "0") == "1"
        refresh = request.args.get("refresh") == "1"

        moves_key = "moves_used_" + league_key
        submitted_moves = request.args.get("moves_used", type=int)
        if submitted_moves is not None and 0 <= submitted_moves <= 100:
            session[moves_key] = submitted_moves
        moves_used = session.get(moves_key)

        limit_key = "weekly_limit_" + league_key
        submitted_limit = request.args.get("weekly_limit", type=int)
        if submitted_limit is not None and 0 <= submitted_limit <= 100:
            session[limit_key] = submitted_limit

        try:
            data = dashboard_service.get(
                league_key, scan=scan, trades=trades, refresh=refresh
            )
        except Exception as exc:
            return render_template(
                "error.html",
                message=_friendly_error(exc),
                connected=True,
            ), 502

        weekly_limit = session.get(limit_key)
        if weekly_limit is None:
            limit_from_yahoo = data["scoring"].get("weekly_add_limit")
            try:
                weekly_limit = int(limit_from_yahoo)
                if weekly_limit <= 0:
                    weekly_limit = None
            except (TypeError, ValueError):
                weekly_limit = None

        remaining_moves = (
            max(0, weekly_limit - moves_used)
            if weekly_limit is not None and isinstance(moves_used, int)
            else None
        )

        return render_template(
            "dashboard.html",
            connected=True,
            data=data,
            scan=scan,
            trades=trades,
            moves_used=moves_used,
            weekly_limit=weekly_limit,
            remaining_moves=remaining_moves,
        )

    @app.get("/league/<league_key>/players")
    def league_players(league_key: str):
        start = max(0, request.args.get("start", default=0, type=int))
        count = 25
        availability = request.args.get("availability", "all")

        try:
            players = yahoo.players_with_ownership(
                league_key,
                start=start,
                count=count,
            )
        except Exception as exc:
            return render_template("error.html", message=_friendly_error(exc)), 502

        if availability != "all":
            players = [
                player
                for player in players
                if _availability_bucket(player["ownership_type"]) == availability
            ]

        return render_template(
            "players.html",
            league_key=league_key,
            players=players,
            start=start,
            count=count,
            availability=availability,
            availability_bucket=_availability_bucket,
        )

    @app.get("/api/league/<league_key>/players")
    def league_players_api(league_key: str):
        start = max(0, request.args.get("start", default=0, type=int))
        count = min(50, max(1, request.args.get("count", default=25, type=int)))

        try:
            players = yahoo.players_with_ownership(
                league_key,
                start=start,
                count=count,
            )
        except Exception as exc:
            return jsonify({"error": _friendly_error(exc)}), 502

        return jsonify(
            {
                "league_key": league_key,
                "start": start,
                "count": len(players),
                "players": players,
            }
        )

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "yahoo_connected": tokens.connected()})

    return app


def _availability_bucket(ownership_type: str) -> str:
    normalized = (ownership_type or "").strip().lower()
    if normalized in {"freeagents", "freeagent", "fa"}:
        return "free_agent"
    if normalized in {"waivers", "waiver", "w"}:
        return "waivers"
    if normalized in {"team", "owned", "t"}:
        return "rostered"
    return "unknown"


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, YahooAuthError):
        return str(exc)
    if isinstance(exc, HTTPError) and exc.response is not None:
        body = exc.response.text.strip()
        return f"Yahoo API returned HTTP {exc.response.status_code}: {body[:600]}"
    return str(exc)


def main() -> None:
    app = create_app()

    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "5050"))
    use_https = os.getenv("WEB_HTTPS", "1").lower() not in {"0", "false", "no"}

    ssl_context = "adhoc" if use_https else None
    scheme = "https" if use_https else "http"
    print(f"Open {scheme}://localhost:{port}")
    if use_https:
        print("A browser warning is expected for the local self-signed certificate.")

    app.run(host=host, port=port, debug=False, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
