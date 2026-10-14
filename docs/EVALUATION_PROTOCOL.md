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

Point metrics are MAE, RMSE and signed mean error, separately by category. Paired
error differences use the same outcomes. Report lead time and injury coverage.
Use a week-cluster bootstrap to keep correlated players and games together;
before eight completed weeks, uncertainty is unavailable. The prespecified
98.33% intervals address the three primary comparisons. Do not combine yards
and counts into a single unscaled accuracy number.

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
