# Threads測試證據

本次所有Threads HTTP都是httpx.MockTransport，並禁止底層真實HTTPTransport。37項新增測試：OAuth state/cookie/expiry/replay/owner revoke、Token密文／跨Tenant驗真／refresh、發布兩步與不同ID、未批准／版本快照、不同角色／Tenant與原生RLS、雙worker競爭、POST timeout/5xx/429/非法ID、崩潰後新Session不重送、Recovery冪等、GET暫失敗及僅讀回重試、明確公開true、Log遮罩與CI/pytest禁止Live。

重新執行：python -m pytest -q；python -m mypy；python -m compileall -q app tests migrations scripts；pip-audit -r requirements-dev.txt；docker compose -p mos-pub-test --profile test run --build --rm tests。環境密鑰全部是合成測試值；禁止放真實Meta App Secret/Token。原P0–P1.4測試必須持續通過。

SQLite原生PG RLS測試跳過是引擎限制，不當成隔離已通過；PostgreSQL使用mos_app非owner／非superuser／NOBYPASSRLS角色，新增表需實測42501寫入拒絕。付費模型live標記刻意deselect；Threads真實transport另外以CI／PYTEST_CURRENT_TEST硬性拒絕，Mock來源不能宣稱OFFICIAL_API驗證。

本機／Docker／掃描／18表備份與遠端CI的最終數值待執行完成後補入。docs/threads/保留原始結果；輸出只正規化行尾空白以通過git diff --check。排程／取消測試不執行，因工單指定必須先真實立即發文成功，前提尚未成立。

## 本機最終結果

| 檢查 | 結果 | 證據 |
|---|---|---|
| SQLite全部 | 275 passed、1原生PG RLS skipped、1模型live deselected | threads/sqlite-final.txt |
| PostgreSQL全部 | 276 passed、1模型live deselected；新表RLS42501 | threads/postgres-final.txt |
| 新增Threads案例 | 37項，含相同Container/Media ID拒絕、三種commit後權限失效、容器續用／到期 | tests/test_threads_publisher.py |
| mypy／compile | 22模組無錯；compileall PASS | threads/mypy.txt |
| 依賴漏洞 | No known vulnerabilities found | threads/dependency-audit.txt |
| Docker build／startup | PASS；schema0009、HTTP/publishing=false、無Threads密鑰、live guard拒絕 | threads/postgres-docker.txt、docker-startup.txt、docker-health.json |
| 合成備份／獨立還原 | 18表指紋一致；備份1.527秒、還原含核對14.338秒、0600/0700、4項負面檢查 | threads/backup-restore.json |
| Git／密鑰 | diff檢查及pattern scan；不代表Production audit | threads/secret-scan.json |

第一次29項版本全套267/268通過、加入容器狀態後33項版本271/272通過，均保留初始建置紀錄；最後採用275/276為本單完整驗收值。三個權限快取回歸使用Core UPDATE不更新既有ORM identity，驗證發送前確實重讀而非靠舊物件判斷。最後全套已包含所有37項。Starlette提示HTTPX TestClient將來需升級，尚未為此重構既有依賴。

實際遠端CI40218909368已驗證實作SHA 2e6ddf479bf24dad9d8404c451e4435bdef004f9：兩個jobs成功，完整275/276、mypy22、漏洞掃描及18表還原均成功。原始metadata與摘要見threads/remote-ci-candidate.json／remote-ci-summary.txt；最後文件SHA的CI另於交付回報精確核對。真實Threads HTTP／公開發布0，真實模型API0，實際AI費用USD0。以上Mock token與ID皆合成，無任何Live驗真含義。

threads/new-tests-final.txt是加入權限快取回歸時的36項補測；其後相同Container/Media ID負面例加入後，最終37項已完整包含在sqlite-final.txt／postgres-final.txt（275／276），不以中間補測數量取代全套結果。

本工單的mos-pub-test API／DB容器已停止，保留資料卷及備份；其他專案不變。GitHub Actions仍有原有Node20 action強制Node24與ubuntu-latest更換映像的提示，本單未為警告新增依賴或修改main；工作流顯示快取名稱P0 checks，驗收以headSha與jobs實際狀態為準。
