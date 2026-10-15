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

## Read-only by design

Yahoo currently provisioned this application for read access. The code does **not** submit add/drop transactions, waiver claims, or lineup changes.

## Local setup

### 1. Clone and install

```bash
git clone https://github.com/robmartinlucas/BaseballAI.git
cd BaseballAI

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configure the Yahoo developer app

In the Yahoo Developer app, add this exact Redirect URI:

```text
https://localhost:5000/oauth/callback
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
YAHOO_REDIRECT_URI=https://localhost:5000/oauth/callback
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
https://localhost:5000
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
