import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from shared.symbol_profile import (
    apply_overrides_to_file,
    build_symbol_profile,
)


class TestSymbolProfile:
    def test_build_profile_basic(self):
        # 상승 추세 + 낮은 거래량 -> 거래량 배수 완화 예상
        days = 120
        dates = [datetime(2025, 1, 1) + timedelta(days=i) for i in range(days)]
        closes = np.linspace(100, 130, days)  # 완만한 상승
        volumes = np.full(days, 50_000)  # 낮은 유동성

        df = pd.DataFrame(
            {
                "PRICE_DATE": dates,
                "CLOSE_PRICE": closes,
                "VOLUME": volumes,
            }
        )

        result = build_symbol_profile("005930", df, lookback=120)
        overrides = result["overrides"]

        assert result["reason"] is None
        # 거래량이 낮으므로 배수가 1.05 근처로 완화되는지 확인
        assert 1.0 <= overrides["TIER2_VOLUME_MULTIPLIER"] <= 1.1
        # RSI 기반 임계치들이 안전한 범위 내에 있는지 확인
        assert 30 <= overrides["BUY_RSI_OVERSOLD_BULL_THRESHOLD"] <= 45
        assert 68 <= overrides["TIER2_RSI_MAX"] <= 80
        assert 72 <= overrides["SELL_RSI_OVERBOUGHT_THRESHOLD"] <= 82

    def test_apply_overrides_to_file(self, tmp_path):
        path = tmp_path / "symbol_overrides.json"
        initial = {"symbols": {"000660": {"TIER2_RSI_MAX": 72}}}
        path.write_text(json.dumps(initial), encoding="utf-8")

        merged = apply_overrides_to_file(
            "005930",
            {"TIER2_VOLUME_MULTIPLIER": 1.1},
            path=str(path),
            dry_run=False,
        )

        # 파일에 기록되었는지 확인
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["symbols"]["005930"]["TIER2_VOLUME_MULTIPLIER"] == 1.1
        # 기존 심볼 데이터 유지
        assert saved["symbols"]["000660"]["TIER2_RSI_MAX"] == 72
        # 반환된 병합 결과도 동일해야 함
        assert merged["symbols"]["005930"]["TIER2_VOLUME_MULTIPLIER"] == 1.1

