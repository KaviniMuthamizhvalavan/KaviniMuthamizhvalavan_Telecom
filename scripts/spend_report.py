"""Show the estimated Claude API spend recorded by the app and the evaluation scripts (no API call).

Run from the repo root:  python -m scripts.spend_report [--days 7]
Figures are estimates from list prices (src/services/llm_client.PRICES); the Anthropic Console is the bill.
"""
import argparse

from src.services.llm_client import SpendLedger
from src.utils.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    s = get_settings()
    path = s.artifacts_dir / "llm_spend.db"
    if not path.exists():
        print(f"no spend recorded yet ({path} does not exist)")
        return
    ledger = SpendLedger(path)
    rows = ledger.report(args.days)
    print(f"{'day (UTC)':12} {'model':20} {'calls':>6} {'est. USD':>9}")
    for day, model, calls, cost in rows:
        print(f"{day:12} {model:20} {calls:>6} {cost:>9.4f}")
    print(f"\ntoday: ${ledger.today():.4f} of the ${s.llm_daily_budget_usd:.2f} daily cap (LLM_DAILY_BUDGET_USD)")


if __name__ == "__main__":
    main()
