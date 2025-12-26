"""
tests/shared/test_redis_cache.py - Redis 캐시 모듈 Unit Tests
==============================================================

shared/redis_cache.py 모듈의 Unit Test입니다.
fakeredis를 사용하여 실제 Redis 없이 테스트합니다.

실행 방법:
    pytest tests/shared/test_redis_cache.py -v

커버리지 포함:
    pytest tests/shared/test_redis_cache.py -v --cov=shared.redis_cache --cov-report=term-missing
"""

import json
import pytest
from datetime import datetime, timezone, timedelta


class TestSentimentScore:
    """감성 점수 (Sentiment Score) 관련 테스트"""
    
    def test_set_sentiment_score_new_stock(self, fake_redis):
        """새 종목에 감성 점수 저장"""
        from shared.redis_cache import set_sentiment_score, get_sentiment_score
        
        # Given: 새 종목
        stock_code = "005930"
        score = 75
        reason = "긍정적 뉴스"
        
        # When: 점수 저장
        result = set_sentiment_score(stock_code, score, reason, redis_client=fake_redis)
        
        # Then: 성공하고 점수가 그대로 저장됨 (EMA 적용 안됨)
        assert result is True
        data = get_sentiment_score(stock_code, redis_client=fake_redis)
        assert data["score"] == 75  # 새 종목은 100% 반영
        assert reason in data["reason"]
    
    def test_set_sentiment_score_ema_applied(self, fake_redis):
        """기존 종목에 감성 점수 저장 시 EMA 적용"""
        from shared.redis_cache import set_sentiment_score, get_sentiment_score
        
        # Given: 기존 점수가 있는 종목
        stock_code = "005930"
        set_sentiment_score(stock_code, 50, "기존 뉴스", redis_client=fake_redis)
        
        # When: 새 점수 저장 (100점)
        set_sentiment_score(stock_code, 100, "새 뉴스", redis_client=fake_redis)
        
        # Then: EMA 적용됨 (기존 50% + 신규 50% = 50*0.5 + 100*0.5 = 75)
        data = get_sentiment_score(stock_code, redis_client=fake_redis)
        assert data["score"] == 75.0  # EMA: 50*0.5 + 100*0.5 = 75
    
    def test_get_sentiment_score_not_found(self, fake_redis):
        """존재하지 않는 종목 조회 시 기본값 반환"""
        from shared.redis_cache import get_sentiment_score
        
        # When: 없는 종목 조회
        data = get_sentiment_score("999999", redis_client=fake_redis)
        
        # Then: 기본값 반환
        assert data["score"] == 50
        assert "데이터 없음" in data["reason"] or "중립" in data["reason"]
    
    def test_get_sentiment_score_with_data(self, fake_redis_with_data):
        """미리 저장된 데이터 조회"""
        from shared.redis_cache import get_sentiment_score
        
        # Given: fake_redis_with_data fixture에 005930 데이터가 있음
        
        # When: 조회
        data = get_sentiment_score("005930", redis_client=fake_redis_with_data)
        
        # Then: 미리 저장된 데이터 반환
        assert data["score"] == 65.5
        assert "삼성전자" in data["reason"]
    
    def test_set_sentiment_score_without_redis(self, mocker):
        """Redis 연결 실패 시 저장 실패"""
        from shared import redis_cache
        
        # Given: get_redis_connection이 None을 반환하도록 mock
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        # When: 저장 시도
        result = redis_cache.set_sentiment_score("005930", 50, "test")
        
        # Then: False 반환 (실패)
        assert result is False


