# P1.2 Token 與費用安全

六類資料分開，沒有互相換名：

| 類別 | 本次值與界線 |
|---|---|
| Mock bytes | 舊 MockLLMProvider 仍是 UTF-8 bytes／Mock units；既有 measurement 明確標示 |
| Local estimated tokens | NULL；沒有安裝 tiktoken，也沒有用 bytes 猜模型 Token |
| Provider reported tokens | 本次 NULL；Mock HTTP 只有 synthetic_provider_usage，雖符合供應商 schema 仍不是真實 Provider 回報 |
| Simulated cost | Mock HTTP usage × request rate snapshot；SETTLE_MOCK，與一般 Mock bytes 的來源可分辨 |
| Provider estimated billable cost | 本次 NULL；未發出真實請求，不造出供應商應付帳款 |
| Verified invoice cost | NULL；receipt 永遠 UNVERIFIED，沒有 invoice importer 或驗真 |

OpenAI input_tokens 是總 input，不可加上 cached/write 再重複收費。依 [官方 caching usage](https://developers.openai.com/api/docs/guides/prompt-caching) 分成 ordinary = total input − cached read − 30m write − 12h write；write 明細之和必須等於 cache_write_tokens，所有子分類不得超出總數。reasoning_tokens 必須 ≤ output_tokens，已包含在 output，不另加一次。缺欄位、負值、布林／字串冒充整數、未知付費欄位或不一致總數，都轉待對帳，不假造可信帳單。

費用全部用 Decimal 與整數 micro-USD：ordinary×input rate + read×cached rate + write30m×write30m rate + write12h×write12h rate + output×output rate，最後向上取整。mock fixture input=1,000（ordinary700、read200、write30m60、write12h40）、output200（含reasoning50）：Luna **190 micro-USD**，Sol **3,770 micro-USD**，都是模擬費用。

完整請求包含 A09／Threads／選定產業 Skill、品牌資料及 output JSON schema；計數走 Mock `responses/input_tokens`，不只計 brief。沒有可靠本地 tokenizer 故先預留全部本機 input cap 4,096，以最昂貴已支援 12h write rate 計算，再加 max output 1,024（含 reasoning）。上限：Luna **1,536 micro-USD**、Sol **30,720 micro-USD**。這是受限純文字契約的離線保守算式，不是對真實帳戶稅費、區域、工具、階梯或未知費用的保證；Live cost_bound_verified 保持 false。

預留在任何 HTTP 前鎖 tenant 並核對每次 cap、available budget、Kill Switch、已安裝 rate version。預留不足連 Mock count 也不發。生成前再檢查停止條件；沒有工具呼叫、prewarm、額外計費功能或 fallback。無法界定成本的功能不當成免費功能。

超額測試：預留1,536、租戶預算2,000，回報可計算成本2,500；**完整記帳2,500**、暫停 budget，不截斷成預留額。token 超限／未知工具／異常 tier 另標 RECONCILIATION_REQUIRED。Timeout／用量無效時無可信金額，保留預留款、追蹤 ID 與未知狀態，不盲重試。API／內部冪等 key、receipt unique constraint、tenant lock 維持，並行請求不突破預算；相同請求不重複扣款。

0006 的兩筆新卡與已執行 Task.snapshot 都不可覆寫；變動 runtime rate 設定不能回頭重算 Ledger。將來更新價格必須官方查核＋新 migration／新 hash，未安裝或費率身份不符拒絕執行；舊卡仍保留。

真實模型請求 **0**、真實模型 API 成本 **USD 0**。24 篇 Mock HTTP benchmark 的模型試算合計 **USD 0.047520**（Luna 0.002280、Sol 0.045240），人工時間／工資亦為合成輸入，不是實際薪資或供應商帳單。Codex Token 使用量未由工具提供；無新增付費服務或主機，重用本機 Docker 與既有 CI，Actions 額度／帳戶帳單未查核，不能宣稱所有帳戶支出為零。
