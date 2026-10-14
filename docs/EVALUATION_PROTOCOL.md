# Prospective evaluation, version 1

The machine-readable registry is config/evaluation-policy.json. Commit its
version before developing or tuning a challenger. Future changes need a new
candidate version and a fresh forward holdout; do not rewrite an old registry,
receipt or outcome snapshot. The source timestamp of Sleeper projections is
unknown: collection time does not establish source-level as-of correctness.

The v1 registry is retained unchanged in config/policies/. Before any game
outcome, v1.1 corrects ordering of mixed second/microsecond timestamp formats
using parsed UTC instants. Distribution parameters and promotion rules are
unchanged. V1 forecasts remain saved and separately evaluable; versions are
never pooled into additional independent outcomes.

Compare raw Sleeper and the unchanged clone for receptions, rushing attempts,
and passing yards. A pair must come from the same live receipt and the same
player, game and category, with finite projections and collection and generation
times before kickoff. Use the earliest valid paired capture for each opportunity.
Repeated hourly observations are alternatives for the same outcome, not extra
independent samples. Report missing pairs, pending finals, unresolved
participation, DNP and exclusions; never silently turn missing outcomes into zero.
Only games kicking off after registration enter the prospective primary report.
Older games stay available as descriptive evidence.

Outcome selection reads immutable receipts only; it never consults a later
cache or rewrites a forecast/outcome snapshot. A resolved value needs a confirmed
past final and a finite integer statistic (passing yards may be negative; counts
may not). When a saved statistics entry is provided, participation, team and the
actual must agree with it. DNP needs explicit attributed participation; a recorded
void stays a distinct unscored exclusion, without inferring venue settlement.
Incomplete later observations cannot erase a previously confirmed result.

Each player/game/category retains distinct receipt and row digests, declared
source/cache identity and version, collection/source timestamps and observed
status/value in outcome_observations. Repeated identical inputs do not create
additional observations or scored outcomes. Compare versions only within the
same mode, declared source and cache path. A saved cache digest (or saved entry
digest when no cache digest exists) identifies a version. If every candidate in
that origin supplies a valid source timestamp, order by that clock; otherwise
order versions by their first recorded collection time. Seeing an already-known
older cache again does not prove either a stale response or a legitimate value
reversion. Without a source clock, retain that version in the active comparison
and quarantine any resulting disagreement; an actual newer sourced timestamp
can confirm a legitimate reversion. This fallback is local observation ordering,
not proof of source freshness; unknown source timestamps stay unknown.

A later consistent, attributed source version can correct a statistic, with all
old receipts retained. Different unattributed/unversioned finals, conflicting
values within the same latest version, tied latest versions, or disagreeing
current sources are quarantined as unresolved with actual:null and an explicit
outcome_conflict flag. Content-digest ordering does not choose a numeric winner.
Agreement or a later valid source correction may reconcile a conflict; its
original observations remain visible. Quarantined values enter neither point
nor probability score denominators. Single legacy finals remain readable, but
missing provenance cannot justify replacing them with a different final value.

Week completion is separate from the selected statistic receipt. A saved matching
team/kickoff row with a confirmed past final and week_confirmed_complete:true can
establish completion even when that later observation lacks the player's stat.
Keep those completion receipt references separately; an outage does not revoke
an already recorded completion. Missing stats still never become zero.

Point metrics are MAE, RMSE and signed mean error, separately by category. Paired
error differences use the same outcomes. Report lead time and injury coverage.
Use a week-cluster bootstrap to keep correlated players and games together;
before eight completed weeks, uncertainty is unavailable. The prespecified
98.33% intervals address the three primary comparisons. Do not combine yards
and counts into a single unscaled accuracy number.

For each category's primary interval, every scored row in a season/week cluster
must have week_confirmed_complete literally true; otherwise exclude that entire
cluster from resampling. The gate still requires eight eligible completed weeks.
Sort eligible week keys before seeded resampling, draw the same number of whole
week blocks with replacement, and retain every paired row in each drawn block.
Each replicate divides summed paired absolute-error differences by the sampled
number of paired outcomes, not by an unweighted average of week means. The
registered seed, replicate count, confidence, thresholds and policy files stay
unchanged.

Report observed, resampled and excluded week/outcome counts, plus the completed-
week paired MAE delta corresponding to the interval. Overall point MAE/RMSE/bias
and paired delta still describe all resolved matched observations, including
partial weeks; their denominator can differ from the completed-week interval.
Use completed_week_mae_delta_clone_minus_raw for its matching point estimate.
Before eight eligible completed weeks, the interval remains unavailable even
when many partial weeks or observations exist. No interval supplies independent
evidence for repeated captures, and completed-week clustering does not establish
calibration, profitability or production readiness.

The first shadow challenger centers on the retained clone and adds a historical
dispersion estimate. Count targets use negative-binomial/Poisson distributions;
yards use an integer-discretized normal that permits negative yards. Dispersion
is shrunk toward fixed priors with eight prior games. Only played observations
from earlier weeks of the same season in the saved build-input snapshot enter
training. Priors are engineering assumptions, not fitted calibration claims.
Save fixed-prior distribution references centered on raw Sleeper and the clone
at the same time as the challenger. These new probability references are not
probabilities produced by the original application.

Probability evaluation reports negative log likelihood, three-way Brier score
(under/equal/over), and central 80% interval coverage, on matched saved forecasts.
Both sides of a line and repeated lines share one outcome; score one recorded
line per opportunity. This tests statistical events, not venue-specific voids,
injury insurance, contest settlement, payouts or profitability.

Promotion is manual and remains disabled. Require at least 200 resolved
player-game outcomes per target and eight completed weeks, at least 2% MAE
improvement, no more than 2% RMSE regression, simultaneous cluster intervals
below zero, better proper probability scores than the saved clone reference,
and holdout calibration, tail, coverage and integrity review. The first
challenger retains the clone's center, so it cannot demonstrate point-MAE
improvement merely by adding a distribution. Passing software tests never
promotes a model. EV/ROI claims additionally require complete entry economics
and verified venue settlement. Explicit owner approval is required before a
production-model change.
