#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_optimize_backtest_scout_e2e.py
-----------------------------------

`backtest_scout_e2e.py` 파라미터를 Grid 방식으로 병렬 실행해
가장 좋은 성과(고수익/저MDD)를 내는 조합을 탐색하는 유틸리티.

- ProcessPoolExecutor를 사용한 병렬 실행
- 이미 테스트한 조합 스킵 (Resume 기능)
- 점수 기반 랭킹 및 결과 저장
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKTEST_SCRIPT = os.path.join(PROJECT_ROOT, "utilities", "backtest_scout_e2e.py")
DEFAULT_LOG_DIR = os.path.join(PROJECT_ROOT, "logs")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("scout_e2e_optimizer")


# ---------------------------------------------------------------------------
# 튜닝 대상 파라미터 (Scout E2E 백테스트에 영향이 큰 항목들)
# ---------------------------------------------------------------------------

PARAMETER_GRID = {
    # === 고정 (점수 기준) ===
    "scout_min_score": [70],                      # 점수 유지
    
    # === 테스트: 거래 제한 ===
    "daily_buy_limit": [3, 5, 8, 99],             # 99 = 무제한
    "max_portfolio_size": [10, 15, 20, 30],       # 포트폴리오 크기
    
    # === 나머지 고정 ===
    "scout_top_n": [20],
    "max_stock_pct": [0.12],
    "target_profit_pct": [0.10],
    "stop_loss_pct": [0.07],
    "buy_signal_threshold": [70],
}

# 파라미터별 설명 (로그용)
PARAM_DESCRIPTIONS = {
    "scout_min_score": "Scout 통과 최소 점수",
    "scout_top_n": "Hot Watchlist 크기",
    "min_llm_score": "Buy Executor 최소 LLM 점수",
    "daily_buy_limit": "일일 매수 한도",
    "max_portfolio_size": "최대 포트폴리오 크기",
    "max_stock_pct": "종목당 최대 비중",
    "target_profit_pct": "목표 수익률",
    "stop_loss_pct": "손절 비율",
    "buy_signal_threshold": "매수 신호 트리거 점수",
}


# ---------------------------------------------------------------------------
# 결과 파싱 & 점수화
# ---------------------------------------------------------------------------

def parse_backtest_output(output: str) -> Dict[str, Optional[float]]:
    """backtest_scout_e2e.py stdout에서 지표를 추출."""
    result = {
        "success": False,
        "total_return_pct": None,
        "mdd_pct": None,
        "final_equity": None,
        "total_trades": None,
    }

    def _extract(pattern: str) -> Optional[float]:
        m = re.search(pattern, output)
        return float(m.group(1)) if m else None

    result["total_return_pct"] = _extract(r"총 수익률:\s*([\-0-9.]+)%")
    result["mdd_pct"] = _extract(r"최대 낙폭:\s*([\-0-9.]+)%")
    result["total_trades"] = _extract(r"총 거래:\s*(\d+)건")
    
    equity_match = re.search(r"최종 자산:\s*([0-9,]+)원", output)
    if equity_match:
        result["final_equity"] = float(equity_match.group(1).replace(",", ""))

    result["success"] = result["total_return_pct"] is not None and result["mdd_pct"] is not None
    return result


def score_result(result: Dict[str, Optional[float]]) -> float:
    """
    수익률을 높이고 MDD는 낮추는 방향으로 점수 계산.
    
    점수 공식:
    - 총 수익률 × 5 (높을수록 좋음)
    - MDD × 4 (낮을수록 좋음, 패널티)
    - MDD > 15% 이면 추가 패널티
    - 거래 횟수가 너무 적으면(<10) 패널티
    """
    if not result["success"]:
        return -1e6

    total_return = result["total_return_pct"] or 0.0
    mdd = result["mdd_pct"] or 0.0
    trades = result["total_trades"] or 0

    # 기본 점수: 수익률 가중 - MDD 패널티
    score = total_return * 5.0 - mdd * 4.0

    # MDD가 15%를 넘어가면 강한 패널티
    if mdd > 15.0:
        score -= (mdd - 15.0) * 10.0

    # 거래가 너무 적으면 통계적으로 신뢰도 낮음
    if trades < 10:
        score -= 50.0
    elif trades < 30:
        score -= 20.0
    
    # 수익률이 음수이면 추가 패널티
    if total_return < 0:
        score -= abs(total_return) * 3.0

    return score


# ---------------------------------------------------------------------------
# 단일 백테스트 실행 (서브 프로세스)
# ---------------------------------------------------------------------------

