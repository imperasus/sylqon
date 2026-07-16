"""Headless CLI: `python -m app.cli ingest "Name#TAG" [--count 20]` and
`python -m app.cli advise MATCH_ID PUUID [--lang hu]`."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict

from app import db
from app.crawler import AccountNotFound, IngestService
from app.ratelimit import build_rate_limiter
from app.riot_client import RiotClient


def _cmd_ingest(args: argparse.Namespace) -> int:
    game_name, _, tag_line = args.riot_id.partition("#")
    if not game_name or not tag_line:
        print("Riot ID must be in 'Name#TAG' form", file=sys.stderr)
        return 2
    engine = db.init_db()
    service = IngestService(
        RiotClient(rate_limiter=build_rate_limiter()), db.get_session_factory(engine)
    )
    try:
        result = service.ingest(game_name, tag_line, args.count)
    except AccountNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), indent=2))
    return 0


def _cmd_advise(args: argparse.Namespace) -> int:
    from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice

    db.init_db()
    with db.open_session() as session:
        try:
            result = get_or_generate_advice(session, args.match_id, args.puuid, lang=args.lang)
        except AdviceNotPossible as exc:
            print(str(exc), file=sys.stderr)
            return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _cmd_benchmarks(args: argparse.Namespace) -> int:
    from app import aggregate

    db.init_db()
    with db.open_session() as session:
        computed = aggregate.refresh_benchmarks(session)
    print(json.dumps(computed, indent=2))
    return 0


def _cmd_crawl(args: argparse.Namespace) -> int:
    from app import seedcrawl

    engine = db.init_db()
    service = IngestService(
        RiotClient(rate_limiter=build_rate_limiter()), db.get_session_factory(engine)
    )
    total = 0
    for i in range(args.cycles):
        inserted = seedcrawl.crawl_cycle(service, db.get_session_factory(engine))
        total += inserted
        print(f"cycle {i + 1}: +{inserted} match(es)")
    print(f"total new matches: {total}")
    return 0


def _cmd_metasync(args: argparse.Namespace) -> int:
    """Prewarm the meta-build payload cache for every eligible champ+role."""
    from app import metasync

    db.init_db()
    with db.open_session() as session:
        bundle = metasync.build_sync_bundle(session, min_games=args.min_games)
    with_payload = sum(1 for e in bundle["entries"] if e["payload"])
    print(f"entries: {len(bundle['entries'])} | with build payload: {with_payload} "
          f"| patch: {bundle['patch']}")
    return 0


def _cmd_pool(args: argparse.Namespace) -> int:
    from app import config, pool

    game_name, _, tag_line = args.riot_id.partition("#")
    engine = db.init_db()
    with db.open_session() as session:
        if game_name and tag_line:
            service = IngestService(
                RiotClient(rate_limiter=build_rate_limiter()), db.get_session_factory(engine)
            )
            try:
                result = service.ingest(game_name, tag_line)
            except AccountNotFound as exc:
                print(str(exc), file=sys.stderr)
                return 1
            puuid = result.puuid
        else:
            puuid = config._env("RIOT_SELF_PUUID", "")
        report = pool.analyze_pool(session, puuid)
    if report is None:
        print("no stored matches for this player yet", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def _cmd_ranks(args: argparse.Namespace) -> int:
    from app import seedcrawl

    engine = db.init_db()
    service = IngestService(
        RiotClient(rate_limiter=build_rate_limiter()), db.get_session_factory(engine)
    )
    done = seedcrawl.backfill_ranks(service, db.get_session_factory(engine), limit=args.limit)
    print(f"fetched {done} rank(s)")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from app import config, report
    from app.notifier import DiscordWebhookNotifier

    puuid = args.puuid or config._env("RIOT_SELF_PUUID", "") or (
        config.WATCH_PUUIDS[0] if config.WATCH_PUUIDS else ""
    )
    if not puuid:
        print("no puuid given and none configured", file=sys.stderr)
        return 2
    db.init_db()
    with db.open_session() as session:
        data = report.build_report(session, puuid, days=args.days)
    if data is None:
        print(f"no stored matches in the last {args.days} days", file=sys.stderr)
        return 1
    print(report.render_text(data, args.lang))
    if args.send:
        notifier = DiscordWebhookNotifier()
        if not notifier.enabled:
            print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
            return 2
        ok = notifier.send_payload(report.build_report_payload(data, args.lang))
        print("delivered" if ok else "delivery FAILED")
        return 0 if ok else 1
    return 0


def _cmd_notify(args: argparse.Namespace) -> int:
    from app import store
    from app.advice.pipeline import AdviceNotPossible, get_or_generate_advice
    from app.notifier import DiscordWebhookNotifier

    notifier = DiscordWebhookNotifier()
    if not notifier.enabled:
        print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 2
    db.init_db()
    with db.open_session() as session:
        try:
            advice = get_or_generate_advice(session, args.match_id, args.puuid, lang=args.lang)
        except AdviceNotPossible as exc:
            print(str(exc), file=sys.stderr)
            return 1
        participant = store.get_participant(session, args.match_id, args.puuid)
        ok = notifier.send(advice, participant, lang=args.lang)
    print("delivered" if ok else "delivery FAILED")
    return 0 if ok else 1


def _cmd_watch(args: argparse.Namespace) -> int:
    from app.notifier import DiscordWebhookNotifier
    from app.watcher import MatchWatcher

    notifier = DiscordWebhookNotifier()
    if not notifier.enabled:
        print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 2
    engine = db.init_db()
    service = IngestService(
        RiotClient(rate_limiter=build_rate_limiter()), db.get_session_factory(engine)
    )
    watcher = MatchWatcher(service, db.get_session_factory(engine), notifier)
    if args.once:
        delivered = watcher.run_once()
        print(f"delivered {delivered} advice message(s)")
        return 0
    print("watching… (Ctrl+C to stop)")
    try:
        watcher._loop()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="ingest a summoner's recent matches")
    p_ingest.add_argument("riot_id", help='Riot ID, e.g. "Name#TAG"')
    p_ingest.add_argument("--count", type=int, default=None)
    p_ingest.set_defaults(func=_cmd_ingest)

    p_advise = sub.add_parser("advise", help="generate post-game advice for a stored match")
    p_advise.add_argument("match_id")
    p_advise.add_argument("puuid")
    p_advise.add_argument("--lang", default="hu", choices=["hu", "en"])
    p_advise.set_defaults(func=_cmd_advise)

    p_notify = sub.add_parser("notify", help="send one stored match's advice to Discord")
    p_notify.add_argument("match_id")
    p_notify.add_argument("puuid")
    p_notify.add_argument("--lang", default="hu", choices=["hu", "en"])
    p_notify.set_defaults(func=_cmd_notify)

    p_bench = sub.add_parser("benchmarks", help="recompute own-data role benchmarks")
    p_bench.set_defaults(func=_cmd_benchmarks)

    p_crawl = sub.add_parser("crawl", help="run co-player seed-crawl cycles")
    p_crawl.add_argument("--cycles", type=int, default=1)
    p_crawl.set_defaults(func=_cmd_crawl)

    p_msync = sub.add_parser("metasync", help="prewarm the bulk meta-sync bundle")
    p_msync.add_argument("--min-games", type=int, default=8)
    p_msync.set_defaults(func=_cmd_metasync)

    p_pool = sub.add_parser("pool", help="champion-pool coverage report")
    p_pool.add_argument("riot_id", nargs="?", default="", help='"Name#TAG" (omit → RIOT_SELF_PUUID)')
    p_pool.set_defaults(func=_cmd_pool)

    p_ranks = sub.add_parser("ranks", help="backfill solo-queue ranks for stored players")
    p_ranks.add_argument("--limit", type=int, default=None)
    p_ranks.set_defaults(func=_cmd_ranks)

    p_report = sub.add_parser("report", help="weekly trend report for a tracked account")
    p_report.add_argument("--puuid", default=None)
    p_report.add_argument("--days", type=int, default=7)
    p_report.add_argument("--lang", default="hu", choices=["hu", "en"])
    p_report.add_argument("--send", action="store_true", help="also post to the Discord webhook")
    p_report.set_defaults(func=_cmd_report)

    p_watch = sub.add_parser("watch", help="poll tracked accounts and deliver post-game advice")
    p_watch.add_argument("--once", action="store_true", help="run a single poll cycle and exit")
    p_watch.set_defaults(func=_cmd_watch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
