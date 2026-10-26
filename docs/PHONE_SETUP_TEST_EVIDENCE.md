# 一次性手機初始化：離線驗收證據

日期：2026-10-26；只使用合成憑證與隔離環境。沒有開放 ngrok 新入口，沒有真實 Meta／AI API 呼叫或貼文。

最終本機結果：Windows SQLite **344 passed／2 skipped／1 deselected**；Docker Linux PostgreSQL **343 passed／3 skipped／1 deselected**。手機初始化新增30個測試案例；mypy檢查28個來源檔案通過，pip-audit沒有已知漏洞。Docker測試映像已實際建置及執行。

隔離備份還原 PASS：20張表的還原指紋一致，合成快照遺失0列，4個失敗情境通過；備份0.450秒、還原與核對6.900秒，備份檔0600／目錄0700。這是本機快照演練，不能推論正式RTO／連續RPO。詳見 `phone-setup/backup-restore.json`。

| 檢查 | 證據 |
|---|---|
| Windows SQLite 全套 | phone-setup/sqlite.txt |
| PostgreSQL 全套與 FORCE RLS | phone-setup/postgres.txt；非 owner／非 superuser runtime role |
| 手機安全案例 | tests/test_phone_setup.py，含密碼學、租戶、越權、重放、並行與故障注入 |
| 真實 Windows DPAPI | 同測試模組的 native roundtrip；只在 tmp Vault 寫入，保存原 key 欄位 |
| 真實瀏覽器加密 | phone-setup/browser.json；Chrome Web Crypto 產生不可匯出 key，受認證註冊、換鑰拒絕、密文提交、Native DPAPI、提交收據全路徑 |
| 實際環境不變 | phone-setup/deployment-safety.json：原 Vault 密文雜湊一致，沒有 deployment；原服務開關亦核對 false |
| 型別／漏洞 | phone-setup/mypy.txt、audit.txt；沒有新增依賴 |
| 手機版空白 UI | phone-setup/screens、inspect/report.json；1440／768／390 無水平溢位；只在 Secret 欄空白時截圖 |

SQLite 會略過舊／新 PostgreSQL 專屬 RLS 兩案；Linux PostgreSQL 會略過 Windows DPAPI／native lock 等平台專屬案例，並由 Windows CI 補足。付費 Live 測試刻意排除。仍有原本的 Starlette TestClient/httpx deprecation warning，未因此升級整套依賴。

重現：`python -m pytest -q --tb=short`、`python -m mypy`、`python -m pip_audit -r requirements-dev.txt`；PostgreSQL 使用專用 `mos-phone-setup-test` project，不用原服務資料卷。備份演練的同名 project 白名單只准合成資料。

瀏覽器測試：`python tests/phone_browser_fixture.py` 只聽127.0.0.1:8891，使用忽略的 `.phone-setup-test`，強制隔離SQLite且移除既有 migration DSN。再執行 `node tests/phone_browser.mjs <design-taste-frontend技能目錄>`；僅此 fixture 有 `__offline` 測試控制點，runtime image 不含它。不可把測試 fixture 部署成公開服務。

審查修正：SQLite 不限制 varchar 長度，PostgreSQL 發現簽發者識別太長；已改為穩定 UUID 審計 actor，完整簽發者仍留在簽署 manifest。另補強 Native claim 前持久化、Native 再驗裝置簽章、Windows DPAPI 提交證明，不能只信任後端狀態字串。

沒有新增 SDK。沿用 cryptography50.0.2、HTTPX0.28.1 與現有鎖定依賴；Web Crypto 為瀏覽器標準。曾審查 python-fido2 的官方版本／授權，未採用：此需求未接 WebAuthn／硬體 attestation，不能為了名義上的身分驗證而加套件或自寫 WebAuthn parser。[Web Crypto 規格](https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/)、[python-fido2 官方專案](https://github.com/Yubico/python-fido2)，查核2026-10-26。

設計沿用既有 framed-sheet／IBM Plex Sans／teal 方向，不重抽視覺。物件只有裝置、授權、指定 App 及期限，無假營運指標。檢查三寬度空白畫面：一秒可辨識受限管理目的，認證前不顯示 Secret 表單；主觀自評設計7.5／易用8／內容9。量測 lint／inspect 0 FAIL、0 WARN，SHA256 固定寬度 hex 的 lint 誤判有明確功能理由註解。

真實 iPhone Safari、首次管理員註冊、真實 App 憑證與官方 OAuth **尚未驗收**。離線簽章／DPAPI 成功不等於已取得真實 Threads ID，也不等於可公開啟用。遠端 CI 以最終交付 SHA 實際結果為準。
