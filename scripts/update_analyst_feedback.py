#!/usr/bin/env python3
"""
scripts/update_analyst_feedback.py
==================================
AI Analyst의 성과를 분석하고, LLM을 통해 '전략적 교훈(Strategic Feedback)'을 도출하여
Redis에 저장하는 스크립트입니다. (Scout Job이 이를 참조하여 의사결정을 개선함)
"""

import sys
import os
import logging
import redis
import pandas as pd
from datetime import datetime, timezone

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db.connection import session_scope, ensure_engine_initialized
from shared.analysis.ai_performance import analyze_performance
from shared.llm import JennieBrain
import shared.auth as auth

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AnalystFeedback")

def get_redis_connection():
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", 6379))
    redis_password = os.getenv("REDIS_PASSWORD", None)
    return redis.Redis(host=redis_host, port=redis_port, password=redis_password, db=0)

def format_report_for_llm(stats, recent_decisions):
    """
    LLM에게 전달할 성과 보고서 텍스트 생성
    """
    report = []
    report.append(f"Analyzing Period: {stats['period_start']} ~ {stats['period_end']}")
    report.append(f"Total Decisions: {stats['total_decisions']}")
    report.append(f"Win Rate: {stats['win_rate']:.1f}%")
    report.append(f"Avg Return (T+5): {stats['avg_return_t5']:.2f}%")
    report.append(f"Profitable Count: {stats['profitable_count']}")
    
    report.append("\n[Performance by Market Regime]")
    for regime, metrics in stats['by_regime'].items():
        report.append(f"- {regime}: Win Rate {metrics['win_rate']:.1f}%, Avg Return {metrics['avg_return']:.2f}% ({metrics['count']} trades)")
        
    report.append("\n[Performance by Hunter Score]")
    for score_range, metrics in stats['by_score'].items():
        report.append(f"- Score {score_range}: Win Rate {metrics['win_rate']:.1f}%, Avg Return {metrics['avg_return']:.2f}%")
        
    report.append("\n[Recent 10 Decisions]")
    for d in recent_decisions[:10]:
        pnl = d.get('return_t5')
        pnl_str = f"{pnl:.2f}%" if pnl is not None else "N/A"
        report.append(f"- {d['stock_name']}({d['stock_code']}): Hunter {d['hunter_score']}, Hybrid {d['hybrid_score']} -> T+5 Return: {pnl_str} (Regime: {d['market_regime']})")

    return "\n".join(report)

