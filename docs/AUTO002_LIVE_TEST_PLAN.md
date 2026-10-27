# 第一次真實 AI 測試：尚未執行

目前 **NO-GO 執行**：沒有另行支出授權、真實帳戶可用性證據，Token 計數端點費用亦未確認。本次沒有任何真實 Provider HTTP。
路徑已完成離線驗證；只有下列條件全部成立才可另行批准一次。

## 官方查核（2026-10-27）

- [gpt-6-luna 官方模型文件](https://developers.openai.com/api/docs/models/gpt-6-luna)：一般公開可用資訊；每百萬 input USD 0.10、cached input 0.01、cache write 0.125、output 0.50。沿用既有不可變 rate snapshot，不能改歷史費用。公開頁不證明使用者 org/project 有模型權限。
- [官方 Token counting](https://developers.openai.com/api/docs/guides/token-counting)：POST `/v1/responses/input_tokens`，有 `input_tokens`；本次可讀文件未載明該端點免費，**COUNT_ENDPOINT_FEE_NOT_VERIFIED**。不得把未標價格當免費。
- [官方 API overview](https://developers.openai.com/api/reference/overview)：組織／專案路由 headers、Provider request IDs；與許可 org/project 綁定。帳戶未實測，**ACCOUNT_ACCESS_NOT_VERIFIED**。

模型頁價格與本地 card 相符不代表可直接扣費。使用前須保存當時官方費率、計數端點零費用及帳戶模型權限的安全證據；未能證明計數零費用時，此版本拒絕正式核准，不能用 boolean 冒充查核結果。若該端點收費，必須先擴充原 Ledger 的費率／預留／收據支援並重新驗收，本次沒有把它視為免費。

## 一次許可範圍

`POST /ai-tests`（Owner 的 budget scope）包含：合成 Brief、唯一 allowlist `gpt-6-luna`、org-/proj_ 帳戶、input 1..4096、output 32..1024、最高 10000 microUSD（USD 0.01）、最長 30 分鐘且不超過當前 Owner Session 到期日。
只允許 **一次計數 HTTP + 一次生成 HTTP**，不是只發一個 HTTP。無 tools、fallback、retry、Threads 權限。
完整請求與 JSON schema 先計數；預留以完整 card input 上限4096、最高 cache write tier 及核准最大 output 保守計算。count 超限絕不生成。Provider output 限制包含 reasoning；實際回報超限仍完整入帳並停用預算。

`POST /admin/ai-tests/{id}/approve` 同時要求受信任管理端 Admin 與原 Owner 工作階段，核對：

- 精確 permit 綁定的 terms_hash。
- 獨立人類支出同意、帳戶權限、完整費用上界的三份 SHA256 證據（保存原證據於受控位置，hash 不代表系統自動查證）。
- `confirm_one_generation_only=true`。
- `count_endpoint_confirmed_free=true`，且 cost evidence 必須實際覆蓋計數端點；未確認不得填 true。

這是內部受信任操作者的 attestation，不取代本人同意或 Provider 帳戶驗證。相同 Tenant 不能重用同意 hash 批准另一許可；已批准條款及結果不可覆寫。REQUESTED 許可不能執行，舊 SYNTHETIC_TEST_AUTHORIZATION 不能升級。單次測試不授予任何持續政策。

## 另行批准後的操作順序（現在不要執行）

1. 由本人另准：一份合成品牌 Brief、指定 org/project／模型、最多一次生成、USD 上限與30分鐘期限。分別取得帳戶與費用證據。Secret 不貼聊天、不進 URL。
2. 使用全新隔離 Compose project `mos-ai-once` 與獨立 volume、備份現有環境但不更動；受控後端配置短效／限額 API Key，避免出現在命令列及終端輸出。沿用環境變數機制，不另建 Secret Store。不要執行 `docker compose config` 以免顯示 key，也不要把含 key 的 env 提交 Git。
3. `compose.yaml` + `compose.ai-test.yaml` 只啟動 `api` 及其新 DB/migrate 依賴，loopback `127.0.0.1:18886`，禁止 ngrok／公開代理及 automation profile。該 overlay 預設仍關閉兩個模型開關，沒有自行部署或啟用。
4. 以本機 Owner／Admin 分別完成上面 create、approve；一般 UI 不處理證據或模型 key。這是最小受控驗證 API 路徑，沒有新增公開 Live UI。
5. 只有本人確認「執行這一份許可」後，管理端啟用 `MOS_SINGLE_AI_TEST_ENABLED=true`、`MOS_MODEL_CALLS_ENABLED=true`、`MOS_ENV=test`、精確 `MOS_OPENAI_ACCOUNT_ID`／`MOS_OPENAI_PROJECT_ID` 與安全 `OPENAI_API_KEY`。Threads HTTP／publish、phone、automation 均保持 false。
6. Owner `POST /ai-tests/{id}/execute` 一次。資料庫先鎖定、預留 Ledger、扣除唯一名額並提交 DISPATCHING，才可送出 HTTP。CI／pytest 的真實 Transport 永遠拒絕；測試只能注入 MockTransport。
7. `GET /ai-tests/{id}` 與 Task receipt 核對 Provider IDs、原始 usage、input count、QA、預留與本地費用。只有 `provider_called=true` 的實際證據才算真實請求；輸出 QA 失敗仍是失敗，不代表已核准文案。
8. 關閉模型開關，撤銷短效 API key，保留審計。Timeout／5xx／異常 usage／中斷是 RECONCILIATION_REQUIRED，不再 execute、不用新許可繞過凍結。同 Tenant 未知／dispatching 結果會擋後續許可。由受信任人員查證費用後另行決定修復，不提供盲目重送按鈕。

Provider usage 是估算帳單，永遠 `invoice_verified=false`；本地成本上界不能保證外部帳單絕對不超支。價格變更、已送出請求、Provider 行為或帳單延遲仍有殘餘風險。
即使本次單篇 AI 驗證成功，也不啟用 Threads 發布或持續自動化。首次真實貼文必須另准精確帳號、Revision 與文字，使用既有 Publisher 並讀回真正 Media ID／網址。
