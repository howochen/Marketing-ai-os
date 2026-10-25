# P1 Agent 架構

## 執行與授權

app/agent_schemas.py 定義 strict Pydantic input/output，額外欄位不接受。輸入包括 task_id、agent_id、platform、industry、brand_profile、target_audience、campaign_goal、tone、brief、結構化 constraints；tenant_id 僅由 Credential context 取得。constraints 的 forbidden_terms、required_terms、max_chars 由 Python 可檢查；不是任意自然語言規則引擎。

app/agent_runtime.py 的 route() 是 A01 確定性路由；allowlist 為 A09/threads/mock-a09-v1，tools 為空。A21 qa() 是本地 JSON/schema、必要欄位、空白、長度、hook/CTA、品牌詞與禁止宣稱檢查。A23 使用 app.main 既有 ledger helpers，沒有第二套帳。

## 一條工作流

DRAFT → RESERVED → RUNNING → PENDING_APPROVAL；必要時 RELEASED 或 RECONCILIATION_REQUIRED。

先在 tenant lock 下讀 task；首次保存 input hash、idempotency key、prompt/hash/version、skill version、route、估算及 seed。DRAFT 自動 reserve；若 owner 已預留，必須 snapshot 存在且足夠，只重用一次。claim 使用 P0 CAS-equivalent tenant serialization，併發只能一方領取。

同 key+內容已完成時直接回傳完整已存結果，不做新的 token count/generation/settlement；同 key不同內容回409；RUNNING/待對帳不自動 retry。原 task.agent_id 與 path/body task ID 必須相符。

生成期間不持有 tenant write lock。最後在同一 ledger settlement transaction 保存 run result、Task.output JSON、receipt、usage、Mock 費用及 audit。owner-approved 狀態只由既有 /approve 控制，provider JSON 沒有權限更改。

## Prompt 邊界

系統級安全（[SYSTEM SAFETY]）→A09專業規則（[AGENT A09]）→Threads寫作 Skill（[PLATFORM RULES]）→server context tenant/task→不可信 request JSON（內含獨立 brand_profile 與單次需求鍵）。JSON 中角括號轉義，控制字元由 JSON encoding 處理；品牌字串無法在程式中變成工具／模型／授權設定。

只讀兩個固定 path，不接受 client 指定 skill/path，不讀其他23個角色的 prompt。完整最終 output schema 在 agents/A09/output.schema.json，由伺服器組裝 metadata；模型只可輸出 draft_text/hook/call_to_action，額外 approval/system/tool 欄位會造成 QA fail。

## Mock 與資源限制

MockLLMProvider 符合既有 LLMProvider count_tokens/generate protocol。固定 seed=0、無隨機取樣，依 prompt 的結構化欄位套固定模板，不是假裝已連上有語意理解能力的真實 LLM。品牌說明、產業、tone、brief 全保留於 prompt，但 Mock 模板不模擬完整寫作能力。

Mock token unit 明定為 UTF-8 bytes；input<=既有rate-card max_input_tokens(4096)，output<=request/global max_output_tokens(1024)。四個共用 Python threads 僅執行純 Mock，沒有工具與網路。生成等待 deadline 最長5秒（含領取後 pre-call 時間）；DB 仍受既有connect/statement/lock timeouts約束，不承諾整個HTTP5秒SLA。

Timeout 可取消排隊 future，不能強制停止已跑的 Python thread；遲到結果沒有 DB／外部 side effects，不會自行 settle。若日後允許不可信 executors，必須改成可終止的隔離程序，不能直接套此 thread 設計到付費工具。

## 計帳與發布

Task.rate_snapshot 不可變。模擬費率沿用該 snapshot 作 benchmark，不宣稱供應商對 mock-a09-v1 定價。receipt_source=MOCK、receipt_status=UNVERIFIED、CostEvent=SETTLE_MOCK；/budget aggregate 仍供預算保守控制，新增 Mock/非Mock分項，不當成真實發票。

所有平台 adapter 維持 manual_only。QA fail 保留原因、warnings、待人工修正／審核；沒有第二次模型改寫、沒有自動 approve，也沒有新增線上編輯功能。
