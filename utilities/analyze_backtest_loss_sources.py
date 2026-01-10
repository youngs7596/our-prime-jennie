#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyze loss exits and map them to LLM decision sources.
Usage:
  python utilities/analyze_backtest_loss_sources.py --trades logs/backtest_scout_e2e_trades_YYYYMMDDHHMMSS.csv
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze loss exits vs LLM decision sources")
    parser.add_argument("--trades", required=True, help="Path to backtest trades CSV")
    parser.add_argument("--db-host", help="Override MARIADB_HOST")
    parser.add_argument("--db-port", help="Override MARIADB_PORT")
    parser.add_argument("--db-user", help="Override MARIADB_USER")
    parser.add_argument("--db-name", help="Override MARIADB_DBNAME")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.db_host:
        os.environ["MARIADB_HOST"] = args.db_host
    if args.db_port:
        os.environ["MARIADB_PORT"] = args.db_port
    if args.db_user:
        os.environ["MARIADB_USER"] = args.db_user
    if args.db_name:
        os.environ["MARIADB_DBNAME"] = args.db_name

    from shared import database  # noqa: E402
    from utilities.backtest_scout_e2e import ScoutSimulator  # noqa: E402

    trades_path = Path(args.trades)
    if not trades_path.exists():
        raise SystemExit(f"Missing trades file: {trades_path}")

    df = pd.read_csv(trades_path)
    df["date"] = pd.to_datetime(df["date"])

    positions = {}
    records = []
    for _, row in df.iterrows():
        code = str(row["code"])
        qty = int(row["quantity"])
        price = float(row["price"])
        fee = float(row.get("fee", 0))
        ts = row["date"]
        if row["type"] == "BUY":
            pos = positions.get(code, {"qty": 0, "avg": 0.0, "first_date": ts})
            total_cost = pos["avg"] * pos["qty"] + price * qty + fee
            new_qty = pos["qty"] + qty
            avg = total_cost / new_qty if new_qty > 0 else 0.0
            positions[code] = {"qty": new_qty, "avg": avg, "first_date": pos.get("first_date", ts)}
        else:
            pos = positions.get(code)
            if not pos:
                continue
            sell_qty = min(qty, pos["qty"])
            proceeds = price * sell_qty - fee
            cost = pos["avg"] * sell_qty
            pnl = proceeds - cost
            pnl_pct = pnl / cost if cost else 0.0
            records.append(
                {
                    "code": code,
                    "buy_date": pos["first_date"].date(),
                    "sell_date": ts.date(),
                    "reason": row["reason"],
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                }
            )
            pos["qty"] -= sell_qty
            if pos["qty"] <= 0:
                positions.pop(code, None)
            else:
                positions[code] = pos

    sell_df = pd.DataFrame(records)
    if sell_df.empty:
        print("No sell records found.")
        return
    loss_df = sell_df[sell_df["reason"].isin(["FIXED_STOP", "ATR_STOP"])].copy()
    if loss_df.empty:
        print("No loss exits found (FIXED_STOP/ATR_STOP).")
        return

    all_buy_groups = sell_df.groupby("buy_date")["code"].apply(lambda s: sorted(set(s))).to_dict()
    loss_buy_groups = loss_df.groupby("buy_date")["code"].apply(lambda s: sorted(set(s))).to_dict()

    conn = database.get_db_connection()
    try:
        scout_sim = ScoutSimulator(
            connection=conn,
            price_cache={},
            stock_names={},
            news_cache={},
        )

        decision_rows = []
        for buy_date, codes in all_buy_groups.items():
            target_date = datetime.combine(buy_date, datetime.min.time())
            decisions = scout_sim.load_llm_decisions_for_date(target_date, codes)
            for code in codes:
                info = decisions.get(code)
                decision_rows.append(
                    {
                        "code": code,
                        "buy_date": buy_date,
                        "source": info["source"] if info else "FACTOR_SCORE",
                        "decision": info["llm_decision_type"] if info else "NO_DECISION",
                        "score": info["estimated_score"] if info else None,
                    }
                )
    finally:
        conn.close()

    decision_df = pd.DataFrame(decision_rows)
    merged_all = sell_df.merge(decision_df, on=["code", "buy_date"], how="left")
    merged_loss = loss_df.merge(decision_df, on=["code", "buy_date"], how="left")

    print(f"loss sells: {len(loss_df)}")
    if not merged_loss.empty:
        print("\nloss source counts:")
        print(merged_loss["source"].value_counts())
        print("\nloss source avg score:")
        print(merged_loss.groupby("source")["score"].mean().sort_values())
        print("\nloss decision counts:")
        print(merged_loss["decision"].value_counts())
        print("\nloss pnl pct mean by source:")
        print(merged_loss.groupby("source")["pnl_pct"].mean().sort_values())

    print("\n=== overall sell source stats ===")
    print("source counts:")
    print(merged_all["source"].value_counts())
    print("\nsource avg score:")
    print(merged_all.groupby("source")["score"].mean().sort_values())
    print("\nsource win rate:")
    print(merged_all.groupby("source")["pnl"].apply(lambda s: (s > 0).mean()).sort_values())
    print("\nsource avg pnl pct:")
    print(merged_all.groupby("source")["pnl_pct"].mean().sort_values())

    print("\n=== loss vs non-loss source share ===")
    loss_source_counts = merged_loss["source"].value_counts()
    all_source_counts = merged_all["source"].value_counts()
    loss_share = (loss_source_counts / all_source_counts).sort_values(ascending=False)
    print(loss_share)


if __name__ == "__main__":
    main()
