# Selected forecasts in Top Picks and sorting

This is an integration of the existing issued forecasts, not a new fitted model
or proof of a forecasting gain. Scientific registrations and R0 evidence stay
unchanged. The source release and actual deployment are reported separately.

## What the user sees

Props defaults to **New forecasts: biggest gap**. A selected category enables
**New forecast: highest**, or **New TD probability: highest** for anytime TD.
Highest-value sorting uses only valid selected values, with missing values last.
Raw values from different categories are never compared in that mode.

Top Overs and Top Unders read a saved selected-ranking snapshot. Every card
labels its selected mean/median, or its R0 fallback. Expanded cards and chips
use the selected forecast for directional leans; a custom line affects only
that user's displayed lean. Official Top Picks retain their original recorded
sportsbook line. Explicit R0 and fantasy-point sorts remain available.

The fixed numeric ranking is `(forecast - line) / category_scale`, using the
existing category scales and lean thresholds. It retains the existing limit of
12 per side, minimum score 0.35, two earlier games, supported 50% snap share,
position-specific projected-PPR eligibility, minimum lines and the 0.4–2.5
projection/line range. The range now checks the effective selected-or-R0 point.
One best prop per player/side is retained; ties use game, player and category IDs.
These eligibility restrictions apply to Top Picks, not the full forecast display.

This is a descriptive forecast-gap ranking. A count mean or yard median does
not supply an over/under probability or expected return. Anytime TD remains a
genuine rushing-or-receiving event probability, with its separate sort.

## Persistence and publication

The existing serialized website writer prepares the new snapshot after the
validated overlay. `weekly-selected-rankings-v1` stores exact market lines,
directions, forecasts, products, model/source-row identities, selected-row
canonical bytes and selection clocks. It does not overwrite canonical R0 data.
The public pointer is `data/weekly-selected-rankings.json`; bodies and completion
receipts are content-addressed under `data/weekly-selected-rankings/`.

Body readback precedes the actual completion clock and pointer publication.
Crossing kickoff or forecast expiry rejects publication. Started games retain
their previously persisted selections and original completion receipts. No
selected pregame record means no retrospective selected Top membership. A
forecast expiring before kickoff cannot become a frozen selection. Expired
displayed entries are omitted without promoting unrecorded replacements.

Missing selected forecasts can use a labeled same-opportunity R0 point. Missing
statistics are not set to zero. Invalid prior selection evidence fails closed.
Without a validated matching selection snapshot, the browser explicitly shows
the original R0 Top list. Source checks bind the existing feed policy to all
14 approved code paths, and the workflow binds the exact policy bytes.

The public graph validator checks the active ranking body and completion
receipt, and the original receipts/bodies supporting frozen selections. Its
staging allowlist includes these assets. Reloading a new process revalidates
physical hashes, board/overlay compatibility, original lines and membership.
Canonical reference history/grades remain separate, within their actual saved
model/engine cohorts. Original R0 identities stay historical. The Record page
does not score the provisional selected stream as reference history or as the
registered Biggest-lean/Projected-points strategies. New Top cards display final
pushes explicitly; live results remain
provisional because signed yardage and corrections can move down.

## Checks and recovery

Fictional Python tests cover reversal of R0 direction, zero/signed values,
missing/expired inputs, deterministic ties, no retrospective membership,
kickoff/expiry crossing, immutable restoration, fresh-process readback and the
complete public graph. Cross-language tests consume Python-produced artifacts
with the actual JS validator; optional browser checks use actual render functions
at 320, 390 and 1280 pixels, with all HTTP blocked. These are software checks,
not additional NFL observations or evidence of forecast accuracy.

```sh
python -m unittest discover -s tests -v
node tests/test-selected-rankings.cjs
SELECTED_RANKINGS_BROWSER=1 node tests/test-selected-rankings.cjs
node tests/test-weekly-primary-forecast.cjs
```

Recovery restores a compatible reader/producer/policy set through the ordinary
reviewed workflow. Preserve all ranking snapshots and receipts. Reverting only
the display to R0 is a fallback, not deletion of the selected stream's evidence.
The scientific model catalog, private models, source policies, odds acquisition,
existing scheduler and exact-PPR label status are not changed by this integration.

## Phase 2 integration boundary

The selected stream preserves the stricter Phase 2 outcome identity/finality
checks and unknown-TD handling. My Picks, personal lines, paper tickets and saved
reference forecasts retain their original bytes and settlement rules. Complete
Pages validation includes the current ranking body/receipt and every required
original frozen body/receipt, using role-specific streamed size caps. An invalid
or missing dependency fails without substituting another generation.

The integrated source still requires fresh source CI, operating acceptance,
production-rooted artifact review and actual deployment verification. Prior
rankings deployment does not certify the expanded Phase 2 release.
