"""Development-only Phase 3 refit oracle. No execution or holdout authority.

Frozen callback must refit every trial, including preprocessing and selection,
for each target permutation. Caller attests code/config/source provenance; a
hash here checks bytes and identity strings, not historical preregistration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import combinations
from math import comb, isfinite

import numpy as np
from ml4t.diagnostic.evaluation.stats import (
    compute_pbo,
    compute_return_statistics,
    deflated_sharpe_ratio,
)
from ml4t.diagnostic.splitters import CombinatorialCV


class OracleContractError(ValueError):
    """Incomplete evidence: result BLOCKED, never PASS or FAIL."""


@dataclass(frozen=True)
class FrozenIdentity:
    code_sha256: str
    config_sha256: str
    data_sha256: str
    environment_sha256: str
    ledger_sha256: str


@dataclass(frozen=True)
class Split:
    test_groups: tuple[int, ...]
    train: tuple[int, ...]
    test: tuple[int, ...]


@dataclass(frozen=True)
class RefitResult:
    """Callback output aligned to every frozen trial, split and daily date."""

    statistics: np.ndarray  # (trials,), larger is better
    returns: np.ndarray  # (daily observations, trials), NET portfolio returns
    train_scores: np.ndarray  # (splits, trials)
    test_scores: np.ndarray  # (splits, trials)


@dataclass(frozen=True)
class OracleDecision:
    status: str
    selected_p: float
    selected_effect: float
    dsr_probability: float
    n_trials_raw: int
    n_trials_effective: float
    pbo: float
    split_count: int
    path_count: int
    path_segments: tuple[tuple[tuple[int, int], ...], ...]
    holdout_access: bool = False
    diagnostic_thresholds_passed: bool = False
    qualification_blockers: tuple[str, ...] = (
        "GLOBAL_LEDGER_COVERAGE_NOT_DERIVED",
        "OOS_PATH_RETURN_DISTRIBUTION_NOT_ASSEMBLED",
        "JOINT_IC_AND_NET_SHARPE_ENDPOINTS_NOT_BOUND",
        "CHRONOLOGICAL_VALIDATION_NOT_ATTACHED",
    )


def _digest_array(values: np.ndarray) -> bytes:
    arr = np.ascontiguousarray(np.asarray(values, dtype="<f8"))
    return repr(arr.shape).encode() + arr.tobytes()


def _digest_hex(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def reconstruct_paths(n_groups: int, n_test_groups: int) -> tuple[tuple[tuple[int, int], ...], ...]:
    """Partition each (split index, OOS group) segment into phi distinct paths.

    This is group-specific assembly, not whole-fold tiling. Each path uses each
    group once. A split may supply segments to different paths.
    """
    if not 2 <= n_test_groups < n_groups <= 10:
        raise OracleContractError("unsupported CPCV group geometry")
    combos = tuple(combinations(range(n_groups), n_test_groups))
    phi = comb(n_groups - 1, n_test_groups - 1)
    paths: list[list[tuple[int, int]]] = [[] for _ in range(phi)]
    for group in range(n_groups):
        occurrences = [i for i, combo in enumerate(combos) if group in combo]
        if len(occurrences) != phi:
            raise OracleContractError("invalid CPCV group incidence")
        for path, split_index in zip(paths, occurrences, strict=True):
            path.append((split_index, group))
    segments = [segment for path in paths for segment in path]
    expected = [(i, g) for i, combo in enumerate(combos) for g in combo]
    if sorted(segments) != sorted(expected) or len({tuple(p) for p in paths}) != phi:
        raise OracleContractError("CPCV segments missing, duplicated or paths repeated")
    return tuple(tuple(path) for path in paths)


def checked_splits(
    starts: tuple[datetime, ...], ends: tuple[datetime, ...],
    *, n_groups: int, n_test_groups: int, embargo: timedelta,
) -> tuple[Split, ...]:
    """Use native group splits; check exact inclusive interval purge and embargo."""
    n = len(starts)
    if n < n_groups or len(ends) != n or embargo <= timedelta(0):
        raise OracleContractError("insufficient observations or invalid embargo")
    if any(s.tzinfo is None or e.tzinfo is None or s.utcoffset() is None
           or e.utcoffset() is None or s > e for s, e in zip(starts, ends, strict=True)):
        raise OracleContractError("invalid aware label intervals")
    start_utc = tuple(s.astimezone(UTC) for s in starts)
    end_utc = tuple(e.astimezone(UTC) for e in ends)
    if tuple(sorted(set(start_utc))) != start_utc:
        raise OracleContractError("decision times must be unique and chronological")
    groups = tuple(tuple(int(i) for i in part) for part in np.array_split(np.arange(n), n_groups))
    combos = tuple(combinations(range(n_groups), n_test_groups))
    native = CombinatorialCV(n_groups=n_groups, n_test_groups=n_test_groups,
                             label_horizon=0, embargo_size=0, isolate_groups=False)
    raw_splits = list(native.split(np.zeros((n, 1), dtype=float)))
    if len(raw_splits) != len(combos):
        raise OracleContractError("native CPCV split coverage incomplete")
    output = []
    for combo, (raw_train, test) in zip(combos, raw_splits, strict=True):
        expected_test = {i for group in combo for i in groups[group]}
        if set(test) != expected_test or set(raw_train) != set(range(n)) - expected_test:
            raise OracleContractError("native CPCV test group mismatch")
        # Every candidate label interval is checked against all test intervals.
        # Embargo after the TEST LABEL END prevents adjacent fitted labels.
        safe = tuple(int(i) for i in raw_train if all(
            not (start_utc[i] <= end_utc[j] and start_utc[j] <= end_utc[i])
            and not (end_utc[j] < start_utc[i] <= end_utc[j] + embargo)
            for j in test
        ))
        if not safe or set(safe) & expected_test:
            raise OracleContractError("purge/embargo exhausted training fold")
        if any(start_utc[i] <= end_utc[j] and start_utc[j] <= end_utc[i]
               or end_utc[j] < start_utc[i] <= end_utc[j] + embargo
               for i in safe for j in test):
            raise OracleContractError("train/test label overlap or embargo violation")
        output.append(Split(combo, safe, tuple(int(i) for i in test)))
    return tuple(output)


def _validate_refit(result: RefitResult, *, n_trials: int, n_splits: int, n_days: int) -> tuple[np.ndarray, ...]:
    arrays = tuple(np.asarray(a, dtype=float) for a in (
        result.statistics, result.returns, result.train_scores, result.test_scores,
    ))
    if tuple(a.shape for a in arrays) != ((n_trials,), (n_days, n_trials),
                                           (n_splits, n_trials), (n_splits, n_trials)):
        raise OracleContractError("refit output incomplete or misaligned")
    if any(not np.isfinite(a).all() for a in arrays):
        raise OracleContractError("refit output nonfinite")
    return arrays


def evaluate_phase3(
    *, trial_ids: tuple[str, ...], selected_trial_id: str,
    targets: np.ndarray, starts: tuple[datetime, ...], ends: tuple[datetime, ...],
    daily_dates: tuple[datetime, ...], holdout_start: datetime,
    identity: FrozenIdentity, observed_data_sha256: str,
    ledger_complete: bool, refit: Callable[[np.ndarray, tuple[Split, ...]], RefitResult],
    blocks: tuple[tuple[int, ...], ...], n_groups: int, n_test_groups: int,
    embargo: timedelta, seed: int, permutations: int = 500, alpha: float = 0.01,
    dsr_floor: float = 0.95, pbo_ceiling: float = 0.05,
    min_effect: float = 0.0, periods_per_year: int = 252,
) -> OracleDecision:
    """Refit on target-block permutations; compare selected to null maxima.

    Callback must refit training, preprocessing, model/parameter selection, and
    OOS evaluation on EACH target vector. No scoring fixed OOF predictions.
    Identity strings name caller-supplied artifacts, not independently verified
    ledger coverage. This bounded implementation returns INCONCLUSIVE even when
    its diagnostic thresholds pass: it cannot grant research qualification,
    protected-holdout access, or deployment authority. Path segments describe
    assembly; they are not actual stitched OOS return paths. The callback has
    one arbitrary endpoint, not the requested joint IC/net-Sharpe test.
    """
    if (not ledger_complete or len(trial_ids) < 2 or len(set(trial_ids)) != len(trial_ids)
        or selected_trial_id not in trial_ids or not all(trial_ids)):
        raise OracleContractError("complete global trial cohort required")
    if not all(_digest_hex(v) for v in (
        identity.code_sha256, identity.config_sha256, identity.data_sha256,
        identity.environment_sha256, identity.ledger_sha256,
    )) or identity.data_sha256 != observed_data_sha256:
        raise OracleContractError("frozen code/config/data/environment/ledger identity required")
    y = np.asarray(targets, dtype=float)
    if y.ndim != 1 or len(y) != len(starts) or not np.isfinite(y).all():
        raise OracleContractError("finite aligned development targets required")
    if holdout_start.tzinfo is None or holdout_start.utcoffset() is None:
        raise OracleContractError("aware holdout boundary required")
    if any(e >= holdout_start for e in ends) or any(
        d.tzinfo is None or d.utcoffset() is None or d >= holdout_start for d in daily_dates
    ):
        raise OracleContractError("protected holdout observation requested")
    if len(daily_dates) < 3 or tuple(sorted(set(daily_dates))) != daily_dates:
        raise OracleContractError("daily return clock must be ordered and complete")
    digest = sha256(_digest_array(y) + repr((starts, ends, daily_dates, trial_ids)).encode()).hexdigest()
    if digest != identity.data_sha256:
        raise OracleContractError("development data identity mismatch")
    if (not isinstance(seed, int) or permutations < 1 or not isinstance(permutations, int)
        or not 0 < alpha < 1 or not 0 < dsr_floor < 1
        or not 0 <= pbo_ceiling <= 1 or not isfinite(min_effect)
        or periods_per_year <= 0):
        raise OracleContractError("invalid frozen thresholds")
    if (len(blocks) < 2 or len({len(block) for block in blocks}) != 1
        or any(tuple(range(block[0], block[0] + len(block))) != block for block in blocks if block)
        or any(not block for block in blocks)
        or sorted(i for block in blocks for i in block) != list(range(len(y)))):
        raise OracleContractError("blocks must partition equal-length ordered target spans")
    paths = reconstruct_paths(n_groups, n_test_groups)
    splits = checked_splits(starts, ends, n_groups=n_groups, n_test_groups=n_test_groups,
                            embargo=embargo)

    def run(target: np.ndarray) -> tuple[np.ndarray, ...]:
        return _validate_refit(refit(target.copy(), splits), n_trials=len(trial_ids),
                               n_splits=len(splits), n_days=len(daily_dates))

    observed_stats, returns, train, test = run(y)
    # Native rank-based PBO has no neutral tie policy. Reject uninformative
    # candidate ordering rather than make qualification depend on column order.
    for scores in (train, test):
        ordered = np.sort(scores, axis=1)
        scale = np.maximum(1.0, np.max(np.abs(ordered), axis=1, keepdims=True))
        if np.any(np.diff(ordered, axis=1) <= 1e-12 * scale):
            raise OracleContractError("PBO candidate score ties require an audited tie policy")
    selected = trial_ids.index(selected_trial_id)
    effect = float(observed_stats[selected])
    exceed = 0
    rng = np.random.default_rng(seed)
    for _ in range(permutations):
        shuffled = np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
        null_stats, _, _, _ = run(y[shuffled])
        exceed += int(np.max(null_stats) >= effect)
    p_value = (exceed + 1) / (permutations + 1)
    try:
        pbo = float(compute_pbo(train, test).pbo)
        dsr = deflated_sharpe_ratio(returns, frequency="daily", periods_per_year=periods_per_year,
                                    correlation_method="effective_rank", min_k_eff=2.0)
        leader = int(np.argmax([compute_return_statistics(returns[:, i])[0]
                                for i in range(len(trial_ids))]))
    except (ValueError, FloatingPointError, ZeroDivisionError) as exc:
        raise OracleContractError("native DSR/PBO could not evaluate cohort") from exc
    if (leader != selected or dsr.n_trials_raw != len(trial_ids)
        or dsr.n_trials_effective is None or not isfinite(dsr.n_trials_effective)
        or not isfinite(dsr.probability) or not isfinite(pbo)
        or not dsr.has_adequate_sample):
        raise OracleContractError("native selected DSR/K_eff/PBO evidence insufficient")
    passed = (effect >= min_effect and p_value < alpha and dsr.probability >= dsr_floor
              and pbo <= pbo_ceiling)
    return OracleDecision("INCONCLUSIVE", p_value, effect,
                          float(dsr.probability), len(trial_ids), float(dsr.n_trials_effective),
                          pbo, len(splits), len(paths), paths,
                          diagnostic_thresholds_passed=bool(passed))
