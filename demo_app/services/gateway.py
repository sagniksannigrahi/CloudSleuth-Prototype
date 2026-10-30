"""gateway: the front door. POST /checkout -> orders."""

import random

from common import CONFIG, call, make_app, own_work, safe

app = make_app({"orders_timeout_s": 6.0})


@app.post("/checkout")
@safe
def checkout():
    own_work()
    order = {"sku": f"sku-{random.randint(1, 20)}", "amount": round(random.uniform(5, 200), 2)}
    return call("orders", "/orders", order, CONFIG["orders_timeout_s"])
