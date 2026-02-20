import csv
import datetime
import decimal
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import lxml.html
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

DB_PATH_ENV = "TW_STOCK_DB_PATH"
QUOTE_EPOCH = datetime.date(2007, 4, 23)  # TWSE/OTC overlap coverage
TWSE_HISTORY_EPOCH = datetime.date(1999, 1, 1)

_TWSE_ID_RE = re.compile(r"^\d{4}[A-Z]?$")
_OTC_ID_RE = re.compile(r"^\d{4}$")
_DB_CONN: sqlite3.Connection | None = None

# Avoid sqlite3 default adapter deprecation warnings on Python 3.12+.
sqlite3.register_adapter(datetime.date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime.datetime, lambda dt: dt.isoformat(sep=" "))


@dataclass
class StockInfo:
    id: str
    name: str
    future: str | None
    mini_future: str | None
    mindate: str | None
    maxdate: str | None

    @property
    def title(self) -> str:
        if self.future:
            if self.mini_future:
                return f"{self.id} {self.name} ({self.future},{self.mini_future})"
            return f"{self.id} {self.name} ({self.future})"
        return f"{self.id} {self.name}"


def _require_db_path() -> Path:
    raw = os.getenv(DB_PATH_ENV)
    if not raw:
        raise RuntimeError(
            f"Environment variable {DB_PATH_ENV} is not set. "
            "Set it to your tw_stock.db absolute path before running this module."
        )
    db_path = Path(raw).expanduser()
    if not db_path.exists():
        raise FileNotFoundError(f"{DB_PATH_ENV} points to a missing file: {db_path}")
    return db_path


def get_db() -> sqlite3.Connection:
    global _DB_CONN
    if _DB_CONN is None:
        _DB_CONN = sqlite3.connect(_require_db_path())
    return _DB_CONN


def close_db() -> None:
    global _DB_CONN
    if _DB_CONN is not None:
        _DB_CONN.close()
        _DB_CONN = None


def to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    raise TypeError(f"Unsupported date value: {value!r}")


def date_str(value) -> str | None:
    d = to_date(value)
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def is_twse(stock_id: str | None):
    return stock_id and _TWSE_ID_RE.match(stock_id.strip().upper())


def is_otc(stock_id: str | None):
    return stock_id and _OTC_ID_RE.match(stock_id.strip())


def is_id(stock_id: str) -> bool:
    if len(stock_id) <= 0:
        return False
    if not re.match(r"^\d+[A-Z]?", stock_id):
        return False
    if len(stock_id) > 4 and stock_id.startswith("7"):
        return False
    if not stock_id.startswith("0"):
        return True
    return stock_id.startswith("00") or stock_id.startswith("01") or stock_id.startswith("02")


def clean(text: str) -> str:
    m = re.match(r'="([^"]*)"', text)
    if m:
        text = m.group(1)
    m = re.match(r"='([^']*)'", text)
    if m:
        text = m.group(1)
    return (
        text.replace(" ", "")
        .replace(",", "")
        .replace("\t", "")
        .replace("&nbsp;", "")
        .replace("\u2295", "")
        .replace("\u2299", "")
        .strip()
    )


def to_decimal(value: str) -> str:
    return str(decimal.Decimal(value))


def _http_get(url: str, timeout: int = 30) -> requests.Response:
    try:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response
    except requests.exceptions.SSLError:
        # Some TWSE cert chains may fail strict verification on specific Windows/Python builds.
        urllib3.disable_warnings(InsecureRequestWarning)
        response = requests.get(url, timeout=timeout, verify=False)
        response.raise_for_status()
        return response


def db_max_date():
    max_date, = get_db().execute(
        "SELECT MAX(maxdate) FROM stock WHERE ID != 'TWSE' AND ID != 'OTC'"
    ).fetchone()
    return to_date(max_date)


def _build_stock_where(begin_date=None, end_date=None, market=None):
    conditions = ["ID != 'TWSE'", "ID != 'OTC'"]
    params: list[str] = []

    begin_date = to_date(begin_date)
    end_date = to_date(end_date)

    if begin_date is not None:
        conditions.append("mindate <= ?")
        params.append(date_str(begin_date))
    if end_date is not None:
        conditions.append("maxdate >= ?")
        params.append(date_str(end_date))
    if market:
        market = market.upper()
        if market == "TPEX":
            market = "OTC"
        conditions.append("market = ?")
        params.append(market)

    return " AND ".join(conditions), tuple(params)


