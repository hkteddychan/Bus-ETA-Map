# 香港巴士到站地圖 (Bus-ETA-Map)

香港巴士到站時間地圖 — 覆蓋九巴 (KMB)、龍運 (LWB)、專線小巴 (GMB)、港鐵巴士 (MTR)。

🔗 Live: https://hkteddychan.github.io/Bus-ETA-Map/

## 功能

- 🗺️ **互動地圖**：全港巴士/小巴/港鐵巴士站，按營運商篩選、按地區快速跳轉、搜尋站名或路線
- ⏱️ **即時 ETA**：九巴/龍運經 `data.etabus.gov.hk`、專線小巴經 `data.etagmb.gov.hk`、港鐵用班次表
- ⏳ **資料舊化標示**：ETA 顯示「X 秒/分鐘前更新」，超過 90 秒轉橙、300 秒轉紅，左下角有全局更新時效 badge
- ⭐ **常用站書籤**：點站彈窗右上角 ☆ 加入常用，用 localStorage 儲存，浮動按鈕 ⭐ 開啟書籤面板一鍵跳轉
- ⚠️ **ETA 錯誤處理**：失敗自動保留上次成功資料並標示「可能過時」、顯示重試按鈕、支援離線提示、15 秒後自動重試
- 🌙 **深色模式**：切換開關，自動切換深色地圖底圖，偏好存入 localStorage
- 📱 **PWA 可安裝**：manifest + Service Worker，可加到主畫面、離線可用（數據檔離線快取）
- 📍 **定位**：顯示我的位置 + 最近站點

## 資料來源

| 營運商 | API |
|--------|-----|
| 九巴 KMB / 龍運 LWB | `https://data.etabus.gov.hk/v1/transport/kmb/eta/{stopId}/{route}/{serviceType}` |
| 專線小巴 GMB | `https://data.etagmb.gov.hk/eta/stop/{stopId}` |
| 港鐵巴士 MTR | 靜態班次表（mtr_data.json） |

地圖底圖：CARTO Basemaps（© OpenStreetMap © CARTO）

> ⚠️ 站點與路線為預先打包的靜態數據（`kmb_data.json` / `mtr_data.json` / `gmb_data.json`），不會自動更新；ETA 則為即時數據。

## 本機執行

```bash
python3 -m http.server 8000
# 開啟 http://localhost:8000
```

純靜態網頁，無需後端。部署到 GitHub Pages 即直接可用的 PWA。

## 未做事項 / 已知限制

- 靜態站點數據需人手重新打包才能更新（無後端定時更新）
- 港鐵巴士用靜態班次表而非即時到站（官方暫無公開即時 API）
- 部分營運商 API 偶發不穩定，已用「保留上次資料」機制降級處理
- Service Worker 初次安裝後需完整載入一次才能完全離線
