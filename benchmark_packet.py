"""패킷 캡처 성능 벤치마크 도구.

사용법:
    python benchmark_packet.py [original|optimized|fast]

비교:
    python benchmark_packet.py all
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from typing import Callable


class PacketBenchmark:
    """패킷 캡처 성능 측정."""

    def __init__(self, manager_class, name: str):
        self.manager_class = manager_class
        self.name = name
        self.packet_count = 0
        self.start_time = 0.0
        self.latencies: list[float] = []
        self.last_packet_time = 0.0

    def on_packet(self, text: str) -> None:
        """패킷 수신 콜백."""
        current_time = time.perf_counter()

        if self.packet_count == 0:
            self.start_time = current_time
        else:
            # 패킷 간 지연 시간 측정
            interval = (current_time - self.last_packet_time) * 1000  # ms
            self.latencies.append(interval)

        self.last_packet_time = current_time
        self.packet_count += 1

        # 진행 상황 표시
        if self.packet_count % 10 == 0:
            print(f"\r{self.name}: {self.packet_count}개 패킷 수신...", end="", flush=True)

    def on_error(self, msg: str) -> None:
        """에러 콜백."""
        print(f"\n{self.name} 오류: {msg}")

    def run(self, duration: int = 30, port: int = 32800) -> dict:
        """벤치마크 실행.

        Args:
            duration: 측정 시간 (초)
            port: 캡처할 포트 번호

        Returns:
            성능 측정 결과 딕셔너리
        """
        print(f"\n{'='*60}")
        print(f"{self.name} 벤치마크 시작 (포트 {port}, {duration}초)")
        print(f"{'='*60}")

        manager = self.manager_class(
            on_packet=self.on_packet,
            on_error=self.on_error,
            port=port,
        )

        if not manager.start():
            return {
                "name": self.name,
                "error": "캡처 시작 실패",
            }

        print(f"패킷 캡처 시작... ({duration}초간 대기)")

        try:
            time.sleep(duration)
        except KeyboardInterrupt:
            print("\n\n중단됨")
        finally:
            manager.stop()

        print(f"\n\n{self.name} 결과:")
        return self._calculate_results()

    def _calculate_results(self) -> dict:
        """측정 결과 계산."""
        if self.packet_count == 0:
            result = {
                "name": self.name,
                "packets": 0,
                "error": "패킷을 수신하지 못했습니다",
            }
            print(f"  패킷 수신: 0 (패킷이 감지되지 않았습니다)")
            return result

        elapsed = self.last_packet_time - self.start_time
        throughput = self.packet_count / elapsed if elapsed > 0 else 0

        result = {
            "name": self.name,
            "packets": self.packet_count,
            "elapsed": elapsed,
            "throughput": throughput,
        }

        print(f"  패킷 수신: {self.packet_count}개")
        print(f"  소요 시간: {elapsed:.2f}초")
        print(f"  처리량: {throughput:.1f} packets/sec")

        if len(self.latencies) > 0:
            avg_latency = statistics.mean(self.latencies)
            min_latency = min(self.latencies)
            max_latency = max(self.latencies)
            p50 = statistics.median(self.latencies)
            p95 = (
                sorted(self.latencies)[int(len(self.latencies) * 0.95)]
                if len(self.latencies) > 20
                else max_latency
            )

            result.update(
                {
                    "avg_latency": avg_latency,
                    "min_latency": min_latency,
                    "max_latency": max_latency,
                    "p50_latency": p50,
                    "p95_latency": p95,
                }
            )

            print(f"  평균 지연: {avg_latency:.2f}ms")
            print(f"  최소 지연: {min_latency:.2f}ms")
            print(f"  최대 지연: {max_latency:.2f}ms")
            print(f"  P50 지연: {p50:.2f}ms")
            print(f"  P95 지연: {p95:.2f}ms")

        return result


def compare_all(duration: int = 30, port: int = 32800) -> None:
    """모든 구현 비교."""
    results = []

    # 1. 원본
    try:
        from makr.packet import PacketCaptureManager as OriginalManager

        bench = PacketBenchmark(OriginalManager, "원본 (packet.py)")
        results.append(bench.run(duration, port))
    except ImportError as e:
        print(f"원본 로드 실패: {e}")

    # 2. 최적화
    try:
        from makr.packet_optimized import (
            OptimizedPacketCaptureManager as OptimizedManager,
        )

        bench = PacketBenchmark(OptimizedManager, "최적화 (packet_optimized.py)")
        results.append(bench.run(duration, port))
    except ImportError as e:
        print(f"최적화 버전 로드 실패: {e}")

    # 3. 고속
    try:
        from makr.packet_fast import FastPacketCaptureManager as FastManager

        bench = PacketBenchmark(FastManager, "고속 (packet_fast.py)")
        results.append(bench.run(duration, port))
    except ImportError as e:
        print(f"고속 버전 로드 실패 (pypcap 미설치?): {e}")

    # 결과 요약
    print(f"\n\n{'='*60}")
    print("성능 비교 요약")
    print(f"{'='*60}")

    baseline = None
    for r in results:
        if "error" in r:
            print(f"{r['name']}: {r['error']}")
            continue

        if baseline is None:
            baseline = r

        speedup = r.get("throughput", 0) / baseline.get("throughput", 1)
        latency_improvement = (
            baseline.get("avg_latency", 0) / r.get("avg_latency", 1)
            if r.get("avg_latency", 0) > 0
            else 1
        )

        print(f"\n{r['name']}:")
        print(f"  처리량: {r.get('throughput', 0):.1f} pps (x{speedup:.2f})")
        print(
            f"  평균 지연: {r.get('avg_latency', 0):.2f}ms (x{latency_improvement:.2f} 향상)"
        )


def main() -> None:
    """메인 함수."""
    parser = argparse.ArgumentParser(description="패킷 캡처 성능 벤치마크")
    parser.add_argument(
        "mode",
        nargs="?",
        default="optimized",
        choices=["original", "optimized", "fast", "all"],
        help="벤치마크할 구현 (기본: optimized)",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        default=30,
        help="측정 시간 (초, 기본: 30)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=32800,
        help="캡처할 포트 (기본: 32800)",
    )

    args = parser.parse_args()

    if args.mode == "all":
        compare_all(args.duration, args.port)
        return

    # 단일 구현 테스트
    if args.mode == "original":
        from makr.packet import PacketCaptureManager
    elif args.mode == "optimized":
        from makr.packet_optimized import (
            OptimizedPacketCaptureManager as PacketCaptureManager,
        )
    elif args.mode == "fast":
        from makr.packet_fast import FastPacketCaptureManager as PacketCaptureManager

    bench = PacketBenchmark(PacketCaptureManager, f"{args.mode} 버전")
    bench.run(args.duration, args.port)


if __name__ == "__main__":
    main()
