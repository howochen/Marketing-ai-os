# P0.5 模型成本與收據設計

保持 integer micro-USD，沒有浮點帳本或付費 API。reserve/settle/release 與 tenant lock、idempotency、receipt uniqueness 沿用 P0。

## 不可變費率

0003 rate_versions 保存 provider/model/effective_date/source_url/snapshot。ID 是本地 canonical JSON 的 SHA-256，**不是捏造的供應商 price ID**。初始版本沿用 P0 rate card，source URL=https://platform.claude.com/docs/en/models/haiku-4-5/overview，生效日2026-10-25為本地卡生效日，並非廠商變價日。本工單沒有重新宣稱即時費率。

runtime 只能讀 rate_versions，update/delete/truncate 有 DB trigger；SQLite 同樣拒絕 update/delete。新版本須由經審查的 migration append 新 row，再切 config，不能改舊 row。active config 的 hash 沒有安裝就拒絕新 reserve。

reserve 時複製 request snapshot 到 task，第一份 snapshot 之後由 ORM 與 DB trigger 禁止變更；CostEvent 記 rate_version。外部 mock receipt 按當時 snapshot 計價，改 config 不會重算舊帳。內建 adapter 若卡與 request 版本不符會拒絕生成，避免以不同費率送出，需人工決定新任務／對帳。舊 P0 task 沒有歷史 snapshot 時不回填假歷史版本；保留 nullable metadata／UNVERIFIED legacy 限制。

## 驗真與成本的區分

ReceiptStatus 明確支援：UNVERIFIED、VERIFIED、RECONCILIATION_REQUIRED。來源區分 TRUSTED_WORKER_ASSERTION 與 PROVIDER_RESPONSE_UNVERIFIED，對外 task list 可辨認 receipt_status/source。

**所有現有結算預設 UNVERIFIED**。可信 worker 權限代表允許提交 usage，不代表供應商已驗真。內建 HTTP response 同樣不是 invoice confirmation。VERIFIED 預留給日後獨立 verifier／供應商帳戶/invoice 對帳；本工單沒有能讓 client/worker 自行升級狀態的 API，也沒有宣稱已核實帳單。

spent_micro 是保守預算扣用、按 snapshot 算出的 usage estimate。它不是已核實付款。金額大於 reservation 必須完整記錄並 pause tenant，不能截斷成 reservation；未知結果保留款項、標待對帳，不能自動盲目 retry。重複 receipt/key 不重扣；錯誤後不把 held funds 當新可用預算。

## Production Gate

需要驗證 provider account/request ID、完整 usage token categories、實際 rate tier/region/discount、effective-time、invoice line、currency及 rounding，並保存驗真 evidence reference／actor/time，採 append-only verification event 追蹤。不能直接覆寫原 ledger，不能讓 rate 更新改歷史金額。

現卡只支援 standard 與5m cache-write，沒有1h cache或特殊tier；內建 provider 不送 cache-control。本工單所有 token/cost 測試為 Mock。正式 Usage/Invoice 對帳與 paid smoke 需另行授權，仍是 Production Gate。
