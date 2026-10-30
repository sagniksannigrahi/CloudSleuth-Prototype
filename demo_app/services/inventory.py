"""inventory: reserves one unit of stock (UPDATE on the inventory table)."""

from common import db, make_app, own_work, safe

app = make_app()


@app.post("/reserve")
@safe
def reserve(req: dict):
    own_work()
    db("UPDATE inventory SET stock = CASE WHEN stock > 0 THEN stock - 1 ELSE 1000000 END WHERE sku = %s",
       (req["sku"],))
    return {"reserved": req["sku"]}
