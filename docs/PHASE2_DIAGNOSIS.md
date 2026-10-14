# Matchup verification diagnosis

Source of truth: main at 3149663447b29f95f06c7259b84da3bd4a21cab0,
including the three original forward receipts. No old ZIP supplied the source.

Before edits, remote backup/pre-phase1-20261013-210e34329d6e was verified at
210e34329d6e5b42b4e8f1af768b63db75ec10c5 (tree 4c2349e3a37905ad8043437b9f661227be488a2c).
Its original app, grader and seven model files match the pinned original source.
The working Phase 1 backup is backup/pre-phase2-20261014-3149663447b2 at
3149663447b29f95f06c7259b84da3bd4a21cab0 (tree 880aa7e3b980be3bf55cb27cb735bf9a3d9a74f3).
Both references were read back remotely before source edits.

The latest inspected successful production run was 38485592435, job 115598343410.
Its overall success did not mean every diagnostic passed: the legacy verifier
reported 805 failures. The original input/output and full local diagnostic log
are retained in a content-addressed diagnostic envelope in data/verification/2026/w06.

Reproduction checked 1,864 factors. The verifier reconstructed the population
from 445 published skill players; the builder used 840 rostered skill players,
including players whose teams have a bye. The subset reproduced 805 factor or
sample-count mismatches. A contemporaneous full-roster observation reproduced
zero. That newer observation explains this snapshot but cannot prove the exact
roster used by an earlier build; the evidence labels that limitation explicitly.
PPR/half-PPR, shape and lean-balance checks found no other failures. All 55
matched previous-week kicker/defense scores agreed. There were no final games
this week, so live scoring coverage was unavailable, not demonstrated.

Two separate reproducibility hazards remain relevant: recent cached statistics
can change following corrections, and started games retain earlier forecasts.
tools/build_recorded.py now wraps the unchanged builder, captures its exact full
positions and prior-week stats, and preserves each frozen game's original input
reference. The verifier rebuilds from those inputs instead of a fresh roster or
mutable cache. Missing original proof, tampering, future inputs, changed frozen
forecasts, wrong factors and wrong sample counts still fail.

The first recorded live rebuild checked 1,860 factors with zero discrepancies;
source changes account for the different count. The seven baseline engine blobs
remain byte-identical. This is software verification, not evidence that the
matchup adjustment improves forecast accuracy.

Offline reproduction from the saved diagnostic (no network or mutable cache):

```sh
python tools/reproduce_matchups.py data/verification/2026/w06/dcf4bce0b2d3a162bdea39217eb6ae0ee2545e3895cce129338afc715a5e8e2a.json.gz
python tools/reproduce_matchups.py data/verification/2026/w06/dcf4bce0b2d3a162bdea39217eb6ae0ee2545e3895cce129338afc715a5e8e2a.json.gz --published-population
```

The second command intentionally exits 1 with the original 805 discrepancies;
it is a negative control, not the release verifier. The full-population command
exits 0 while retaining the explicit historical-input provenance limitation.
