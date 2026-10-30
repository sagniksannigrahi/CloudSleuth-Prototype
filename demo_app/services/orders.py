"""orders: saves the order, reserves stock (inventory), charges (payments),
and puts a job on the queue for the worker."""

from common import CONFIG, call, db, make_app, own_work, safe

app = make_app({"inventory_timeout_s": 5.0, "payments_timeout_s": 2.0})


@app.post("/orders")
@safe
def create_order(order: dict):
    own_work()
    order_id = db("INSERT INTO orders (sku, amount) VALUES (%s, %s) RETURNING id",
                  (order["sku"], order["amount"]), fetch=True)[0][0]
    call("inventory", "/reserve", {"sku": order["sku"]}, CONFIG["inventory_timeout_s"])
    call("payments", "/charge", {"order_id": order_id, "amount": order["amount"]}, CONFIG["payments_timeout_s"])
    db("INSERT INTO jobs (order_id) VALUES (%s)", (order_id,))      # queue for the worker
    return {"order_id": order_id}
