"""Built-in example pipelines. Data is inline so examples run anywhere."""

from .models import Example

_ORDERS = '''\
orders = pd.DataFrame({
    "order_id": range(1, 13),
    "user_id":  [1, 2, 2, 3, 4, 4, 5, 6, 7, 7, 8, 9],
    "amount":   [20.0, 35.5, 12.0, 80.0, 5.0, 42.0, 18.0, 60.0, 25.0, 30.0, 11.0, 99.0],
    "status":   ["paid", "paid", "refunded", "paid", "paid", "pending",
                 "paid", "paid", "refunded", "paid", "paid", "paid"],
})
# Bug: user 4 appears twice in the users table (a duplicated CRM record)
users = pd.DataFrame({
    "user_id": [1, 2, 3, 4, 4, 5, 6],
    "country": ["US", "MX", "US", "CA", "CA", "MX", None],
})
'''

EXAMPLES = [
    Example(
        id="revenue",
        title="Revenue by country (with a hidden join bug)",
        description="Filter, left join, groupby. A duplicated key inflates revenue; unmatched users become nulls.",
        code=_ORDERS + '''
paid = orders[orders.status == "paid"]
enriched = paid.merge(users, on="user_id", how="left")
revenue = (enriched
           .groupby("country", dropna=False)
           .agg(revenue=("amount", "sum"), orders=("order_id", "count"))
           .sort_values("revenue", ascending=False))
print(revenue)
''',
    ),
    Example(
        id="cleaning",
        title="Cleaning with silent dtype drift",
        description="reindex introduces NaN and silently turns int64 into float64; dropna then loses rows.",
        code='''\
sensors = pd.DataFrame({
    "sensor": ["a", "b", "c", "d"],
    "reading": [10, 12, 9, 14],
}).set_index("sensor")

full = sensors.reindex(["a", "b", "c", "d", "e", "f"])   # e, f have no readings
full["reading_x2"] = full["reading"] * 2
clean = full.dropna()
clean = clean.astype({"reading": "int64"})
''',
    ),
    Example(
        id="reshape",
        title="Wide ↔ long reshape",
        description="melt to long form, filter, then pivot_table back to wide.",
        code='''\
wide = pd.DataFrame({
    "store": ["north", "south", "east"],
    "jan": [100, 80, 95],
    "feb": [110, 70, 105],
    "mar": [120, 90, None],
})
long = wide.melt(id_vars="store", var_name="month", value_name="sales")
long = long.dropna()
top = long.query("sales >= 90")
summary = top.pivot_table(index="store", columns="month", values="sales", aggfunc="sum")
''',
    ),
    Example(
        id="pushdown",
        title="Pushdown opportunities",
        description="Work pandas won't optimize for you: a filter after a join, unused columns, a pointless sort.",
        code='''\
import io

orders = pd.read_csv(io.StringIO("""order_id,user_id,amount,status,coupon,notes
1,1,12.0,paid,,first order
2,2,40.0,paid,SPRING,
3,2,8.5,refunded,,
4,3,55.0,paid,,gift
5,4,31.0,paid,SPRING,
6,5,9.0,paid,,
7,1,70.0,paid,,
8,3,15.0,paid,,
"""))
users = pd.DataFrame({"user_id": [1, 2, 3, 4, 5], "country": ["US", "MX", "US", "CA", "MX"]})

enriched = orders.merge(users, on="user_id", how="inner")
large = enriched[enriched["amount"] > 20]         # only uses orders' columns
ranked = large.sort_values("amount")              # order is thrown away below
by_country = ranked.groupby("country")["amount"].sum()
''',
    ),
    Example(
        id="concat",
        title="Concatenating monthly extracts",
        description="concat with mismatched schemas creates nulls; drop_duplicates removes overlap.",
        code='''\
jan = pd.DataFrame({"id": [1, 2, 3], "value": [5, 6, 7]})
feb = pd.DataFrame({"id": [3, 4, 5], "value": [7, 8, 9], "channel": ["web", "app", "web"]})
all_months = pd.concat([jan, feb], ignore_index=True)
deduped = all_months.drop_duplicates(subset="id")
by_channel = deduped["channel"].value_counts(dropna=False)
''',
    ),
]
