# MOS-BRAND-001：品牌快速建立

分支：`codex/marketing-ai-os-brand-quick-setup`。本次不部署；原 Windows API 仍為 `caf71275745e123b0c0d78b73eac60b47d9fb923`。

## 範圍與實際狀態

- 免費快速建立：完成。六種既有產業、AJ創美學苑範例、可編輯預覽、明確套用、取消、過期預覽阻擋、原表單儲存。
- 工作台重用：同名品牌優先取目前租戶可讀的 Brief；指定工作台來源優先。保留品牌與內容兩份禁用詞、必要詞及原補充需求。
- AI 智能補全：**未實作付費品牌補全**。現有 Provider 僅有 A09 文案輸出契約，不能把它當成品牌補全。入口明示未開放，點擊提供免費預覽，沒有模型 HTTP；不能因為有 Key 就開啟。若工單要求真正可執行的付費品牌補全，本單整體為 **PARTIAL**，不得宣稱已全部完成。
- 不把建議當成已核實品牌事實，不自動加入 Owner 品牌知識、核准素材或授權。更換品牌且草稿已有知識／素材時，要求先核對，避免沿用另一品牌的授權內容。

## 使用方式

1. 在自動化中心展開「建立自動化政策」。
2. 輸入品牌名稱、選擇產業，按「快速建立品牌設定」；AJ 範例可直接點選。
3. 預覽中可修改建議產業、介紹、服務領域、客群、目的、語氣、主題、Hook、CTA、禁用詞、風險與長度。上方套用按鈕在捲動時保持可用。
4. 按「套用至目前政策」只更新表單；取消不改原資料。若原表單已被編輯，舊預覽拒絕套用，需重新預覽。
5. 核對帳號、模式、時段、期限與預算，按原本「儲存為待授權政策」。這不會啟用政策、Worker、AI 或發文；既有政策保持原樣。

## 資料與檔案

沒有新增 API、Migration、資料表、Provider、套件或服務。沿用 `POST /automation/policies`、`GET /ui/content/tasks` 與既有 Tenant RBAC。

`brand-quick.js` 只做瀏覽器端規則建議；`automation.js` 接入預覽並保留 `Brief.supplementary`。介紹、客群、目的、語氣、產業、禁用詞及長度仍存入原 Brief；主題存原 `terms.topics`，Hook／CTA／服務領域與風險規則存 `supplementary`（合計最多800字，超限拒絕、不截斷）。原 A09 會讀取這些補充需求。複製政策也保留原補充需求，沒有另一套品牌資料庫。

## 驗收

- 針對性 Python HTTP／資料庫回歸：38 passed；mypy：36 modules 通過。
- Node 規則測試：4 passed（亦由 Python wrapper 執行）；CI 另檢查新 JS 語法與規則測試。
- [瀏覽器證據](brand001/browser-evidence.json)：預覽不覆寫、取消後不遺留隱藏必填欄位、修改後套用、過期預覽、XSS 逃逸、AI 回退零 HTTP、工作台優先、手機實際點擊儲存、新政策保留規則及舊政策不變。
- 1440／768／390 寬度沒有橫向溢出。採既有 Framed sheet、保留原字型與配色；沒有重做整頁。
- 三尺寸視覺 inspector 沒有 FAIL；有原有 `IBM Plex Sans` 回退 WARN。本次依使用者限制保留原字型設定，不擴大修補字型資產。
- 手機驗收是 Windows Chromium 的390px尺寸與實際滑鼠點擊，**未驗證實體 iPhone Safari／虛擬鍵盤**。視覺檢查是同一真實 UI 的無腳本合成資料快照，非另一個產品介面。
- 真實模型呼叫0次、費用USD0；真實Threads呼叫0次，原Token／DPAPI／資料庫與部署開關未修改。

畫面：[手機預覽](brand001/ui/brand-preview-viewport-390.png)、[桌面預覽](brand001/ui/brand-preview-viewport-1440.png)、[手機保存結果](brand001/ui/mobile-saved-policy.png)。這些是隔離資料畫面，不是正式品牌事實或真實發布證據。
