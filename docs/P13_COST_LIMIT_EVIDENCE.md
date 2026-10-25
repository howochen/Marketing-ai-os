# P1.3 成本上限驗證

沿用 P1.2 fixed rate snapshots（公開文件查核日2026-10-25），本次沒有更新舊價格或呼叫供應商。重新驗證的是**離線受限契約**：A09完整 prompt／選定 skill／品牌 context＋JSON schema、input cap4096、output cap1024（含reasoning）、default tier、純文字、無工具、無prewarm／fallback／retry／區域功能。Batch snapshot、已安裝 RateVersion、目前 reviewed config 必須一致，任何未定價欄位／契約變化拒絕新 dispatch，無效 usage 轉待對帳。

預留公式沿用所有 input 以最貴已支援 cache write tier 計價＋最大 output；Luna為1536 micro-USD，Sol為30720。這些是 Mock 契約的保守預留，並非已驗證真實 Provider 帳戶、稅費、cache政策或帳單的上限；live_cost_bound_verified 仍false。

| 測試 | 證據／結果 |
|---|---|
| 最後一個名額 | 兩個 assigned Worker、8個競爭請求，只准1個；`p13/concurrency-last_slot.json` |
| Batch cap1600 | 8個並行請求，只准1×1536預留；`p13/concurrency-batch_budget.json` |
| Tenant cap1600 | 不因batch剩餘額足夠而超過tenant資金；`p13/concurrency-tenant_budget.json` |
| 相同 key 並行 | 唯一Attempt、一次名額、一次預留；內容不同409 |
| 程序重啟 | 新Python process讀同DB，仍count1／reserved1536；`p13/fresh-process.json` |
| Unknown freeze | timeout／5xx／無效或未知計價usage保留1536、uncertain1、新呼叫402／重送409 |
| 完整超額 | 預留1536、batch1600、tenant2000，合成成本2500完整記錄，pause batch＋tenant，不截斷 |
| 差額 | owner Mock proof200→300，原Ledger追加100；遲到結果對150補50至200，不改舊receipt／Revision |

Batch counters 是同一帳務交易的投影：reservations對應尚未結算／未取消Attempt，estimated_spent對應該批次原 Ledger SETTLE_MOCK／差額事件。測試核對 projections、Task費用與Tenant Ledger總和。count永不因取消、timeout或重啟退還。負向差異留Evidence與pause，不自動沖銷歷史或增加可花額度。

合成正常示例 `p13/normal-example.json`：1000 input＋200 output（含50 reasoning子集），合成費用200 micro-USD＝**USD0.000200**。Mock count endpoint回333，明確是合成Provider-schema count；不是UTF-8 bytes、local tokenizer估算或真實Provider回報。舊Mock bytes測試維持原標示，不混用。

本次真實模型呼叫 **0**、真實API費用 **USD0**、新增付費服務0、新增依賴0。各回歸會建立多份合成Ledger，不能將其加總當成API帳單。Codex token用量工具未提供；本機Docker與既有GitHub Actions資源／額度沿用，未取得帳戶總費用明細。

**本地 gate 只能控制接納／預留與已知結果記帳，不能保證外部供應商帳單絕對不超支。** 已送出請求、供應商不遵守上限、費率／tier變動、額外功能、帳單延遲或稅費可能使外部計費高於估算。已知超額必須完整記帳並停止後續呼叫；未知費用凍結待查。本單完全不送Live，不能把Mock安全上限當成真實支出授權。
