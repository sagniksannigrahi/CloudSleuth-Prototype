"""Load generator: sends real checkout traffic to the gateway (no OTel needed)."""

import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TARGET = os.environ.get("TARGET", "http://gateway:8000")
RPS = float(os.environ.get("RPS", "5"))


def one_request():
    req = urllib.request.Request(f"{TARGET}/checkout", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception:
        pass                                         # errors are part of the experiment


if __name__ == "__main__":
    print(f"loadgen: {RPS} requests/s -> {TARGET}", flush=True)
    with ThreadPoolExecutor(max_workers=64) as pool:
        while True:
            pool.submit(one_request)
            time.sleep(1 / RPS)
