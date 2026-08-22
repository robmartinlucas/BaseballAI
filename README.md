# BaseballAI

BaseballAI is a personal, non-commercial project for integrating with Yahoo Fantasy Baseball and assisting with fantasy roster management.

## Purpose

The project is intended for a single user managing their own Yahoo Fantasy Baseball team. Its goals are to:

- Read league, team, roster, player, standings, and transaction data from the Yahoo Fantasy Sports API.
- Analyze available players and roster needs.
- Produce roster and lineup recommendations.
- If Yahoo grants the required authorization, submit user-authorized roster transactions such as add/drop moves and lineup changes.

## Intended Use

- **Users:** 1
- **Leagues:** Personal fantasy leagues owned or joined by the user
- **Commercial use:** None
- **Data resale or redistribution:** None
- **Public exposure of Yahoo Fantasy data:** None

BaseballAI is not a public fantasy platform, paid service, or data redistribution product. It is a private utility for managing the owner's own fantasy baseball participation.

## Yahoo API Access

The application is designed to authenticate through Yahoo-supported OAuth and use only permissions explicitly granted by Yahoo and the account owner.

API credentials, OAuth tokens, refresh tokens, and other secrets are never committed to this repository. Local configuration is loaded from environment variables.

Write functionality is conditional on Yahoo granting the necessary API permissions. If write access is unavailable, the project operates in analysis/read-only mode and does not attempt to bypass Yahoo's access controls.

## Planned Components

- Yahoo OAuth authentication
- League and team discovery
- Roster retrieval
- Free-agent and waiver-player analysis
- Player comparison and recommendations
- Transaction preparation
- Optional user-authorized add/drop and lineup transactions when supported by Yahoo

## Privacy and Security

This project is intended to access only the owner's authorized Yahoo Fantasy account data. Credentials and tokens are stored locally and excluded from source control.

## Status

Early development / personal project.

## Disclaimer

This project is not affiliated with, endorsed by, or sponsored by Yahoo. Yahoo and Yahoo Fantasy Sports are trademarks of their respective owners.
