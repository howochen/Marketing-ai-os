# MOS-PUB-002 測試證據

2026-10-26，僅離線 Mock／合成資料；來源 SHA `2d653c0475fa840ca7ce0458ee601f3c3869f4b9`。

| 驗收 | 結果與證據 |
|---|---|
| SQLite 全套 | 288 passed、1 skipped、1 deselected；pub002/sqlite.txt |
| PostgreSQL 全套 | 289 passed、1 deselected；非 owner／非 superuser mos_app，RLS 實測；pub002/postgres.txt |
| 新增 UI／安全測試 | tests/test_social_ui.py，13 cases；含 Cookie／CSRF、管理員分離、同瀏覽器 OAuth callback、明確版本確認、防重複、跨 tenant、worker 禁止操作 owner、偽造 Cookie、憑證失效與有界刷新 |
| 既有 Threads 發布 | tests/test_threads_publisher.py 37 cases，完整回歸包含；保留並行發布、防重複、崩潰與未知結果凍結、Token 遮罩及不可變版本 |
| mypy | 24 modules 通過；pub002/mypy.txt |
| 語法／靜態 | compileall app/tests/migrations/scripts、node --check app/web/app.js 通過 |
| 漏洞 | pip-audit -r requirements-dev.txt：No known vulnerabilities found；pub002/audit.txt |
| 密鑰檢查 | 高可信模式掃描非忽略文字檔 + 人工 diff；未發現真實密鑰；pub002/secret-scan.json。不是完整秘密偵測保證 |
| 瀏覽器 | 真實 headless Chrome、12 responsive views（4頁×3寬度）、不可變預覽；pub002/browser.json／screens |
| 設計量測 | lint 與 inspect 皆 0 FAIL／0 WARN；pub002/inspect/report.json，人工圖像審查見 PUB002_DESIGN_REVIEW.md |
| Docker | runtime/tests image 建置、全新合成 volume migration 0001→0010，/health、/ready、/app 與資產 HTTP 200；pub002/docker-health.json |
| 備份還原 | 18 tables 指紋一致、0600／0700、4負面檢查通過；備份1.70秒、還原含核對14.02秒、快照資料零遺失；pub002/backup-restore.json |

SQLite 跳過的唯一案例是資料庫強制 RLS，SQLite 不具 PostgreSQL RLS，已由 PostgreSQL 全套實際執行補足。Live 模型測試依 pytest 的 `not live` 排除；不是漏測後宣稱成功。既有 Starlette TestClient/httpx deprecation warning 仍存在；本次不為單一警告升級整套相依。

可重現指令：

```powershell
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m mypy
.venv/Scripts/python -m pip_audit -r requirements-dev.txt
.venv/Scripts/python -m compileall -q app tests migrations scripts
node --check app/web/app.js
docker compose -p mos-pub002-test --profile test run --build --rm tests
$env:MOS_DRILL_PROJECT='mos-pub002-test'
.venv/Scripts/python scripts/backup_drill.py
git diff --check
```

Docker 測試先配置獨立合成 POSTGRES_PASSWORD／MOS_APP_PASSWORD／MOS_MIGRATION_PASSWORD／MOS_ADMIN_KEY；不得沿用客戶 volume。備份演練只准白名單專用 project；重跑須依文件選新的隔離測試資料庫，不能刪既有客戶資料。數字只代表本機快照演練，不是營運 RTO／RPO 保證。

瀏覽器回歸：先依 UI guide 啟動專用 preview，再 issue-code，使用 `node tests/ui_browser.mjs <design-taste-frontend技能根目錄>`。`ui_inspect.mjs` 透過實際一次性登入表單建立 Cookie 後呼叫技能 inspector，不在 runtime 新增測試免登入路徑。完整測試不會操作官方帳號。

遠端 CI：`.github/workflows/ci.yml` 執行 SQLite、mypy、compileall、diff、漏洞與 PostgreSQL/RLS、Docker、備份；三個 Threads 旗標全關閉。此文件提交時不預先宣稱遠端成功；最終 Commit SHA 的實際結果與連結由最終交付回報，亦可在 GitHub Actions 查對該 SHA。
