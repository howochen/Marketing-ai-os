# MOS-P1.1-001 最終驗收

狀態：**PARTIAL — PENDING_REMOTE_CI**。本機驗收已通過；遠端新 SHA 成功前不得宣稱 PASS。

範圍：離線、受控、合成資料。來源 `cc23f454e1414315714efc7b2695583619939f3f`，交付分支 `codex/marketing-ai-os-p1-1-quality-evals`。提交 SHA 與遠端 CI 將在推送後記錄；來源分支保留。

| 要求 | 結果與證據 |
|---|---|
| 六產業至少 60 例 | 60／60 預期判定符合，原稿 QA 18／60；`P11_EVAL_REPORT.md`, `p11/eval-results.json` |
| Rubric／評分來源 | 八項 0–5；HUMAN／RULE／UNEVALUATED 明確區分；`agents/A09/evals/v1_1/rubric.json` |
| Revision 不可覆寫 | ORM + DB update/delete 拒絕，PG truncate 拒絕；`tests/test_quality_revisions.py` |
| 批准與佇列精確版本 | 新稿清除批准、舊稿歷史保留、publication FK／內容 trigger；`P11_REVISION_SECURITY.md` |
| 多租戶／角色／並行／注入 | API 負面測試 + 非特權 PG raw RLS；既有並行預算回歸保留 |
| SQLite | 142 passed、1 skipped、1 live deselected；`p11/sqlite.txt` |
| PostgreSQL | 143 passed、1 live deselected；`p11/postgres.txt` |
| 型別／靜態／漏洞 | mypy 11 modules PASS，compileall PASS，pip-audit 0 known；`p11/mypy.txt`, `p11/pip-audit.json` |
| Docker／migration | runtime/test build PASS，health／ready schema 0005；`p11/docker-startup.txt`, `p11/docker-health.json`；0004 舊內容保留回歸 |
| 備份歷史 | 合成專案 12 表完整指紋一致，檔案0600／目錄0700、4負面檢查；`p11/backup-restore.json` |
| 遠端 CI | PENDING_REMOTE_CI，需本分支實際 GitHub Actions success |
| 真實 API／服務 | 模型 0 calls、USD 0；無新依賴／付費服務；`P11_TOKEN_UNIT_AUDIT.md` |
| Skill 按需／單位分離 | 產業2檔 vs 全部12檔；569 vs 3,481 bytes；`p11/skill-context.json` |

SQLite 跳過的唯一測試是 `test_postgres_all_tables_raw_isolation`：SQLite 沒有原生 RLS，不能用 ORM 測試冒充 DB 隔離。它在 PostgreSQL 完整執行；新表的原始 SQL RLS 檢查也在 PG 執行。付費 live test 明確 deselect，沒有藉由執行真實 API 換取通過。Starlette 提示 HTTPX 棄用，測試仍通過；此警告保留待相容性升級，不新增 httpx2。

備份本機實測 backup 約 0.391 秒、restore + 12 表驗證約 3.437 秒，snapshot rows lost 0。只代表這次無同時寫入的小型合成 snapshot，沒有 PITR、連續 RPO 或正式 RTO 保證，不能接觸客戶資料卷。

提交前 git diff --check 通過；已檢視變更範圍並掃描密鑰／私鑰格式，沒有真實密鑰發現，見 `p11/secret-scan.json`（模式掃描並非完整安全認證）。遠端 CI 證據待推送後補齊。版本識別採 Git commit 及 CI 的 headSha，不以文件內自我參照假造最終 SHA。

下一階段：**NO-GO，等待遠端 CI**。即使離線 GO，也不授權真實客戶發布或正式營運。未解風險包括詞彙 QA 不具完整語義判斷、人工評分非專業驗證、真實 Token／Provider invoice 未對帳、正式身份供應商／加密備份／營運地合規與正式環境安全驗證未完成。
