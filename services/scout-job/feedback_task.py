
import logging
import os
import sys
import pandas as pd
from datetime import datetime, timezone
import redis

# Shared Modules
from shared.db.connection import session_scope, ensure_engine_initialized
from shared.analysis.ai_performance import analyze_performance
from shared.llm import JennieBrain
import shared.auth as auth

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
    for d in recent_decisions:
        pnl = d.get('return_5d')
        pnl_str = f"{pnl*100:.2f}%" if pnl is not None else "N/A"
        report.append(f"- {d['stock_name']}({d['stock_code']}): Hunter {d['hunter_score']} -> T+5 Return: {pnl_str} (Regime: {d['market_regime']})")

    return "\n".join(report)

def run_analyst_feedback_update():
    """
    Scout Job Worker에서 호출되는 메인 함수
    """
    logger.info("🚀 [Task] Analyst Feedback Update Started...")
    
    # 1. Initialize DB & Brain
    try:
        ensure_engine_initialized()
        brain = JennieBrain(project_id="local")
    except Exception as e:
        logger.error(f"❌ Initialization failed: {e}")
        return

    # 2. Analyze Performance
    logger.info("📊 Analyzing AI Performance...")
    try:
        with session_scope() as session:
            df = analyze_performance(session)
    except Exception as e:
        logger.error(f"❌ Performance analysis failed: {e}")
        return
    
    if df.empty:
        logger.warning("⚠️ 데이터가 너무 적어(또는 가격 데이터 부재) 피드백 생성을 건너뜁니다.")
        return

    # Calculate Stats from DataFrame
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

    recent_decisions = df.sort_values('timestamp', ascending=False).head(10).to_dict('records')

    if stats['total_decisions'] < 10:
        logger.warning(f"⚠️ 데이터가 너무 적어({stats['total_decisions']}개) 피드백 생성을 건너뜁니다.")
        return

    # 3. Generate Feedback via LLM
    report_text = format_report_for_llm(stats, recent_decisions)
    logger.info(f"📜 Performance Report Generated ({len(report_text)} chars)")
    
    logger.info("🧠 Generating Strategic Feedback (Thinking Tier)...")
    try:
        feedback = brain.generate_strategic_feedback(report_text)
    except Exception as e:
        logger.error(f"❌ LLM generation failed: {e}")
        return
    
    if not feedback:
        logger.error("❌ Feedback generation returned empty string.")
        return
        
    logger.info("\n" + "="*40)
    logger.info(" [Generated Feedback] ")
    logger.info(feedback)
    logger.info("="*40 + "\n")
    
    # 4. Save to Redis
    try:
        r = get_redis_connection()
        r.set("analyst:feedback:summary", feedback)
        r.set("analyst:feedback:updated_at", datetime.now(timezone.utc).isoformat())
        logger.info("✅ Feedback saved to Redis (key: analyst:feedback:summary)")
    except Exception as e:
        logger.error(f"❌ Redis save failed: {e}")
