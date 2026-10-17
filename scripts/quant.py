"""Dual-mode research CLI. Economic rejection is not a command failure."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_vault import PanelBuilder
from src.data_vault.market_materializer import materialize_price_markets
from src.engine.common import QuantError
from src.engine.funnel import ResearchFunnel
from src.engine.research_handoff import validate_handoff
from src.engine.spec_parser import CandidateSpec, parse_spec
from src.engine.thesis_ingest import convert_thesis
from src.oracle.research_protocols import parse_research_spec

STORE = '/home/quant/dev/quant/ml4t-data/.data/store'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('schema', help='print the executable candidate JSON schema')
    cfd = commands.add_parser('build-cfd', help='compile an explicit calendar-qualified CFD cash-session view')
    cfd.add_argument('--source-root', required=True)
    cfd.add_argument('--source-identity', required=True)
    cfd.add_argument('--symbol', required=True)
    cfd.add_argument('--output', required=True)
    cfd.add_argument('--start', required=True)
    cfd.add_argument('--end', required=True)
    cfd.add_argument('--calendar', required=True)
    cfd.add_argument('--source-bar-seconds', type=int, default=60)
    cfd.add_argument('--bar-seconds', type=int, default=1800)
    cfd.add_argument('--spread-bps', type=float, required=True)
    cfd.add_argument('--spread-assumption', required=True)
    cfd.add_argument('--carry-assumption', required=True)
    discover = commands.add_parser('discover', help='read source names and report exact matched stores')
    discover.add_argument('--store', default=STORE)
    build = commands.add_parser('build', help='compile immutable development-only canonical partitions')
    build.add_argument('--store', default=STORE)
    build.add_argument('--output', required=True)
    build.add_argument('--start', required=True)
    build.add_argument('--end', required=True, help='exclusive UTC endpoint, never after protected start')
    build.add_argument('--symbols', nargs='*')
    build.add_argument('--bar-seconds', type=int, default=3600)
    build.add_argument('--spread-bps', type=float, default=0.)
    build.add_argument('--spread-assumption', required=True)
    build.add_argument('--funding-mark-policy', choices=['observed_only', 'trade_open_proxy'], default='trade_open_proxy')
    build.add_argument('--funding-time-tolerance-ms', type=int, default=1000)
    build.add_argument('--include-protected', action='store_true',
                       help='trusted ingestion only: compile separate protected files, never expose them to Workbench')
    markets = commands.add_parser('materialize-markets',
                                  help='materialize all observed FX/index/metals price-only vaults')
    markets.add_argument('--store', default=STORE)
    markets.add_argument('--output-root', default=str(ROOT / 'data' / 'vault' / 'markets_20261015'))
    markets.add_argument('--groups', nargs='+', default=['forex', 'index', 'metals'],
                          choices=['forex', 'index', 'metals'])
    markets.add_argument('--frequencies', nargs='+', default=['1h', '1d'],
                          choices=['1s', '1m', '1h', '1d'])
    markets.add_argument('--start', default='2000-01-01T00:00:00Z')
    markets.add_argument('--end', default='2026-10-01T00:00:00Z')
    markets.add_argument('--include-protected', action='store_true',
                          help='trusted ingestion only: separate 2026 protected partitions, never Workbench access')
    run = commands.add_parser('run', help='execute frozen Stage 1..4, stopping normally on falsification')
    run.add_argument('spec')
    run.add_argument('--development-only', action='store_true',
                     help='fail closed after development Stage 3; never open or claim protected data')
    run.add_argument('--run-log', default=str(ROOT / 'run_log'))
    run.add_argument('--store', default=STORE)
    run.add_argument('--build-if-missing', action='store_true',
                     help='compile development panel before running; protected data remains separate')
    validate = commands.add_parser('validate', help='parse executable YAML without reading market data')
    validate.add_argument('spec')
    ingest = commands.add_parser('ingest', aliases=['ingest-thesis'],
                                 help='translate a research thesis into validated executable candidate YAML')
    ingest.add_argument('source')
    ingest.add_argument('-o', '--output', required=True)
    handoff = commands.add_parser('validate-handoff', help='validate descriptive research inbox handoffs')
    handoff.add_argument('candidate_dir', nargs='?', default=str(ROOT / 'research_inbox'))
    train_remote = commands.add_parser('train-remote', help='train an ML model artifact remotely on Google Colab GPU')
    train_remote.add_argument('spec', help='template CandidateSpec YAML or thesis specification')
    train_remote.add_argument('--training-script', default=None, help='optional custom Python training script')
    train_remote.add_argument('--gpu', choices=['T4', 'L4', 'A100'], default='T4', help='Colab accelerator')
    train_remote.add_argument('--timeout', type=int, default=3600, help='remote execution timeout in seconds')
    train_remote.add_argument('--run-log', default=str(ROOT / 'run_log'))
    train_remote.add_argument('-o', '--output', required=True, help='destination path for updated CandidateSpec YAML')
    args = parser.parse_args(argv)
    try:
        if args.command == 'schema':
            print(json.dumps(CandidateSpec.model_json_schema(), sort_keys=True))
            return 0
        if args.command in ('ingest', 'ingest-thesis'):
            spec = convert_thesis(args.source, args.output)
            validated = parse_spec(args.output)
            if validated.spec_hash != spec.spec_hash:
                raise QuantError('INVALID_EVIDENCE', 'Candidate changed between ingest and validate')
            print(json.dumps({'status': 'CONVERTED', 'validation': 'VALID_SPEC',
                              'candidate_id': spec.candidate_id, 'spec_hash': spec.spec_hash,
                              'output': str(Path(args.output))}, sort_keys=True))
            return 0
        if args.command == 'validate-handoff':
            target = Path(args.candidate_dir)
            candidates = sorted(target.iterdir()) if target.resolve() == (ROOT / 'research_inbox').resolve() else [target]
            results = [validate_handoff(path) for path in candidates if path.is_dir() and not path.name.startswith('.')]
            if not results:
                raise QuantError('INVALID_HANDOFF', 'No candidate directories found')
            for result in results:
                print(json.dumps(result, sort_keys=True))
            return 0
        if args.command == 'train-remote':
            from src.engine.colab_trainer import ColabTrainer

            trainer = ColabTrainer(args.spec, run_log=args.run_log)
            artifact, updated_spec = trainer.train(
                training_script=args.training_script,
                gpu=args.gpu,
                timeout=args.timeout,
                output_candidate_path=args.output,
            )
            print(json.dumps({
                'status': 'TRAINED_REMOTE',
                'candidate_id': updated_spec.candidate_id,
                'artifact_path': artifact.path,
                'artifact_sha256': artifact.sha256,
                'output': str(Path(args.output).resolve()),
            }, sort_keys=True, indent=2))
            return 0
        if args.command == 'materialize-markets':
            for group in args.groups:
                for granularity in args.frequencies:
                    if (group == 'metals' and granularity == '1d') or (
                            group != 'index' and granularity == '1s'):
                        print(json.dumps({'status': 'NO_SOURCE', 'category': group,
                                          'frequency': granularity,
                                          'reason': 'No matching native source in ml4t-data'}), flush=True)
                        continue
                    target = Path(args.output_root) / f'{group}_{granularity}'
                    manifest = materialize_price_markets(
                        args.store, target, category=group, granularity=granularity,
                        start=args.start, end=args.end,
                        trusted_partitioning=args.include_protected)
                    print(json.dumps({'status': 'COMPILED', 'category': group,
                                      'frequency': granularity, 'output': str(target),
                                      'manifest_hash': manifest['manifest_hash'],
                                      'summary': manifest['quality_summary'],
                                      'excluded': len(manifest['excluded'])}, sort_keys=True), flush=True)
            return 0
        if args.command == 'build-cfd':
            manifest = PanelBuilder(args.source_root, args.output).build_cfd(
                source_root=args.source_root, source_identity=args.source_identity, symbol=args.symbol,
                start=args.start, end=args.end, exchange_calendar=args.calendar,
                source_bar_seconds=args.source_bar_seconds, bar_seconds=args.bar_seconds,
                spread_bps=args.spread_bps, spread_assumption=args.spread_assumption,
                carry_assumption=args.carry_assumption)
            print(json.dumps({'status': 'COMPILED', 'manifest_hash': manifest['manifest_hash'],
                              'entries': len(manifest['entries'])}, sort_keys=True))
            return 0
        if args.command == 'discover':
            report = PanelBuilder(args.store, ROOT / 'data' / 'vault').discovery_report()
            print(json.dumps(report, sort_keys=True))
            return 0
        if args.command == 'build':
            manifest = PanelBuilder(args.store, args.output, funding_mark_policy=args.funding_mark_policy,
                                    funding_time_tolerance_ms=args.funding_time_tolerance_ms).build(
                start=args.start, end=args.end, symbols=args.symbols,
                bar_seconds=args.bar_seconds, spread_bps=args.spread_bps,
                spread_assumption=args.spread_assumption, trusted_partitioning=args.include_protected)
            print(json.dumps({'status': 'COMPILED', 'manifest_hash': manifest['manifest_hash'],
                              'entries': len(manifest['entries']), 'excluded': manifest['excluded']}, sort_keys=True))
            return 0
        spec = parse_research_spec(args.spec)
        is_event = not isinstance(spec, CandidateSpec)
        if args.command == 'validate':
            if is_event:
                print(json.dumps({'status': 'VALID_SPEC', 'candidate_id': spec.strategy_id,
                                  'spec_hash': spec.spec_hash, 'source_spec_status': 'exact',
                                  'protocol': spec.protocol}))
            else:
                print(json.dumps({'status': 'VALID_SPEC', 'candidate_id': spec.candidate_id,
                                  'spec_hash': spec.spec_hash, 'source_spec_status': spec.source_spec_status}))
            return 0
        if is_event and args.build_if_missing:
            raise QuantError('INVALID_SPEC', 'Frozen event authority cannot be rebuilt by --build-if-missing')
        if args.build_if_missing and not (Path(spec.panel_root) / 'manifest.json').exists():
            warmup = timedelta(seconds=spec.bar_seconds * max(spec.universe.lookback_bars,
                                                              spec.universe.minimum_history_bars))
            PanelBuilder(args.store, spec.panel_root, spec.windows.protected.start).build(
                start=spec.windows.train.start - warmup, end=spec.windows.validation.end,
                bar_seconds=spec.bar_seconds, spread_bps=spec.costs.spread_bps,
                spread_assumption='Frozen candidate cost model; not a measured historical spread')
        funnel = ResearchFunnel(run_log=args.run_log, isolate=True)
        # Preserve the historical one-argument runner invocation for existing
        # ATS callers. The holdout-prohibited mode must be explicitly requested.
        report = (funnel.run(spec, development_only=True)
                  if args.development_only else funnel.run(spec))
        print(json.dumps({'status': report['status'], 'candidate_id': report['candidate_id'],
                          'casefile': str(Path(report['output_path']) / 'casefile.json'),
                          'holdout_access': report['holdout_access'], 'reason': report.get('reason'),
                          'stages': {k: v['status'] for k, v in report['stages'].items()}}, sort_keys=True))
        if report['status'].startswith('FALSIFIED_') or report['status'] in ('HOLDOUT_EVALUATED', 'DEVELOPMENT_QUALIFIED'):
            return 0
        if report['status'] == 'PARTIALLY_QUALIFIED' or report['status'].startswith(('INCONCLUSIVE', 'BLOCKED', 'HOLDOUT_')):
            return 3
        return 2
    except QuantError as exc:
        print(json.dumps({'status': exc.status, 'reason': exc.reason}), file=sys.stderr)
        return 3 if exc.status.startswith(('BLOCKED', 'INCONCLUSIVE')) else 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary returns a structured nonzero engineering failure
        print(json.dumps({'status': 'ENGINEERING_ERROR', 'reason': f'{type(exc).__name__}: {exc}'}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
