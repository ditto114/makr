"""테스트 시 성능 병목을 손쉽게 찾기 위한 경량 프로파일링 도구."""

from __future__ import annotations

import argparse
import cProfile
import io
import runpy
import sys
import time
from pathlib import Path
from typing import Iterable

import pstats


def _normalize_args(raw_args: Iterable[str]) -> list[str]:
    args = list(raw_args)
    if args and args[0] == "--":
        return args[1:]
    return args


def _format_slow_functions(stats: pstats.Stats, threshold_ms: float) -> str:
    slow_rows: list[tuple[float, float, int, str]] = []
    for (filename, lineno, func_name), (cc, nc, tt, ct, callers) in stats.stats.items():
        cum_ms = ct * 1000
        if cum_ms < threshold_ms:
            continue
        slow_rows.append((cum_ms, tt * 1000, nc, f"{func_name} ({Path(filename).name}:{lineno})"))

    if not slow_rows:
        return "임계치 초과 함수가 없습니다."

    slow_rows.sort(key=lambda row: row[0], reverse=True)
    lines = ["임계치 초과 함수 요약 (cumulative ms 기준):"]
    lines.append("cumulative(ms) | total(ms) | calls | 위치")
    lines.append("-" * 70)
    for cum_ms, total_ms, calls, location in slow_rows:
        lines.append(f"{cum_ms:12.2f} | {total_ms:9.2f} | {calls:5d} | {location}")
    return "\n".join(lines)


def _build_report(
    stats: pstats.Stats,
    *,
    limit: int,
    threshold_ms: float,
    sort: str,
    runtime_ms: float,
    target_desc: str,
) -> str:
    stats_stream = io.StringIO()
    original_stream = getattr(stats, "stream", None)
    try:
        stats.stream = stats_stream
        stats.sort_stats(sort).print_stats(limit)
    finally:
        stats.stream = original_stream

    report_lines = [
        "# makr 성능 프로파일링 결과",
        f"- 대상: {target_desc}",
        f"- 총 실행 시간: {runtime_ms:.2f}ms",
        f"- 정렬 기준: {sort}",
        f"- 상위 {limit}개 항목:",
        "",
        stats_stream.getvalue().strip(),
        "",
        "## 임계치 초과 함수",
        _format_slow_functions(stats, threshold_ms),
    ]
    return "\n".join(report_lines)


def profile_target(
    *,
    module: str | None,
    script: str | None,
    target_args: Iterable[str],
    limit: int = 20,
    sort: str = "cumulative",
    threshold_ms: float = 10.0,
    output: Path = Path("perf_report.txt"),
    stats_file: Path | None = None,
) -> str:
    """지정한 모듈 또는 스크립트를 실행하며 프로파일링 결과를 생성한다."""

    if (module is None) == (script is None):
        raise ValueError("module 또는 script 중 하나만 지정해야 합니다.")

    args = _normalize_args(target_args)
    profiler = cProfile.Profile()
    start = time.perf_counter()
    original_argv = sys.argv
    sys.argv = [module or script or ""] + args
    try:
        if module:
            profiler.runcall(lambda: runpy.run_module(module, run_name="__main__", alter_sys=True))
            target_desc = f"모듈 {module} (args: {args})"
        else:
            profiler.runcall(lambda: runpy.run_path(script, run_name="__main__"))
            target_desc = f"스크립트 {script} (args: {args})"
    finally:
        runtime_ms = (time.perf_counter() - start) * 1000
        sys.argv = original_argv

    stats = pstats.Stats(profiler)
    stats.strip_dirs()

    report_text = _build_report(
        stats,
        limit=limit,
        threshold_ms=threshold_ms,
        sort=sort,
        runtime_ms=runtime_ms,
        target_desc=target_desc,
    )

    output_path = output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_text, encoding="utf-8")

    if stats_file is not None:
        stats_file_path = stats_file.resolve()
        stats_file_path.parent.mkdir(parents=True, exist_ok=True)
        stats.dump_stats(stats_file_path)

    return report_text


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="프로그램 테스트 시 성능 병목을 빠르게 확인할 수 있는 프로파일링 도구",
        epilog="추가 인자를 전달하려면 -- 이후에 입력하세요 (예: ... -- --help)",
    )
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--module", "-m", help="프로파일링할 모듈 경로 (예: makr.app)")
    target_group.add_argument("--script", "-s", help="프로파일링할 스크립트 경로")

    parser.add_argument("target_args", nargs=argparse.REMAINDER, help="대상에 전달할 인자 목록")
    parser.add_argument("--limit", type=int, default=20, help="보고서에 표시할 상위 항목 수")
    parser.add_argument(
        "--sort",
        choices=["cumulative", "time", "calls"],
        default="cumulative",
        help="정렬 기준 (cumulative, time, calls)",
    )
    parser.add_argument("--threshold-ms", type=float, default=10.0, help="느린 함수로 표시할 누적 시간 임계값(ms)")
    parser.add_argument("--output", type=Path, default=Path("perf_report.txt"), help="보고서 출력 경로")
    parser.add_argument("--stats-file", type=Path, help="pstats 저장 경로 (.prof)")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = profile_target(
        module=args.module,
        script=args.script,
        target_args=args.target_args,
        limit=args.limit,
        sort=args.sort,
        threshold_ms=args.threshold_ms,
        output=args.output,
        stats_file=args.stats_file,
    )

    print(report)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI 진입점
    raise SystemExit(main())
