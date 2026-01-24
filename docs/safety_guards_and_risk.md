# Risk Management & Safety Guards (Junho's System)

> **Version**: v1.2.0  
> **Applicable From**: 2026-01-24  
> **Core Concept**: "Maximize Aggression, Minimize Ruin"

Junho(전략가)의 피드백을 반영하여, 개별 트레이드의 공격성(Risk 1.0%)은 유지하되 포트폴리오 전체의 파산 위험을 원천 차단하는 **이중 방어 시스템**입니다.

---

## 🛡️ 1. Portfolio Heat Shield (계좌 보호)

계좌 전체가 노출된 총 위험(Total 1R Risk)을 제한하여, 시장 폭락 시에도 생존을 보장합니다.

- **Portfolio Heat Limit**: **5.0%** (Max)
  - 의미: 보유 중인 모든 종목이 동시에 손절가(-1R)에 도달해도, 총 계좌 손실은 -5%로 제한됩니다.
  - 동작: 신규 진입 시 `(현재 Heat + 신규 Trade Risk) > 5.0%`이면 **진입을 원천 차단**합니다.
  - 파일: `shared/position_sizing.py` (`check_portfolio_heat`)

---

## ⚖️ 2. Dynamic Position Sizing (비중 관리)

트레이드 확신도(LLM Score)와 시장 상황에 따라 비중을 동적으로 조절합니다.

| 구분 | 비중 상한 | 조건 |
|------|-----------|------|
| **기본 (Default)** | **12%** | 일반적인 진입 신호 |
| **A+ Setup** | **18%** | LLM Score **80점 이상** (고확신) |
| **Sector Penalty** | **0.7x Risk** | 이미 동일 섹터 종목 보유 시 리스크 감산 |

- **Sector Risk Penalty**: 같은 섹터 종목을 추가로 매수할 때, 리스크를 0.7배로 줄여 섹터 쏠림(Correlation Risk)을 방지합니다.

---

## 🔒 3. Smart Profit Lock (익절 잠금)

ATR(변동성)을 기반으로 "먹은 수익을 토해내지 않는" 동적 익절 시스템입니다.

### ATR-Based Dynamic Trigger
트리거(발동점)가 고정값이 아닌 **ATR(평균 진폭)**에 따라 변동됩니다.

- **Level 1 (Break-Even):**
  - **Trigger**: `ATR * 1.5` (단, **1.5% ~ 3.0%** 범위로 제한/Clamp)
  - **Action**: 수익률이 이 구간에 도달했다가 하락 시, **+0.2% (수수료/세금 커버)**에서 즉시 청산.
  - **목적**: "수익 → 손실 전환 방지" (No Free Ride)

- **Level 2 (Secure Gain):**
  - **Trigger**: `ATR * 2.5` (단, **3.0% ~ 5.0%** 범위로 제한/Clamp)
  - **Action**: 수익률이 이 구간 도달 시, **+1.0%** 이익 보장선 설정.
  - **목적**: "변동성이 큰 종목에서 확실한 1% 챙기기"

---

## 🚦 4. Execution Filters (진입 필터)

단순 가격/이평선 조건 외에, 시장의 과열/노이즈를 걸러내는 추가 필터입니다.

### Conditional VWAP Block (조건부 차단)
무조건적인 VWAP 이격 차단 대신, **"위험 신호가 중첩될 때만"** 차단하여 기회 비용을 줄입니다.

- **차단 조건 (AND 조건)**:
  1. 거래량이 평소의 **2배 이상** 폭증 (`Volume Ratio > 2.0`)
  2. 현재가가 VWAP(거래량가중평균가)보다 **2% 이상** 높음
- **의미**: "뉴스/재료로 인해 이미 가격이 급등해버린(추격 매수)" 상태를 정밀 타격하여 차단.

---

## 📉 5. Risk Parameter Summary

| Parameter | Value | Description |
|-----------|-------|-------------|
| **Risk Per Trade** | **1.0%** | 종목당 1R 손실 허용폭 (Account Equity 기준) |
| **Take Profit** | Trailing | 고점 대비 -3.5% 하락 시 청산 (Min 3% 수익 후) |
| **Stop Loss** | **-6.0%** / ATR 2.0 | 고정 손절 -6% 또는 ATR 2배 중 더 타이트한 값 |
| **No-Trade Window** | 09:00~09:30 | 장 초반 높은 변동성 구간 진입 금지 |
