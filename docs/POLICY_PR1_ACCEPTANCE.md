# PR #1：自動化政策草稿422

PR來源：`7dbf42d8fbf5c5cd0f5d8630a44e79d33ff4fd02`（已以merge整合至部署分支，沒有修改main或原來源分支）。被中斷的前端欄位提示與保留輸入修正已先保存，再按PR語意調整。

## 根因與修正

原 Windows 映像未標SHA；前端與 `app/automation.py` 正規化雜湊與 `2413f94` 相符。在原部署以明確不完整的受控輸入實際取得 `HTTP422 / body.terms / Value error, Unique owner facts required`；FULL+MATERIALS另取得三段核准素材錯誤。這是受控重現，不是回溯未保存的使用者原始request。

原Schema把啟用前提也套用在DRAFT儲存，導致AJ品牌建議尚未填入事實時不能保存與配置Key。PR將「缺少事實／三段素材」檢查移到啟用端點，保留事實ID唯一性、所有字數／日期／預算／欄位限制。啟用前檢查發生在Worker憑證發給或ACTIVE狀態變更之前。

前端同步允許不完整草稿；只有啟用才要求事實與素材。沒有自動捏造或確認品牌事實。伺服器422會依欄位顯示中文，不回顯input或敏感資料；失敗不render或清空表單。其他缺項、超長介紹、重複事實ID、日期／預算格式仍在送出前提示。

## 回歸與Windows驗收方法

- Python針對性回歸42 passed，mypy36個核心模組通過；Node9個規則與欄位測試通過。
- 隔離真實HTTP/SQLite與390px瀏覽器：快速套用AJ→選gpt-6-luna→FULL/BRAND_GUIDED、facts=[]→POST201、DRAFT卡片與API Key欄位出現。
- UI啟用預檢阻擋；直接呼叫後端啟用仍HTTP422 `VERIFIED_BRAND_FACTS_REQUIRED_BEFORE_ACTIVATION`，政策維持DRAFT，沒有Worker執行。
- 實際伺服器回傳的重複ID與品牌介紹超長422均顯示中文欄位，表單輸入完整保留。
- 證據：`docs/policy-pr1/browser-evidence.json`、`draft-api-key-mobile.png`。這是Chromium手機尺寸，不代表實體Safari已驗證。

部署只重建同一API映像中的修正程式，不執行Migration、不更換資料庫或金鑰。沿用原容器環境，特別保留Threads HTTP=true，AI／發布／Worker=false；更新既有Windows恢復所登錄的容器ID與映像。部署前保留pg_dump、原容器、加密設定與恢復設定。Windows實測使用一次性記憶體登入，驗收用DRAFT在確認201與Key欄位後撤銷，測試Session登出；不刪除其他政策。

Key欄位只供安全配置，不等於已授權扣費。未呼叫真實模型、不發布Threads，不自行進入下一階段。