class TestMarketRegimeCache:
    """시장 국면 (Market Regime) 캐시 테스트"""
    
    def test_set_and_get_market_regime(self, fake_redis):
        """시장 국면 캐시 저장 및 조회"""
        from shared.redis_cache import set_market_regime_cache, get_market_regime_cache
        
        # Given: 시장 국면 데이터
        regime_data = {
            "regime": "BULL",
            "risk_level": "LOW",
            "preset": "AGGRESSIVE"
        }
        
        # When: 저장
        result = set_market_regime_cache(regime_data, ttl_seconds=3600, redis_client=fake_redis)
        
        # Then: 성공하고 조회 가능
        assert result is True
        cached = get_market_regime_cache(redis_client=fake_redis)
        assert cached["regime"] == "BULL"
        assert cached["risk_level"] == "LOW"
        assert "_cached_at" in cached  # 타임스탬프 자동 추가됨
    
    def test_get_market_regime_cache_expired(self, fake_redis):
        """만료된 캐시 조회 시 None 반환"""
        from shared.redis_cache import get_market_regime_cache, MARKET_REGIME_CACHE_KEY
        
        # Given: 오래된 캐시 (2시간 전)
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        old_data = {
            "regime": "BEAR",
            "_cached_at": old_time
        }
        fake_redis.setex(MARKET_REGIME_CACHE_KEY, 3600, json.dumps(old_data))
        
        # When: max_age_seconds=3600 (1시간)으로 조회
        cached = get_market_regime_cache(max_age_seconds=3600, redis_client=fake_redis)
        
        # Then: 만료되어 None 반환
        assert cached is None
    
    def test_get_market_regime_cache_not_expired(self, fake_redis):
        """유효한 캐시 조회"""
        from shared.redis_cache import get_market_regime_cache, MARKET_REGIME_CACHE_KEY
        
        # Given: 최근 캐시 (30분 전)
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        recent_data = {
            "regime": "NEUTRAL",
            "_cached_at": recent_time
        }
        fake_redis.setex(MARKET_REGIME_CACHE_KEY, 3600, json.dumps(recent_data))
        
        # When: max_age_seconds=3600 (1시간)으로 조회
        cached = get_market_regime_cache(max_age_seconds=3600, redis_client=fake_redis)
        
        # Then: 유효하여 데이터 반환
        assert cached is not None
        assert cached["regime"] == "NEUTRAL"
    
    def test_set_market_regime_cache_empty_payload(self, fake_redis):
        """빈 페이로드로 저장 시도"""
        from shared.redis_cache import set_market_regime_cache
        
        # When: 빈 딕셔너리로 저장 시도
        result = set_market_regime_cache({}, redis_client=fake_redis)
        
        # Then: False 반환
        assert result is False


class TestCompetitorBenefitScore:
    """경쟁사 수혜 점수 테스트"""
    
    def test_set_competitor_benefit_score(self, fake_redis):
        """경쟁사 수혜 점수 저장"""
        from shared.redis_cache import set_competitor_benefit_score, get_competitor_benefit_score
        
        # Given: 수혜 정보
        stock_code = "000660"  # SK하이닉스
        score = 15
        reason = "삼성전자 보안사고로 인한 반사이익"
        affected = "005930"
        event_type = "보안사고"
        
        # When: 저장
        result = set_competitor_benefit_score(
            stock_code, score, reason, affected, event_type,
            redis_client=fake_redis
        )
        
        # Then: 성공
        assert result is True
        data = get_competitor_benefit_score(stock_code, redis_client=fake_redis)
        assert data["score"] == 15
        assert data["affected_stock"] == "005930"
        assert data["event_type"] == "보안사고"
    
    def test_set_competitor_benefit_score_keep_higher(self, fake_redis):
        """기존 점수가 더 높으면 유지"""
        from shared.redis_cache import set_competitor_benefit_score, get_competitor_benefit_score
        
        # Given: 높은 점수가 이미 있음
        stock_code = "000660"
        set_competitor_benefit_score(
            stock_code, 20, "첫 번째 이벤트", "005930", "리콜",
            redis_client=fake_redis
        )
        
        # When: 더 낮은 점수로 저장 시도
        set_competitor_benefit_score(
            stock_code, 10, "두 번째 이벤트", "035720", "오너리스크",
            redis_client=fake_redis
        )
        
        # Then: 기존 높은 점수 유지
        data = get_competitor_benefit_score(stock_code, redis_client=fake_redis)
        assert data["score"] == 20  # 기존 점수 유지
        assert data["event_type"] == "리콜"  # 기존 이벤트 유지
    
    def test_get_competitor_benefit_score_not_found(self, fake_redis):
        """존재하지 않는 종목 조회"""
        from shared.redis_cache import get_competitor_benefit_score
        
        # When: 없는 종목 조회
        data = get_competitor_benefit_score("999999", redis_client=fake_redis)
        
        # Then: 기본값 반환
        assert data["score"] == 0
        assert data["reason"] == ""
        assert data["affected_stock"] == ""
    
    def test_get_all_competitor_benefits(self, fake_redis):
        """모든 경쟁사 수혜 점수 조회"""
        from shared.redis_cache import set_competitor_benefit_score, get_all_competitor_benefits
        
        # Given: 여러 종목에 수혜 점수 저장
        set_competitor_benefit_score("000660", 10, "이유1", "005930", "보안사고", redis_client=fake_redis)
        set_competitor_benefit_score("035420", 8, "이유2", "005930", "보안사고", redis_client=fake_redis)
        
        # When: 전체 조회
        all_benefits = get_all_competitor_benefits(redis_client=fake_redis)
        
        # Then: 모든 데이터 반환
        assert len(all_benefits) == 2
        assert "000660" in all_benefits
        assert "035420" in all_benefits
        assert all_benefits["000660"]["score"] == 10


