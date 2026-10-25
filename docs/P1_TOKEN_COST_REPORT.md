# P1 Token 成本報告

本工單真實模型 API **0 calls / USD 0**，新增付費服務0。Codex per-task token 用量工具不可得：NOT_AVAILABLE；未推算訂閱費或混入 tenant ledger。GitHub Actions 使用既有帳號方案，未查CI帳單，不假定所有CI資源永遠免費。

## 固定 seed-0 合成範例

原始資料：p1/mock-cost-example.json；使用固定 synthetic-tenant 與固定 task ID。不是正式模型 tokenizer 或付款收據。

| 項目 | 數值 |
|---|---:|
| Mock input units（UTF-8 bytes） | 1,780 |
| Mock output units（UTF-8 bytes） | 265 |
| Mock usage 合計 | 2,045 |
| Output 上界預留 units | 1,024 |
| 最壞估算／預留費用 | 6,900 micro-USD = USD0.006900 |
| 依合成 usage 結算 | 3,105 micro-USD = USD0.003105 |
| 真實模型 API 成本 | USD0 |

預留值不等於花費；剩餘預留由既有 settle 釋放。fixture 的品牌名稱、audience、goal 及模板輸出可重現；真實 API task 使用 UUID tenant context，input bytes 可與這個固定示例不同，以每次保存的 usage 為準。

## 避免不必要 prompt 的對照

測試 spy 確認只讀 A09 system 與 Threads Skill 兩個檔案。對照 `prompt * 24` 是**明示的反事實冗餘基準**，不是其他23份真實 prompts 的量測：42,720 vs 1,780 Mock input units，避免40,940冗餘單位。不得把這個數字宣稱為真實供應商95.8%節省或真實24角色品質比較。

正常端到端流程只有1次 Mock generate，A01/A21/A23 為0次LLM呼叫；冪等重試為0新增generate/費用。單元測試為證明 provider deterministic，刻意直接呼叫同一 Mock 兩次；這不是工作流自我重試，也沒有真實支出。QA失敗不另呼叫模型改寫。

整套 suite 多次重跑與併發包含不同合成任務，沒有把其動態 ledger 加總成正式消費。每次 estimate、usage、cost_micro_usd、receipt ID、prompt version及elapsed_ms保存在 Task.agent_run/result。實際平台/tokenizer、cache折扣、invoice驗真及真實品質/成本 benchmark 都未在本單執行。
