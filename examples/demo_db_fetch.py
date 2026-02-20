"""
Quick fetch examples for tw_stock.

Prerequisite:
- Set TW_STOCK_DB_PATH to your tw_stock.db absolute path.
"""

from tw_stock import db_max_date, fetch_quotes, stock_info


def demo_stock_info(stock_id: str) -> None:
    info = stock_info(stock_id)
    if info is None:
        print(f"{stock_id}: not found")
        return
    print(f"[{stock_id}] {info.title}")
    print(f"  market range: {info.mindate} ~ {info.maxdate}")


def demo_recent_quotes(stock_id: str, limit: int = 5) -> None:
    rows = list(reversed(fetch_quotes(stock_id, limit=limit, descending=True)))
    print(f"\nRecent {len(rows)} rows for {stock_id}:")
    for row in rows[-limit:]:
        date, opening, high, low, close, volume, turnover, delta, tickcount = row
        print(
            f"  {date} O={opening} H={high} L={low} C={close} "
            f"V={volume} T={turnover} d={delta} ticks={tickcount}"
        )


if __name__ == "__main__":
    print(f"DB max date: {db_max_date()}")
    demo_stock_info("2330")
    demo_stock_info("0050")
    demo_recent_quotes("2330", limit=5)
