-- Migration: Add political risk fields to DAILY_MACRO_INSIGHT
-- Date: 2026-02-02
-- Description: Council이 정치/지정학적 리스크를 분석하여 트레이딩 권고에 반영

-- 정치 리스크 레벨 컬럼 추가 (low, medium, high, critical)
ALTER TABLE DAILY_MACRO_INSIGHT
ADD COLUMN IF NOT EXISTS POLITICAL_RISK_LEVEL VARCHAR(20) DEFAULT 'low';

-- 정치 리스크 요약 컬럼 추가
ALTER TABLE DAILY_MACRO_INSIGHT
ADD COLUMN IF NOT EXISTS POLITICAL_RISK_SUMMARY TEXT;

-- 인덱스 추가 (리스크 레벨로 조회 시)
CREATE INDEX IF NOT EXISTS idx_macro_insight_political_risk
ON DAILY_MACRO_INSIGHT (POLITICAL_RISK_LEVEL);
