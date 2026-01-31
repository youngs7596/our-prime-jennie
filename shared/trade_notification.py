# shared/trade_notification.py
# 거래 알림 통합 모듈
# buy-executor, sell-executor에서 공통으로 사용

import os
import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def format_buy_notification(
    stock_code: str,
    stock_name: str,
    price: float,
    quantity: int,
    signal_type: str,
    llm_score: float,
    trade_tier: str = "TIER1",
    is_super_prime: bool = False,
    tier2_conditions: Optional[list] = None,
    dry_run: bool = False,
    trading_mode: str = "REAL"
) -> str:
    """
    매수 체결 알림 메시지 포맷

    Args:
        stock_code: 종목 코드
        stock_name: 종목명
        price: 매수가
        quantity: 수량
        signal_type: 매수 신호 유형
        llm_score: LLM 점수
        trade_tier: TIER1, TIER2, RECON
        is_super_prime: Super Prime 여부
        tier2_conditions: TIER2 충족 조건 목록
        dry_run: Dry Run 모드 여부
        trading_mode: REAL 또는 MOCK

    Returns:
        포맷된 텔레그램 메시지 문자열
    """
    total_amount = quantity * price

    # 모드 표시
    mode_indicator = ""
    if trading_mode == "MOCK":
        mode_indicator = "[MOCK] "
    if dry_run:
        mode_indicator += "[DRY RUN] "

    # 승인 상태
    if trade_tier == "TIER1":
        approval_status = "TIER1 (Judge 통과)"
    elif trade_tier == "RECON":
        approval_status = "RECON (정찰병: 소액 진입)"
    else:
        approval_status = "TIER2 (Judge 미통과, 기술적 신호)"

    # Tier2 조건 표시
    tier2_extra = ""
    if trade_tier != "TIER1" and tier2_conditions:
        tier2_extra = f"\nTier2 조건: {', '.join(tier2_conditions[:4])}"

    # 헤더 태그
    header_tag = "매수 체결"
    if is_super_prime:
        header_tag = "[긴급/강력매수] SUPER PRIME 체결"

    message = f"""{mode_indicator}*{header_tag}*

*종목*: {stock_name} ({stock_code})
*가격*: {price:,}원
*수량*: {quantity}주
*총액*: {total_amount:,}원
*신호*: {signal_type}
*LLM 점수*: {llm_score:.1f}점
*승인*: {approval_status}{tier2_extra}"""

    return message


def format_sell_notification(
    stock_code: str,
    stock_name: str,
    sell_price: float,
    buy_price: float,
    quantity: int,
    profit_pct: float,
    profit_amount: float,
    sell_reason: str,
    holding_days: int = 0,
    dry_run: bool = False,
    trading_mode: str = "REAL"
) -> str:
    """
    매도 체결 알림 메시지 포맷

    Args:
        stock_code: 종목 코드
        stock_name: 종목명
        sell_price: 매도가
        buy_price: 매수가
        quantity: 수량
        profit_pct: 수익률 (%)
        profit_amount: 수익금
        sell_reason: 매도 사유
        holding_days: 보유 일수
        dry_run: Dry Run 모드 여부
        trading_mode: REAL 또는 MOCK

    Returns:
        포맷된 텔레그램 메시지 문자열
    """
    # 모드 표시
    mode_indicator = ""
    if trading_mode == "MOCK":
        mode_indicator = "[MOCK] "
    if dry_run:
        mode_indicator += "[DRY RUN] "

    # 수익/손실 이모지
    profit_emoji = "+" if profit_pct > 0 else ""

    message = f"""{mode_indicator}*매도 체결*

*종목*: {stock_name} ({stock_code})
*매도가*: {sell_price:,}원
*매수가*: {buy_price:,}원
*수량*: {quantity}주

*수익금*: {profit_emoji}{profit_amount:,.0f}원
*수익률*: {profit_emoji}{profit_pct:.2f}%
*사유*: {sell_reason}
*보유일*: {holding_days}일"""

    return message


def send_trade_notification(
    telegram_bot,
    message: str,
    parse_mode: str = "Markdown"
) -> bool:
    """
    거래 알림 전송

    Args:
        telegram_bot: TelegramBot 인스턴스
        message: 전송할 메시지
        parse_mode: 파싱 모드 (Markdown, HTML 등)

    Returns:
        전송 성공 여부
    """
    if not telegram_bot:
        logger.warning("[Notification] 텔레그램 봇이 설정되지 않았습니다.")
        return False

    try:
        telegram_bot.send_message(message)
        logger.info("[Notification] 텔레그램 알림 발송 완료")
        return True
    except Exception as e:
        logger.warning(f"[Notification] 텔레그램 알림 발송 실패: {e}")
        return False


def send_buy_notification(
    telegram_bot,
    stock_code: str,
    stock_name: str,
    price: float,
    quantity: int,
    signal_type: str,
    llm_score: float,
    **kwargs
) -> bool:
    """
    매수 체결 알림 전송 (편의 함수)

    Args:
        telegram_bot: TelegramBot 인스턴스
        stock_code: 종목 코드
        stock_name: 종목명
        price: 매수가
        quantity: 수량
        signal_type: 매수 신호 유형
        llm_score: LLM 점수
        **kwargs: format_buy_notification의 추가 인자

    Returns:
        전송 성공 여부
    """
    # 환경변수에서 기본값 조회
    trading_mode = kwargs.pop("trading_mode", os.getenv("TRADING_MODE", "REAL"))
    dry_run = kwargs.pop("dry_run", os.getenv("DRY_RUN", "true").lower() == "true")

    message = format_buy_notification(
        stock_code=stock_code,
        stock_name=stock_name,
        price=price,
        quantity=quantity,
        signal_type=signal_type,
        llm_score=llm_score,
        trading_mode=trading_mode,
        dry_run=dry_run,
        **kwargs
    )

    return send_trade_notification(telegram_bot, message)


def send_sell_notification(
    telegram_bot,
    stock_code: str,
    stock_name: str,
    sell_price: float,
    buy_price: float,
    quantity: int,
    profit_pct: float,
    profit_amount: float,
    sell_reason: str,
    **kwargs
) -> bool:
    """
    매도 체결 알림 전송 (편의 함수)

    Args:
        telegram_bot: TelegramBot 인스턴스
        stock_code: 종목 코드
        stock_name: 종목명
        sell_price: 매도가
        buy_price: 매수가
        quantity: 수량
        profit_pct: 수익률 (%)
        profit_amount: 수익금
        sell_reason: 매도 사유
        **kwargs: format_sell_notification의 추가 인자

    Returns:
        전송 성공 여부
    """
    # 환경변수에서 기본값 조회
    trading_mode = kwargs.pop("trading_mode", os.getenv("TRADING_MODE", "REAL"))
    dry_run = kwargs.pop("dry_run", os.getenv("DRY_RUN", "true").lower() == "true")

    message = format_sell_notification(
        stock_code=stock_code,
        stock_name=stock_name,
        sell_price=sell_price,
        buy_price=buy_price,
        quantity=quantity,
        profit_pct=profit_pct,
        profit_amount=profit_amount,
        sell_reason=sell_reason,
        trading_mode=trading_mode,
        dry_run=dry_run,
        **kwargs
    )

    return send_trade_notification(telegram_bot, message)
