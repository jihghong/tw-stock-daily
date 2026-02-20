"""
Use count_stocks() to get total count for displaying or to estimate processing time.
Use list_stocks() to iterate the above matched stocks.
"""

from itertools import islice

from tw_stock import count_stocks, list_stocks

begin_date = "2020-01-01"

all_twse = count_stocks(begin_date, market="TWSE")
all_otc = count_stocks(begin_date, market="OTC")
all_total = count_stocks(begin_date)

print(f"TWSE count: {all_twse}")
print(f"OTC count: {all_otc}")
print(f"TOTAL count: {all_total}")
print()

for i, stock in enumerate(islice(list_stocks(begin_date, market="TWSE"), 10), start=1):
    print(
        f"({i}/{all_twse}) {stock.title} "
        f"code={stock.id} name={stock.name} future={stock.future} mini_future={stock.mini_future}"
    )
print('...')