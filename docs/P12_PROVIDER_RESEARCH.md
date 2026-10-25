# P1.2 Provider 官方文件查核

查核日期：**2026-10-25（Asia/Taipei）**。本次只讀公開文件；沒有用金鑰查詢帳戶、模型清單或任何模型 API。下列是官方文件列出的 API ID，不等於已驗證本帳戶有存取權。價格是 USD／百萬 tokens、第一方標準短 context，不能套用至所有區域／服務層級。

| API ID | Input | Output | Cached input | Cache write | 文件 |
|---|---:|---:|---:|---|---|
| `gpt-6-luna` | 0.10 | 0.50 | 0.01 | 30m 0.125；12h 0.25 | [模型](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| `gpt-6.1-sol` | 2.00 | 10.00 | 0.10 | 30m 2.50；12h 5.00 | [模型](https://developers.openai.com/api/docs/models/gpt-6.1-sol) |
| `claude-haiku-5-5` | 0.10 | 0.50 | 0.01 | 5m 0.125；1h 0.20 | [模型](https://platform.claude.com/docs/en/models/haiku-5-5/overview) |
| `claude-sonnet-5-5` | 2.00 | 10.00 | 0.10 | 5m 2.50；1h 4.00 | [模型](https://platform.claude.com/docs/en/models/sonnet-5-5/overview) |

[OpenAI pricing](https://developers.openai.com/api/docs/pricing)、[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) 是費率來源。Haiku 5.5 上表僅限 prompt ≤100,000 tokens；超過時 input/output/cache hit 分別為 0.50／2.50／0.05，write 為 0.625／1.00。OpenAI 長 context、Fast／Ultrafast、Flex／Batch、區域處理與額外工具有不同計價；不包含在本 Adapter。表內 OpenAI 12h 為費率與 usage 解析項目，不代表本次請求啟用該選項。

OpenAI 兩個模型頁列 context 1,050,000、max output 128,000；Anthropic 兩個模型頁列 1M／128K。這些是官方上限，不是本系統允許值；本次仍限完整 input 4,096、max output 1,024。OpenAI RPM／TPM 隨帳戶 tier，不以不存在的固定數字代替；[rate limits](https://developers.openai.com/api/docs/guides/rate-limits)。Anthropic 也依組織／模型 tier 分 RPM、ITPM、OTPM，[官方 limits](https://platform.claude.com/docs/en/api/rate-limits)。帳戶實際限制與可用額度未驗證。

OpenAI 使用 Responses API；[API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)、[structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)。解析 body `id`、header `x-request-id`、`usage.input_tokens/output_tokens/total_tokens`、`input_tokens_details.cached_tokens`、cache write lifetime 明細及 `output_tokens_details.reasoning_tokens`。`max_output_tokens` 包括可見輸出與 reasoning，不能將 reasoning 再加收一次 output。Luna 可用 `none`，Sol 不支援 `none/minimal`；共用 Adapter 明確選 `low`，未傳 temperature。工具可能另收費，故 tools 固定空陣列。

OpenAI [prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)：read、30m write、12h write 分開計算，input 總數包含這些互斥分類。命中不能靠本地猜測。生成請求使用文件共同支援的 `prompt_cache_options={mode:explicit,ttl:30m}`，沒有 breakpoint／prewarm。官方 create reference 與 caching guide 對 TTL 可用性描述不完全一致，保持 Live 關閉，未據此承諾實際帳單。完整請求計數參數另外查核 [count reference](https://developers.openai.com/api/reference/cli/resources/responses/subresources/input_tokens/methods/count) 及 [官方 SDK count params](https://github.com/openai/openai-python/blob/main/src/openai/types/responses/input_token_count_params.py)：傳 model/input/text/tools/reasoning，不傳 count endpoint 未列的 cache options、store 或 max_output_tokens。

Anthropic [Messages](https://platform.claude.com/docs/en/api/messages/create) 使用 body id、model、usage.input_tokens/output_tokens、cache_read_input_tokens/cache_creation_input_tokens；request-id header 用於診斷。[Thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking) 為 billed output 的一部分，明細可見 output_tokens_details.thinking_tokens；不可額外重複收費。[Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) 的 `output_config.format` 支援 Haiku/Sonnet 5.5，但本單沒有把新 Claude 模型接到 Runtime。Web search 等 server tools 可能另計費，不能忽略 server_tool_use。現有舊 Claude rate card 保留作歷史記帳，不以新價重算，也不允許發出 Live 請求。

繁體中文 Threads：這些是可納入未來短文案評測的文字／結構化輸出候選，成本定位有差異；是否符合臺灣品牌語感、Hook、CTA 及專業宣稱要求只能由 12 案例＋人工評分查證，**本次未驗證語言品質或市場成效**，不因模型較貴而推論較優。

## 免費工具與維護選型

| 選項（本日查核） | 版本／授權／維護 | 決策 |
|---|---|---|
| [官方 OpenAI Python SDK](https://pypi.org/project/openai/)／[官方介紹](https://developers.openai.com/api/docs/libraries) | 3.37.0，2026-10-22，Apache-2.0；有型別、結構化 helper，當前使用 HTTPX2 | 不新增；本次兩個非串流 REST 契約現有 HTTPX 足夠，避免增加依賴及預設重試行為 |
| [HTTPX](https://pypi.org/project/httpx/) | 已固定 0.28.1，BSD-3-Clause；最新 stable 同版，另有 1.0.dev6 預覽 | 重用 MockTransport／Client；不為本單升級預覽版。現有 Starlette 棄用警告保留 |
| [tiktoken](https://pypi.org/project/tiktoken/) | 0.14.0，2026-08-17，MIT；模型特定 encoding | 不安裝；未驗證選定兩模型的完整 request/schema 編碼映射，不以 bytes 或任意 encoding 估計真實 Token |
| 大型 Agent framework／多模型代理／付費評審 | 無本階段必要性 | 不採用；使用既有 Python、Pydantic、SQLAlchemy、Alembic、pytest |

新增依賴 **0**。本次漏洞掃描覆蓋現有固定 requirements／constraints，不表示未安裝 SDK 或 tiktoken 已通過安全掃描；將來採用須重新固定版本、查核授權並掃描。
