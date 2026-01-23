---
description: 손실 종목 정리 후 특정 종목 집중 매수
---

# /rebalance_to [종목코드 또는 종목명]

손실 중인 종목을 시장가 매도하고, 지정한 종목에 집중 매수하는 리밸런싱 워크플로우입니다.

## 사전 작업

1. **Target Stock 확인**:
   - 사용자가 종목명(예: "현대자동차")을 제공하면 6자리 코드로 변환 (예: "005380")
   - 종목이 지정되지 않으면 사용자에게 물어보기

## 실행

// turbo
```bash
cd /home/youngs75/projects/my-prime-jennie
source .venv/bin/activate

# Dry Run 먼저 실행 (권장)
python scripts/ops_rebalance.py --target [CODE] --mode loss-cut --dry-run

# 실제 실행
python scripts/ops_rebalance.py --target [CODE] --mode loss-cut
```

## 옵션

| 인자 | 설명 |
|------|------|
| `--target` | 매수할 종목 코드 (필수) |
| `--mode` | `loss-cut` (손실만, 기본) / `all` (전량) |
| `--dry-run` | 시뮬레이션 모드 |

## DB 동기화

거래 실행 시 자동으로 다음 테이블이 업데이트됩니다:
- **TRADELOG**: `strategy_signal = 'REBALANCE_TO'`
- **ACTIVE_PORTFOLIO**: 포트폴리오 수량 업데이트
