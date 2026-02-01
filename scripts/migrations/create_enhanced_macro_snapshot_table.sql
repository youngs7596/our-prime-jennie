-- Create ENHANCED_MACRO_SNAPSHOT table for Enhanced Macro Insight system
-- 글로벌 매크로 데이터 스냅샷 저장용 테이블

CREATE TABLE IF NOT EXISTS ENHANCED_MACRO_SNAPSHOT (
    ID INT AUTO_INCREMENT PRIMARY KEY,
    SNAPSHOT_DATE DATE NOT NULL,
    SNAPSHOT_TIME DATETIME NOT NULL,

    -- US Indicators
    FED_RATE DECIMAL(5,2) COMMENT 'Federal Funds Rate (%)',
    US_CPI_YOY DECIMAL(5,2) COMMENT 'US CPI YoY (%)',
    US_PCE_YOY DECIMAL(5,2) COMMENT 'US PCE YoY (%)',
    TREASURY_2Y DECIMAL(5,3) COMMENT '2Y Treasury Yield (%)',
    TREASURY_10Y DECIMAL(5,3) COMMENT '10Y Treasury Yield (%)',
    TREASURY_SPREAD DECIMAL(5,3) COMMENT '10Y-2Y Spread (%)',
    US_UNEMPLOYMENT DECIMAL(5,2) COMMENT 'US Unemployment Rate (%)',
    US_PMI DECIMAL(5,2) COMMENT 'US Manufacturing PMI',

    -- Volatility
    VIX DECIMAL(6,2) COMMENT 'VIX Index',
    VIX_REGIME VARCHAR(20) COMMENT 'VIX Regime: low_vol, normal, elevated, crisis',

    -- Currency
    DXY_INDEX DECIMAL(6,2) COMMENT 'Dollar Index',
    USD_KRW DECIMAL(8,2) COMMENT 'USD/KRW Exchange Rate',
    USD_JPY DECIMAL(8,4) COMMENT 'USD/JPY Exchange Rate',
    USD_CNY DECIMAL(8,4) COMMENT 'USD/CNY Exchange Rate',

    -- Korea Indicators
    BOK_RATE DECIMAL(5,2) COMMENT 'BOK Base Rate (%)',
    KOREA_CPI_YOY DECIMAL(5,2) COMMENT 'Korea CPI YoY (%)',
    KOSPI_INDEX DECIMAL(8,2) COMMENT 'KOSPI Index',
    KOSDAQ_INDEX DECIMAL(8,2) COMMENT 'KOSDAQ Index',
    KOSPI_CHANGE_PCT DECIMAL(6,2) COMMENT 'KOSPI Daily Change (%)',
    KOSDAQ_CHANGE_PCT DECIMAL(6,2) COMMENT 'KOSDAQ Daily Change (%)',

    -- Calculated Fields
    RATE_DIFFERENTIAL DECIMAL(5,2) COMMENT 'Fed Rate - BOK Rate (%)',

    -- Sentiment
    GLOBAL_NEWS_SENTIMENT DECIMAL(4,3) COMMENT 'Global News Sentiment (-1.0 to 1.0)',
    KOREA_NEWS_SENTIMENT DECIMAL(4,3) COMMENT 'Korea News Sentiment (-1.0 to 1.0)',

    -- Metadata (JSON)
    DATA_SOURCES JSON COMMENT 'List of data sources used',
    MISSING_INDICATORS JSON COMMENT 'List of missing indicators',
    STALE_INDICATORS JSON COMMENT 'List of stale indicators (>24h)',
    VALIDATION_ERRORS JSON COMMENT 'Validation errors and warnings',
    DATA_FRESHNESS DECIMAL(3,2) COMMENT 'Overall data freshness (0.0-1.0)',
    COMPLETENESS_SCORE DECIMAL(3,2) COMMENT 'Data completeness score (0.0-1.0)',

    -- Timestamps
    CREATED_AT DATETIME DEFAULT CURRENT_TIMESTAMP,
    UPDATED_AT DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Constraints
    UNIQUE KEY UK_SNAPSHOT_DATE (SNAPSHOT_DATE),
    INDEX IDX_SNAPSHOT_TIME (SNAPSHOT_TIME),
    INDEX IDX_VIX_REGIME (VIX_REGIME),
    INDEX IDX_CREATED_AT (CREATED_AT)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Enhanced Macro Insight snapshot data from multiple global sources';


-- Add columns to existing DAILY_MACRO_INSIGHT table
-- (Only run if columns don't exist)

ALTER TABLE DAILY_MACRO_INSIGHT
    ADD COLUMN IF NOT EXISTS GLOBAL_SNAPSHOT JSON COMMENT 'GlobalMacroSnapshot data',
    ADD COLUMN IF NOT EXISTS DATA_SOURCES_USED JSON COMMENT 'List of data sources used',
    ADD COLUMN IF NOT EXISTS DATA_CITATIONS JSON COMMENT '3현자 요구: 근거 데이터 인용',
    ADD COLUMN IF NOT EXISTS VIX_REGIME VARCHAR(20) COMMENT 'VIX Regime hint',
    ADD COLUMN IF NOT EXISTS RATE_DIFFERENTIAL DECIMAL(5,2) COMMENT 'Fed Rate - BOK Rate (%)';
