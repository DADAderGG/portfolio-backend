"""
投資組合後端 API
支援：Binance / OKX 加密貨幣持倉、Yahoo Finance 股票報價
部署平台：Render (免費方案)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import hashlib
import hmac
import base64
import time
import urllib.parse
from datetime import datetime, timezone

app = FastAPI(title="投資組合 API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════
#  健康檢查
# ═══════════════════════════════════════════════════════
@app.get("/")
def root():
    return {"status": "ok", "message": "投資組合 API 運作中 🚀"}


# ═══════════════════════════════════════════════════════
#  股票報價 (Yahoo Finance)
# ═══════════════════════════════════════════════════════
@app.get("/price")
async def get_prices(symbols: str = Query(...)):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    results = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for symbol in symbol_list:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                meta = resp.json()["chart"]["result"][0]["meta"]
                results[symbol] = {
                    "symbol": symbol,
                    "price": meta.get("regularMarketPrice", 0),
                    "currency": meta.get("currency", "USD"),
                    "name": meta.get("longName") or meta.get("shortName", symbol),
                    "change_pct": round(
                        (meta.get("regularMarketPrice", 0) - meta.get("chartPreviousClose", 0))
                        / max(meta.get("chartPreviousClose", 1), 0.0001) * 100, 2
                    ),
                }
            except Exception as e:
                results[symbol] = {"symbol": symbol, "price": 0, "error": str(e)}
    return {"prices": results, "timestamp": int(time.time())}


# ═══════════════════════════════════════════════════════
#  USD/TWD 匯率
# ═══════════════════════════════════════════════════════
@app.get("/fx")
async def get_fx():
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/USDTWD=X",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            rate = resp.json()["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return {"USDTWD": round(rate, 4), "timestamp": int(time.time())}
        except Exception as e:
            return {"USDTWD": 32.5, "note": "使用備用匯率", "error": str(e)}


# ═══════════════════════════════════════════════════════
#  Binance 持倉（自動嘗試多個備用網域）
# ═══════════════════════════════════════════════════════
BINANCE_HOSTS = [
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api.binance.com",
]

def binance_sign(params: dict, secret: str) -> str:
    query = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

@app.get("/binance/balances")
async def binance_balances(api_key: str = Query(...), api_secret: str = Query(...)):
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "omitZeroBalances": "true"}
    params["signature"] = binance_sign(params, api_secret)

    last_error = "未知錯誤"
    async with httpx.AsyncClient(timeout=15) as client:
        for host in BINANCE_HOSTS:
            try:
                resp = await client.get(
                    f"{host}/api/v3/account",
                    headers={"X-MBX-APIKEY": api_key},
                    params=params
                )
                if resp.status_code == 451:
                    last_error = f"{host} 地區限制(451)"
                    continue
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail=resp.json())
                data = resp.json()
                balances = [
                    {"asset": b["asset"], "free": float(b["free"]),
                     "locked": float(b["locked"]),
                     "total": float(b["free"]) + float(b["locked"])}
                    for b in data.get("balances", [])
                    if float(b["free"]) + float(b["locked"]) > 0.000001
                ]
                return {"exchange": "Binance", "balances": balances, "host": host, "timestamp": int(time.time())}
            except HTTPException:
                raise
            except Exception as e:
                last_error = str(e)
                continue
    raise HTTPException(status_code=451, detail=f"所有 Binance 網域均受地區限制：{last_error}")


# ═══════════════════════════════════════════════════════
#  OKX 持倉（修正簽名與時間戳格式）
# ═══════════════════════════════════════════════════════
def okx_make_sign(ts: str, method: str, req_path: str, body: str, secret: str) -> str:
    msg = ts + method + req_path + body
    mac = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

@app.get("/okx/balances")
async def okx_balances(
    api_key: str = Query(...),
    api_secret: str = Query(...),
    passphrase: str = Query(...)
):
    now = datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%dT%H:%M:%S.') + f"{now.microsecond // 1000:03d}Z"
    req_path = "/api/v5/account/balance"
    sig = okx_make_sign(ts, "GET", req_path, "", api_secret)

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get("https://www.okx.com" + req_path, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            if data.get("code") != "0":
                raise HTTPException(status_code=400, detail=f"OKX 錯誤 {data.get('code')}: {data.get('msg')}")
            balances = []
            for detail in data["data"][0].get("details", []):
                total = float(detail.get("cashBal", 0))
                if total > 0.000001:
                    balances.append({
                        "asset": detail["ccy"],
                        "total": total,
                        "available": float(detail.get("availBal", 0))
                    })
            return {"exchange": "OKX", "balances": balances, "timestamp": int(time.time())}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
#  加密貨幣報價（OKX 公開 API，支援所有幣種）
# ═══════════════════════════════════════════════════════
@app.get("/crypto/prices")
async def crypto_prices(symbols: str = Query(...)):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    results = {}
    stable = {"USDT", "USDC", "USD", "BUSD", "DAI"}
    async with httpx.AsyncClient(timeout=15) as client:
        for sym in sym_list:
            if sym in stable:
                results[sym] = {"symbol": sym, "price_usd": 1.0, "change_24h": 0.0}
                continue
            try:
                resp = await client.get(
                    "https://www.okx.com/api/v5/market/ticker",
                    params={"instId": f"{sym}-USDT"}
                )
                data = resp.json()
                if data.get("code") == "0" and data.get("data"):
                    ticker = data["data"][0]
                    last = float(ticker.get("last", 0))
                    open24 = float(ticker.get("open24h", last) or last)
                    change = round((last - open24) / open24 * 100, 2) if open24 else 0
                    results[sym] = {"symbol": sym, "price_usd": last, "change_24h": change}
                else:
                    results[sym] = {"symbol": sym, "price_usd": 0, "change_24h": 0, "error": "找不到幣種"}
            except Exception as e:
                results[sym] = {"symbol": sym, "price_usd": 0, "change_24h": 0, "error": str(e)}
    return {"prices": results, "timestamp": int(time.time())}
