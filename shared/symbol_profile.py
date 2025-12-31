"""
종목별 특성 프로파일러
----------------------
최근 일봉을 바탕으로 RSI 분포/거래량/변동성을 요약해
per-symbol 설정 오버라이드 값을 산출합니다.

사용처:
- 종목별 TIER2 거래량 배수, RSI 구간, 매도 과열 기준 자동 산출
- 결과를 config/symbol_overrides.json 또는 DB 키(SYMBOL_{code}__*)에 반영
"""

import json
import logging
import os
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from shared import strategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------
def _clamp(value: Optional[float], lo: float, hi: float) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return max(lo, min(hi, float(value)))


def _safe_percentile(series: pd.Series, q: float, default: Optional[float] = None) -> Optional[float]:
    if series is None or len(series) == 0:
        return default
    try:
        return float(np.percentile(series, q))
    except Exception:
        return default


def _compute_rsi_series(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    단순 RSI 시퀀스 계산 (EMA/단순평균 혼합 대신 롤링 평균 기반)
    - 길이가 부족하면 빈 Series 반환
    """
    s = pd.Series(prices).astype(float)
    if s.empty or len(s) < period + 1:
        return pd.Series(dtype=float)

    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.dropna()


# ---------------------------------------------------------------------------
# 프로파일 생성
# ---------------------------------------------------------------------------
def build_symbol_profile(stock_code: str, daily_prices_df: pd.DataFrame, lookback: int = 120) -> Dict:
    """
    일봉 DataFrame으로부터 종목별 프로파일과 추천 오버라이드를 산출합니다.

    Returns:
        {
          "overrides": {...},   # 설정 오버라이드 제안
          "insights": {...},    # 참고용 메트릭
          "reason": None|str    # 실패/스킵 사유
        }
    """
    if daily_prices_df is None or daily_prices_df.empty:
        return {"overrides": {}, "insights": {}, "reason": "일봉 데이터 없음"}

    df = daily_prices_df.tail(lookback).copy()
    needed_cols = {"CLOSE_PRICE", "VOLUME"}
    if not needed_cols.issubset(set(df.columns)):
        return {"overrides": {}, "insights": {}, "reason": f"컬럼 부족: {needed_cols - set(df.columns)}"}

    # 거래량 기반 유동성/안전장치 배수
    volume_window = df["VOLUME"].tail(60)
    mean_vol = float(volume_window.mean()) if not volume_window.empty else None
    volume_multiplier = 1.2
    if mean_vol:
        if mean_vol < 200_000:
            volume_multiplier = 1.05
        elif mean_vol < 500_000:
            volume_multiplier = 1.10
    volume_multiplier = _clamp(volume_multiplier, 1.0, 1.5)

    # RSI 분포 기반 임계치
    rsi_series = _compute_rsi_series(df["CLOSE_PRICE"], period=14)
    rsi_p20 = _safe_percentile(rsi_series, 20, default=None)
    rsi_p80 = _safe_percentile(rsi_series, 80, default=None)

    buy_rsi_oversold_bull = _clamp(rsi_p20 if rsi_p20 is not None else 40, 30, 45)
    tier2_rsi_max = _clamp((rsi_p80 + 2) if rsi_p80 is not None else 70, 68, 80)
    sell_rsi_overbought = _clamp(rsi_p80 if rsi_p80 is not None else 75, 72, 82)

    overrides = {
        "TIER2_VOLUME_MULTIPLIER": volume_multiplier,
        "BUY_RSI_OVERSOLD_BULL_THRESHOLD": buy_rsi_oversold_bull,
        "TIER2_RSI_MAX": tier2_rsi_max,
        "SELL_RSI_OVERBOUGHT_THRESHOLD": sell_rsi_overbought,
    }

    insights = {
        "volume_mean_60": mean_vol,
        "rsi_p20": rsi_p20,
        "rsi_p80": rsi_p80,
        "rsi_count": int(len(rsi_series)),
    }

    return {"overrides": overrides, "insights": insights, "reason": None}


def build_symbol_profile_from_db(stock_code: str, session, lookback: int = 120) -> Dict:
    """DB에서 일봉을 조회한 뒤 프로파일을 생성합니다."""
    try:
        from shared import database

        df = database.get_daily_prices(session, stock_code, limit=lookback)
        return build_symbol_profile(stock_code, df, lookback=lookback)
    except Exception as e:
        logger.error(f"[{stock_code}] 프로파일 생성 실패: {e}", exc_info=True)
        return {"overrides": {}, "insights": {}, "reason": f"에러: {e}"}


# ---------------------------------------------------------------------------
# 오버라이드 파일 갱신
# ---------------------------------------------------------------------------
def apply_overrides_to_file(
    stock_code: str,
    overrides: Dict,
    path: Optional[str] = None,
    dry_run: bool = False,
) -> Dict:
    """
    config/symbol_overrides.json에 종목별 오버라이드를 병합 저장합니다.
    - path 미지정 시 프로젝트 루트 기준 config/symbol_overrides.json 사용.
    - dry_run=True면 파일에 쓰지 않고 병합 결과만 반환.
    """
    if path is None:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        path = os.path.join(project_root, "config", "symbol_overrides.json")

    os.makedirs(os.path.dirname(path), exist_ok=True)

    data = {"symbols": {}}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    data.update(existing)
    except Exception as e:
        logger.warning(f"symbol_overrides.json 로드 실패, 새로 생성합니다: {e}")

    symbols = data.get("symbols") if isinstance(data.get("symbols"), dict) else {}
    current = symbols.get(stock_code, {}) if isinstance(symbols.get(stock_code), dict) else {}
    merged = {**current, **overrides}
    symbols[stock_code] = merged
    data["symbols"] = symbols

    if not dry_run:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[{stock_code}] symbol_overrides.json 갱신 완료")

    return data

