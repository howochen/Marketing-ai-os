# P1.5 Live Test Gate 計畫（P1.2 不啟用）

**現在 NO-GO。** 這張工單沒有任何實際支出授權。MOS_MODEL_CALLS_ENABLED／MOS_LIVE_TESTS、環境 key、測試命令或文件中的金額，都不能構成另外授權。兩個 Adapter 都拒絕真實 transport；既有 `-m live` 測試明確 skip，絕不自動切成 Live。

`app/live_gate.py:LiveTestPlan` 是可測的計畫驗證器，不是網路授權器。必須有 controlled-test 環境、非空另外授權識別、精確兩模型 allowlist、單次與整批 micro-USD cap、執行次數上限（最多24），且確認可靠成本上界。拒絕 tools、fallback、retry、社群發布。每次驗證 spent＋reserved＋本次 bound ≤ batch cap 且本次 ≤ request cap，次數未滿、Kill Switch 未啟動、無未知結果。資料缺失或成本不可界定即拒絕。

即使計畫完整，validate_attempt 只回傳 PLAN_ONLY_NOT_EXECUTION_AUTHORIZATION／live_transport_enabled=false；enable_live 永遠拒絕。測試中的 SYNTHETIC 授權字串只檢查欄位與阻擋規則，不能證明有人同意花錢。沒有新增可透過環境變數開啟的旁路。

未來需要另外工單／人類明確授權的執行程序：

1. 指定總 USD 上限、每篇上限、帳戶、模型 API ID、24次以內的批次／期限、停止條件及負責對帳的人；授權識別需由受控配置／人類審核綁定，不接受客戶端自稱已授權。
2. 重新查核當日官方模型可用性、實際帳戶 tier、費率／context／cache write／reasoning／區域／稅費及 count endpoint 參數。模型 alias 不等於永遠固定行為，記錄回應 model ID、日期與版本；無可靠前置上界時整批 NO-GO。
3. 實作並審查持久化 batch reservation／execution counter：在 DB 原子交易中扣 slot＋預留 cap，程序重啟、並行與未知結果不可重置額度。現有 tenant Ledger 已原子化，但計畫驗證器本身不提供 durable batch 執行器，**本項尚未完成**。
4. 僅限合成資料、單一 text request、無工具／第三方功能、無自動 fallback；timeout／5xx／解析失敗先保留款項與追蹤 ID 待對帳，retry=0。達 batch cap／次數或 Kill Switch 即停止後續 request；不假設能取消已送出的請求。
5. 先驗證數次極小額請求與 usage／費率對帳，再經明確同意擴展至12案例×2模型；任何 schema／安全 QA 失敗不得自動批准。人工 revision／指定版本 owner approval 與 MANUAL_REQUIRED 一律保留。
6. 實際 Provider usage 與帳戶 invoice 由可信 importer 驗真，才能填 verified invoice cost；未驗真只可稱 provider-estimated，不可稱已核實帳單。全批保留 raw安全ID、快照、對帳狀態及停止紀錄。

沒有先替使用者選擇「可直接扣款」的小額金額。本次 Benchmark 的預留算式只是規劃資料；P1.2 PASS 不代表上述 Production／P1.5 前置條件已完成。
