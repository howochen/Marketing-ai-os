# P1 安全審查

僅針對受控、合成資料 Mock runtime；Production NO-GO 繼續有效。

- 新 mutation endpoint 只接受 tenant-bound execute worker；owner/manager/reviewer 無權冒充 worker。原 approve owner-only、scope、expiry/revoke、IP throttling、production HTTPS guard 不變。
- task query 必帶 authenticated tenant，沿用 Task RLS/ORM guard。GET agent-run 包含敏感 prompt/輸出，只允許同 tenant read scope；另一租戶讀/執行均404。
- tenant_id 不接受任務自報，task ID 必須吻合 path。品牌描述中的 tenant/model/budget/approval/tool 指令只是 escaped JSON data；權限、route、工具空 allowlist 皆為程式控制，不解析模型要求作工具呼叫。
- 模型只有 mock-a09-v1，executor只有A09_THREADS_MOCK。未知agent422、未實作executor/platform501、非法model/tools422；沒有付費 fallback。
- enabled=false 時連Mock都503且無generate；Mock只允許development/test。Anthropic原 enabled/MOS_LIVE_TESTS/key guard未更動；本次fixture移除真實key並攔截任何live httpx.post/Anthropic.generate。
- 一次claim只生成一次；同key不同內容409，重複/並行不重扣；kill switch/budget/token超限拒絕新生成。未知結果持有款項、標RECONCILIATION_REQUIRED，不盲目重試。未知generation_calls記null而不是捏造0或1。
- Mock source明確標MOCK，永不VERIFIED，ledger分項不是付款證明。原成本/audit immutable、snapshot trigger、RLS沒有放寬。
- 完整schema及metadata為server-owned；模型輸出擅加approval=false會QA fail，不能更動Task.approved_by。QA fail仍待人工，owner日後明確審核不等於QA自動批准。
- 只記固定安全/失敗事件，不記prompt/raw provider exception；SQLAlchemy hide_parameters=True 防止DB錯誤trace輸出品牌/輸出 bind params。原SecretFilter、capsys/caplog敏感資訊測試保留。

## 已知限制

Mock模板不能證明真實LLM對Prompt Injection的抵抗力、語意品牌一致性或醫療/法律/廣告合規。QA是有限詞表/格式/長度規則，certification=RULE_CHECK_ONLY，並非正式認證。長度以Unicode code points計，不是官方平台整合驗證。

五秒future等待不會終止已執行Python thread；僅限純Mock、無工具/DB side effect的工作。未來真實executor須先處理process isolation、可取消工具、provider收據驗真與公開服務負載。若Mock結果未知，保留對帳狀態，沒有提供任意client自行釋放未知帳務的捷徑。

Task內的prompt/品牌資料雖然有tenant防護，仍屬應保護資料；本單只合成資料，尚無正式retention/加密/使用者內容秘密辨識政策。P0.5列出的IdP/MFA、實際HTTPS部署、DB TLS、備份異地/PITR、外部滲透等Production Gate未消失。
