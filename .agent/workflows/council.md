---
description: Ask the Prime Council (Jennie, Minji, Junho) for advice on code or strategy
---

1. [internal] Get the current active file path
2. Run the council query script
   ```bash
   # $1 is the optional query from the user, defaults to "Review this code"
   # $FILE represents the current active file
   python scripts/ask_prime_council.py --query "${1:-Review this code}" --file "$FILE"
   ```
3. Open the generated report
   ```bash
   # Find the latest report and open it
   LATEST_REPORT=$(ls -t .ai/reviews/council_report_*.md | head -n 1)
   echo "Opening report: $LATEST_REPORT"
   code "$LATEST_REPORT"
   ```