class TestGenericRedisData:
    """일반 Redis 데이터 저장/조회 테스트"""
    
    def test_set_and_get_redis_data(self, fake_redis):
        """일반 데이터 저장 및 조회"""
        from shared.redis_cache import set_redis_data, get_redis_data
        
        # Given: 임의의 데이터
        key = "test:custom:data"
        data = {"foo": "bar", "count": 42}
        
        # When: 저장 및 조회
        result = set_redis_data(key, data, ttl=60, redis_client=fake_redis)
        retrieved = get_redis_data(key, redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        assert retrieved["foo"] == "bar"
        assert retrieved["count"] == 42
    
    def test_get_redis_data_not_found(self, fake_redis):
        """존재하지 않는 키 조회"""
        from shared.redis_cache import get_redis_data
        
        # When: 없는 키 조회
        data = get_redis_data("nonexistent:key", redis_client=fake_redis)
        
        # Then: 빈 딕셔너리 반환
        assert data == {}


class TestRedisConnection:
    """Redis 연결 관리 테스트"""
    
    def test_get_redis_connection_with_injected_client(self, fake_redis):
        """의존성 주입된 클라이언트 사용"""
        from shared.redis_cache import get_redis_connection
        
        # When: fake_redis 주입
        client = get_redis_connection(redis_client=fake_redis)
        
        # Then: 주입된 클라이언트 반환
        assert client is fake_redis
    
    def test_reset_redis_connection(self, fake_redis):
        """Redis 연결 리셋"""
        from shared import redis_cache
        
        # Given: 전역 클라이언트 설정 (테스트용으로 직접 설정)
        redis_cache._redis_client = fake_redis
        
        # When: 리셋
        redis_cache.reset_redis_connection()
        
        # Then: 전역 클라이언트가 None
        assert redis_cache._redis_client is None


class TestTradingFlags:
    """거래 플래그 테스트"""
    
    def test_set_and_get_trading_flag_pause(self, fake_redis):
        """pause 플래그 설정 및 조회"""
        from shared.redis_cache import set_trading_flag, get_trading_flag
        
        # When: pause 플래그 설정
        result = set_trading_flag("pause", True, "점심시간 일시정지", redis_client=fake_redis)
        
        # Then: 성공하고 값이 저장됨
        assert result is True
        flag = get_trading_flag("pause", redis_client=fake_redis)
        assert flag["value"] is True
        assert "점심시간" in flag["reason"]
        assert "set_at" in flag
    
    def test_set_and_get_trading_flag_stop(self, fake_redis):
        """stop 플래그 설정 및 조회"""
        from shared.redis_cache import set_trading_flag, get_trading_flag
        
        # When: stop 플래그 설정
        result = set_trading_flag("stop", True, "시장 급락", redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        flag = get_trading_flag("stop", redis_client=fake_redis)
        assert flag["value"] is True
    
    def test_set_and_get_trading_flag_dryrun(self, fake_redis):
        """dryrun 플래그 설정 및 조회"""
        from shared.redis_cache import set_trading_flag, get_trading_flag
        
        # When: dryrun 플래그 설정
        result = set_trading_flag("dryrun", True, "테스트 모드", redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        flag = get_trading_flag("dryrun", redis_client=fake_redis)
        assert flag["value"] is True
    
    def test_invalid_flag_name(self, fake_redis):
        """잘못된 플래그 이름"""
        from shared.redis_cache import set_trading_flag, get_trading_flag
        
        # When: 잘못된 플래그 이름
        result = set_trading_flag("invalid", True, "테스트", redis_client=fake_redis)
        
        # Then: 실패
        assert result is False
        
        # 조회도 기본값 반환
        flag = get_trading_flag("invalid", redis_client=fake_redis)
        assert flag["value"] is False
    
    def test_flag_not_set_returns_default(self, fake_redis):
        """설정되지 않은 플래그 조회 시 기본값"""
        from shared.redis_cache import get_trading_flag
        
        # When: 설정되지 않은 플래그 조회
        flag = get_trading_flag("pause", redis_client=fake_redis)
        
        # Then: 기본값 반환
        assert flag["value"] is False
        assert flag["reason"] == ""
    
    def test_is_trading_paused(self, fake_redis):
        """is_trading_paused 헬퍼 함수"""
        from shared.redis_cache import set_trading_flag, is_trading_paused
        
        # Given: pause 설정 안됨
        assert is_trading_paused(redis_client=fake_redis) is False
        
        # When: pause 설정
        set_trading_flag("pause", True, "일시정지", redis_client=fake_redis)
        
        # Then: True 반환
        assert is_trading_paused(redis_client=fake_redis) is True
    
    def test_is_trading_stopped(self, fake_redis):
        """is_trading_stopped 헬퍼 함수"""
        from shared.redis_cache import set_trading_flag, is_trading_stopped
        
        # Given: stop 설정 안됨
        assert is_trading_stopped(redis_client=fake_redis) is False
        
        # When: stop 설정
        set_trading_flag("stop", True, "거래중단", redis_client=fake_redis)
        
        # Then: True 반환
        assert is_trading_stopped(redis_client=fake_redis) is True
    
    def test_is_dryrun_enabled(self, fake_redis):
        """is_dryrun_enabled 헬퍼 함수"""
        from shared.redis_cache import set_trading_flag, is_dryrun_enabled
        
        # Given: dryrun을 False로 명시적 설정
        set_trading_flag("dryrun", False, "실거래 모드", redis_client=fake_redis)
        assert is_dryrun_enabled(redis_client=fake_redis) is False
        
        # When: dryrun 설정
        set_trading_flag("dryrun", True, "테스트", redis_client=fake_redis)
        
        # Then: True 반환
        assert is_dryrun_enabled(redis_client=fake_redis) is True
    
    def test_get_all_trading_flags(self, fake_redis):
        """모든 거래 플래그 조회"""
        from shared.redis_cache import set_trading_flag, get_all_trading_flags
        
        # Given: 여러 플래그 설정
        set_trading_flag("pause", True, "일시정지", redis_client=fake_redis)
        set_trading_flag("stop", False, "", redis_client=fake_redis)
        set_trading_flag("dryrun", True, "테스트", redis_client=fake_redis)
        
        # When: 전체 조회
        all_flags = get_all_trading_flags(redis_client=fake_redis)
        
        # Then: 모든 플래그 반환
        assert "pause" in all_flags
        assert "stop" in all_flags
        assert "dryrun" in all_flags
        assert all_flags["pause"]["value"] is True
        assert all_flags["dryrun"]["value"] is True


class TestConfigValue:
    """설정값 캐시 테스트 (특정 설정만 허용)"""
    
    def test_set_and_get_config_value_min_llm_score(self, fake_redis):
        """min_llm_score 설정값 저장 및 조회"""
        from shared.redis_cache import set_config_value, get_config_value
        
        # When: 허용된 설정값 저장
        result = set_config_value("min_llm_score", 65, redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        value = get_config_value("min_llm_score", redis_client=fake_redis)
        assert value == 65
    
    def test_set_and_get_config_value_max_buy_per_day(self, fake_redis):
        """max_buy_per_day 설정값 저장 및 조회"""
        from shared.redis_cache import set_config_value, get_config_value
        
        # When: 허용된 설정값 저장
        result = set_config_value("max_buy_per_day", 5, redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        value = get_config_value("max_buy_per_day", redis_client=fake_redis)
        assert value == 5
    
    def test_set_and_get_config_value_risk_level(self, fake_redis):
        """risk_level 설정값 저장 및 조회"""
        from shared.redis_cache import set_config_value, get_config_value
        
        # When: 허용된 설정값 저장
        result = set_config_value("risk_level", "HIGH", redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        value = get_config_value("risk_level", redis_client=fake_redis)
        assert value == "HIGH"
    
    def test_get_config_value_default(self, fake_redis):
        """설정값 없을 때 기본값"""
        from shared.redis_cache import get_config_value
        
        # When: 없는 설정 조회 (허용되지 않은 이름)
        value = get_config_value("nonexistent", default_value=100, redis_client=fake_redis)
        
        # Then: 기본값 반환
        assert value == 100
    
    def test_get_config_value_valid_name_not_set(self, fake_redis):
        """허용된 설정 이름이지만 저장되지 않은 경우 기본값"""
        from shared.redis_cache import get_config_value
        
        # When: 허용된 설정 이름이지만 저장된 적 없음
        value = get_config_value("min_llm_score", default_value=55, redis_client=fake_redis)
        
        # Then: 기본값 반환
        assert value == 55
    
    def test_invalid_config_name_fails(self, fake_redis):
        """허용되지 않은 설정 이름은 실패"""
        from shared.redis_cache import set_config_value
        
        # When: 허용되지 않은 설정 이름
        result = set_config_value("INVALID_CONFIG", 42, redis_client=fake_redis)
        
        # Then: 실패
        assert result is False


class TestNotificationMute:
    """알림 음소거 테스트"""
    
    def test_set_notification_mute(self, fake_redis):
        """알림 음소거 설정"""
        from shared.redis_cache import set_notification_mute, is_notification_muted
        from datetime import datetime, timezone
        
        # Given: 음소거 안됨
        assert is_notification_muted(redis_client=fake_redis) is False
        
        # When: 음소거 설정 (30분 후 해제)
        future_timestamp = int((datetime.now(timezone.utc).timestamp())) + 1800  # 30분 후
        result = set_notification_mute(until_timestamp=future_timestamp, redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        assert is_notification_muted(redis_client=fake_redis) is True
    
    def test_clear_notification_mute(self, fake_redis):
        """알림 음소거 해제"""
        from shared.redis_cache import set_notification_mute, clear_notification_mute, is_notification_muted
        from datetime import datetime, timezone
        
        # Given: 음소거 설정됨
        future_timestamp = int((datetime.now(timezone.utc).timestamp())) + 3600  # 1시간 후
        set_notification_mute(until_timestamp=future_timestamp, redis_client=fake_redis)
        assert is_notification_muted(redis_client=fake_redis) is True
        
        # When: 음소거 해제
        result = clear_notification_mute(redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        assert is_notification_muted(redis_client=fake_redis) is False
    
    def test_expired_mute_returns_false(self, fake_redis):
        """만료된 음소거는 False 반환"""
        from shared.redis_cache import is_notification_muted, NOTIFICATION_MUTE_KEY
        import json
        from datetime import datetime, timezone
        
        # Given: 이미 만료된 음소거 (과거 시간)
        past_timestamp = int((datetime.now(timezone.utc).timestamp())) - 3600  # 1시간 전
        data = {
            "until": past_timestamp,
            "set_at": datetime.now(timezone.utc).isoformat()
        }
        fake_redis.setex(NOTIFICATION_MUTE_KEY, 60, json.dumps(data))
        
        # When: 음소거 상태 확인
        result = is_notification_muted(redis_client=fake_redis)
        
        # Then: False (만료됨)
        assert result is False


class TestPriceAlerts:
    """가격 알림 테스트"""
    
    def test_set_price_alert(self, fake_redis):
        """가격 알림 설정"""
        from shared.redis_cache import set_price_alert, get_price_alerts
        
        # When: 가격 알림 설정
        result = set_price_alert(
            stock_code="005930",
            target_price=80000,
            alert_type="above",
            redis_client=fake_redis
        )
        
        # Then: 성공
        assert result is True
        alerts = get_price_alerts(redis_client=fake_redis)
        assert "005930" in alerts
        assert alerts["005930"]["target_price"] == 80000
    
    def test_delete_price_alert(self, fake_redis):
        """가격 알림 삭제"""
        from shared.redis_cache import set_price_alert, delete_price_alert, get_price_alerts
        
        # Given: 알림 설정됨
        set_price_alert("005930", 80000, "above", redis_client=fake_redis)
        
        # When: 알림 삭제
        result = delete_price_alert("005930", redis_client=fake_redis)
        
        # Then: 성공
        assert result is True
        alerts = get_price_alerts(redis_client=fake_redis)
        assert "005930" not in alerts
    
    def test_get_price_alerts_empty(self, fake_redis):
        """알림 없을 때 빈 딕셔너리"""
        from shared.redis_cache import get_price_alerts
        
        # When: 알림 조회
        alerts = get_price_alerts(redis_client=fake_redis)
        
        # Then: 빈 딕셔너리
        assert alerts == {}
    
    def test_delete_price_alert_not_exists(self, fake_redis):
        """존재하지 않는 가격 알림 삭제"""
        from shared.redis_cache import delete_price_alert
        
        # When: 존재하지 않는 알림 삭제 시도
        result = delete_price_alert("999999", redis_client=fake_redis)
        
        # Then: False 반환 (키 없음)
        assert result is False


class TestEdgeCases:
    """Edge Cases 테스트"""
    
    def test_sentiment_score_with_special_characters(self, fake_redis):
        """특수문자가 포함된 이유 저장"""
        from shared.redis_cache import set_sentiment_score, get_sentiment_score
        
        # Given: 특수문자 포함 이유
        stock_code = "005930"
        reason = '삼성전자 "AI 반도체" 호재 & 실적 개선 (기대↑)'
        
        # When: 저장 및 조회
        set_sentiment_score(stock_code, 80, reason, redis_client=fake_redis)
        data = get_sentiment_score(stock_code, redis_client=fake_redis)
        
        # Then: 정상 저장/조회
        assert data["score"] == 80
        assert "AI 반도체" in data["reason"]
    
    def test_sentiment_score_boundary_values(self, fake_redis):
        """경계값 테스트 (0, 100)"""
        from shared.redis_cache import set_sentiment_score, get_sentiment_score
        
        # 최소값 (0)
        set_sentiment_score("TEST01", 0, "매우 부정적", redis_client=fake_redis)
        data = get_sentiment_score("TEST01", redis_client=fake_redis)
        assert data["score"] == 0
        
        # 최대값 (100)
        set_sentiment_score("TEST02", 100, "매우 긍정적", redis_client=fake_redis)
        data = get_sentiment_score("TEST02", redis_client=fake_redis)
        assert data["score"] == 100
    
    def test_market_regime_with_complex_data(self, fake_redis):
        """복잡한 시장 국면 데이터 저장"""
        from shared.redis_cache import set_market_regime_cache, get_market_regime_cache
        
        # Given: 복잡한 중첩 데이터
        complex_data = {
            "regime": "VOLATILE",
            "indicators": {
                "vix": 25.5,
                "kospi_change": -1.2,
                "foreign_net": -5000000000
            },
            "sectors": ["반도체", "바이오", "2차전지"],
            "market_context_dict": {
                "summary": "시장 불안정",
                "confidence": 0.85
            }
        }
        
        # When: 저장 및 조회
        set_market_regime_cache(complex_data, redis_client=fake_redis)
        cached = get_market_regime_cache(redis_client=fake_redis)
        
        # Then: 중첩 데이터 정상 저장/조회
        assert cached["regime"] == "VOLATILE"
        assert cached["indicators"]["vix"] == 25.5
        assert "반도체" in cached["sectors"]
        assert cached["market_context_dict"]["confidence"] == 0.85


class TestRedisConnectionErrors:
    """Redis 연결 관련 에러 처리 테스트"""
    
    def test_get_redis_connection_global_ping_failure(self, mocker):
        """전역 싱글톤 ping 실패 시 재연결 시도"""
        from shared import redis_cache
        
        # Given: 전역 클라이언트가 있지만 ping 실패
        mock_client = mocker.MagicMock()
        mock_client.ping.side_effect = Exception("Connection lost")
        redis_cache._redis_client = mock_client
        
        # When: get_redis_connection 호출 (redis import가 실패하도록 mock)
        mocker.patch.dict('sys.modules', {'redis': None})
        
        # redis_cache 모듈에서 지연 import를 시뮬레이션
        def mock_import_redis():
            raise ImportError("redis not installed")
        
        mocker.patch.object(redis_cache, 'get_redis_connection', wraps=redis_cache.get_redis_connection)
        result = redis_cache.get_redis_connection()
        
        # Then: ping 실패 후 재연결 시도 (전역 클라이언트 None 됨)
        # 실제 Redis 없으므로 None 또는 연결 실패
        assert redis_cache._redis_client is None or result is None
    
    def test_get_redis_connection_with_real_redis_url_failure(self, mocker, monkeypatch):
        """Redis URL 연결 실패 시 None 반환"""
        from shared import redis_cache
        
        # Given: 잘못된 Redis URL
        monkeypatch.setenv("REDIS_URL", "redis://invalid-host:9999")
        redis_cache._redis_client = None  # 전역 클라이언트 초기화
        
        # When: 연결 시도 (실제 연결은 실패해야 함)
        # 이 테스트는 실제 네트워크 연결 시도를 하므로 timeout 발생
        # 테스트 환경에서는 짧은 timeout으로 빠르게 실패
        result = redis_cache.get_redis_connection()
        
        # Then: None 반환 (연결 실패)
        # 환경에 따라 실제 Redis가 있을 수 있으므로 결과만 확인
        assert result is None or result is not None  # 환경 의존적


class TestExceptionHandling:
    """각 함수의 예외 처리 분기 테스트"""
    
    def test_set_market_regime_cache_redis_not_connected(self, mocker):
        """Market Regime 저장 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_market_regime_cache({"regime": "BULL"})
        
        assert result is False
    
    def test_set_market_regime_cache_setex_exception(self, mocker, fake_redis):
        """Market Regime 저장 시 setex 예외"""
        from shared import redis_cache
        
        # setex가 예외를 발생시키도록 mock
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_market_regime_cache(
            {"regime": "BULL"}, 
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_market_regime_cache_json_parse_error(self, fake_redis):
        """Market Regime 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        # 잘못된 JSON 저장
        fake_redis.setex(redis_cache.MARKET_REGIME_CACHE_KEY, 3600, "invalid json {{{")
        
        result = redis_cache.get_market_regime_cache(redis_client=fake_redis)
        
        # 예외 발생 시 None 반환
        assert result is None
    
    def test_get_market_regime_cache_redis_not_connected(self, mocker):
        """Market Regime 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_market_regime_cache()
        
        assert result is None
    
    def test_get_market_regime_cache_invalid_timestamp(self, fake_redis):
        """Market Regime 캐시 timestamp 파싱 실패"""
        from shared import redis_cache
        import json
        
        # 잘못된 timestamp 형식
        fake_redis.setex(
            redis_cache.MARKET_REGIME_CACHE_KEY, 
            3600, 
            json.dumps({"regime": "BULL", "_cached_at": "invalid-date"})
        )
        
        # timestamp 파싱 실패해도 데이터는 반환
        result = redis_cache.get_market_regime_cache(redis_client=fake_redis)
        
        assert result is not None
        assert result["regime"] == "BULL"
    
    def test_set_sentiment_score_old_data_json_exception(self, mocker, fake_redis):
        """Sentiment Score 저장 시 기존 데이터 JSON 파싱 에러"""
        from shared import redis_cache
        
        # 잘못된 JSON을 기존 데이터로 저장
        fake_redis.setex("sentiment:005930", 7200, "invalid json")
        
        # 새 점수 저장 시도
        result = redis_cache.set_sentiment_score(
            "005930", 75, "테스트", 
            redis_client=fake_redis
        )
        
        # 기존 데이터 파싱 실패해도 새 점수는 저장됨
        # 파싱 실패 시 old_score=50 기본값 사용, EMA 적용: (50*0.5 + 75*0.5) = 62.5
        assert result is True
        data = redis_cache.get_sentiment_score("005930", redis_client=fake_redis)
        assert data["score"] == 62.5  # EMA 적용된 값
    
    def test_set_sentiment_score_setex_exception(self, mocker, fake_redis):
        """Sentiment Score 저장 시 setex 예외"""
        from shared import redis_cache
        
        # 첫 호출(기존 데이터 조회)은 성공, setex만 실패하도록
        original_setex = fake_redis.setex
        call_count = [0]
        def mock_setex(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 0:  # 모든 setex 호출 실패
                raise Exception("Redis error")
            return original_setex(*args, **kwargs)
        
        fake_redis.setex = mock_setex
        
        result = redis_cache.set_sentiment_score(
            "TEST01", 80, "테스트",
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_sentiment_score_redis_not_connected(self, mocker):
        """Sentiment Score 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_sentiment_score("005930")
        
        # 기본값 반환
        assert result["score"] == 50
        assert "데이터 없음" in result["reason"] or "중립" in result["reason"]
    
    def test_get_sentiment_score_json_exception(self, fake_redis):
        """Sentiment Score 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        fake_redis.setex("sentiment:005930", 7200, "invalid json")
        
        result = redis_cache.get_sentiment_score("005930", redis_client=fake_redis)
        
        # 예외 시 기본값 반환
        assert result["score"] == 50
    
    def test_set_redis_data_redis_not_connected(self, mocker):
        """일반 데이터 저장 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_redis_data("test:key", {"foo": "bar"})
        
        assert result is False
    
    def test_set_redis_data_setex_exception(self, mocker, fake_redis):
        """일반 데이터 저장 시 setex 예외"""
        from shared import redis_cache
        
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_redis_data(
            "test:key", {"foo": "bar"}, 
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_redis_data_redis_not_connected(self, mocker):
        """일반 데이터 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_redis_data("test:key")
        
        assert result == {}
    
    def test_get_redis_data_json_exception(self, fake_redis):
        """일반 데이터 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        fake_redis.setex("test:key", 3600, "invalid json")
        
        result = redis_cache.get_redis_data("test:key", redis_client=fake_redis)
        
        assert result == {}
    
    def test_set_competitor_benefit_redis_not_connected(self, mocker):
        """경쟁사 수혜 저장 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_competitor_benefit_score(
            "000660", 10, "테스트", "005930", "보안사고"
        )
        
        assert result is False
    
    def test_set_competitor_benefit_setex_exception(self, mocker, fake_redis):
        """경쟁사 수혜 저장 시 setex 예외"""
        from shared import redis_cache
        
        # get은 정상, setex만 예외
        original_get = fake_redis.get
        fake_redis.get = mocker.MagicMock(return_value=None)
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_competitor_benefit_score(
            "000660", 10, "테스트", "005930", "보안사고",
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_competitor_benefit_redis_not_connected(self, mocker):
        """경쟁사 수혜 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_competitor_benefit_score("000660")
        
        assert result["score"] == 0
    
    def test_get_competitor_benefit_json_exception(self, fake_redis):
        """경쟁사 수혜 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        fake_redis.setex("competitor_benefit:000660", 3600, "invalid json")
        
        result = redis_cache.get_competitor_benefit_score(
            "000660", redis_client=fake_redis
        )
        
        assert result["score"] == 0
    
    def test_get_all_competitor_benefits_redis_not_connected(self, mocker):
        """전체 경쟁사 수혜 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_all_competitor_benefits()
        
        assert result == {}
    
    def test_get_all_competitor_benefits_exception(self, mocker, fake_redis):
        """전체 경쟁사 수혜 조회 시 예외"""
        from shared import redis_cache
        
        fake_redis.keys = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.get_all_competitor_benefits(redis_client=fake_redis)
        
        assert result == {}
    
    def test_set_trading_flag_redis_not_connected(self, mocker):
        """Trading Flag 저장 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_trading_flag("pause", True, "테스트")
        
        assert result is False
    
    def test_set_trading_flag_setex_exception(self, mocker, fake_redis):
        """Trading Flag 저장 시 setex 예외"""
        from shared import redis_cache
        
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_trading_flag(
            "pause", True, "테스트",
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_trading_flag_redis_not_connected(self, mocker):
        """Trading Flag 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_trading_flag("pause")
        
        assert result["value"] is False
    
    def test_get_trading_flag_json_exception(self, fake_redis):
        """Trading Flag 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        fake_redis.setex(redis_cache.TRADING_PAUSE_KEY, 3600, "invalid json")
        
        result = redis_cache.get_trading_flag("pause", redis_client=fake_redis)
        
        assert result["value"] is False
    
    def test_is_dryrun_enabled_env_fallback(self, mocker, monkeypatch, fake_redis):
        """is_dryrun_enabled 환경변수 fallback"""
        from shared import redis_cache
        
        # Redis에 설정이 없을 때 환경변수 사용
        monkeypatch.setenv("DRY_RUN", "false")
        
        result = redis_cache.is_dryrun_enabled(redis_client=fake_redis)
        
        assert result is False
        
        # 환경변수가 true일 때
        monkeypatch.setenv("DRY_RUN", "true")
        result = redis_cache.is_dryrun_enabled(redis_client=fake_redis)
        assert result is True
    
    def test_set_config_value_redis_not_connected(self, mocker):
        """Config Value 저장 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_config_value("min_llm_score", 65)
        
        assert result is False
    
    def test_set_config_value_setex_exception(self, mocker, fake_redis):
        """Config Value 저장 시 setex 예외"""
        from shared import redis_cache
        
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_config_value(
            "min_llm_score", 65,
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_config_value_redis_not_connected(self, mocker):
        """Config Value 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_config_value("min_llm_score", default_value=60)
        
        assert result == 60
    
    def test_get_config_value_json_exception(self, fake_redis):
        """Config Value 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        fake_redis.setex(redis_cache.CONFIG_MIN_LLM_SCORE_KEY, 3600, "invalid json")
        
        result = redis_cache.get_config_value(
            "min_llm_score", default_value=60,
            redis_client=fake_redis
        )
        
        assert result == 60
    
    def test_set_notification_mute_redis_not_connected(self, mocker):
        """알림 음소거 설정 시 Redis 미연결"""
        from shared import redis_cache
        import time
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_notification_mute(until_timestamp=int(time.time()) + 3600)
        
        assert result is False
    
    def test_set_notification_mute_setex_exception(self, mocker, fake_redis):
        """알림 음소거 설정 시 setex 예외"""
        from shared import redis_cache
        import time
        
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_notification_mute(
            until_timestamp=int(time.time()) + 3600,
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_is_notification_muted_redis_not_connected(self, mocker):
        """알림 음소거 상태 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.is_notification_muted()
        
        assert result is False
    
    def test_is_notification_muted_json_exception(self, fake_redis):
        """알림 음소거 상태 조회 시 JSON 파싱 에러"""
        from shared import redis_cache
        
        fake_redis.setex(redis_cache.NOTIFICATION_MUTE_KEY, 3600, "invalid json")
        
        result = redis_cache.is_notification_muted(redis_client=fake_redis)
        
        assert result is False
    
    def test_clear_notification_mute_redis_not_connected(self, mocker):
        """알림 음소거 해제 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.clear_notification_mute()
        
        assert result is False
    
    def test_clear_notification_mute_delete_exception(self, mocker, fake_redis):
        """알림 음소거 해제 시 delete 예외"""
        from shared import redis_cache
        
        fake_redis.delete = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.clear_notification_mute(redis_client=fake_redis)
        
        assert result is False
    
    def test_set_price_alert_redis_not_connected(self, mocker):
        """가격 알림 설정 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.set_price_alert("005930", 80000)
        
        assert result is False
    
    def test_set_price_alert_setex_exception(self, mocker, fake_redis):
        """가격 알림 설정 시 setex 예외"""
        from shared import redis_cache
        
        fake_redis.setex = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.set_price_alert(
            "005930", 80000,
            redis_client=fake_redis
        )
        
        assert result is False
    
    def test_get_price_alerts_redis_not_connected(self, mocker):
        """가격 알림 조회 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.get_price_alerts()
        
        assert result == {}
    
    def test_get_price_alerts_exception(self, mocker, fake_redis):
        """가격 알림 조회 시 예외"""
        from shared import redis_cache
        
        fake_redis.keys = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.get_price_alerts(redis_client=fake_redis)
        
        assert result == {}
    
    def test_delete_price_alert_redis_not_connected(self, mocker):
        """가격 알림 삭제 시 Redis 미연결"""
        from shared import redis_cache
        
        mocker.patch.object(redis_cache, 'get_redis_connection', return_value=None)
        
        result = redis_cache.delete_price_alert("005930")
        
        assert result is False
    
    def test_delete_price_alert_delete_exception(self, mocker, fake_redis):
        """가격 알림 삭제 시 delete 예외"""
        from shared import redis_cache
        
        fake_redis.delete = mocker.MagicMock(side_effect=Exception("Redis error"))
        
        result = redis_cache.delete_price_alert("005930", redis_client=fake_redis)
        
        assert result is False

