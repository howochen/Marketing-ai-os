# MOS-CONTENT-001：測試證據

查核日期2026-10-26。只使用隔離資料與合成品牌；人工工作流是真實HTTP／資料庫流程，不是靜態Mock畫面。

| 驗收 | 實際結果／檔案 |
|---|---|
| Windows SQLite全套 | **368 passed／2 skipped／1 deselected**，110.42秒；content/sqlite.txt |
| Docker PostgreSQL全套 | **367 passed／3 skipped／1 deselected**，92.05秒；content/postgres.txt |
| 新增內容測試 | **24案例**；tests/test_content_workbench.py，包含Task CRUD、原始人工Revision、舊草稿快照、QA負面、語意未評估、精確批准、撤銷、並行編輯／核准、Tenant、時區／DST、計畫、不可覆寫、原0011資料升級及本機啟動器 |
| mypy | 29來源檔通過；content/mypy.txt |
| 依賴漏洞掃描 | 沒有已知漏洞；content/audit.txt |
| 編譯／JS語法／diff | compileall、node --check、git diff --check通過 |
| 真實瀏覽器操作 | content/browser.json、tests/content_browser.mjs；127.0.0.1真實HTTP，原HttpOnly Cookie／CSRF及SQLite |
| 三尺寸視覺 | 1440／768／390，無水平溢位、無console error；content/screens、workbench-inspect.json；沿用既有framed-sheet／IBM Plex Sans／teal，未換框架 |
| Docker／全新遷移 | tests image實際建置，非owner／非superuser runtime role通過FORCE RLS；migration head0012 |
| 備份還原 | content/backup-restore.json，21表指紋一致，0列合成快照資料遺失，4個失敗檢查；備份0.850秒，還原核對6.295秒；0600檔案／0700目錄 |
| 原環境保護 | content/environment-safety.json；原Vault密文雜湊一致、原DB未遷移、原服務未部署，模型／發文／手機通道仍false |

SQLite略過2案是PostgreSQL專屬RLS，PostgreSQL略過3案是Windows DPAPI／原生鎖；Windows CI另驗證Windows平台測試。1個付費Live案例明確排除。既有Starlette TestClient/httpx deprecation warning仍存在，不因此大幅升級套件。

瀏覽器從登入表單開始，實際點擊：建立需求 → 手動文案 → QA FAIL不能批准 → 修訂 → Owner批准 → 保存等待帳號計畫 → 新版使舊計畫待重核 → 任意版本diff → 舊版另存 → 模擬409保留未儲存文字。畫面與資料皆為合成內容，不含App Secret、Token或真實品牌。沒有用固定AI模板假裝生成。

量測沿用設計技能的app模式與規則，對已認證工作台實際執行probe／layout／app及judge；三寬度均0 FAIL／0 WARN。未登入的既有登入頁留白警示不當作工作台量測。主觀自評設計7.5／易用8／內容9，非真實使用者研究。

發現並修正：重複重新渲染可能清掉排程輸入；Docker測試映像漏帶新增啟動器。上述修正後已重新跑完整回歸，沒有保留失敗輸出冒充成功證據。

## 重現

Windows：`.venv\Scripts\python -m pytest -q --tb=short`；mypy及pip-audit使用requirements-dev.txt。PostgreSQL：設定僅測試用MOS_ADMIN_KEY／POSTGRES_PASSWORD／MOS_APP_PASSWORD／MOS_MIGRATION_PASSWORD，執行 `docker compose -p mos-content-test --profile test run --build --rm tests`。這是獨立project，不可改成原mos-threads-local。

在相同隔離PostgreSQL上執行 `MOS_DRILL_PROJECT=mos-content-test python scripts/backup_drill.py`（Windows使用PowerShell環境變數語法）。演練建立獨立source／restore DB，不觸碰原服務資料卷；重複演練要用新的乾淨專用測試project或管理員核對合成DB名稱，不能刪原資料卷來省事。

瀏覽器：執行 `python tests/content_browser_fixture.py`，再 `node tests/content_browser.mjs <design-taste-frontend技能目錄>`。fixture只綁127.0.0.1:8892、使用忽略的.content-test，沒有額外公開控制路由；測試有既有合成管理憑證，只能本機測試，不能部署。自動化使用獨立headless profile，不使用使用者Chrome設定檔。

GitHub Actions會針對最終SHA執行Windows、SQLite、PostgreSQL／Docker、mypy、漏洞掃描及備份還原；以交付連結的實際結果為準。沒有透過修改main／來源分支取得通過。

**未驗證實體iPhone Safari或WebKit引擎**；390寬Chromium操作不能取代它。沒有實際AI、Threads OAuth或發布驗收，也沒有正式營運／第三方滲透測試結論。備份時間是本機合成演練，不是正式RTO／RPO承諾。
