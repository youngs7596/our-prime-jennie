#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
shared/macro_data/clients - 매크로 데이터 API 클라이언트
=======================================================

각 데이터 소스별 API 클라이언트를 제공합니다.
"""

from .base import MacroDataClient
from .finnhub_client import FinnhubClient
from .fred_client import FREDClient
from .bok_ecos_client import BOKECOSClient
from .pykrx_client import PyKRXClient
from .rss_news_client import RSSNewsClient
from .political_news_client import PoliticalNewsClient

__all__ = [
    "MacroDataClient",
    "FinnhubClient",
    "FREDClient",
    "BOKECOSClient",
    "PyKRXClient",
    "RSSNewsClient",
    "PoliticalNewsClient",
]
