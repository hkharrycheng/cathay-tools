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
