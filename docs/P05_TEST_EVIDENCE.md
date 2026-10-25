# P0.5 測試證據

日期：2026-10-25 Asia/Taipei。僅離線、合成資料。

| 檢查 | 結果 | 原始證據 |
|---|---|---|
| SQLite 全套 P0+P0.5 | 36 passed / 1 skipped / 1 deselected，9.28s | p05/sqlite.txt |
| PostgreSQL 全套 P0+P0.5 | 37 passed / 1 deselected，7.45s | p05/postgres-final.txt |
| 初始全新 PostgreSQL volume / 0001→0003 | 成功 | p05/postgres.txt |
| mypy | 5 個模組成功 | p05/types.txt、mypy.ini |
| Python compileall、Compose config、Git whitespace | 本機成功，CI 另行驗證 | workflow、提交前檢查 |
| pip-audit pinned runtime + dev | 零已知漏洞 | p05/dependency-audit.json |
| 九表備份／獨立還原／四項拒絕案例 | PASS | p05/backup-restore.json |
| 真正 recovery process 重啟 | 1 次重啟、1 次 release、250000 micro 保留、0 model calls | p05/scheduler-process.json |
| /health、/ready | status ok/ready、schema 0003、model/publish=false | p05/health.txt |

SQLite 唯一 skip 是 PostgreSQL raw-RLS 測試；同一測試在 PostgreSQL 成功。live 測試明確排除，不供應任何真實模型 key。一項既有 TestClient/HTTPX deprecation warning 保留，不為消除 warning 引入另一個 HTTP client。

P0 全部既有測試原樣保留；tests/conftest.py 每個 case 清除 shared limiter 合成 counter，並標明 MOS_ENV=test。實際部署不清除 limiter。新測試在 tests/test_readiness.py：atomic counter concurrency/expiry、暴力登入429、管理員與worker隔離、environment-bound key、immutable price/request snapshot、config rollover 不重算舊帳、UNVERIFIED 收據、scheduler restart/kill-switch、production guard/HTTPS、ready/body-size、log exception遮罩、explicit receipt states、DB limiter失效503。P0原有到期／撤銷／replay／越權／八路預算及雙結算回歸持續通過。

## 遠端 CI

來源 SHA 的成功紀錄：[40125294300](https://github.com/howochen/Marketing-ai-os/actions/runs/40125294300)，head=0aed3c1229ac0c2d30a6e908f648ac9e96b3d852。這不是本分支驗收結果。

本分支候選 SHA **fab11e550ac89a9a31605ef324d01baf71e21a3f**：**REMOTE_CI_PASS**。[實際 run 40152338071](https://github.com/howochen/Marketing-ai-os/actions/runs/40152338071) status=completed / conclusion=success。sqlite 與 postgres jobs 均 success，包含 compileall、mypy、commit whitespace、pytest、pip-audit、非特權RLS、獨立 backup/restore drill 與 artifact。完整 metadata 在 p05/remote-ci.json，測試摘要在 p05/remote-ci-summary.txt。

後續收尾提交只更新此遠端證據與 GO 文件，不改程式碼；最後交付會另確認最終 SHA 的 workflow，不能把來源 P0 的成功混用。

## 成本及資料安全

Codex per-task token 計量工具未提供：NOT_AVAILABLE。真實模型 API 0 calls / USD 0；未新增付費服務。Mock usage/cost 僅用來驗證帳本，不是實際帳單。可重現 fixture 的單筆 100000 input tokens × USD 1/M = 100000 micro-USD 只是 mock；provider contract 10 input + 2 output + 10 cached input = 21 micro-USD 也是 mock。多輪測試會反覆產生合成帳本，不能加總成真實費用。

資源瞬間樣本：API 70.03 MiB / 0.16% CPU、recovery 20.53 MiB / 0.00%、DB 78.62 MiB / 2.52%，合計169.18 MiB；DB 9,124,887 bytes。證據 p05/resources.jsonl、database-size.txt。新增常駐程序僅 recovery（一個 tenant）；新主機 0。樣本含演練與測試後 cache，不是和舊版相同負載下的嚴格增量對照；不含 Docker VM／host、images、DR database sizes。CI 套用帳號既有額度，未查帳單，不假造 CI 費用為零。

固定 SHA 由 Git commit 識別；本文件無法包含自己的 commit hash。以 `git log -1 --format=%H -- docs/P05_TEST_EVIDENCE.md` 及最終交付訊息確認，不能拿來源 SHA 當成已完成修改的 SHA。

## P0.5 必要驗收結論

**PASS（受控離線基礎設施範圍）**：原P0回歸與新增測試、RLS/併發預算、遠端CI、實測備份/程序重啟、預設關閉模型/發布、固定版本/掃描與提交前檢查均完成。P1僅離線開發 GO；Production NO-GO 不變。這不是商用安全驗證。
