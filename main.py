import asyncio
import datetime
import pandas as pd
import requests
from bingx_py import BingXAsyncClient

# ✅ Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1387480183698886777/RAzRv4VECjgloChid-aL0vg24DnEqpAHw66ASMSLszpMJTNxm9djACseKE4x7kjydD63"

# ✅ BingX API 金鑰
API_KEY = "L9ywGJGME1uqTkIRd1Od08IvXyWCCyA2YKGwMPnde8BWOmm8gAC5xCdGAZdXFWZMt1euiT574cgAvQdQTw"
API_SECRET = "NYY1OfADXhu26a6F4Tw67RbHDvJcQ2bGOcQWOI1vXccWRoutdIdfsvxyxVtdLxZAGFYn9eYZN6RX7w2fQ"

# ✅ 幣種與 ATR 設定
SYMBOLS = []
INTERVAL = "1h"
ATR_PERIOD = 14
atr_cache = {symbol: {"value": None, "last_sent": None} for symbol in SYMBOLS}


# ✅ 傳送 Discord 訊息
def send_discord_msg(msg: str):
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    except Exception as e:
        print(f"❌ 傳送 Discord 訊息錯誤：{e}")


# ✅ 使用 BingXAsyncClient 抓取並回傳格式化後的 DataFrame
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


# ✅ 計算 ATR
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


# ✅ 更新 ATR 並通知
async def update_atr_and_notify():
    now = datetime.datetime.now()

    for symbol in SYMBOLS:
        df = await fetch_klines_bingx(symbol, interval=INTERVAL)
        print(f"symbol={symbol} df_len={len(df) if df is not None else 'None'}")

        if df is None or len(df) < ATR_PERIOD + 1:
            send_discord_msg(f"⚠️ `{symbol}` 無法取得有效 K 線資料")
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
            # send_discord_msg(f"ℹ️ `{symbol}` ATR 維持 {atr_str}（{time_str}）")


# ✅ 排程器
async def scheduler():
    while True:
        try:
            await update_atr_and_notify()
        except Exception as e:
            send_discord_msg(f"❌ ATR 更新時出錯：{str(e)}")
        await asyncio.sleep(300)  # 每 5 分鐘更新一次


# ✅ 啟動
if __name__ == "__main__":
    asyncio.run(scheduler())
