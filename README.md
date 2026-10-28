# 國泰機票助手 (Cathay Staff Tickets)

國泰員工機票記錄、統計、乘客航線世界地圖分析工具。

---

## 📋 目錄

1. [ADMIN 使用說明](#admin-使用說明)
2. [Logic Flow](#logic-flow)
3. [JSON Structure](#json-structure)
4. [Version Control](#version-control)

---

## ADMIN 使用說明

### 前置條件

- GitHub Account（存放程式同 GitHub Pages 託管）
- 本地 OneDrive 目錄：`C:\Users\Harry\OneDrive\Harry Information System\豆包Agents Program Backup\Cathay\`
- 數據源飛書多維表格：Cathay Tickets Dashboard（base_token: `C2x4byTkEaN3Ths9FXwcagDSn5e`）

### 日常操作

1. 在本地 OneDrive 目錄修改 `index.html` / 重新生成 `cathay.json`
2. localhost 測試：`python3 -m http.server 8773`（注意用 python3，唔係 python）
3. 用戶確認 OK 後先上傳 GitHub
4. 每次上傳版本號 +0.01，HTML version + README Version Control 同步

### 數據更新

1. 修改飛書多維表格（Cathay Tickets / Passengers 表）
2. 重跑 `gen_cathay_json.py` 重新生成 `cathay.json`
3. 上傳 `cathay.json` 到 GitHub

---

## Logic Flow

### 頁面載入流程

```
用戶打開 index.html
        │
        ▼
  載入 cathay.json
        │
        ▼
  renderAll()
        │
        ├─ renderTickets() → 航班列表（3 Tab 中嘅航班 Tab）
        ├─ renderStats() → 統計指標 + Pie + Line
        └─ renderMap() → 世界地圖（ECharts）
        │
        ▼
  頁面就緒
        │
        ├─ 航班 Tab：Filter chips / Search / Sort dropdown
        ├─ 統計 Tab：6 指標格 + Pie Chart + Line Chart
        └─ 地圖 Tab：乘客 / 機場 / 月份 Slider / 區域 Filter
```

### 地圖 Filter 邏輯

```
用戶選擇 Filter
        │
        ▼
  refreshMapAll()
        │
        ├─ 乘客：無 / 全部乘客 / 個別乘客 → 過濾航線
        ├─ 機場：全部 / 單一機場 A → 顯示涉及 A 嘅航班（去 A 或由 A 返）
        ├─ 月份：Slider 拉動 → 只顯示該月份航班
        └─ 區域：SEA / NEA / EU / MEA / AM → 機場 visible/invisible
        │
        ▼
  更新 ECharts option
```

### 實付推送流程（GitHub Actions Bridge，v1.03 → v1.05 自動 sync + 全航班可改）

前端唔直接呼叫飛書 API（瀏覽器 CORS 唔支援 open.feishu.cn），改為經 GitHub 中轉：

```
用戶喺航班卡按「✏️ 改實付 / 補實付」（所有航班可改：有值改實付、冇值補實付）
        │
        ▼
  edits 存 localStorage（cathayPaidEdits，待推送 tag）
        │
        ▼
  按「📤 推送實付」
        │
        ├─ 1. 讀取 localStorage 嘅 GitHub Token（XOR+Base64 加密，key='cathay-2026-his-tools'）
        ├─ 2. 每次提交前動態 GET pending-paid.json 攞最新 sha
        ├─ 3. PUT data/pending-paid.json（{records:{record_id:金額}, updatedAt}）
        │      └─ 撞 409（Actions 清空緊檔案）→ 自動重試最多 4 次
        ▼
  GitHub Actions（.github/workflows/push-paid.yml，監控 data/pending-paid.json）
        │
        ├─ 1. 讀 repo secrets：FEISHU_APP_ID / FEISHU_APP_SECRET
        ├─ 2. POST /open-apis/auth/v3/tenant_access_token/internal 換 tenant token
        ├─ 3. GET /open-apis/bitable/v1/apps/{base}/tables/{table}/records/{rid} 診斷
        ├─ 4. PUT 同一 URL，body={"fields":{"Y HK$": 金額}}
        ├─ 5. 【v1.04】自動重生 cathay.json：tenant token 讀飛書 2 張表全部 record
        │        → 重算 stats / rollingProb / staffTrend / upcoming
        │        → version +0.01 → 上傳（HTML refresh 即時見最新實付，唔使再跑 J00）
        ├─ 6. 寫 data/push-status.json（updatedAt / ok / fail / errors）
        └─ 7. 清空 data/pending-paid.json（防循環觸發）
        │
        ▼
  前端 polling data/push-status.json（每 5 秒，最多 2 分鐘）
        │
        ├─ updatedAt ≥ 提交時間 → 顯示成功/失敗
        └─ 成功 → 清空本地 edits + 重新 fetch cathay.json（Actions 已重生新數據）→ render 最新畫面
```

**權限要求（飛書）**：App 需開 `base:record:read` + `base:record:write` 並發布版本；App 必須加入目標 Base 做協作者（可編輯）。

**自動 sync 機制（v1.04）**：每次推送實付後，Actions 用 tenant token 直接讀飛書 Cathay Tickets + Passengers 兩張表，重新生成 cathay.json（version 自動 +0.01）並上傳。以後修改多維表格後**唔需要人手重跑 gen_cathay_json.py** —— 任何一次實付推送都會順手 sync 埋最新數據。

**v1.05 更新**：
1. **所有航班可改實付**：唔止 NULL，已填實付嘅航班都有「✏️ 改實付」按鈕（prompt 預填現值，方便修改）
2. **推送成功自動 reload**：polling 到成功後自動重新 fetch cathay.json（cache-busting）再 render，唔使手動 refresh
3. **BASE_PATH 路徑邏輯**：GitHub Pages 用絕對路徑 `/cathay-tools/cathay.json`（dev/ 子目錄都能讀到根目錄最新 json），localhost 自動用相對路徑 —— 解決 dev/ GitHub Pages 下 cathay.json 404 問題
4. **Dev 測試流程教訓**：dev/ 目錄冇 cathay.json（自動 sync 只更新根目錄嗰個），所以 dev 版必須用絕對路徑指向根目錄 json，唔可以靠相對路徑

---

## JSON Structure

### cathay.json

```json
{
  "version": "1.02",
  "lastUpdate": "2026-10-13 07:27",
  "source": { "baseToken": "...", "ticketsTable": "...", "passengersTable": "...", "dashboardId": "..." },
  "stats": { "noOfFlights": 17, "successful": 12, "successRate": 70.6, "...": "..." },
  "rollingProb": [ { "time": "...", "prob": 0.7 } ],
  "staffTrend": [ { "time": "...", "staff": 5 } ],
  "upcoming": [],
  "tickets": [],
  "passengers": [ { "id": "...", "name": "Alice", "appName": "CHENG / KA YING ALICE MS" } ]
}
```

由 `gen_cathay_json.py` 生成（讀取飛書多維表格）。

---

## Version Control

| 版本 | 日期 | 更新內容 |
|------|------|----------|
| v1.18 | 2026-10-28 | 國泰員工機票使用統計（龍虎榜）：只計有 Flight Load App Name 嘅成員；圓形頭像對齊 bar 底部 + 名稱；頭像直接從飛書成員表 Profile Pict 下載（唔再 hardcode mapping）；修復 hidden tab chart resize；航班卡片恢復乘客頭像 |
| v1.17 | 2026-10-28 | Cloudflare Worker `/api/refresh` endpoint：push 實付後自動 dispatch GitHub Actions regen-cathay.yml；HTML 加 🔄 Refresh 按鈕；Reset 按鈕清空未推送數據；推送按鈕縮細放航班列表行右邊 |
| v1.05 | 2026-10-13 | 所有航班可改實付（有值「改實付」/冇值「補實付」）+ 推送成功後自動 reload cathay.json + BASE_PATH 絕對路徑（修 dev/ GitHub Pages 404） |
| v1.04 | 2026-10-13 | Actions 自動重生 cathay.json：推送實付後用 tenant token 讀飛書全部數據重算並上傳（version 自動 +0.01），HTML refresh 即時見最新，唔使再跑 J00 |
| v1.03 | 2026-10-13 | 實付推送功能：航班可編輯「Y HK$」實付價（IF NULL）+ 儲存加密 GitHub Token（XOR+Base64 存 localStorage）+ 推送實付經 GitHub Actions Bridge 寫入飛書多維表格 |
| v1.02 | 2026-10-13 | 數據更新：沖舅父由八月東京 NRT 行程移至五月大阪 KIX 行程（CX596/CX506 加入沖舅父；CX526/CX509 移除沖舅父） |
| v1.01 | 2026-10-12 | 首個 GitHub 部署。3 Tab 結構 + 航班排序 dropdown + 地圖 filter（combobox/slider/dropdown）+ 新 LOGO + 刪機場方格 + 乘客「全部乘客」選項 + 機場「涉及 A 航班」邏輯 |
| v1.00 | 2026-10-12 | 本地 Prototype（localhost:8773 測試版） |

### 版本規則

- 初始版本：v1.00
- 每次更新 +0.01
- HTML 頂部顯示 `v{版本號}`
- README.md 必須記錄每次更新日期同改動內容

---

## 外部連結

- **GitHub Pages**: https://hkharrycheng.github.io/cathay-tools/
- **數據源**: [Cathay Tickets Dashboard](https://feishu.doubao.com/base/C2x4byTkEaN3Ths9FXwcagDSn5e)

---

## License

MIT License
