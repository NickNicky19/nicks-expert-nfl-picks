# Sleeper NFL selection capture

The adapter reuses the existing request to api.sleeper.app/lines/available; it
adds no endpoint, paid dependency, account or wagering action. It records normal,
active, pregame NFL player selections for receptions, rushing attempts and
passing yards. Other sports, alternatives, season-long and started-game offers
are outside this first scope. NFL event mapping requires agreement with the
same current-week Sleeper projection input and the builder's team/opponent.
Rest-of-season projection requests cannot replace that current-week mapping.

Each captured selection includes the source game/line/market IDs, exact player
contract, line, side, raw offered multiplier, collection time, raw updated_at and
its UTC interpretation when valid, and rule-document provenance. The provider
updated_at field is not represented as a guaranteed quote time or executable
availability. Preserve raw source fields rather than estimating omitted prices.
New collection receipts retain microseconds, so an update earlier within the
same second is not incorrectly flagged as future. Existing second-resolution
receipts remain unchanged; raw provider epoch milliseconds are always retained.

Collection status is complete_selection_capture, no_offer, source_unavailable
or missing_information. An empty successful response is different from a failed
request. Malformed/ambiguous contracts and missing game/price/rule fields remain
incomplete. The raw target-scope source rows and full-response digest accompany
the normalized records, so failures and transformations can be reproduced.

A complete selection capture is not a complete executable contest entry. Full
entry format, payout table, acceptance/context and entry-specific settlement
binding remain missing, with complete_executable_entries = 0. Both source-side
multipliers are retained independently; no American odds, break-even chance,
combined payout, EV or ROI is invented. Statistical outcomes and probabilities
are kept separate from venue injury insurance, voids and settlement.

The retrieved rule versions are recorded in config/sleeper-rules-provenance.json
with URLs, retrieval times and HTTP-content hashes. Relevant official references:

- [Player Picks rules](https://support.sleeper.com/en/articles/9047931-sleeper-player-picks-rules)
- [NFL injury insurance](https://support.sleeper.com/en/articles/9869560-nfl-injury-insurance)
- [Picks statistics](https://support.sleeper.com/en/articles/6262990-sleeper-player-picks-stats-explained)
- [Public API documentation](https://docs.sleeper.com/)

The rules describe contest-level payouts, participation/void conditions and
statistical treatment; this adapter records their provenance without claiming
that a particular entry has been accepted or that its final settlement is known.
The public API documentation describes non-commercial read-only access but does
not separately document this Picks endpoint. This change reuses the repository's
existing hobby collection; expanded or commercial licensing is not established.
If a source becomes unavailable, retain the explicit status; do not add an
account/service or bypass access controls to obtain missing entry information.