def count_stocks(begin_date=None, end_date=None, market=None) -> int:
    where_sql, params = _build_stock_where(begin_date, end_date, market)
    count, = get_db().execute(
        f"SELECT COUNT(*) FROM stock_future_view WHERE {where_sql}",
        params,
    ).fetchone()
    return count


def list_stocks(begin_date=None, end_date=None, market=None):
    where_sql, params = _build_stock_where(begin_date, end_date, market)
    sql = (
        "SELECT ID, name, future, mini_future, mindate, maxdate "
        f"FROM stock_future_view WHERE {where_sql} ORDER BY ID"
    )
    for row in get_db().execute(sql, params):
        yield StockInfo(*row)


def stock_info(stock_id: str) -> StockInfo | None:
    row = get_db().execute(
        "SELECT ID, name, future, mini_future, mindate, maxdate "
        "FROM stock_future_view WHERE ID = ?",
        (stock_id,),
    ).fetchone()
    if row is None:
        return None
    return StockInfo(*row)


def fetch_quotes(
    stock_id: str,
    begin_date=None,
    end_date=None,
    limit: int | None = None,
    descending: bool = False,
):
    begin_date = to_date(begin_date)
    end_date = to_date(end_date)

    conditions = ["ID = ?"]
    params: list[object] = [stock_id]
    if begin_date is not None:
        conditions.append("date >= ?")
        params.append(date_str(begin_date))
    if end_date is not None:
        conditions.append("date <= ?")
        params.append(date_str(end_date))

    order = "DESC" if descending else "ASC"
    sql = (
        "SELECT date, open, high, low, close, volume, turnover, delta, tickcount "
        f"FROM quote WHERE {' AND '.join(conditions)} ORDER BY date {order}"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return list(get_db().execute(sql, tuple(params)))


def _upsert_market_marker(market: str, date: datetime.date, count: int) -> None:
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO stock (ID, name, market, mindate, maxdate) VALUES (?, ?, ?, ?, ?)",
        (market, market, market, date, date),
    )
    db.execute("UPDATE stock SET maxdate = ? WHERE ID = ?", (date, market))
    db.execute(
        "INSERT OR REPLACE INTO quote (ID, date, volume) VALUES (?, ?, ?)",
        (market, date, count),
    )


def _safe_int(value: str) -> int | None:
    value = clean(value)
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_decimal(value: str) -> str | None:
    value = clean(value)
    if value in {"", "---", "--"}:
        return None
    try:
        return to_decimal(value)
    except decimal.InvalidOperation:
        return None


def update_daily_twse_quotes(date, force: bool = False) -> None:
    date = to_date(date)
    db = get_db()
    market = "TWSE"

    if db.execute("SELECT 1 FROM quote WHERE ID = ? AND date = ?", (market, date)).fetchone() and not force:
        return

    if force:
        db.execute(
            "DELETE FROM quote WHERE (ID IN (SELECT ID FROM stock WHERE market = ?) OR ID = ?) AND date = ?",
            (market, market, date),
        )

    yyyymmdd = date.strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=csv&date={yyyymmdd}&type=ALL"

    for retry in range(3):
        try:
            print(f"retrieving {url}")
            count = 0
            response = _http_get(url)
            time.sleep(5)  # TWSE may reject bursty requests
            for row in csv.reader(response.content.decode("cp950", errors="ignore").split("\r\n")):
                    if len(row) < 11:
                        continue
                    stock_id = clean(row[0])
                    if not is_id(stock_id):
                        continue
                    name = clean(row[1])
                    volume = _safe_int(row[2])
                    opening = _safe_decimal(row[5])
                    if volume is None or volume <= 0 or opening is None:
                        continue

                    turnover = _safe_int(row[4])
                    high = _safe_decimal(row[6])
                    low = _safe_decimal(row[7])
                    closing = _safe_decimal(row[8])
                    tickcount = _safe_int(row[3])
                    delta = None if clean(row[9]) == "X" else _safe_decimal(row[10])

                    if (
                        turnover is None
                        or high is None
                        or low is None
                        or closing is None
                        or tickcount is None
                    ):
                        continue

                    if (
                        float(opening) <= 0
                        or float(high) <= 0
                        or float(low) <= 0
                        or float(closing) <= 0
                    ):
                        continue

                    db.execute(
                        "INSERT INTO quote (ID, date, volume, turnover, open, high, low, close, delta, tickcount) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            stock_id,
                            date,
                            volume,
                            turnover,
                            opening,
                            high,
                            low,
                            closing,
                            delta,
                            tickcount,
                        ),
                    )
                    inserted = db.execute(
                        "INSERT OR IGNORE INTO stock (ID, name, market, mindate, maxdate) VALUES (?, ?, ?, ?, ?)",
                        (stock_id, name, market, date, date),
                    )
                    if inserted.rowcount <= 0:
                        db.execute(
                            "UPDATE stock SET name = ?, market = ?, maxdate = ? WHERE ID = ?",
                            (name, market, date, stock_id),
                        )
                    count += 1

            print(f"{date}: {count} records inserted")
            _upsert_market_marker(market, date, count)
            db.commit()
            break
        except Exception as exc:
            print(repr(exc))
            if retry >= 2:
                raise


