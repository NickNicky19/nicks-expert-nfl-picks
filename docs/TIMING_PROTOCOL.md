# Separate selection and timing extension, version 1

**Status: registered design only, not implemented or deployed.** The current
owner safely hands this stage off while the GitHub-triggered Codex environment
is blocked. There is no timing recorder, checkpoint scorecard, confirmation
evaluator or new About feature yet. The following rules specify the next
implementation stage; descriptions of those rules are not completion claims.

Registry: `config/timing-policy.json`, phase2-timing-v1. This extends reporting;
it does not change the raw Sleeper versus clone experiment, its earliest paired
capture, categories, metrics, promotion criteria or immutable registry.
Production selection rules and the shadow model are unchanged.

The fixed checkpoints are 24 hours, 6 hours and 90 minutes before the **saved**
kickoff. At each boundary use the latest snapshot already recorded at or before
that boundary, at most 60 minutes old. This supports the existing hourly runner;
it does not promise an exact fresh quote at the boundary. Capture age and source
timestamp availability are reported. Never substitute a later forecast, price,
line, eligibility state or direction. A missing snapshot produces NO_ACTION;
an unknown opportunity universe is reported as unknown. A checkpoint preceding
registration is excluded, even if its game has not started. Changed schedules
are flagged; saved decisions are not moved or rewritten.

Preserve the recorded selection time and kickoff in UTC, derive their two
weekdays separately with America/Chicago (including daylight saving), and save
seconds remaining at the selection time. The scheduled checkpoint time is an
additional field, not a replacement selection timestamp. Grading collection
time never determines a performance weekday.

Compare recorded selected overs and unders separately for Top Picks and all
qualifying leans. A Top Pick is recorded membership, not a fresh ranking. A
qualifying lean is the recorded over/under against a real DraftKings or Sleeper
line; it need not pass the stricter Top Pick role filter. Top Picks are also
leans, so these two cohorts overlap and must not be pooled. Scope includes the
ten retained pickable statistic categories, including rush + receiving yards.
"Venue" means offer venue (DraftKings or Sleeper), not an invented stadium.
Model version includes the retained engine digest. Shadow forecasts have no
recorded selections and do not acquire inferred over/under decisions.

Older receipts provide a separate descriptive history: first recorded selected
decision per player/game/category **within each cohort**, or the first NO_ACTION
if never selected. This is not a retrospectively registered checkpoint policy.
Unknown historical eligibility and prices stay unknown. Earlier NO_ACTIONs,
later changes and every source receipt remain available; duplicates do not add
outcomes. Checkpoint policies freeze all decisions, including NO_ACTION, once.

Each policy reports its observed universe, available snapshots, qualifying and
selected coverage, exclusions and unique games/weeks. Checkpoint comparisons
first audit the common universe (including NO_ACTION), then compare selections
on the same player/game/category, venue and model. Each policy retains its own
line and side; line changes and direction flips are reported. Report each
policy's total coverage alongside its matched subset. The same underlying
outcome appearing at several checkpoints is not independent evidence.

Report selected n, unique games/weeks, wins, losses, pushes, confirmed DNP,
pending/unresolved and hit rate (W / (W + L)). These are **statistical** results,
not venue settlement. No standard odds are assumed. The supported feed has no
verified full entry payout or entry-specific settlement, and DraftKings prices
are absent, so paper profit and ROI are unavailable. Sleeper leg multipliers
remain captured observations; a multi-leg ticket's payout cannot be attributed
to an individual over/under subgroup.

All category, venue, model and day/timing subgroup tables are exploratory.
Selections from one game, nested cohorts and repeated checkpoint policies are
related. Use whole NFL weeks as bootstrap clusters; require eight completed
weeks, twenty games and thirty decided selections per side for the fourteen
registered overall/checkpoint contrasts. Their intervals use Bonferroni family
correction. Subgroup tables have no significance declarations. Rates compare
selected populations and do not identify a causal weekday effect.

Observed leaders need ten decided selections and five games but are explicitly
unconfirmed. Confirmation requires a separate immutable hypothesis registered
before later games, a fixed group/comparator/side/cohort/checkpoint, and its hash
already saved in those games' observation receipts. Use only decisions and
games after both registration and discovery cutoff, at least eight completed
weeks, twenty games and 100 decided selections in each group. Correct across
all ten permitted hypothesis slots. A positive simultaneous interval is a
later-game finding for that fixed contrast, not profitability or model
promotion. With no registered hypothesis or insufficient evidence, confirmed
findings stay empty. Reports never switch production models automatically.

This policy is preserved before the extension implementation and before any
eligible checkpoint outcomes. Future parameter changes require a new version;
never edit a registry already referenced by a decision receipt.
