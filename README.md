# BaseballAI

A small personal, non-commercial Yahoo Fantasy Sports web app. The current UI is focused on **Yahoo Fantasy Basketball** and uses Yahoo's read-only Fantasy Sports API access.

## What it does

- Handles Yahoo OAuth in the browser.
- Stores OAuth tokens locally outside source control.
- Refreshes access tokens automatically using the Yahoo refresh token.
- Finds the current Yahoo Fantasy Basketball season and your leagues.
- Pages through league players.
- Reads each player's Yahoo `ownership` resource to show:
  - rostered
  - free agent
  - waivers
  - unknown
- Also shows NBA team, fantasy position eligibility, and Yahoo injury/status text.
- Exposes the same player data as a small local JSON endpoint.

The app intentionally avoids Yahoo's `status=A` and `status=FA` player filters because those filters have hung during current API testing. It retrieves player ownership directly instead.

## Matchup command center

Choose a league from the home page to open its dashboard. The app is intended to
support **winning the current head-to-head category matchup**, without implying
that a short-term gain guarantees a win.

- **Category battle:** Your current Yahoo H2H category values, opponent scores,
  and close/tied categories that might be worth targeting. These are *actual
  scores*, not projections.
- **Weekly game plan:** A manual tracker for how many adds you have used this
  week. The app reads the weekly add limit from Yahoo settings when supplied;
  your remaining adds are an estimate based on your manual entry.
- **Add candidates:** Yahoo-confirmed free agents and waiver players found by
  checking ownership across the first **300 Yahoo overall-rank-sorted players**,
  expandable to **500**. Prioritizes Yahoo ranking context, injury risk,
  upcoming games, and available category stats; one extra game is not assumed
  to make an otherwise weaker player a better add. If Yahoo's documented
  `sort=OR` filter fails, falls back to the unranked collection and labels it.
  Does not use Yahoo's `status=A/FA` filters because they hung during testing.
- **Roster pulse:** Your team, injury alerts, upcoming games, and available
  recent seven-day category results. Season or recent stats may be empty early
  in the season. The app does not equate raw weekly totals to per-game trends.
- **Drop watchlist:** Players with short-term injury/playing-window concerns,
  clearly marked **review**, not an instruction to cut them.
- **Trade radar:** An on-demand scan of other managers' current rosters,
  showing potential targets and the owner to approach. Before Week 1, uses
  Yahoo's overall-ranking order for players in the ranked player scan rather
  than showing arbitrary alphabetic names. Category fit uses available Yahoo
  season stats; this is still **not** a fair-value calculation, trade package,
  or actual trade offer.

Upcoming NBA contests use ESPN's unofficial public schedule feed when it
responds. It is separate from Yahoo and can fail or change. Game counts are
used to rank matchup streamers **only** when Yahoo supplies a verified matchup
date window. Always check Yahoo's current lineup, acquisition limit, free
agent/waiver state, and player game eligibility before making changes.

Results are cached locally for five minutes. Use **Refresh Yahoo data**
to force another fetch. A ranked scan of 300 players involves roughly 12
paginated Yahoo API requests plus stat and roster requests, so the first
refresh may take noticeably longer. Expanded scans and the trade radar make
additional requests. Players may appear with missing injury or season stats
before the NBA season starts.

### Update an existing connected installation

If you already have the app working on `https://127.0.0.1:5000`,
**do not change the Yahoo redirect URI or your existing `.env`**:

```bash
# Stop the current server with Control-C first.
cd ~/Development/BaseballAI
git pull --ff-only
source .venv/bin/activate
python -m pip install -e .
baseball-ai
```

Then visit `https://127.0.0.1:5000` and click your basketball league.
Your existing locally saved Yahoo tokens stay in `instance/`.

### Offline checks

These tests require no Yahoo credentials or ESPN connection:

```bash
python -m unittest discover -s tests -v
```

The repository also contains a GitHub Actions workflow for Python 3.9 and 3.11.

## Read-only by design

Yahoo currently provisioned this application for read access. The code does **not** submit add/drop transactions, waiver claims, or lineup changes.

## Local setup

Requires **Python 3.9+**.

### 1. Clone and install

```bash
git clone https://github.com/robmartinlucas/BaseballAI.git
cd BaseballAI

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

### 2. Configure the Yahoo developer app

In the Yahoo Developer app, add this exact Redirect URI:

```text
https://localhost:5050/oauth/callback
```

The Redirect URI in Yahoo and `YAHOO_REDIRECT_URI` in your local `.env` file must match exactly.

### 3. Create local environment settings

```bash
cp .env.example .env
```

Fill in:

```text
YAHOO_CLIENT_ID=...
YAHOO_CLIENT_SECRET=...
YAHOO_REDIRECT_URI=https://localhost:5050/oauth/callback
FLASK_SECRET_KEY=...
```

Generate a Flask secret with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Never commit the completed `.env` file.

### 4. Run

```bash
baseball-ai
```

Then open:

```text
https://localhost:5050
```

The development server uses a local self-signed HTTPS certificate, so your browser will display a certificate warning. Continue to the local site, click **Connect Yahoo**, approve access, and Yahoo will redirect back to the app.

After the first successful login, you should not need to copy/paste authorization codes or access tokens. Tokens are stored locally at:

```text
instance/yahoo_tokens.json
```

The entire `instance/` directory is ignored by git.

## Player status page

Choose a league from the home page. The player table shows ownership status plus player metadata.

Pagination requests Yahoo in groups of 25:

```text
/league/{league_key}/players;start={start};count=25/ownership
```

The app maps Yahoo ownership types into the UI:

- `freeagents` → Free agent
- `waivers` → Waivers
- `team` → Rostered

A JSON view is also available:

```text
/api/league/{league_key}/players?start=0&count=25
```

## Security

- Yahoo Client Secret stays in the local `.env` file.
- OAuth access and refresh tokens stay in `instance/yahoo_tokens.json`.
- Both are excluded from git.
- The local token file is chmod'd to user-only permissions when the operating system supports it.
- OAuth uses a random `state` value to protect the callback flow.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Yahoo. Yahoo and Yahoo Fantasy Sports are trademarks of their respective owners.