def update_daily_otc_quotes(date, force: bool = False) -> None:
    date = to_date(date)
    db = get_db()
    market = "OTC"

    if db.execute("SELECT 1 FROM quote WHERE ID = ? AND date = ?", (market, date)).fetchone() and not force:
        return

    if force:
        db.execute(
            "DELETE FROM quote WHERE (ID IN (SELECT ID FROM stock WHERE market = ?) OR ID = ?) AND date = ?",
            (market, market, date),
        )

    url = f"http://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={date:%Y/%m/%d}&response=csv"

    for retry in range(3):
        try:
            print(f"retrieving {url}")
            count = 0
            response = _http_get(url)
            time.sleep(0.1)
            for row in csv.reader(response.content.decode("cp950", errors="ignore").split("\r\n")):
                if len(row) < 11:
                    continue
                stock_id = clean(row[0])
                if not is_id(stock_id):
                    continue

                name = clean(row[1])
                closing = _safe_decimal(row[2])
                delta = _safe_decimal(row[3])
                volume = _safe_int(row[8])
                opening = _safe_decimal(row[4])
                high = _safe_decimal(row[5])
                low = _safe_decimal(row[6])
                turnover = _safe_int(row[9])
                tickcount = _safe_int(row[10])

                if (
                    closing is None
                    or volume is None
                    or volume <= 0
                    or opening is None
                    or high is None
                    or low is None
                    or turnover is None
                    or tickcount is None
                ):
                    continue

                if (
                    float(opening) <= 0
                    or float(high) <= 0
                    or float(low) <= 0
                    or float(closing) <= 0
                ):
                    continue

                db.execute(
                    "INSERT INTO quote (date, ID, close, delta, open, high, low, volume, turnover, tickcount) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        date,
                        stock_id,
                        closing,
                        delta,
                        opening,
                        high,
                        low,
                        volume,
                        turnover,
                        tickcount,
                    ),
                )
                inserted = db.execute(
                    "INSERT OR IGNORE INTO stock (ID, name, market, mindate, maxdate) VALUES (?, ?, ?, ?, ?)",
                    (stock_id, name, market, date, date),
                )
                if inserted.rowcount <= 0:
                    db.execute(
                        "UPDATE stock SET name = ?, market = ?, maxdate = ? WHERE ID = ?",
                        (name, market, date, stock_id),
                    )
                count += 1

            print(f"{date}: {count} records inserted")
            _upsert_market_marker(market, date, count)
            db.commit()
            break
        except Exception as exc:
            print(repr(exc))
            if retry >= 2:
                raise


def continue_update_quotes() -> None:
    now = datetime.datetime.now()
    today = now.date()
    if now.hour < 15:
        today -= datetime.timedelta(days=1)

    db = get_db()
    twse_last, = db.execute("SELECT MAX(date) FROM quote WHERE ID = 'TWSE'").fetchone()
    otc_last, = db.execute("SELECT MAX(date) FROM quote WHERE ID = 'OTC'").fetchone()

    twse_from = QUOTE_EPOCH if twse_last is None else to_date(twse_last) + datetime.timedelta(days=1)
    otc_from = QUOTE_EPOCH if otc_last is None else to_date(otc_last) + datetime.timedelta(days=1)

    current = min(twse_from, otc_from)
    while current <= today:
        if current >= twse_from:
            update_daily_twse_quotes(current)
        if current >= otc_from:
            update_daily_otc_quotes(current)
        current += datetime.timedelta(days=1)


