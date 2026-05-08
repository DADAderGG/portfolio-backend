# 投資組合後端 API

Python FastAPI 後端，部署於 Render 免費方案。

## 支援功能

| API 端點 | 說明 |
|----------|------|
| `GET /` | 健康檢查 |
| `GET /price?symbols=2330.TW,AAPL` | 台股/美股即時報價 |
| `GET /fx` | USD/TWD 匯率 |
| `GET /crypto/prices?symbols=BTC,ETH` | 加密貨幣報價 (CoinGecko) |
| `GET /binance/balances?api_key=&api_secret=` | Binance 持倉 |
| `GET /okx/balances?api_key=&api_secret=&passphrase=` | OKX 持倉 |

---

## 部署步驟（Render）

### 第一步：上傳程式碼到 GitHub

```bash
# 在電腦上建立資料夾
mkdir portfolio-backend && cd portfolio-backend

# 把這四個檔案放進去：
# main.py / requirements.txt / render.yaml / README.md

git init
git add .
git commit -m "初始版本"
git branch -M main
git remote add origin https://github.com/你的帳號/portfolio-backend.git
git push -u origin main
```

### 第二步：在 Render 建立服務

1. 前往 https://render.com，用 GitHub 帳號登入
2. 點「New +」→「Web Service」
3. 連結你的 GitHub repo
4. 設定如下：
   - **Name**: `portfolio-api`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: `Free`
5. 點「Create Web Service」，等待 2-3 分鐘部署完成

### 第三步：取得你的 API 網址

部署完成後，你會得到一個網址，例如：
```
https://portfolio-api-xxxx.onrender.com
```

這就是你的後端 API 網址，把它填入前端 Web App 設定中。

---

## 本地測試

```bash
# 安裝套件
pip install -r requirements.txt

# 啟動伺服器
uvicorn main:app --reload

# 開啟瀏覽器
# http://localhost:8000/docs  ← 互動式 API 文件
```

---

## Binance API Key 申請（只讀）

1. 登入 Binance → 右上角帳號 → API 管理
2. 點「建立 API」→ 選「系統生成」
3. **只勾選「讀取」權限**，不要開啟提幣/交易
4. 完成後複製 API Key 和 Secret Key

## OKX API Key 申請（只讀）

1. 登入 OKX → 個人中心 → API
2. 點「建立 V5 API Key」
3. 權限只選「讀取」
4. 設定 Passphrase（自訂密碼）
5. 複製 API Key、Secret Key、Passphrase

---

## 注意事項

- **API Key 安全**：絕對不要把 API Key 寫死在前端程式碼中
- **Render 免費方案**：閒置 15 分鐘會休眠，第一次請求會慢 30 秒
- **台股報價**：使用 Yahoo Finance，延遲約 15 分鐘（即時需付費）
- **CORS 設定**：正式上線後，把 `main.py` 中的 `allow_origins=["*"]` 改成你的前端網址
