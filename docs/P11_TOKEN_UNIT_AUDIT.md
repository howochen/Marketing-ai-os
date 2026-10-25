# P1.1 Token 單位與成本審查

Mock Provider 原本 `count_tokens` 使用 UTF-8 bytes。本次沒有把 bytes 改名假裝真實 Token；保留相容欄位，新增 `measurement` 至結果及持久化 receipt。舊資料不補造真實計量；舊 report 的 `token_unit=MOCK_UTF8_BYTES` 仍適用。

| 欄位／單位 | 意義 |
|---|---|
| utf8_bytes.input/output | 實際編碼 bytes；漢字與 emoji 不等於一字元一 byte |
| mock_units | 本地測試規則：1 unit = 1 UTF-8 byte |
| legacy usage.input_tokens/output_tokens、input_tokens_estimate、max_output_tokens | 舊 API 相容欄位；Mock 路徑只代表 Mock units／上限，不可拿來作 Provider Token 報表 |
| vendor_tokens | NULL，沒有供應商回報 |
| model_specific_token_estimate | NULL，未安裝／運行特定模型 tokenizer |
| simulated_cost_micro_usd | Mock units 乘上 request 當時固定費率快照的試算；既有 Ledger SETTLE_MOCK |
| provider_cost_micro_usd | 0，真正模型請求數 0；不是已驗真帳單 |
| provider_called / reconciled | false / false，收據仍 MOCK／UNVERIFIED |

計量版本 `mock-bytes-v1`，來源 MOCK_LOCAL_TEMPLATE，執行模型 mock-a09-v1。`rate_version` 為既有不可變快照 hash；報告同時提供 reference_rate_provider/model、rate_source_url/effective_date 與 pricing_basis=MOCK_UNITS_USING_REQUEST_RATE_SNAPSHOT。參考費率模型名稱不是實際呼叫模型。歷史 rate card、整數 micro-USD 算法與預算保留，不改寫已記帳值。

實測示例 [measurement-example.json](p11/measurement-example.json)：input 1,817 bytes／Mock units，output 265，試算 3,142 micro-USD = **USD 0.003142 模擬費用**；真正 Provider 成本 USD 0、對帳 false。Unicode 單位測試：`漢😀` 是 2 個 Python 字元、7 UTF-8 bytes；沒有宣稱它是真實模型 7 tokens。每次 CI／回歸會產生額外合成 Ledger，沒有將所有測試試算加成 API 帳單。

官方免費工具研究（查核 2026-10-25）：[OpenAI tiktoken](https://pypi.org/project/tiktoken/) 0.14.0，2026-08-17 發版；[MIT 授權](https://github.com/openai/tiktoken/blob/main/LICENSE)。[官方 Cookbook](https://developers.openai.com/cookbook/examples/how_to_count_tokens_with_tiktoken) 說明 model-specific encoding；[Token counting 指引](https://developers.openai.com/api/docs/guides/token-counting) 區分本地純文字計算與請求計數。若將來使用，必須固定 tokenizer／encoding／模型版本，標註估算範圍，不能用 OpenAI encoding 推斷 Claude 或 Mock Token，也不能將本地文字計數當成多模態／工具完整請求或帳單。

本階段沒有需要支援的真實 OpenAI 模型，故不安裝 tiktoken、不下載 encoding、不加 API 計數端點。它未加入本次依賴漏洞掃描範圍；未主張候選套件零漏洞。真實 usage／cache token／invoice 對帳、供應商模型映射及費率更新審核仍為 Production Gate。

成本：新增依賴 0、付費服務 0、真實模型呼叫 0、真實模型 API 支出 USD 0；Codex 本次 Token 使用量工具未提供，不能以測試 Mock units 代替。重用本機 Docker、PostgreSQL 與既有 GitHub Actions，未採購主機；測試映像／獨立 volume 為暫時磁碟與 CPU 負擔，CI 可能消耗帳戶既有 Actions 額度，未查得實際計費明細，不能宣稱帳戶總費用零。