def chinese_date(expression: str) -> datetime.date:
    m = (
        re.match(r"^(\d+)\.(\d+)\.(\d+)$", expression)
        or re.match(r"^(\d+)/(\d+)/(\d+)$", expression)
        or re.match(r"^(\d+)-(\d+)-(\d+)$", expression)
    )
    if m:
        return datetime.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    raise ValueError(f"{expression!r} is not a Chinese date")


def update_monthly_twse_history(year: int, month: int) -> None:
    yyyymmdd = datetime.date(year, month, 1).strftime("%Y%m%d")
    url = f"https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?response=csv&date={yyyymmdd}"
    print(f"retrieving {url}")

    count = 0
    db = get_db()
    response = _http_get(url)
    time.sleep(5)
    for row in csv.reader(response.content.decode("cp950", errors="ignore").split("\r\n")):
            if len(row) < 5:
                continue
            try:
                date = chinese_date(row[0].strip())
                opening = to_decimal(clean(row[1]))
                high = to_decimal(clean(row[2]))
                low = to_decimal(clean(row[3]))
                closing = to_decimal(clean(row[4]))
            except Exception:
                continue

            db.execute(
                "INSERT OR REPLACE INTO twse (date, open, high, low, close) VALUES (?, ?, ?, ?, ?)",
                (date, opening, high, low, closing),
            )
            count += 1

    print(f"year={year} month={month}: {count} records inserted")
    db.commit()


def update_twse_history() -> None:
    db = get_db()
    max_date, = db.execute("SELECT MAX(date) FROM twse").fetchone()
    date = TWSE_HISTORY_EPOCH if max_date is None else to_date(max_date)
    today = datetime.date.today()

    while date <= today:
        update_monthly_twse_history(date.year, date.month)
        if date.month < 12:
            date = datetime.date(date.year, date.month + 1, 1)
        else:
            date = datetime.date(date.year + 1, 1, 1)


def stock_future_codes() -> None:
    doc = lxml.html.fromstring(_http_get("https://www.taifex.com.tw/cht/2/stockLists").text)
    db = get_db()
    db.execute("DELETE FROM stock_future")

    count = 0
    for tr in doc.xpath("//tr"):
        row = [td.text_content().strip() for td in tr.iter("td")]
        if len(row) < 11:
            continue

        code = row[0] + "F"
        stock_id = row[2]
        multiplier = row[10]
        if not is_id(stock_id):
            continue

        exists = db.execute("SELECT 1 FROM stock_future WHERE ID = ?", (stock_id,)).fetchone()
        if multiplier == "100":
            if exists:
                db.execute("UPDATE stock_future SET mini_future = ? WHERE ID = ?", (code, stock_id))
            else:
                db.execute("INSERT OR REPLACE INTO stock_future (ID, mini_future) VALUES (?, ?)", (stock_id, code))
        else:
            if exists:
                db.execute("UPDATE stock_future SET future = ? WHERE ID = ?", (code, stock_id))
            else:
                db.execute("INSERT OR REPLACE INTO stock_future (ID, future) VALUES (?, ?)", (stock_id, code))
        count += 1

    db.commit()
    print(f"stock_future_codes() {count} rows processed")


def update_all() -> None:
    stock_future_codes()
    continue_update_quotes()
    update_twse_history()


def _usage() -> str:
    return """
Usage:
    python -m tw_stock update
    python -m tw_stock future codes    # Update stock future code
    python -m tw_stock quotes update   # Continue updating stock quotes until today
    python -m tw_stock twse update     # Update TWSE index history until today
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ["update"]:
            update_all()
        elif argv == ["future", "codes"]:
            stock_future_codes()
        elif argv == ["quotes", "update"]:
            continue_update_quotes()
        elif argv == ["twse", "update"]:
            update_twse_history()
        else:
            raise SystemExit(_usage())
        return 0
    finally:
        close_db()


if __name__ == "__main__":
    raise SystemExit(main())
