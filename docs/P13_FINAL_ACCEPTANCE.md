# MOS-P1.3-001 最終驗收

**P1.3 PASS（僅離線、Mock HTTP、合成授權）**。本機與實際遠端CI均成功，不授權Live或Production。

來源 `eb15715244009f1386176d6055224b1a8a52d083`，分支 `codex/marketing-ai-os-p1-3-durable-gate`。新表／API／worker僅離線合成資料，不修改main/develop或前階段分支。實作提交 `e0cfbe5b5bcfcf5de5a22a0a86de4981d008a08f` 已推送並通過 [CI 40211352227](https://github.com/howochen/Marketing-ai-os/actions/runs/40211352227)。其後只補證據／文件；最終SHA及其CI以交付回報與GitHub headSha為準，避免文件自我參照。

| 驗收 | 證據 |
|---|---|
| Synthetic授權／固定範圍 | `P13_DURABLE_GATE_DESIGN.md`、create_batch／DB CHECK；client reference不生效 |
| 原子Batch／Tenant／次數預留 | 共用Tenant鎖與原Ledger，同交易更新；三份`p13/concurrency-*.json` |
| Durable狀態／重啟／不盲重試 | 新程序及四crash階段、遲到收據測試；`P13_FAILURE_INJECTION.md`, `p13/fresh-process.json` |
| 成本／超額／未知結果 | 完整2500記帳、pause、保留未知預留、差額追加原Ledger；`P13_COST_LIMIT_EVIDENCE.md` |
| QA／Revision／發布 | 沿用A21、不可覆寫Revision／精確批准、MANUAL_REQUIRED；新舊安全測試 |
| SQLite | 212 passed、1原生PG RLS skip、1 live deselect；`p13/sqlite.txt` |
| PostgreSQL | 213 passed、1 live deselect；non-owner/NOBYPASSRLS，raw insert42501；`p13/postgres.txt` |
| 型別／靜態／依賴 | mypy17模組、compileall、0 known vulnerabilities；`p13/mypy.txt`, `p13/pip-audit.json` |
| Docker／migration | fresh mos-p13-test volume、0001→0007，runtime／test build；health/readiness PASS、schema0007；`p13/docker-health.json`、`p13/docker-startup.txt` |
| 備份還原 | 專屬合成專案15表指紋一致、0600/0700、4負面檢查；`p13/backup-restore.json` |
| 遠端CI exact SHA | [40211352227 success](https://github.com/howochen/Marketing-ai-os/actions/runs/40211352227)，SQLite／PG／mypy／scan／15表backup全部成功；`p13/remote-ci-candidate.json`、`p13/remote-ci-summary.txt` |
| Secret／範圍 | diff／cached check通過，密鑰模式掃描無發現；`p13/secret-scan.json`。沒有真實key或客戶資料 |

SQLite唯一skip是原生PostgreSQL RLS測試，在PG實際執行；新表raw RLS亦在PG驗證，不能用SQLite ORM冒充。Live測試明確deselect，real transport未啟用。Starlette/HTTPX既有棄用警告保留，沒有為消警告改依賴。

正常合成示例1200個Provider-schema token-shaped units／USD0.000200試算，預留USD0.001536；不是真實Token或帳單。真實模型呼叫0、真實API成本USD0、新增依賴0、付費服務0；Codex用量工具未提供。

**P1.5 NO-GO，Production NO-GO**，五個分開判斷見 `P15_LIVE_GO_NO_GO.md`。本地預留無法保證外部帳單絕對不超支，也不保證外部exactly-once；真正費率與帳戶、支出授權、Invoice驗真及正式營運安全尚缺。

本機備份實測：backup約0.835秒、restore＋15表驗證約9.556秒，snapshot rows lost0；只代表本次無同時寫入的合成snapshot，不是正式RTO／連續RPO保證。最後的error category／usage missing reason欄位亦通過`p13/durable-final.txt`全部28項回歸。
