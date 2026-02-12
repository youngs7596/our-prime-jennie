#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/macro_insight/test_daily_insight_db.py
----------------------------------------------------
save_insight_to_db() SQL 구문 검증 테스트.

배경: 2026-02-12 macro_council 장애
  - INSERT 컬럼 35개 vs VALUES 플레이스홀더 34개 불일치
  - 테스트가 없어서 배포 전 검출 실패
"""

import re
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from shared.macro_insight.daily_insight import (
    DailyMacroInsight,
    save_insight_to_db,
)


class TestSaveInsightToDbSqlConsistency(unittest.TestCase):
    """SQL INSERT 문의 컬럼/플레이스홀더/파라미터 개수 일치 검증."""

    def _make_dummy_insight(self) -> DailyMacroInsight:
        """테스트용 DailyMacroInsight 생성."""
        return DailyMacroInsight(
            insight_date=date(2026, 2, 12),
            source_channel="test",
            source_analyst="test",
            sentiment="neutral",
            sentiment_score=50,
            regime_hint="SIDEWAYS",
            sector_signals={},
            key_themes=[],
            risk_factors=[],
            opportunity_factors=[],
            key_stocks=[],
            risk_stocks=[],
            opportunity_stocks=[],
            raw_message="test",
            raw_council_output={},
            council_cost_usd=0.1,
            position_size_pct=100,
            stop_loss_adjust_pct=100,
            strategies_to_favor=[],
            strategies_to_avoid=[],
            sectors_to_favor=[],
            sectors_to_avoid=[],
            trading_reasoning="test",
            political_risk_level="low",
            political_risk_summary="",
        )

    @patch("shared.macro_insight.daily_insight.database")
    def test_placeholder_count_matches_columns_and_params(self, mock_db):
        """INSERT 컬럼 수 == %s 플레이스홀더 수 == params 튜플 길이 검증."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        insight = self._make_dummy_insight()
        save_insight_to_db(insight, conn=mock_conn)

        # cursor.execute 호출 확인
        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]

        # INSERT 컬럼 수 파싱
        insert_match = re.search(r"INSERT INTO \w+\s*\(([^)]+)\)", sql, re.DOTALL)
        self.assertIsNotNone(insert_match, "INSERT INTO ... () 구문을 찾을 수 없음")
        columns = [c.strip() for c in insert_match.group(1).split(",") if c.strip()]

        # VALUES 플레이스홀더 수
        values_match = re.search(r"VALUES\s*\(([^)]+)\)", sql, re.DOTALL)
        self.assertIsNotNone(values_match, "VALUES () 구문을 찾을 수 없음")
        placeholders = values_match.group(1).count("%s")

        # 3자 일치 검증
        self.assertEqual(
            len(columns), placeholders,
            f"컬럼 수({len(columns)}) != 플레이스홀더 수({placeholders})"
        )
        self.assertEqual(
            len(columns), len(params),
            f"컬럼 수({len(columns)}) != params 수({len(params)})"
        )
        self.assertEqual(
            placeholders, len(params),
            f"플레이스홀더 수({placeholders}) != params 수({len(params)})"
        )

    @patch("shared.macro_insight.daily_insight.database")
    def test_save_returns_true_on_success(self, mock_db):
        """정상 저장 시 True 반환."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        insight = self._make_dummy_insight()
        result = save_insight_to_db(insight, conn=mock_conn)

        self.assertTrue(result)
        mock_conn.commit.assert_called_once()

    @patch("shared.macro_insight.daily_insight.database")
    def test_save_returns_false_on_db_error(self, mock_db):
        """DB 에러 시 False 반환 (예외 삼키기 확인)."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("DB error")
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        insight = self._make_dummy_insight()
        result = save_insight_to_db(insight, conn=mock_conn)

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
