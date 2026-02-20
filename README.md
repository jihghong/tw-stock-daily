# tw-stock-daily

提供台股日線資料庫 `tw_stock.db` 及更新程式。

## 取用資料 tw_stock.db

直接下載網址 [https://github.com/jihghong/tw-stock-daily/releases/latest/download/tw_stock.db](https://github.com/jihghong/tw-stock-daily/releases/latest/download/tw_stock.db)

若用於訓練模型，須注意台股自 2015 年 6 月 1 日 起漲跌幅限制由 7% 改為 10%。

## 以程式更新

### 1. 安裝更新程式

```bash
pip install https://github.com/jihghong/tw-stock-daily
```

### 2. 設定資料庫路徑環境變數

將環境變數 `TW_STOCK_DB_PATH` 指向 `tw_stock.db`

```bash
setx TW_STOCK_DB_PATH 'D:\data\tw_stock.db'
```

### 3. 執行更新指令：

```bash
python -m tw_stock update
```

會執行：
- 補齊個股日K（更新 `quote` + `stock`）
- 補齊大盤日K（更新 `twse`）
- 更新個股期貨代碼（覆寫 `stock_future`）

也可分開執行：

```bash
python -m tw_stock quotes update   # Continue updating stock quotes until today
python -m tw_stock twse update     # Update TWSE index history until today
python -m tw_stock future codes    # Update stock future code
```

## `tw_stock.db` Schema（表格與欄位）

目前資料庫包含 5 個 table + 1 個 view。

### Table: `stock`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `ID` | `VARCHAR(10)` | 股票代碼（PK） |
| `name` | `VARCHAR(100)` | 名稱 |
| `market` | `VARCHAR(10)` | 市場（如 `TWSE`、`OTC`） |
| `mindate` | `DATE` | 該代碼在 `quote` 最早日期 |
| `maxdate` | `DATE` | 該代碼在 `quote` 最新日期 |

### Table: `quote`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | `DATE` | 交易日（PK part 1） |
| `ID` | `VARCHAR(10)` | 股票代碼（PK part 2） |
| `volume` | `INT` | 成交量 |
| `turnover` | `INT` | 成交金額 |
| `open` | `DECIMAL(8,2)` | 開盤價 |
| `high` | `DECIMAL(8,2)` | 最高價 |
| `low` | `DECIMAL(8,2)` | 最低價 |
| `close` | `DECIMAL(8,2)` | 收盤價 |
| `delta` | `DECIMAL(8,2)` | 漲跌 |
| `tickcount` | `INT` | 成交筆數 |

### Table: `stock_future`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `ID` | `VARCHAR(10)` | 股票代碼（PK） |
| `future` | `VARCHAR(10)` | 對應個股期貨代碼 |
| `mini_future` | `VARCHAR(10)` | 對應小型個股期貨代碼 |
| `smooth` | `VARCHAR(1)` | 保留欄位 |

### Table: `twse`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | `DATE` | 日期（PK） |
| `open` | `DECIMAL(8,2)` | 開盤 |
| `high` | `DECIMAL(8,2)` | 最高 |
| `low` | `DECIMAL(8,2)` | 最低 |
| `close` | `DECIMAL(8,2)` | 收盤 |

### Table: `future`

| 欄位 | 型別 |
|---|---|
| `security_code` | `VARCHAR(20)` (PK) |
| `contract` | `VARCHAR(20)` |
| `name` | `VARCHAR(100)` |
| `target_security` | `VARCHAR(20)` |
| `multiplier` | `double` |
| `price_tick` | `double` |
| `price_limit` | `double` |
| `price_limit1` | `double` |
| `price_limit2` | `double` |
| `delivery_date` | `VARCHAR(20)` |
| `delivery_time` | `time` |
| `delivery_time1` | `time` |
| `commission` | `double` |
| `markets_per_day` | `integer` |
| `market_open` | `time` |
| `market_close` | `time` |
| `market_open1` | `time` |
| `market_close1` | `time` |

### View: `stock_future_view`

```sql
SELECT s.ID, s.name, s.market, f.future, f.mini_future, s.mindate, s.maxdate
FROM stock s
LEFT JOIN stock_future f ON s.ID = f.ID
```

## 未來展望

- 可建立 GitHub actions 每日更新。
- 舊程式係以爬網取得資料，正確做法應呼叫 [TWSE Open API](https://openapi.twse.com.tw/)、[TPEX Open API](https://www.tpex.org.tw/openapi/) 及 [TAIFEX Open API]。(https://openapi.taifex.com.tw/)
- 因經驗不足，資料品質不是很好，有心貢獻者可協助補充更完整之歷史資料。

