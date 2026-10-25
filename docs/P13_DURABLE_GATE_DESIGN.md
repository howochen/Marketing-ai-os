# P1.3 Durable Gate 設計

## 權限及持久化資料

TestBatch 儲存 id（batch_id）、tenant、test environment、後端產生的 synthetic authorization reference/status、實際 authorized_by Credential ID、assigned worker IDs、model allowlist、immutable rate snapshots、total/request micro-USD caps、request limit、reserved／estimated spent／request／uncertain counters、deadline、paused、created_at、closed_at。

建立時必須是已通過既有 hashed／expiring／revocable credential 驗證、具有 budget scope 的 tenant owner。所有 worker ID 都必須是該 tenant 的有效 test worker。deadline 在未來且不超過操作人授權到期與24小時；權限、模型、金額、期間固定不可覆寫。客戶端 authorization_reference/status/environment 欄位直接422；reference 由伺服器產生，永遠只有 SYNTHETIC_TEST_AUTHORIZATION。新的 admission／dispatch 再查原操作人是否已撤銷／過期，沒有把字串當成真實支出授權。

BatchAttempt 綁 tenant/batch/task、reserve worker、model/rate version/snapshot、fixed key／request hash、payload／scenario、預留額、已記成本、狀態／收據分類、持久化原結果／匯入結果、client/request/response ID、usage缺失原因／error category、lease與各階段時間／elapsed_ms。每 Task 只能綁一個 Attempt，tenant/batch/key 唯一；更改相同 key 的內容409。

同租戶read可用 `GET /batches/{bid}/attempts/{aid}/evidence` 查閱不可覆寫的收據差異；其他tenant404。ReconciliationEvidence 保存匯入人、MOCK來源、原／新估算與差額、完整合成 receipt、key／hash／時間。歷史 append-only；不是第二份資金帳本。所有帳務事件仍使用既有 CostEvent，MOCK_HTTP 一律 SETTLE_MOCK。

## 交易及狀態

先鎖既有 Tenant row，再讀 Batch／Task／Attempt，所有 Worker 使用相同鎖順序。admission 驗證 worker assignment、owner grant、期限、model／rate contract、request cap、batch cap、次數、tenant cap、Kill Switch 與 unknown freeze；同交易提交 Task預留＋Ledger RESERVE＋唯一Attempt＋Batch預留／名額＋Audit。失敗全 rollback，沒有依賴程序記憶體計數。

| 狀態 | 行為 |
|---|---|
| RESERVED | 原子建立即帶資金與名額，合併 CREATED 概念，避免可見的未預留半成品 |
| DISPATCHING | Task claim、client ID=attempt ID、lease、audit 先 commit，再做一次 Mock generation |
| PROVIDER_RESULT_RECORDED | 原始有效 receipt 先獨立 commit，不依賴之後結算成功 |
| SETTLED | 原 Ledger 結算、Batch reserved→spent、Task／QA／Revision、Audit 同交易 commit |
| RECONCILIATION_REQUIRED | 不明送達／用量、過期 dispatch 或收據差異；不重送，unknown counter凍結新 admission／dispatch |
| CANCELLED_BEFORE_DISPATCH | 已知未生成才釋放原 Ledger 預留；名額不退、不歸零，保留歷史 |

原結果與匯入結果一旦落盤不可替換。SQL trigger 拒絕非法轉換與 request_count 下降；授權、請求、費率、cap、deadline 不可改。舊 Task reserve/claim/execute/settle/release、原 A09 Runtime／rehearsal 都拒絕繞過 Batch coordinator。批准與人工修訂沿用原 Revision API，發布仍綁定已批准 Revision，永遠 MANUAL_REQUIRED。

Recovery 重用 `/maintenance/recover` 與現有 scheduler。已保存結果可直接結算，無第二次 HTTP；RESERVED lease或batch期限到期可取消；DISPATCHING lease過期只能標未知並保留款項。lease120秒是本地偵測參數，不是 Provider delivery 保證。assigned worker 可 Recovery；owner 關閉批次時也可處理該批次已知未送出的預留，即使 worker 已撤銷。close 不重置名額、不取消已送出的外部請求。

遲到結果若尚未由別的收據結算，可以直接記錄／結算原 Attempt；若 owner 先匯入合成收據，後續結果成為獨立 Evidence，保留原文及差額，正向差額經原 Ledger 補記並暫停。不得用新的 receipt 改寫已批准的 Revision；負向差額不自動退款，繼續待人工查核。

**DB 持久化不保證外部 exactly-once delivery。** 在 DISPATCHING commit 與實際發送之間崩潰，無法只靠 DB 判斷是否已送達；因此必須凍結，不能以 retry/fallback 補送。本階段沒有可開啟的 Live transport。

elapsed_ms 是本機觀測的 dispatch→result／失敗偵測時間；lease Recovery 的時間包含離線等待，不宣稱為供應商實際執行耗時。
