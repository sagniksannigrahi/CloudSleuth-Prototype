"""payments: records a payment for an order."""

from common import db, make_app, own_work, safe

app = make_app()


@app.post("/charge")
@safe
def charge(req: dict):
    own_work(loops=40000)
    db("INSERT INTO payments (order_id, amount) VALUES (%s, %s)", (req["order_id"], req["amount"]))
    return {"charged": req["order_id"]}
