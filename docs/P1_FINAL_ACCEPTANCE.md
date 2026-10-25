# P1 最終驗收 — MOS-P1-001

狀態：**P1 PASS（僅離線 Mock Agent Runtime）**。本機SQLite60通過/1合理skip、PostgreSQL61通過，7模組mypy、掃描與Docker建置/啟動通過；程式碼 SHA 81c646ef7595a5c6dc5254c7cf8a273d871cad2c 的遠端CI 40154859877已實際success。此文件不代表商用准入或真實AI驗真。

| 工作單 | 實際交付 |
|---|---|
| A 來源及准入 | SHA與乾淨工作目錄核對，P0.5離線GO，指定新branch |
| B Registry/路由 | A01 deterministic allowlist，只有A09 executor，A21 QA/A23 Ledger無LLM |
| C 文案 | Threads strict input及完整server-owned output，其他平台NOT_IMPLEMENTED |
| D Prompt/Skill | versioned A09 system/output schema/evals，按需Threads skill，escaped untrusted data |
| E Adapter | 新Mock符合既有Protocol，Anthropic guard不改；固定seed，不需key，MOCK/UNVERIFIED |
| F 成本 | 估算＋immutable snapshot、一次generate、時間/usage/receipt、冪等並行、未知結果持款 |
| G QA | 格式/必要欄位/長度/品牌詞/宣稱/系統冒充規則，無二次模型、無自動approve |
| H 工作流 | DRAFT→RESERVED→RUNNING→PENDING_APPROVAL，原owner審核及MANUAL_REQUIRED |
| I 測試 | 全部P0/P0.5＋A09安全/併發回歸；本機SQLite/PostgreSQL/type/scan/Docker及exact程式碼SHA遠端CI通過 |
| J 開源 | 新增直接依賴0，沿用固定工具鏈，無Agent/RAG/自動化框架 |
| K 文件 | 本目錄七份P1交付文件及raw evidence |
| L Git | 驗收候選需commit/push才能觸發CI；確定成功後記錄結果，最終SHA以Git與交付訊息為準 |

成本示例：1780 input +265 output Mock byte units，3105 micro-USD模擬費用，6900 micro-USD上界預留。真實模型0 calls/USD0；不憑空估Codex訂閱token。

尚未完成：真實語意生成品質、真實Provider收據/Invoice驗真、客戶/社群授權與發布、production TLS/IdP/備援、安全認證。Mock成功不能代表以上完成。

下一階段建議先加小型離線品牌/語氣/禁止宣稱evals與人工修訂版本追蹤；仍不增加自主agent群或真實發布。任何Live AI/Production Gate都必須另行授權。

提交與推送：程式碼候選分支已實際推送origin；最終文件證據commit在同一分支，完整SHA由 `git log -1 --format=%H` 與最後交付確認。來源P0.5 SHA保持0ff9fc22543d79478d7cc819a9d7a59610c28e5d。
