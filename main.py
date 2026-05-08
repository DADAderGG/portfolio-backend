"""
投資組合後端 API
支援：Binance / OKX 加密貨幣持倉、Yahoo Finance 股票報價
部署平台：Render (免費方案)
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import hashlib
import hmac
import time
import urllib.parse
import os
from typing import Optional

app = FastAPI(title="投資組合 API", version="1.0.0")

# ── CORS：允許你的前端網址呼叫此 API ──────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 部署後改成你的前端網址，例如 ["https://yourapp.com"]
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
#  GET /price?symbols=2330.TW,AAPL,BTC-USD
# ═══════════════════════════════════════════════════════
@app.get("/price")
async def get_prices(symbols: str = Query(..., description="逗號分隔的代號，台股加 .TW")):
    """
    取得多支股票/ETF/加密貨幣即時報價
    台股範例: 2330.TW, 0050.TW
    美股範例: AAPL, NVDA, SPY
    加密貨幣: BTC-USD, ETH-USD
    """
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    results = {}

    async with httpx.AsyncClient(timeout=15) as client:
        for symbol in symbol_list:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                headers = {"User-Agent": "Mozilla/5.0"}
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
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
#  GET /fx
# ═══════════════════════════════════════════════════════
@app.get("/fx")
async def get_fx():
    """取得 USD/TWD 即時匯率"""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/USDTWD=X",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            data = resp.json()
            rate = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return {"USDTWD": round(rate, 4), "timestamp": int(time.time())}
        except Exception as e:
            return {"USDTWD": 32.5, "note": "使用備用匯率", "error": str(e)}


# ═══════════════════════════════════════════════════════
#  Binance 持倉
#  GET /binance/balances?api_key=xxx&api_secret=yyy
# ═══════════════════════════════════════════════════════
def binance_sign(params: dict, secret: str) -> str:
    query = urllib.parse.urlencode(params)
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

@app.get("/binance/balances")
async def binance_balances(
    api_key: str = Query(...),
    api_secret: str = Query(...)
):
    """取得 Binance 現貨帳戶餘額（非零資產）"""
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "omitZeroBalances": "true"}
    params["signature"] = binance_sign(params, api_secret)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.binance.com/api/v3/account",
                headers={"X-MBX-APIKEY": api_key},
                params=params
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.json())
            data = resp.json()
            balances = [
                {
                    "asset": b["asset"],
                    "free": float(b["free"]),
                    "locked": float(b["locked"]),
                    "total": float(b["free"]) + float(b["locked"])
                }
                for b in data.get("balances", [])
                if float(b["free"]) + float(b["locked"]) > 0.000001
            ]
            return {"exchange": "Binance", "balances": balances, "timestamp": int(time.time())}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════
#  OKX 持倉
#  GET /okx/balances?api_key=xxx&api_secret=yyy&passphrase=zzz
# ═══════════════════════════════════════════════════════
def okx_sign(timestamp: str, method: str, path: str, body: str, secret: str) -> str:
    msg = timestamp + method + path + body
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()

import base64

@app.get("/okx/balances")
async def okx_balances(
    api_key: str = Query(...),
    api_secret: str = Query(...),
    passphrase: str = Query(...)
):
    """取得 OKX 資金帳戶餘額"""
    ts = str(time.time())
    path = "/api/v5/account/balance"
    method = "GET"
    body = ""
    sig_bytes = okx_sign(ts, method, path, body, api_secret)
    sig = base64.b64encode(sig_bytes).decode()

    headers = {
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "x-simulated-trading": "0"
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get("https://www.okx.com" + path, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text)
            data = resp.json()
            if data.get("code") != "0":
                raise HTTPException(status_code=400, detail=data.get("msg", "OKX API 錯誤"))

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
#  加密貨幣 USD 報價（CoinGecko 免費 API）
#  GET /crypto/prices?coins=bitcoin,ethereum,solana
# ═══════════════════════════════════════════════════════
COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin",
    "SOL": "solana", "XRP": "ripple", "ADA": "cardano",
    "DOGE": "dogecoin", "AVAX": "avalanche-2", "DOT": "polkadot",
    "MATIC": "matic-network", "USDT": "tether", "USDC": "usd-coin",
    "LTC": "litecoin", "LINK": "chainlink", "UNI": "uniswap",
}

@app.get("/crypto/prices")
async def crypto_prices(symbols: str = Query(..., description="逗號分隔的幣種代號，例如 BTC,ETH,SOL")):
    """取得加密貨幣 USD 報價（CoinGecko）"""
    sym_list = [s.strip().upper() for s in symbols.split(",")]
    ids = [COINGECKO_IDS.get(s, s.lower()) for s in sym_list]

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": ",".join(ids), "vs_currencies": "usd", "include_24hr_change": "true"}
            )
            data = resp.json()
            results = {}
            for sym, coin_id in zip(sym_list, ids):
                if coin_id in data:
                    results[sym] = {
                        "symbol": sym,
                        "price_usd": data[coin_id].get("usd", 0),
                        "change_24h": round(data[coin_id].get("usd_24h_change", 0), 2)
                    }
            return {"prices": results, "timestamp": int(time.time())}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
