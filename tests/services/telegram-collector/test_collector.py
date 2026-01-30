#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/services/telegram-collector/test_collector.py
----------------------------------------------------
TelegramCollector 서비스 단위 테스트
"""

import os
import sys
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

# 프로젝트 루트 설정
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "services", "telegram-collector"))

from channels import (
    TELEGRAM_CHANNELS,
    TelegramChannel,
    ChannelRole,
    ContentType,
    get_channel_by_username,
    get_macro_channels,
    get_all_channel_usernames,
)
from collector import (
    compute_content_hash,
    is_duplicate,
    clear_hash_cache,
    extract_metadata_from_content,
    CollectedMessage,
    generate_mock_messages,
)


class TestChannelConfiguration:
    """채널 설정 테스트"""

    def test_channel_count(self):
        """3개 채널이 설정되어 있어야 함"""
        assert len(TELEGRAM_CHANNELS) == 3

    def test_channel_usernames(self):
        """채널 username 확인"""
        usernames = get_all_channel_usernames()
        assert "hedgecat0301" in usernames
        assert "HanaResearch" in usernames
        assert "meritz_research" in usernames

    def test_get_channel_by_username(self):
        """username으로 채널 조회"""
        channel = get_channel_by_username("hedgecat0301")
        assert channel is not None
        assert channel.name == "키움증권 전략/시황 한지영"
        assert channel.role == ChannelRole.MACRO_SIGNAL

    def test_get_channel_not_found(self):
        """존재하지 않는 채널"""
        channel = get_channel_by_username("nonexistent")
        assert channel is None

    def test_macro_channels(self):
        """Macro Signal 역할 채널만 필터링"""
        macro_channels = get_macro_channels()
        assert len(macro_channels) == 1
        assert macro_channels[0].username == "hedgecat0301"

    def test_channel_weights(self):
        """채널 가중치 설정 확인 (3현자 권고: 합계 ≤1.0)"""
        total_weight = sum(ch.weight for ch in TELEGRAM_CHANNELS)
        assert total_weight <= 1.0

        # 키움 채널이 가장 높은 가중치
        kiwoom = get_channel_by_username("hedgecat0301")
        hana = get_channel_by_username("HanaResearch")
        meritz = get_channel_by_username("meritz_research")

        assert kiwoom.weight > hana.weight
        assert kiwoom.weight > meritz.weight

    def test_channel_roles(self):
        """채널 역할 구분 확인"""
        kiwoom = get_channel_by_username("hedgecat0301")
        hana = get_channel_by_username("HanaResearch")
        meritz = get_channel_by_username("meritz_research")

        assert kiwoom.role == ChannelRole.MACRO_SIGNAL
        assert hana.role == ChannelRole.STOCK_REFERENCE
        assert meritz.role == ChannelRole.STOCK_REFERENCE


class TestContentHashing:
    """콘텐츠 해싱 테스트"""

    def setup_method(self):
        """각 테스트 전 캐시 초기화"""
        clear_hash_cache()

    def test_compute_hash(self):
        """해시 계산"""
        content = "테스트 콘텐츠입니다"
        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)

        assert len(hash1) == 16
        assert hash1 == hash2

    def test_hash_normalization(self):
        """공백 정규화 후 해시"""
        content1 = "테스트   콘텐츠"
        content2 = "테스트 콘텐츠"

        assert compute_content_hash(content1) == compute_content_hash(content2)

    def test_duplicate_detection(self):
        """중복 감지"""
        content = "중복 테스트 콘텐츠"
        hash1 = compute_content_hash(content)

        # 첫 번째는 중복 아님
        assert is_duplicate(hash1) is False
        # 두 번째는 중복
        assert is_duplicate(hash1) is True

    def test_clear_cache(self):
        """캐시 초기화"""
        content = "캐시 테스트"
        hash1 = compute_content_hash(content)

        assert is_duplicate(hash1) is False
        assert is_duplicate(hash1) is True

        clear_hash_cache()

        # 캐시 초기화 후 다시 새 메시지로 인식
        assert is_duplicate(hash1) is False


class TestMetadataExtraction:
    """메타데이터 추출 테스트"""

    def test_extract_link(self):
        """링크 감지"""
        channel = get_channel_by_username("HanaResearch")
        content = "리포트 링크: https://vo.la/xxx"

        metadata = extract_metadata_from_content(content, channel)
        assert metadata["has_link"] is True

    def test_extract_stock_code(self):
        """종목코드 감지"""
        channel = get_channel_by_username("HanaResearch")
        content = "삼성전자 (005930.KS/매수)"

        metadata = extract_metadata_from_content(content, channel)
        assert metadata["has_stock_code"] is True

    def test_extract_macro_keywords(self):
        """매크로 키워드 감지"""
        channel = get_channel_by_username("hedgecat0301")
        content = "FOMC 금리 인상 결정. 환율 변동성 확대 예상."

        metadata = extract_metadata_from_content(content, channel)
        assert metadata["is_macro_related"] is True
        assert "금리" in metadata["detected_macro_keywords"]
        assert "FOMC" in metadata["detected_macro_keywords"]
        assert "환율" in metadata["detected_macro_keywords"]

    def test_extract_sector_keywords(self):
        """섹터 키워드 감지"""
        channel = get_channel_by_username("HanaResearch")
        content = "반도체 업황 개선. 자동차 업종 호조."

        metadata = extract_metadata_from_content(content, channel)
        assert "반도체" in metadata.get("detected_sectors", [])
        assert "자동차" in metadata.get("detected_sectors", [])

    def test_non_macro_content(self):
        """비매크로 콘텐츠"""
        channel = get_channel_by_username("meritz_research")
        content = "삼성전자 4분기 실적 리뷰. 목표주가 상향."

        metadata = extract_metadata_from_content(content, channel)
        assert metadata["is_macro_related"] is False


class TestCollectedMessage:
    """CollectedMessage 데이터 클래스 테스트"""

    def test_to_stream_format(self):
        """Redis Stream 발행 형식 변환"""
        now = datetime.now(timezone.utc)

        msg = CollectedMessage(
            message_id=123,
            channel_username="hedgecat0301",
            channel_name="키움증권 전략/시황 한지영",
            channel_role="macro_signal",
            content="테스트 메시지",
            published_at=now,
            collected_at=now,
            content_hash="abc123",
            weight=0.6,
            metadata={"is_macro_related": True},
        )

        stream_data = msg.to_stream_format()

        assert "page_content" in stream_data
        assert "metadata" in stream_data
        assert stream_data["page_content"] == "테스트 메시지"
        assert stream_data["metadata"]["channel_username"] == "hedgecat0301"
        assert stream_data["metadata"]["weight"] == 0.6
        assert stream_data["metadata"]["source"] == "telegram"
        assert stream_data["metadata"]["is_macro_related"] is True


class TestMockMessages:
    """모의 메시지 생성 테스트"""

    def setup_method(self):
        clear_hash_cache()

    def test_generate_mock_messages(self):
        """모의 메시지 생성"""
        messages = generate_mock_messages()

        assert len(messages) == 3

    def test_mock_message_channels(self):
        """모의 메시지 채널 확인"""
        messages = generate_mock_messages()

        usernames = [msg.channel_username for msg in messages]
        assert "hedgecat0301" in usernames
        assert "HanaResearch" in usernames
        assert "meritz_research" in usernames

    def test_mock_message_weights(self):
        """모의 메시지 가중치 확인"""
        messages = generate_mock_messages()

        kiwoom_msg = next(m for m in messages if m.channel_username == "hedgecat0301")
        assert kiwoom_msg.weight == 0.6

    def test_mock_message_metadata(self):
        """모의 메시지 메타데이터 추출"""
        messages = generate_mock_messages()

        kiwoom_msg = next(m for m in messages if m.channel_username == "hedgecat0301")
        assert kiwoom_msg.metadata.get("is_macro_related") is True

        # 키움 메시지에 관세 키워드가 있어야 함
        assert "detected_macro_keywords" in kiwoom_msg.metadata

    def test_mock_stream_format(self):
        """모의 메시지 스트림 형식 변환"""
        messages = generate_mock_messages()

        for msg in messages:
            stream_data = msg.to_stream_format()
            assert "page_content" in stream_data
            assert "metadata" in stream_data
            assert len(stream_data["page_content"]) > 0


class TestChannelParsing:
    """채널별 파싱 패턴 테스트"""

    def test_kiwoom_title_pattern(self):
        """키움 채널 제목 패턴"""
        channel = get_channel_by_username("hedgecat0301")
        content = "[1/30, 장 시작 전 생각: 트럼프 vs 파월, 키움 한지영]"

        import re
        match = re.search(channel.title_pattern, content)
        assert match is not None
        assert match.group(1) == "1/30"

    def test_hana_title_pattern(self):
        """하나증권 제목 패턴"""
        channel = get_channel_by_username("HanaResearch")
        content = "삼성전자 (005930.KS/매수): 4Q24 실적 리뷰"

        import re
        match = re.search(channel.title_pattern, content)
        assert match is not None
        assert match.group(2) == "005930"

    def test_meritz_title_pattern(self):
        """메리츠 제목 패턴"""
        channel = get_channel_by_username("meritz_research")
        content = "📮 [반도체/디스플레이 김선우]"

        import re
        match = re.search(channel.title_pattern, content)
        assert match is not None


class TestStreamIntegration:
    """Redis Stream 연동 테스트 (Mock)"""

    def setup_method(self):
        clear_hash_cache()

    @patch('shared.messaging.stream_client.publish_news_batch')
    def test_publish_to_stream(self, mock_publish):
        """스트림 발행"""
        from collector import publish_to_stream

        mock_publish.return_value = 3

        messages = generate_mock_messages()
        published = publish_to_stream(messages)

        assert published == 3
        mock_publish.assert_called_once()

    @patch('shared.messaging.stream_client.publish_news_batch')
    def test_publish_empty_messages(self, mock_publish):
        """빈 메시지 리스트 발행"""
        from collector import publish_to_stream

        published = publish_to_stream([])

        assert published == 0
        mock_publish.assert_not_called()


# ==============================================================================
# Test Runner
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
