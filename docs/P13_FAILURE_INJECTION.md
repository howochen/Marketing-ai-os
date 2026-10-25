# P1.3 失敗注入與重啟證據

完整結果：`p13/sqlite.txt`、`p13/postgres.txt`；新增28項Durable Gate案例，加上全部P0–P1.2回歸。SQLite212 passed／1個原生PG RLS skip／1 live deselect；PostgreSQL213 passed／1 live deselect。mypy17模組、compileall、依賴掃描與Docker見 `p13/`。遠端CI狀態以最終驗收為準。

| 故障點 | 驗證結果 |
|---|---|
| RESERVED後關閉session／新程序 | count、amount不重置；固定key仍同Attempt；新slot被cap拒絕；可續跑原未送出Attempt |
| DISPATCHING落盤後BaseException | 模擬程序突然離開，未跑一般except補償；120秒lease後Recovery轉Recon、保留預留，不重發 |
| 結果commit後BaseException | PROVIDER_RESULT_RECORDED保存；重新Recovery只結算，不再呼叫Provider |
| Ledger flush後、commit前BaseException | 整筆結算rollback，Batch／Tenant沒有半套扣款；Recovery結算一次 |
| 兩次Recovery | 不重複release、不重複SETTLE_MOCK、uncertain counter不重複增加 |
| 遲到結果 | Recovery先凍結仍保留原結果；若已有owner proof，追加Evidence與正向差額，不替換原內容 |
| Count超input cap | 未生成，CANCELLED_BEFORE_DISPATCH，釋放資金但不退slot |
| refusal／truncated | 有效usage照記費，QA失敗、不能批准，沒有fallback |
| timeout／5xx／unknown receipt／unknown cost | 待對帳、freeze、資金保留、後續請求阻擋 |

`test_fresh_process_keeps_reserved_slot_and_amount` 真正以 subprocess 啟動新Python程序，讀取同一持久化SQLite／PostgreSQL DB；不是僅清掉Python變數。其他四個crash failpoint使用BaseException跳過補償及新Session重讀，驗證提交／rollback邊界；沒有宣稱模擬了主機斷電、磁碟損毀、網路分割或外部實際重複計費。

可重現：`pytest -q tests/test_durable_gate.py`。指定報告：`p13/crash-dispatching.json`、`p13/crash-result_recorded.json`、`p13/crash-settlement_uncommitted.json`、`p13/fresh-process.json`。沒有mock故障自動轉高價模型，所有HTTP都走固定MockTransport。

未知請求送達狀態無法靠本地DB推斷，禁止把DISPATCHING當成「一定沒送出」。對帳介面僅接收授權owner提交的合成MOCK proof，任何INVOICE_VERIFIED／真實provider來源都不接受；重複proof不能重複扣款。
