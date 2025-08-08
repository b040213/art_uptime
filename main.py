import asyncio
import datetime
import pandas as pd
import requests
from bingx_py import BingXAsyncClient
from flask import Flask
import threading
import os
import httpx 

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1387480183698886777/RAzRv4VECjgloChid-aL0vg24DnEqpAHw66ASMSLszpMJTNxm9djACseKE4x7kjydD63"
API_KEY = "L9ywGJGME1uqTkIRd1Od08IvXyWCCyA2YKGwMPnde8BWOmm8gAC5xCdGAZdXFWZMt1euiT574cgAvQdQTw"
API_SECRET = "NYY1OfADXhu26a6F4Tw67RbHDvJcQ2bGOcQWOI1vXccWRoutdIdfsvxyxVtdLxZAGFYn9eYZN6RX7w2fQ"
SYMBOLS = []  # 你的幣種清單
INTERVAL = "1h"
ATR_PERIOD = 14
atr_cache = {symbol: {"value": None, "last_sent": None} for symbol in SYMBOLS}

def send_discord_msg(msg: str):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except Exception as e:
        print(f"❌ 傳送 Discord 訊息錯誤：{e}")

async def fetch_klines_bingx(symbol: str, interval: str = "1h", limit: int = 100) -> pd.DataFrame:
    async with BingXAsyncClient(api_key=API_KEY, api_secret=API_SECRET) as client:
        try:
            res = await client.swap.kline_candlestick_data(symbol=symbol, interval=interval, limit=limit)
            data = [kline.__dict__ for kline in res.data]
            df = pd.DataFrame(data)
            if df.empty:
                return None

            df = df.sort_values('time')
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            df.set_index('time', inplace=True)

            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            return df
        except Exception as e:
            print(f"⚠️ {symbol} 抓取錯誤: {e}")
            return None

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr.iloc[-1]

async def update_atr_and_notify():
    now = datetime.datetime.now()

    if not SYMBOLS:
        print(f"{now} ⚠️ SYMBOLS 清單為空，10秒後重試")
        await asyncio.sleep(10)
        return

    for symbol in SYMBOLS:
        df = await fetch_klines_bingx(symbol, interval=INTERVAL)
        print(f"{now} symbol={symbol} df_len={len(df) if df is not None else 'None'}")

        if df is None or len(df) < ATR_PERIOD + 1:
            print(f"{now} ⚠️ `{symbol}` 無法取得有效 K 線資料，60秒後重試")
            send_discord_msg(f"⚠️ `{symbol}` 無法取得有效 K 線資料")
            await asyncio.sleep(60)
            continue

        atr = calculate_atr(df, ATR_PERIOD)
        cached = atr_cache[symbol]
        previous_atr = cached["value"]
        last_sent_time = cached["last_sent"]
        atr_str = f"{atr:.6f}"
        time_str = now.strftime("%Y-%m-%d %H:%M:%S")

        if previous_atr is None or atr > previous_atr:
            atr_cache[symbol]["value"] = atr
            atr_cache[symbol]["last_sent"] = now
            send_discord_msg(f"📈 `{symbol}` ATR 更新為 {atr_str}（{time_str}）")

        elif last_sent_time is None or (now - last_sent_time).seconds >= 900:
            atr_cache[symbol]["last_sent"] = now

async def scheduler():
    print(f"{datetime.datetime.now()} 程式啟動完成，開始進入排程迴圈")
    while True:
        try:
            await update_atr_and_notify()
        except Exception as e:
            send_discord_msg(f"❌ ATR 更新時出錯：{str(e)}")
        await asyncio.sleep(300)

async def fetch_fear_greed_index():
    url = "https://api.alternative.me/fng/"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            data = response.json()
           send_discord_msg("抓到的資料:", data)   # 加印
            if not data.get("data"):
                print("⚠️ data 欄位為空或不存在")
                return None
            latest = data["data"][0]

            ts = int(latest["timestamp"])
            data_date = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")

            return {
                "data_date": data_date,
                "value": latest["value"],
                "value_classification": latest["value_classification"]
            }
    except Exception as e:
        print(f"⚠️ 抓取恐懼與貪婪指數失敗: {e}")
        return None

async def fear_greed_job():
    while True:
        now = datetime.datetime.now()
        fg_data = await fetch_fear_greed_index()

        if fg_data is None:
            print("⚠️ 無法取得恐懼與貪婪指數資料，跳過此次更新。")
            await asyncio.sleep(60)  # 失敗時延遲一下再重試
            continue

        try:
            x = int(fg_data['value'])
        except Exception as e:
            print(f"⚠️ 解析恐懼與貪婪指數失敗: {e}")
            await asyncio.sleep(60)
            continue

        if 26 <= x <= 74:
            msg = (
                f"現在日期 {now.month}/{now.day}  "
                f"情緒指數日期 {fg_data['data_date']}  "
                f"指數: {fg_data['value']} ({fg_data['value_classification']})"
            )
        elif x >= 75:
            msg = (
                f"現在日期 {now.month}/{now.day}  "
                f"情緒指數日期 {fg_data['data_date']}  "
                f"指數: {fg_data['value']} ({fg_data['value_classification']})\n"
                f"🔥🔥注意風險 , 極度貪婪🔥🔥"
            )
        elif x <= 25:
            msg = (
                f"現在日期 {now.month}/{now.day}  "
                f"情緒指數日期 {fg_data['data_date']}  "
                f"指數: {fg_data['value']} ({fg_data['value_classification']})\n"
                f"🧊🧊注意風險 , 極度恐懼🧊🧊"
            )
        else:
            msg = "⚠️ 無法判斷恐懼與貪婪指數狀態"

        send_discord_msg(msg)
        await asyncio.sleep(12 * 3600)
        
# Flask App
app = Flask(__name__)

@app.route("/")
def home():
    return "ATR 更新服務運作中。"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

async def main():
    task1 = asyncio.create_task(scheduler())
    task2 = asyncio.create_task(fear_greed_job())
    await asyncio.gather(task1, task2)

def run_asyncio_loop():
    asyncio.run(main())
if __name__ == "__main__":
    # 用 Thread 方式同時跑 Flask 和 asyncio
    t1 = threading.Thread(target=run_flask)
    t1.start()

    t2 = threading.Thread(target=run_asyncio_loop)
    t2.start()









