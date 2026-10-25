# P1 測試證據 — MOS-P1-001

來源P0.5 SHA：0ff9fc22543d79478d7cc819a9d7a59610c28e5d。只在新分支 codex/marketing-ai-os-p1-agent-runtime 開發，合成資料、無Live AI。

## 本機驗收

本機 SQLite：60 passed / 1 skipped / 1 deselected（14.62s）；PostgreSQL：61 passed / 1 deselected（10.40s）。原始紀錄見 p1/sqlite.txt / p1/postgres-final.txt。全部原P0/P0.5測試保留；只調整readiness schema斷言0003→0004。SQLite的PostgreSQL專用RLS單一skip為預期，同一測試在PostgreSQL通過；live明確deselect。

新增 tests/test_agent_runtime.py 覆蓋：正常A09文案與全schema/ledger存檔、未實作agent/platform、model/tool/tenant allowlists、角色越權、另一租戶prompt/輸出隔離、停用模型、kill switch、budget/input cap、八路重複及八任務budget競爭、輸入注入無工具權限、QA schema/空白/hook/長度/品牌詞/系統冒充、QA不自動批准、provider timeout與future deadline、重試不生成、無敏感log、既有reservation重用、SQL參數隱藏、按需檔案讀取spy與固定seed成本對照。

原測試繼續驗證 credential到期/撤銷、RLS七表raw SQL、不可變audit/cost/rates、mock以外結算、防重複receipt、scheduler、production guard與四平台manual_only。

mypy擴大到7個模組，見 p1/types.txt。pip-audit固定runtime/dev零已知漏洞，見 p1/dependency-audit.json。Docker test與runtime image均成功建置，包含Agent/Skill檔案；實際server /health預設false、/ready schema0004，見 p1/docker-health.txt。Python compileall及提交前diff/secret-pattern檢查另留記錄。

## 遠端 CI

**PENDING_REMOTE_CI**：需推送本分支候選commit，確認exact headSha、兩套suite、mypy、掃描與既有backup drill實際成功後，才完成最終PASS。不以來源P0.5成功替代。

## 可重現合成案例

Fixture在 agents/A09/evals/threads.json；輸出/成本示例在 p1/mock-cost-example.json。Mock文字：

> Demo Studio，讓日常多一點靈感。
> 為creative students帶來新的選擇：Explore a new notebook。
> 歡迎留言分享你的想法。

這是合成草稿，不是已發布貼文。正常API結果保存在同tenant的agent-run與Task.output，待owner明確審核。真實API 0 calls / USD0；Mock與Codex使用量分開，詳見 P1_TOKEN_COST_REPORT。
