# P1.2 離線測試證據

來源 SHA `df40071a67b9ff16f340059b0fe2b4b439bcf02d`，起始工作目錄乾淨；從精確來源建立 `codex/marketing-ai-os-p1-2-provider-readiness`。P0–P1.1 核心測試保留，沒有重建 Runtime。舊 HTTP wire test 改用真正 MockTransport，原斷言保留；唯一 Live 測試明確封鎖，並未因新增 Provider 而放行付費測試。

| 檢查 | 本機結果／證據 |
|---|---|
| SQLite | **184 passed、1 skipped、1 live deselected**；`p12/sqlite.txt` |
| PostgreSQL 非特權 runtime role | **185 passed、1 live deselected**；`p12/postgres.txt` |
| mypy | 15 modules，PASS；`p12/mypy.txt` |
| 靜態 | compileall app/tests/migrations/scripts PASS；git diff --check／cached check 提交前確認 |
| 固定依賴漏洞 | 0 known vulnerabilities；`p12/pip-audit.json`；沒有新增套件 |
| Docker／新資料庫 | 新 mos-p12-test volume，0001→0006 migration、test/runtime image build；`p12/postgres.txt`、`p12/docker-startup.txt`、`p12/docker-health.json` |
| Mock benchmark | 12案例×2模型，24合成稿，格式 QA24/24；`p12/mock-benchmark.json` |
| 遠端 CI | [40206743183 success](https://github.com/howochen/Marketing-ai-os/actions/runs/40206743183)，exact SHA `482d52a9ef922b80b9218b11f917ee12cd06b46a`；`p12/remote-ci-summary.txt` |

SQLite 唯一跳過是 `test_postgres_all_tables_raw_isolation`，因 SQLite 無原生 PostgreSQL RLS；該案例與新表的原始 SQL 保護都在 PG 執行。Live marker 依預設 deselect，即使單獨指定也明確 skip。Starlette/HTTPX 棄用警告保留，沒有為消警告而升級依賴。起初 Docker Linux engine pipe 未就緒，啟動／確認 Docker 後才執行隔離卷測試，沒有以此略過 PG。

新增 `test_provider_readiness.py` 涵蓋：

- disabled／缺key／model allowlist／缺 MockTransport／production／live opt-in 全部零 HTTP；舊 Anthropic 也拒絕 real transport。
- 完整 prompt＋schema 計數、Token 不是 bytes、cache read/write 互斥、reasoning 不重複收費、usage缺漏／型別／總數異常不得結算。
- request／response／client trace ID、安全錯誤分類、timeout未知狀態保留預留與ID、拒絕盲重試；raw error含合成key也不洩漏。
- request cap／tenant budget／Kill Switch 在任何 HTTP 前阻擋；計數後 switch／expiry／disabled 阻擋 generation。
- 冪等請求、並行重複不重複扣款、並行總預算、完整超額記帳與自動暫停；歷史費率不因 config 變更重算。
- 同 tenant receipt read、跨 tenant404；Provider與費率身份不符422；reservation key不可換rate。
- truncated／refusal／invalid schema／未知工具的有效用量仍記已知成本，但不批准；未知費用特徵另停用等待對帳。
- owner 精確版本批准、worker不可批准、publication MANUAL_REQUIRED，舊多租戶／Ledger／Revision／Approval負面測試不退步。
- Live plan 各條件與停止上限；即使計畫有效也無 Live 授權；Benchmark空缺評分／人工時間不冒充0成本、重複case/model拒絕。

重現：既有 `requirements-dev.txt` 安裝後 `pytest -q`、`mypy`、`python -m compileall -q app tests migrations scripts`、`pip-audit -r requirements-dev.txt`。Compose 需合成測試密碼，`docker compose -p mos-p12-test --profile test run --build --rm tests`。不得把MOS_ENV改production、注入真實資料或透過任何測試試圖送出Live請求。

實際 CI 結果與本機一致：SQLite184／PG185／mypy15／0 known vulnerabilities，合成備份還原 job 也成功。最後文件提交仍核對其 exact SHA 的 CI，不以本次 run 代替另一個 SHA。
