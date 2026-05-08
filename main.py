"""
投資組合後端 API v2
- 股票/加密貨幣報價
- 持倉資料儲存（存在伺服器 JSON 檔）
- 匯出 JSON
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import hashlib
import hmac
import base64
import time
import json
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

app = FastAPI(title="投資組合 API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 資料儲存路徑 ──────────────────────────────────────────
DATA_FILE = "/tmp/portfolio_data.json"

DEFAULT_DATA = {
    "stocks": [],
    "us": [],
    "crypto": [],
    "cash": [],
    "updated_at": ""
}

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_DATA.copy()

def save_data(data: dict):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════
#  健康檢查
# ═══════════════════════════════════════════════════════
@app.get("/")
def root():
    return {"status": "ok", "message": "投資組合 API v2 🚀"}


# ═══════════════════════════════════════════════════════
#  持倉 CRUD
# ═══════════════════════════════════════════════════════
@app.get("/portfolio")
def get_portfolio():
    """取得所有持倉資料"""
    return load_data()

@app.post("/portfolio")
def save_portfolio(data: dict):
    """儲存全部持倉資料（整包覆蓋）"""
    # 只保留合法欄位
    allowed = {"stocks", "us", "crypto", "cash"}
    cleaned = {k: v for k, v in data.items() if k in allowed}
    existing = load_data()
    existing.update(cleaned)
    save_data(existing)
    return {"status": "ok", "updated_at": existing["updated_at"]}

@app.get("/portfolio/export")
def export_portfolio():
    """匯出 JSON 備份"""
    data = load_data()
    return data


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
#  加密貨幣報價（OKX 公開 API）
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
