# P1 離線開發 GO / NO-GO

目前：**NO-GO / PENDING_REMOTE_CI**，待本分支候選 SHA 的遠端 CI 真正成功後更新。來源 P0 CI 成功不替代本分支。

本機必要條件已通過：既有P0回歸、新濫用/憑證/費率/scheduler測試、PostgreSQL非特權RLS與併發預算、備份刪除合成資料後獨立還原、實際scheduler重啟、mypy/compileall、pinned依賴零已知漏洞、model/publishing預設禁用。

解除遠端CI阻擋後，GO 也**只允許離線、受控、合成資料的 Agent 開發**；不能使用付費 Live API、真實客戶／社群帳號或正式營運。這份文件不開始任何 P1 實作，後續工作仍需獨立任務授權。

Production NO-GO 持續成立：正式成熟 IdP/MFA/交付服務、真實部署 HTTPS/可信代理/DB TLS/秘密管理、供應商 Usage/Invoice 收據驗真、加密異地備份與PITR/SLA、正式負載/安全審查、真實平台 OAuth/permissions/webhook signatures 均未完成。這些不因 mock 通過而消失。

可重用元件與最小 Agent/Router 設計保留在 P1_READINESS.md；不要引入24個服務、Kafka/Kubernetes、RAG或自動發布。新P0.5環境限定credential、immutable rate snapshot、明確receipt status、scheduler與safe logs也必須重用。
