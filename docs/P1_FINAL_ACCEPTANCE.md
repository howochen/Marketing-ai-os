# P1 最終驗收 — MOS-P1-001

狀態：**PARTIAL / PENDING_REMOTE_CI**。本機實作與測試完成；exact候選SHA遠端CI成功後才改PASS。此文件不代表商用准入。

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
| I 測試 | 全部P0/P0.5＋A09安全/併發回歸；本機SQLite/PostgreSQL/type/scan/Docker通過，遠端待確認 |
| J 開源 | 新增直接依賴0，沿用固定工具鏈，無Agent/RAG/自動化框架 |
| K 文件 | 本目錄七份P1交付文件及raw evidence |
| L Git | 驗收候選需commit/push才能觸發CI；確定成功後記錄結果，最終SHA以Git與交付訊息為準 |

成本示例：1780 input +265 output Mock byte units，3105 micro-USD模擬費用，6900 micro-USD上界預留。真實模型0 calls/USD0；不憑空估Codex訂閱token。

尚未完成：真實語意生成品質、真實Provider收據/Invoice驗真、客戶/社群授權與發布、production TLS/IdP/備援、安全認證。Mock成功不能代表以上完成。

下一階段建議先加小型離線品牌/語氣/禁止宣稱evals與人工修訂版本追蹤；仍不增加自主agent群或真實發布。任何Live AI/Production Gate都必須另行授權。