def run_single_backtest(params: Dict[str, float], args: argparse.Namespace) -> Dict:
    unique_id = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    
    log_dir = os.path.join(PROJECT_ROOT, "logs", "opt_scout_e2e")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, f"backtest_{timestamp}_{unique_id}.log")

    cmd = [
        sys.executable,
        BACKTEST_SCRIPT,
        "--start-date", args.start_date,
        "--end-date", args.end_date,
        "--capital", str(args.capital),
    ]

    # 파라미터 추가
    for key, value in params.items():
        cmd.append(f"--{key.replace('_', '-')}")
        cmd.append(str(value))

    try:
        started = time.time()
        with open(log_file_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.run(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                timeout=args.timeout,
            )
        elapsed = time.time() - started

        if os.path.exists(log_file_path):
            with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                output = f.read()
        else:
            output = ""

        if proc.returncode != 0:
            return {"success": False, "error": f"Process failed (code {proc.returncode})", "params": params}

        metrics = parse_backtest_output(output)
        metrics["params"] = params
        metrics["elapsed"] = elapsed
        metrics["score"] = score_result(metrics)
        return metrics

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout", "params": params}
    except Exception as exc:
        return {"success": False, "error": str(exc), "params": params}


# ---------------------------------------------------------------------------
# Optimizer 본체
# ---------------------------------------------------------------------------

@dataclass
class OptimizationResult:
    params: Dict[str, float]
    total_return_pct: float
    mdd_pct: float
    total_trades: int
    score: float
    elapsed: float = field(default=0.0)


class ScoutE2EOptimizer:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.results: List[OptimizationResult] = []
        self.best_result: Optional[OptimizationResult] = None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.history_file = os.path.join(PROJECT_ROOT, f"scout_e2e_opt_results_{timestamp}.json")
        
        if self.args.resume:
            self.history_file = self.args.resume
            self._load_history()
        
        self.summary_dir = os.path.join(DEFAULT_LOG_DIR, "optimize_summary")
        os.makedirs(self.summary_dir, exist_ok=True)

    def _load_history(self):
        if not os.path.exists(self.history_file):
            logger.warning(f"Resume 파일이 존재하지 않습니다: {self.history_file}")
            return

        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for entry in data.get("results", []):
                res = OptimizationResult(
                    params=entry["params"],
                    total_return_pct=entry["total_return_pct"],
                    mdd_pct=entry["mdd_pct"],
                    total_trades=entry.get("total_trades", 0),
                    score=entry["score"],
                    elapsed=entry.get("elapsed", 0.0)
                )
                self.results.append(res)
                
                if self.best_result is None or res.score > self.best_result.score:
                    self.best_result = res
            
            logger.info(f"🔄 이전 결과 {len(self.results)}개 로드 완료")
        except Exception as e:
            logger.error(f"이력 로드 실패: {e}")

    def _should_skip(self, params: Dict[str, float]) -> bool:
        for res in self.results:
            if res.params == params:
                return True
        return False

    def _save_results(self):
        payload = {
            "timestamp": datetime.now().isoformat(),
            "args": {
                "start_date": self.args.start_date,
                "end_date": self.args.end_date,
                "capital": self.args.capital,
            },
            "results": [r.__dict__ for r in self.results],
            "best": self.best_result.__dict__ if self.best_result else None,
        }
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._write_summary()

    def _write_summary(self):
        if not self.results:
            return
        sorted_results = sorted(self.results, key=lambda r: r.score, reverse=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = os.path.join(self.summary_dir, f"scout_e2e_opt_summary_{timestamp}.txt")
        latest_path = os.path.join(self.summary_dir, "scout_e2e_opt_summary_latest.txt")

        lines = []
        lines.append("=== Scout E2E Optimization Summary ===")
        lines.append(f"생성 시각: {datetime.now().isoformat()}")
        lines.append(f"기간: {self.args.start_date} ~ {self.args.end_date}")
        lines.append(f"총 테스트 조합: {len(self.results)}")
        
        if sorted_results:
            best = sorted_results[0]
            lines.append("")
            lines.append("🏅 Best Combination")
            lines.append(
                f"- Score {best.score:.2f} | 수익률 {best.total_return_pct:.2f}% | "
                f"MDD {best.mdd_pct:.2f}% | 거래 {best.total_trades}건 | "
                f"소요시간 {best.elapsed:.1f}s"
            )
            lines.append(f"- Params: {json.dumps(best.params, ensure_ascii=False)}")

        lines.append("")
        lines.append("Top 10 Results")
        for idx, entry in enumerate(sorted_results[:10], start=1):
            lines.append(
                f"{idx:02d}. Score {entry.score:.2f} | 수익률 {entry.total_return_pct:.2f}% | "
                f"MDD {entry.mdd_pct:.2f}% | 거래 {entry.total_trades}건"
            )
            lines.append(f"    Params: {json.dumps(entry.params, ensure_ascii=False)}")

        text = "\n".join(lines)
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(text)
        with open(latest_path, "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("📝 요약 파일 생성: %s", summary_path)

    def generate_param_sets(self) -> List[Dict[str, float]]:
        # 지정된 파라미터만 사용하거나 전체 Grid 사용
        if self.args.quick:
            # Quick 모드: 핵심 파라미터만
            grid = {
                "scout_min_score": [60, 70, 80],
                "target_profit_pct": [0.10, 0.15, 0.20],
                "stop_loss_pct": [0.05, 0.07],
            }
        else:
            grid = PARAMETER_GRID

        param_names = list(grid.keys())
        param_values = list(grid.values())

        combinations = []
        for combo in itertools.product(*param_values):
            params = dict(zip(param_names, combo))
            if not self._should_skip(params):
                combinations.append(params)

        if not combinations:
            logger.info("이미 모든 조합을 테스트했습니다.")
            return []

        if len(combinations) > self.args.max_combinations:
            combinations = random.sample(combinations, self.args.max_combinations)

        random.shuffle(combinations)
        
        logger.info(f"📊 테스트할 조합: {len(combinations)}개")
        return combinations

    def run(self):
        combos = self.generate_param_sets()
        if not combos:
            return

        cpu_count = os.cpu_count() or 8
        max_workers = min(self.args.max_workers, max(1, cpu_count // 2))
        logger.info(
            f"🚀 Grid 최적화 시작: 조합 {len(combos)}개 / 병렬 worker {max_workers}개"
        )

        completed = 0
        total_tasks = len(combos)

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(run_single_backtest, params, self.args): params
                for params in combos
            }

            for future in as_completed(futures):
                completed += 1
                result = future.result()
                
                progress_str = f"({completed}/{total_tasks})"
                
                if result["success"]:
                    res_obj = OptimizationResult(
                        params=result["params"],
                        total_return_pct=result["total_return_pct"],
                        mdd_pct=result["mdd_pct"],
                        total_trades=int(result.get("total_trades") or 0),
                        score=result["score"],
                        elapsed=result.get("elapsed", 0),
                    )
                    self.results.append(res_obj)
                    self._save_results()

                    if self.best_result is None or res_obj.score > self.best_result.score:
                        self.best_result = res_obj
                        logger.info(
                            f"{progress_str} ✅ 새로운 최고 점수! 수익률 {res_obj.total_return_pct:.2f}% / "
                            f"MDD {res_obj.mdd_pct:.2f}% / 점수 {res_obj.score:.2f}"
                        )
                    else:
                        logger.info(
                            f"{progress_str} ℹ️ 완료 (점수 {res_obj.score:.2f}, 수익률 {res_obj.total_return_pct:.2f}%)"
                        )
                else:
                    logger.warning(f"{progress_str} ❌ 실패 - {result.get('error', 'Unknown')}")

        if not self.results:
            logger.info("유효한 결과를 얻지 못했습니다.")
            return

        # 최종 요약 출력
        logger.info("=" * 60)
        if self.best_result:
            logger.info("🎯 최적 조합 발견!")
            logger.info(f"   수익률: {self.best_result.total_return_pct:.2f}%")
            logger.info(f"   MDD: {self.best_result.mdd_pct:.2f}%")
            logger.info(f"   점수: {self.best_result.score:.2f}")
            logger.info(f"   거래: {self.best_result.total_trades}건")
            logger.info(f"   파라미터: {json.dumps(self.best_result.params, ensure_ascii=False, indent=2)}")
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    # 기본값: 최근 6개월
    from datetime import datetime, timedelta
    default_end = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")  # 어제
    default_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")  # 6개월 전
    
    parser = argparse.ArgumentParser(description="Scout E2E 백테스트 파라미터 자동 최적화")
    parser.add_argument("--start-date", type=str, default=default_start, help=f"시작일 (기본: {default_start})")
    parser.add_argument("--end-date", type=str, default=default_end, help=f"종료일 (기본: {default_end})")
    parser.add_argument("--capital", type=float, default=10_000_000, help="초기 자본금")
    parser.add_argument("--max-combinations", type=int, default=50, help="최대 테스트 조합 수")
    parser.add_argument("--max-workers", type=int, default=max(1, (os.cpu_count() or 8) // 2), help="병렬 프로세스 수")
    parser.add_argument("--resume", type=str, default=None, help="이전 결과 파일 경로 (이어하기)")
    parser.add_argument("--timeout", type=int, default=900, help="각 백테스트 타임아웃(초)")
    parser.add_argument("--quick", action="store_true", help="Quick 모드 (핵심 파라미터만)")
    return parser


def main():
    args = build_parser().parse_args()
    optimizer = ScoutE2EOptimizer(args)
    optimizer.run()


if __name__ == "__main__":
    main()
