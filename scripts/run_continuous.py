#!/usr/bin/env python3
"""3시간 연속 크롤링 + 파인튜닝 스크립트.

수집 → 정제 → 데이터셋 빌드 → QLoRA 학습을 반복 실행한다.
사이클 사이에 5분 휴식으로 Instagram 차단을 방지한다.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.data_pipeline.cycle_pipeline import run_cycle, load_cycle_state

logger = get_logger()

TOTAL_HOURS = 3
REST_MINUTES = 5  # 사이클 간 휴식 (Instagram 차단 방지)
CRAWL_COUNT = 20  # 소스당 수집 게시글 수


def main():
    start = datetime.now()
    deadline = start + timedelta(hours=TOTAL_HOURS)
    results: list[dict] = []

    print("=" * 60)
    print(f"  연속 학습 시작: {start.strftime('%H:%M:%S')}")
    print(f"  종료 예정:     {deadline.strftime('%H:%M:%S')} ({TOTAL_HOURS}시간)")
    print(f"  사이클 간 휴식: {REST_MINUTES}분")
    print("=" * 60)

    cycle_num = 0

    while datetime.now() < deadline:
        cycle_num += 1
        remaining = deadline - datetime.now()
        remaining_min = remaining.total_seconds() / 60

        print(f"\n{'━' * 60}")
        print(f"  사이클 #{cycle_num} 시작 | 남은 시간: {remaining_min:.0f}분")
        print(f"{'━' * 60}")

        # 남은 시간이 10분 미만이면 학습만 하고 종료
        skip_crawl = remaining_min < 15

        try:
            result = run_cycle(
                skip_crawl=skip_crawl,
                skip_train=False,
                crawl_count=CRAWL_COUNT,
                headless=False,
            )
            results.append(result)

            # 진행 상황 출력
            samples = result.get("training_samples", 0)
            training_status = result.get("training", "unknown")
            print(f"\n  ✓ 사이클 #{cycle_num} 완료")
            print(f"    학습 샘플: {samples}개")
            print(f"    학습 상태: {training_status}")

            if skip_crawl:
                print("    (시간 부족으로 크롤링 생략, 기존 데이터로 학습)")

        except KeyboardInterrupt:
            print("\n\n  사용자에 의해 중단됨")
            break
        except Exception as exc:
            print(f"\n  ✗ 사이클 #{cycle_num} 실패: {exc}")
            traceback.print_exc()
            results.append({"cycle": cycle_num, "error": str(exc)})

        # GPU 메모리 강제 해제 (사이클 간 OOM 방지)
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()
                vram_free = torch.cuda.mem_get_info()[0] / 1024**3
                print(f"    GPU 메모리 정리 완료 (여유: {vram_free:.1f}GB)")
        except Exception:
            pass

        # 시간 남았으면 휴식
        if datetime.now() < deadline:
            rest_until = datetime.now() + timedelta(minutes=REST_MINUTES)
            if rest_until > deadline:
                break
            print(f"\n  💤 {REST_MINUTES}분 휴식 (Instagram 차단 방지)...")
            time.sleep(REST_MINUTES * 60)

    # 최종 요약
    end = datetime.now()
    elapsed = end - start

    print("\n" + "=" * 60)
    print("  연속 학습 완료")
    print("=" * 60)
    print(f"  시작: {start.strftime('%H:%M:%S')}")
    print(f"  종료: {end.strftime('%H:%M:%S')}")
    print(f"  소요: {elapsed.total_seconds() / 60:.0f}분")
    print(f"  완료 사이클: {len(results)}회")

    # 사이클별 결과
    for r in results:
        c = r.get("cycle", "?")
        s = r.get("training_samples", 0)
        t = r.get("training", "?")
        err = r.get("error", "")
        if err:
            print(f"    #{c}: 실패 - {err}")
        else:
            print(f"    #{c}: {s}개 샘플, 학습={t}")

    # 최종 상태
    state = load_cycle_state()
    print(f"\n  총 누적 샘플: {state.get('total_samples', 0)}개")
    print(f"  발견된 해시태그: {len(state.get('discovered_hashtags', []))}개")
    print(f"  발견된 검색어: {len(state.get('discovered_searches', []))}개")

    # 결과 저장
    log_path = PROJECT_ROOT / "data" / "continuous_training_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        json.dumps({
            "started_at": start.isoformat(),
            "finished_at": end.isoformat(),
            "elapsed_minutes": elapsed.total_seconds() / 60,
            "cycles": results,
        }, ensure_ascii=False, indent=2, default=str),
        "utf-8",
    )
    print(f"\n  로그 저장: {log_path}")


if __name__ == "__main__":
    main()
