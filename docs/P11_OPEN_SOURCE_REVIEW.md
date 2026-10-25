# P1.1 開源與成本選型

新增直接／間接套件：**0**；requirements／constraints 沿用已固定版本。[既有授權及維護決策](P05_OPEN_SOURCE_REVIEW.md)、[依賴清單](DEPENDENCIES.md)。本次固定集合掃描未發現已知漏洞，原始結果 `p11/pip-audit.json`，不代表未來或所有安全問題不存在。

| 問題 | 採用的現有方案 | 免費成熟替代 | 付費方案／決策 |
|---|---|---|---|
| 版本歷史／差異 | SQLAlchemy + Alembic + stdlib difflib | 外加版本管理套件 | SaaS CMS 不需要；三張小表即可保持歷史、RLS 與交易 |
| 60 案例與規則 | pytest/Pydantic + 版本化 JSON | 外加 eval framework | 付費 LLM judge 不採用，離線 synthetic 評分不應偽裝真實模型評審 |
| Rubric／人工輸入 | Pydantic 嚴格 0–5 + append-only 分數 | 自建表單框架 | 未開發新 UI／付費評審服務，已有 API 足以受控驗收 |
| 計量 | stdlib UTF-8 byte 長度 + 明確來源欄位 | 官方 tiktoken 0.14.0 / MIT | 真實計數 API／第三方成本平台不必要；不安裝 tokenizer，Mock 無可對應的 vendor encoding |
| 行業規則 | 固定 allowlist 的 JSON + SKILL.md 按需讀 | 額外設定管理庫 | 不加 CMS／向量庫／RAG，不能用產業常識覆蓋品牌事實 |
| 權限／一致性 | 既有 FastAPI、PostgreSQL RLS、tenant lock | 現有開源資料庫能力 | 無需新身份平台、Redis、Kafka 或大型 Agent framework |

[tiktoken 官方 PyPI](https://pypi.org/project/tiktoken/) 查核 2026-10-25：0.14.0（2026-08-17）顯示持續發版；[官方 MIT license](https://github.com/openai/tiktoken/blob/main/LICENSE)。它是模型特定 tokenizer，本地文字計數不能驗真帳單，無法直接適用 Claude／Mock。候選未安裝也未執行其依賴掃描；未來採用時需針對固定版本重新掃描與 encoding 來源審查。詳細界線見 [單位審查](P11_TOKEN_UNIT_AUDIT.md)。

產業資料為自行撰寫合成注意事項，未複製官方文章。[FDA cosmetics claims](https://www.fda.gov/cosmetics/cosmetics-labeling/cosmetics-labeling-claims) 作美容效果詞參考；[FTC advertising basics](https://www.ftc.gov/business-guidance/advertising-marketing/advertising-marketing-basics) 作證據與誠實廣告的一般參考；[NYC real estate advertisements](https://www.nyc.gov/site/fairhousing/rights-responsibilities/real-estate-advertisements.page) 作房地產歧視用詞警示參考。每個 JSON／MD 有來源、檢查日期與版本，均是美國參考，不是臺灣或其他營運地的合規認證。

未引入常駐 24 Agent、模型評分服務、向量資料庫、真實發布、顧客訂閱或多供應商切換。這些沒有本階段驗收價值，也會增加費用與攻擊面。
