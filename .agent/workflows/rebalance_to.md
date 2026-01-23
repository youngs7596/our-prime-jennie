---
description: Sell losing positions and buy a TARGET stock. Usage: /rebalance_to [Stock Name]
---

1. **Identify Target Stock**:
   - The user will provide the target stock name as an argument (e.g., `/rebalance_to 삼성전자`).
   - If a name is provided, **RESOLVE** it to a standard 6-digit stock code (e.g., "삼성전자" -> "005930").
   - If no stock is specified, ASK the user to provide one.

2. **Execute Rebalance**:
   - Run the script with the resolved code.
   
```bash
python scripts/ops_rebalance.py --target [RESOLVED_CODE] --mode loss-cut
```
