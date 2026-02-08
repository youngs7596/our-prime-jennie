#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/shared/test_news_deduplicator.py
----------------------------------------
NewsDeduplicator (Redis SET 기반 영속 중복 체크) 테스트
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from shared.messaging.stream_client import (
    NewsDeduplicator,
    compute_news_hash,
)


class TestComputeNewsHash(unittest.TestCase):
    """compute_news_hash 유틸 함수 테스트"""

    def test_same_title_same_hash(self):
        h1 = compute_news_hash("삼성전자 반도체 투자 확대")
        h2 = compute_news_hash("삼성전자 반도체 투자 확대")
        self.assertEqual(h1, h2)

    def test_normalized_ignores_whitespace_and_special(self):
        h1 = compute_news_hash("삼성전자, 반도체 투자!")
        h2 = compute_news_hash("삼성전자 반도체 투자")
        self.assertEqual(h1, h2)

    def test_different_titles_different_hash(self):
        h1 = compute_news_hash("삼성전자 반도체")
        h2 = compute_news_hash("SK하이닉스 메모리")
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = compute_news_hash("테스트 뉴스 제목")
        self.assertEqual(len(h), 12)


class TestNewsDeduplicator(unittest.TestCase):
    """NewsDeduplicator Redis 기반 중복 체크 테스트"""

    def setUp(self):
        self.dedup = NewsDeduplicator(prefix="test:dedup:news")
        self.mock_redis = MagicMock()
        self.mock_pipe = MagicMock()
        self.mock_redis.pipeline.return_value = self.mock_pipe

    def _patch_redis(self):
        return patch(
            "shared.messaging.stream_client.get_redis_client",
            return_value=self.mock_redis,
        )

    # ──────────────────────────────────────────────
    # _today_key / _recent_keys
    # ──────────────────────────────────────────────

    @patch("shared.messaging.stream_client.datetime")
    def test_today_key_format(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 8, 12, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        key = self.dedup._today_key()
        self.assertEqual(key, b"test:dedup:news:20260208")

    @patch("shared.messaging.stream_client.datetime")
    def test_recent_keys_returns_3_days(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 8, 12, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        keys = self.dedup._recent_keys()
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[0], b"test:dedup:news:20260208")
        self.assertEqual(keys[1], b"test:dedup:news:20260207")
        self.assertEqual(keys[2], b"test:dedup:news:20260206")

    # ──────────────────────────────────────────────
    # is_seen
    # ──────────────────────────────────────────────

    def test_is_seen_returns_false_when_not_found(self):
        with self._patch_redis():
            self.mock_pipe.execute.return_value = [False, False, False]
            result = self.dedup.is_seen("abc123")
            self.assertFalse(result)

    def test_is_seen_returns_true_when_found_in_any_day(self):
        with self._patch_redis():
            self.mock_pipe.execute.return_value = [False, True, False]
            result = self.dedup.is_seen("abc123")
            self.assertTrue(result)

    def test_is_seen_fallback_on_redis_error(self):
        with self._patch_redis():
            self.mock_pipe.execute.side_effect = Exception("Redis down")
            result = self.dedup.is_seen("abc123")
            self.assertFalse(result)  # 안전한 폴백: 신규로 처리

    # ──────────────────────────────────────────────
    # mark_seen
    # ──────────────────────────────────────────────

    def test_mark_seen_calls_sadd_and_expire(self):
        with self._patch_redis():
            self.dedup.mark_seen("abc123")
            self.mock_pipe.sadd.assert_called_once()
            self.mock_pipe.expire.assert_called_once()
            self.mock_pipe.execute.assert_called_once()

    def test_mark_seen_handles_redis_error(self):
        with self._patch_redis():
            self.mock_pipe.execute.side_effect = Exception("Redis down")
            # 예외 발생하지 않아야 함
            self.dedup.mark_seen("abc123")

    # ──────────────────────────────────────────────
    # check_and_mark
    # ──────────────────────────────────────────────

    def test_check_and_mark_new_returns_true(self):
        with self._patch_redis():
            # is_seen → False
            self.mock_pipe.execute.side_effect = [
                [False, False, False],  # is_seen pipeline
                None,  # mark_seen pipeline
            ]
            result = self.dedup.check_and_mark("new_hash")
            self.assertTrue(result)

    def test_check_and_mark_duplicate_returns_false(self):
        with self._patch_redis():
            self.mock_pipe.execute.return_value = [False, True, False]
            result = self.dedup.check_and_mark("dup_hash")
            self.assertFalse(result)

    # ──────────────────────────────────────────────
    # filter_new_batch
    # ──────────────────────────────────────────────

    def test_filter_new_batch_empty_input(self):
        result = self.dedup.filter_new_batch([])
        self.assertEqual(result, set())

    def test_filter_new_batch_all_new(self):
        with self._patch_redis():
            # 2개 hash × 3 days = 6 SISMEMBER 결과, 전부 False
            self.mock_pipe.execute.side_effect = [
                [False, False, False, False, False, False],  # 조회
                None,  # 마킹
            ]
            result = self.dedup.filter_new_batch(["hash_a", "hash_b"])
            self.assertEqual(result, {"hash_a", "hash_b"})

    def test_filter_new_batch_some_duplicates(self):
        with self._patch_redis():
            # hash_a: 3일 전부 False → 신규
            # hash_b: 어제 True → 중복
            self.mock_pipe.execute.side_effect = [
                [False, False, False, False, True, False],  # 조회
                None,  # 마킹 (hash_a만)
            ]
            result = self.dedup.filter_new_batch(["hash_a", "hash_b"])
            self.assertEqual(result, {"hash_a"})

    def test_filter_new_batch_all_duplicates(self):
        with self._patch_redis():
            self.mock_pipe.execute.return_value = [True, False, False, False, True, False]
            result = self.dedup.filter_new_batch(["hash_a", "hash_b"])
            self.assertEqual(result, set())

    def test_filter_new_batch_fallback_on_error(self):
        with self._patch_redis():
            self.mock_pipe.execute.side_effect = Exception("Redis down")
            result = self.dedup.filter_new_batch(["hash_a", "hash_b"])
            # 폴백: 전체를 신규로 처리
            self.assertEqual(result, {"hash_a", "hash_b"})


if __name__ == "__main__":
    unittest.main()
