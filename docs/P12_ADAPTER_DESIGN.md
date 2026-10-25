# P1.2 Adapter 設計與範圍

`app/openai_provider.py:OpenAIProvider` 結構上符合既有 LLMProvider（count_tokens/generate），沒有重建 A09 Runtime。只支援非串流、單次 Responses、純文字 input、嚴格三欄 Draft JSON、固定兩個 API model ID、低 reasoning、default tier、無 tools／conversation／background／fallback。`config/openai-readiness.json` 為本次 allowlist 與查核費率，request 使用它的深拷貝快照。

**沒有公開 OpenAI generation endpoint，也沒有 Live transport。** Adapter 要求 enabled、MOS_ENV=test、MOS_LIVE_TESTS=false、有環境 key，且 transport 的實際型別必須是 httpx.MockTransport。普通 Client、HTTPTransport 或空 transport 都拒絕。測試只注入合成 key；HTTPTransport 亦被測試 monkeypatch 成禁止網路。環境變數不能將測試自動轉成 Live。

`app/provider_rehearsal.py:rehearse` 是內部測試 harness：驗證 worker execute scope，同 tenant 鎖定 Task，使用既有 reserve／claim／settle_receipt。先用 rate card 的全部 4,096 input cap、最貴受支援 cache write 類別及最大 output 算保守預留，再做完整 prompt＋JSON schema 的 Mock count；count 超限拒絕生成。計數後再次檢查 Kill Switch、Task status／expiry；generation 不重試。CopyRequest 仍是既有 A09 品牌內容 context，真實 Adapter model 由伺服器物件的 allowlist 決定，不開放 client 改變 Runtime 路由。

Timeout 是 connect 5 秒、read/write/pool 20 秒，無 redirects、環境 proxy 或自動 retry。HTTP 400/401/403/429 分別分類為 request/auth/access/rate-limit；5xx、其他協定狀態、timeout、無效 JSON 或 usage 為未知結果。回傳固定錯誤分類，不抄送錯誤 body、API Key 或原始 exception。這些錯誤不觸發較貴模型 fallback。

回應保存原始 body response ID、x-request-id、自己送出的 X-Client-Request-Id，以及 provider usage 原形與標準化計價欄位。ID 有長度／字元與 secret-redaction 檢查；不安全 ID 不落盤。未知結果在 Task.receipt 保存可得的安全追蹤 ID、錯誤分類、usage=null；沒有 usage 就不編造扣款，仍保留預留款及 RECONCILIATION_REQUIRED，重送同 Task 拒絕。追蹤 ID 的用途參照 [官方 request debugging](https://developers.openai.com/api/reference/overview)。

有效 usage 即使遇到 truncated/incomplete、refusal、無法解析 Draft 或輸出 schema 錯誤，仍完整計算模擬用量與 Ledger，產生不可批准的硬性 QA 結果。未知工具或非 default tier 不當成免費：記錄已知 token 成本、標記 billing anomaly／RECONCILIATION_REQUIRED 並啟動 Kill Switch，額外未知費用不假裝已對帳。超出回報 token limits 也停止後續呼叫。有效輸出仍只到 PENDING_APPROVAL，owner 必須批准指定 Revision，佇列永遠 MANUAL_REQUIRED。

Mock HTTP 產生 MOCK_HTTP receipt source、SETTLE_MOCK Ledger、MOCK Revision，不進入非 Mock 支出。`GET /tasks/{id}/receipt` 需要同租戶 read，含資料庫 RLS／ORM 既有保護；跨租戶不洩漏存在性。Log 仍僅記 allowlist event／ID，不記品牌文案；OPENAI_API_KEY 納入現有遮罩。

Schema **0006** 只新增兩筆 frozen RateVersion seed，沒有刪表或改寫歷史；migration 內嵌固定 JSON，不讀會變動的 runtime config。新增 reserve 的可選 rate_version 只准 test 環境挑選已審查的 readiness 卡，舊請求預設不變；同 key 不可切換費率。結算 provider 與 model 必須同時匹配 snapshot。原有 rate snapshot／Ledger append-only 與 tenant transaction 保留。

舊 Anthropic Adapter 也改為只接受 test 環境 MockTransport，保留舊 wire-contract 斷言、60 秒 timeout 與歷史計價。舊 live test 改成明確跳過，不再偷偷啟用 feature flag。這是本工單刻意收緊的安全行為，不代表正式 Anthropic 新模型接入已完成。

尚未實作正式串流／工具／SDK、真實模型帳戶存取、可信 receipt importer、發票驗真或多供應商切換；不需為此新增常駐服務。
