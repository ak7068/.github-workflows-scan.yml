import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error

BASE_URL = "https://api.india.delta.exchange"
TIMEFRAME = "5m"
CANDLE_SECONDS = 300


def get_json(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json",
                 "User-Agent": "Delta-EMA-Scanner"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not data.get("success", False):
        raise RuntimeError("Delta API returned unsuccessful response")

    return data


def get_products():
    products = []
    after = None

    for _ in range(20):
        params = {
            "contract_types": "perpetual_futures",
            "states": "live",
            "page_size": 100
        }

        if after:
            params["after"] = after

        data = get_json(BASE_URL + "/v2/products", params)
        page = data.get("result", [])

        products.extend(page)

        after = data.get("meta", {}).get("after")
        if not after or not page:
            break

    return [
        p for p in products
        if p.get("contract_type") == "perpetual_futures"
        and p.get("state") == "live"
        and p.get("symbol")
    ]


def get_candles(symbol):
    now = int(time.time())

    data = get_json(
        BASE_URL + "/v2/history/candles",
        {
            "resolution": TIMEFRAME,
            "symbol": symbol,
            "start": now - 100 * CANDLE_SECONDS,
            "end": now
        }
    )

    candles = data.get("result", [])
    candles.sort(key=lambda x: int(x["time"]))

    # Only use fully closed candles
    return [
        c for c in candles
        if int(c["time"]) + CANDLE_SECONDS <= now
    ]


def calculate_ema(values, period):
    multiplier = 2 / (period + 1)
    ema = values[0]

    result = [ema]

    for price in values[1:]:
        ema = (price - ema) * multiplier + ema
        result.append(ema)

    return result


def telegram_alert(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Telegram secrets not configured.")
        print(message)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode()

    req = urllib.request.Request(url, data=payload)

    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.loads(response.read().decode())

    if not result.get("ok"):
        raise RuntimeError("Telegram message failed")


def scan():
    products = get_products()
    print("Total live perpetual futures:", len(products))

    signals = []

    for product in products:
        symbol = product["symbol"]

        try:
            candles = get_candles(symbol)

            if len(candles) < 30:
                continue

            closes = [float(c["close"]) for c in candles]

            ema9 = calculate_ema(closes, 9)
            ema21 = calculate_ema(closes, 21)

            previous_9 = ema9[-2]
            previous_21 = ema21[-2]
            current_9 = ema9[-1]
            current_21 = ema21[-1]

            signal = None

            if previous_9 <= previous_21 and current_9 > current_21:
                signal = "BUY"

            elif previous_9 >= previous_21 and current_9 < current_21:
                signal = "SELL"

            if signal:
                price = closes[-1]
                candle_time = candles[-1]["time"]

                message = (
                    f"Delta EMA 9/21 {signal}\n"
                    f"Symbol: {symbol}\n"
                    f"Timeframe: {TIMEFRAME}\n"
                    f"Price: {price}\n"
                    f"EMA 9: {current_9:.6f}\n"
                    f"EMA 21: {current_21:.6f}\n"
                    f"Candle: {candle_time}\n"
                    f"Signal only - No automatic trade"
                )

                signals.append(message)

            print("Scanned:", symbol)

        except Exception as error:
            print("Error:", symbol, str(error))

    for message in signals:
        telegram_alert(message)

    print("Scan completed. Signals:", len(signals))


if __name__ == "__main__":
    scan()
          