def main():
    logger.info("🚀 Starting Analyst Feedback Update...")
    
    # 1. Initialize DB & Brain
    ensure_engine_initialized()
    brain = JennieBrain(project_id="local")
    
    # 2. Analyze Performance
    logger.info("📊 Analyzing AI Performance...")
    with session_scope() as session:
        df = analyze_performance(session)
    
    # 3. Analyze Shadow Radar (Missed Opportunities)
    # Run this BEFORE early exit check, because in Bear Market we might have 0 trades but valid Shadow Radar data.
    from shared.analysis.shadow_radar import analyze_shadow_performance

    logger.info("📡 Analyzing Shadow Radar (Missed Opportunities)...")
    with session_scope() as session:
        shadow_result = analyze_shadow_performance(session, lookback_days=5, regret_threshold=0.04) # 4% threshold
    
    # Check if we have ANYTHING to report
    # Minimum 20 decisions required for statistical significance (matches 20-day rolling window)
    MIN_DECISIONS_FOR_ANALYSIS = 20
    has_trading_data = not df.empty and len(df) >= MIN_DECISIONS_FOR_ANALYSIS
    has_shadow_data = shadow_result['regret_count'] > 0 or shadow_result['good_rejection_count'] > 0
    
    if not has_trading_data and not has_shadow_data:
        logger.warning(f"⚠️ 데이터 부족: 매매 기록도 없고({len(df)}건), Shadow Radar 데이터도 없습니다. 피드백 생성을 건너뜁니다.")
        return

    # Calculate Stats from DataFrame (if available)
    stats = {
        'total_decisions': len(df),
        'period_start': df['timestamp'].min().date() if not df.empty else 'N/A',
        'period_end': df['timestamp'].max().date() if not df.empty else 'N/A',
        'win_rate': 0.0,
        'avg_return_t5': 0.0,
        'profitable_count': 0,
        'by_regime': {},
        'by_score': {}
    }

    if has_trading_data:
        if 'return_5d' in df.columns:
            valid_5d = df.dropna(subset=['return_5d'])
            if not valid_5d.empty:
                stats['win_rate'] = (valid_5d['return_5d'] > 0).mean() * 100
                stats['avg_return_t5'] = valid_5d['return_5d'].mean() * 100
                stats['profitable_count'] = (valid_5d['return_5d'] > 0).sum()

            # By Regime
            if 'market_regime' in df.columns:
                for regime, group in df.groupby('market_regime'):
                    valid_group = group.dropna(subset=['return_5d'])
                    if not valid_group.empty:
                        stats['by_regime'][regime] = {
                            'win_rate': (valid_group['return_5d'] > 0).mean() * 100,
                            'avg_return': valid_group['return_5d'].mean() * 100,
                            'count': len(valid_group)
                        }

            # By Score
            bins = [0, 40, 60, 80, 100]
            labels = ['F', 'C/D', 'B/A', 'S']
            df['score_bucket'] = pd.cut(df['hunter_score'], bins=bins, labels=labels)
            for bucket, group in df.groupby('score_bucket', observed=True):
                valid_group = group.dropna(subset=['return_5d'])
                if not valid_group.empty:
                    stats['by_score'][bucket] = {
                        'win_rate': (valid_group['return_5d'] > 0).mean() * 100,
                        'avg_return': valid_group['return_5d'].mean() * 100
                    }

    recent_decisions = df.sort_values('timestamp', ascending=False).head(10).to_dict('records') if not df.empty else []

    # 4. Generate Feedback via LLM
    report_text = format_report_for_llm(stats, recent_decisions)
    
    # Append Shadow Radar insights
    if shadow_result['regret_count'] > 0:
        report_text += "\n\n[Shadow Radar - Missed Opportunities (Regret Analysis)]"
        report_text += f"\nWarning: You rejected {shadow_result['regret_count']} stocks that subsequently rose >4%."
        for item in shadow_result['regrets'][:5]: # Top 5 regrets
            report_text += f"\n- {item['name']}({item['code']}): Rejected on {item['rejected_at']} (Reason: {item['reason']}) -> Rose +{item['max_return']:.1f}%"
    
    if shadow_result['good_rejection_count'] > 0:
        report_text += "\n\n[Shadow Radar - Validations]"
        report_text += f"\nGood Job: You correctly rejected {shadow_result['good_rejection_count']} stocks that subsequently fell."
        
    logger.info(f"📜 Performance Report Generated ({len(report_text)} chars)")
    
    logger.info("🧠 Generating Strategic Feedback (Thinking Tier)...")
    feedback = brain.generate_strategic_feedback(report_text)
    
    if not feedback:
        logger.error("❌ Feedback generation failed.")
        sys.exit(1)
        
    logger.info("\n" + "="*40)
    logger.info(" [Generated Feedback] ")
    logger.info(feedback)
    logger.info("="*40 + "\n")
    
    # 4. Save to Redis
    try:
        r = get_redis_connection()
        r.set("analyst:feedback:summary", feedback)
        
        # 메타데이터 저장 (생성 시간)
        r.set("analyst:feedback:updated_at", datetime.now(timezone.utc).isoformat())
        
        logger.info("✅ Feedback saved to Redis (key: analyst:feedback:summary)")
    except Exception as e:
        logger.error(f"❌ Redis save failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
