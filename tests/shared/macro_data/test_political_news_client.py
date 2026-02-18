"""
tests/shared/macro_data/test_political_news_client.py
------------------------------------------------------
PoliticalNewsClient 키워드 감지 및 word boundary 테스트.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = str(Path(__file__).parent.parent.parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ==============================================================================
# Word Boundary 테스트
# ==============================================================================

class TestWordBoundary:
    """짧은 영문 키워드의 word boundary 적용 테스트"""

    def _make_client(self):
        with patch("shared.macro_data.clients.political_news_client.get_rate_limiter"), \
             patch("shared.macro_data.clients.political_news_client.get_macro_cache"):
            from shared.macro_data.clients.political_news_client import PoliticalNewsClient
            return PoliticalNewsClient()

    def test_war_not_match_award(self):
        """'war'가 'award'에 매칭되지 않아야 함 (word boundary)"""
        client = self._make_client()
        # "war"는 현재 KEYWORD_CONFIG에서 제거됨 (복합 키워드로 교체)
        # 대신 "ira" (3자, ASCII)로 테스트
        detected = client._detect_keywords("The award ceremony was held")
        categories = [d[1] for d in detected]
        assert "geopolitical" not in categories

    def test_ira_word_boundary(self):
        """'ira'가 단어 경계에서만 매칭"""
        client = self._make_client()

        # "ira" 단독 → us_trade_policy (IRA = Inflation Reduction Act)
        detected = client._detect_keywords("The IRA impacts Korean battery makers")
        categories = [d[1] for d in detected]
        assert "us_trade_policy" in categories

        # "ira" 부분 매칭 (thirst, viral 등) → 매칭 안됨
        detected = client._detect_keywords("The viral video spread quickly")
        kw_categories = [d[1] for d in detected]
        assert "us_trade_policy" not in kw_categories

    def test_ecb_word_boundary(self):
        """'ecb' (3자) word boundary 테스트"""
        client = self._make_client()

        detected = client._detect_keywords("ECB rate decision expected")
        categories = [d[1] for d in detected]
        assert "central_banks" in categories

    def test_boj_not_match_bojangles(self):
        """'boj' (3자)가 'bojangles'에 매칭되지 않아야 함"""
        client = self._make_client()

        detected = client._detect_keywords("Bojangles opens new restaurant")
        categories = [d[1] for d in detected]
        assert "central_banks" not in categories

    def test_long_korean_keyword_no_boundary(self):
        """한국어/긴 키워드는 word boundary 없이 부분 매칭"""
        client = self._make_client()

        detected = client._detect_keywords("연준의 금리 인하 기대감이 높아지고 있다")
        categories = [d[1] for d in detected]
        assert "fed" in categories


# ==============================================================================
# 복합 키워드 매칭 테스트
# ==============================================================================

class TestCompoundKeywords:
    """복합 키워드 기반 감지 테스트"""

    def _make_client(self):
        with patch("shared.macro_data.clients.political_news_client.get_rate_limiter"), \
             patch("shared.macro_data.clients.political_news_client.get_macro_cache"):
            from shared.macro_data.clients.political_news_client import PoliticalNewsClient
            return PoliticalNewsClient()

    def test_military_conflict_matches_geopolitical(self):
        """'military conflict'는 geopolitical로 감지"""
        client = self._make_client()
        detected = client._detect_keywords("Military conflict escalates in region")
        categories = [d[1] for d in detected]
        assert "geopolitical" in categories

    def test_standalone_war_not_detected(self):
        """단독 'war'는 더 이상 geopolitical로 감지되지 않음"""
        client = self._make_client()
        detected = client._detect_keywords("The war memorial was visited")
        categories = [d[1] for d in detected]
        assert "geopolitical" not in categories

    def test_standalone_recession_not_detected(self):
        """단독 'recession'은 crisis로 감지되지 않음"""
        client = self._make_client()
        detected = client._detect_keywords("recession fears are overstated")
        categories = [d[1] for d in detected]
        assert "crisis" not in categories

    def test_recession_warning_detected(self):
        """'recession warning'은 crisis로 감지됨"""
        client = self._make_client()
        detected = client._detect_keywords("recession warning from major bank")
        categories = [d[1] for d in detected]
        assert "crisis" in categories

    def test_market_crash_detected(self):
        """'market crash'는 crisis로 감지됨"""
        client = self._make_client()
        detected = client._detect_keywords("market crash fears grow")
        categories = [d[1] for d in detected]
        assert "crisis" in categories

    def test_missile_launch_detected(self):
        """'missile launch'는 geopolitical로 감지됨"""
        client = self._make_client()
        detected = client._detect_keywords("North Korea missile launch detected")
        categories = [d[1] for d in detected]
        assert "geopolitical" in categories


# ==============================================================================
# us_trade_policy 카테고리 테스트
# ==============================================================================

class TestUsTradePolicy:
    """us_trade_policy (신규 카테고리) 테스트"""

    def _make_client(self):
        with patch("shared.macro_data.clients.political_news_client.get_rate_limiter"), \
             patch("shared.macro_data.clients.political_news_client.get_macro_cache"):
            from shared.macro_data.clients.political_news_client import PoliticalNewsClient
            return PoliticalNewsClient()

    def test_trump_tariff_critical(self):
        """'trump tariff'는 us_trade_policy (critical)로 감지"""
        client = self._make_client()
        detected = client._detect_keywords("Trump tariff on Korean chips announced")
        us_trade = [d for d in detected if d[1] == "us_trade_policy"]
        assert len(us_trade) > 0
        assert us_trade[0][2] == "critical"

    def test_section_301_detected(self):
        """'section 301'는 us_trade_policy로 감지"""
        client = self._make_client()
        detected = client._detect_keywords("Section 301 investigation launched")
        categories = [d[1] for d in detected]
        assert "us_trade_policy" in categories

    def test_chips_act_detected(self):
        """'chips act'는 us_trade_policy로 감지"""
        client = self._make_client()
        detected = client._detect_keywords("CHIPS Act subsidies allocated")
        categories = [d[1] for d in detected]
        assert "us_trade_policy" in categories

    def test_korea_tariff_detected(self):
        """'korea tariff'는 us_trade_policy로 감지"""
        client = self._make_client()
        detected = client._detect_keywords("Korea tariff exemption considered")
        categories = [d[1] for d in detected]
        assert "us_trade_policy" in categories
        # impact_direction: exemption → bullish
        impacts = [d[3] for d in detected if d[1] == "us_trade_policy"]
        assert "bullish" in impacts


# ==============================================================================
# us_politics severity 변경 테스트
# ==============================================================================

class TestUsPoliticsSeverity:
    """us_politics 카테고리 severity 변경 테스트"""

    def _make_client(self):
        with patch("shared.macro_data.clients.political_news_client.get_rate_limiter"), \
             patch("shared.macro_data.clients.political_news_client.get_macro_cache"):
            from shared.macro_data.clients.political_news_client import PoliticalNewsClient
            return PoliticalNewsClient()

    def test_us_politics_severity_is_medium(self):
        """us_politics severity가 medium으로 변경됨"""
        client = self._make_client()
        assert client.KEYWORD_CONFIG["us_politics"]["severity"] == "medium"

    def test_trump_standalone_not_in_us_politics(self):
        """'trump' 단독 키워드는 us_politics에서 제거됨"""
        client = self._make_client()
        us_politics_kws = [kw.lower() for kw in client.KEYWORD_CONFIG["us_politics"]["keywords"]]
        assert "trump" not in us_politics_kws
        assert "biden" not in us_politics_kws

    def test_white_house_still_matches(self):
        """'white house'는 여전히 us_politics로 감지"""
        client = self._make_client()
        detected = client._detect_keywords("White House announces new policy")
        categories = [d[1] for d in detected]
        assert "us_politics" in categories


# ==============================================================================
# impact_direction_hints 테스트
# ==============================================================================

class TestImpactDirectionHints:
    """impact_direction_hints 정확성 테스트"""

    def _make_client(self):
        with patch("shared.macro_data.clients.political_news_client.get_rate_limiter"), \
             patch("shared.macro_data.clients.political_news_client.get_macro_cache"):
            from shared.macro_data.clients.political_news_client import PoliticalNewsClient
            return PoliticalNewsClient()

    def test_peace_bullish_in_geopolitical(self):
        """geopolitical에서 'peace'는 bullish"""
        client = self._make_client()
        detected = client._detect_keywords("peace deal reached in military conflict zone")
        geo = [d for d in detected if d[1] == "geopolitical"]
        assert len(geo) > 0
        assert geo[0][3] == "bullish"

    def test_rate_cut_bullish(self):
        """fed에서 'rate cut'는 bullish"""
        client = self._make_client()
        detected = client._detect_keywords("Federal Reserve signals rate cut")
        fed = [d for d in detected if d[1] == "fed"]
        assert len(fed) > 0
        assert any(d[3] == "bullish" for d in fed)
