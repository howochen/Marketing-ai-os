# P1.3 免費／開源選型

審查日2026-10-26。新增直接／間接依賴 **0**，requirements與constraints固定版本完全不變；實際漏洞結果 `p13/pip-audit.json` 無已知漏洞。未將未安裝候選宣稱為掃描通過。

| 需求 | 重用／授權 | 選擇理由 |
|---|---|---|
| 交易／原子預留 | SQLAlchemy2.1.6、Alembic／MIT | [官方2.1交易文件](https://docs.sqlalchemy.org/en/21/orm/session_transaction.html)仍列2.1.6為current；同Session提交原Ledger與batch投影，不另建資金帳本 |
| 租戶／持久化 | 既有固定digest的PostgreSQL16／[PostgreSQL License](https://www.postgresql.org/about/licence/) | [版本16官方RLS](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)仍在supported清單；本單不做大版本升級或RC導入 |
| API／合約 | 已有FastAPI、Pydantic／MIT | 既有角色／scope、extra forbid、strict整數、受信任actor，無新身份平台 |
| Mock HTTP | HTTPX0.28.1／BSD-3-Clause | 沿用既有Provider解析、固定MockTransport，無外部SDK、key或付款服務 |
| 回歸／型別 | pytest、mypy／MIT | 既有工具增加crash／並行／新程序測試，無另加故障注入framework |
| Executor／Recovery | Python stdlib、既有worker／scheduler | 不加Kafka、Celery、Redis、Kubernetes或大型Agent framework；少一套獨立計費與狀態系統 |
| Build／CI | 既有Docker、GitHub Actions | 重用既有環境，沒有採購主機／付費服務；Docker Desktop商用授權資格及Actions帳戶總帳單未另外核實 |

其餘既有版本／授權來源見 `DEPENDENCIES.md`、`P05_OPEN_SOURCE_REVIEW.md`、`P12_PROVIDER_RESEARCH.md`。本單未考慮新增套件，沒有以「最新」為理由升級已通過的工具。PostgreSQL授權開放使用不代表Docker Desktop或託管服務對所有組織均免付費。

標準庫＋現有DB transaction解決此單一受控executor的需求；若未來有跨機器真實工作排程需求，先以實測吞吐與失敗模式提出獨立工單，而不是現在引入常駐大型基礎設施。
