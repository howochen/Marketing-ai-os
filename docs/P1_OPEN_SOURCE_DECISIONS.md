# P1 免費／開源選型

新增直接依賴：**0**。requirements.txt、requirements-dev.txt、constraints.txt 沿用 P0.5 exact pins；新模組僅使用現有套件與 Python stdlib。

| 問題 | 採用 | 不採用理由 |
|---|---|---|
| Input/output contracts | 已有Pydantic BaseModel/JSON schema | 不加新JSON schema套件或供應商SDK，伺服器可直接validate輸出 |
| Router/QA | Python確定性allowlist與規則 | 不用付費模型判路由或反覆QA，不加LangChain/LangGraph/CrewAI |
| Mock provider | 既有LLMProvider interface＋stdlib json/hash | 無網路、固定seed/輸入，無需API key、付費服務或模型SDK |
| 預算及receipt | 既有SQLAlchemy/Alembic/PostgreSQL Ledger | 不複製財務抽象、不加queue/Redis、保留RLS與交易 |
| 執行時間 | stdlib四thread pool、future deadline | 只為純Mock提供等待上界；不建24個Agent服務或通用workflow engine |
| Prompt/Skill | 本機固定路徑、按需讀兩份小檔案 | 沒有RAG、向量庫或把其他23份Prompt一併載入 |
| CI/scan/type | 既有pytest、mypy、pip-audit、GitHub Actions | 沿用固定工具與license決策，不為新工具而新增依賴 |

既有版本與授權來源見 P05_OPEN_SOURCE_REVIEW.md / DEPENDENCIES.md。付費平台、OpenAI adapter及真實SDK的接入沒有本階段必要性，因此連額外adapter實作/大型設計都未加入。後續只有在獨立授權、可量測需求及Production Gate滿足時再研究官方協定，不能默認啟用。
