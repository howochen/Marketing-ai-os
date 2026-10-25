# MOS-P1.2-001 最終驗收

**PARTIAL — 等待遠端 CI**。離線本機驗收通過，尚不可宣稱整單 PASS。

交付分支 `codex/marketing-ai-os-p1-2-provider-readiness`，來源 `df40071a67b9ff16f340059b0fe2b4b439bcf02d`。main／develop／原 P1.1 分支不修改。提交與最終 SHA 的 CI 結果在推送後核對，不以舊成功摘要替代。

| 驗收 | 證據 |
|---|---|
| 當日官方模型／費率／SDK研究 | `P12_PROVIDER_RESEARCH.md`，2026-10-25，OpenAI與Anthropic官方來源 |
| OpenAI Adapter | `app/openai_provider.py`，兩個模型allowlist、Mock HTTP only、IDs／usage／cache／reasoning／schema／錯誤分類 |
| 保留 Runtime／Ledger／安全 | `app/provider_rehearsal.py` 重用既有流程；原測試持續通過 |
| Token與計價安全 | `P12_COST_AND_TOKEN_SAFETY.md`；未把bytes當Token，費用分類、不可變snapshot、超額／未知結果回歸 |
| 獨立 Live Gate | `P12_LIVE_TEST_PLAN.md`, `app/live_gate.py`；計畫驗證不授權Live，真實transport永遠拒絕 |
| 六產業12例／兩模型規格 | `P12_MODEL_BENCHMARK_SPEC.md`, `agents/A09/evals/p12/benchmark.json` |
| Mock報表 | 24篇合成，QA格式24/24，人工分數／時間皆合成；`p12/mock-benchmark.json` |
| SQLite／PostgreSQL | 184 passed＋1原生RLS skip；PG185 passed；各1 live deselect，`P12_TEST_EVIDENCE.md` |
| mypy／static／scan／Docker | mypy15 modules、compileall、0 known vulnerabilities、Docker隔離測試；`p12/`原始紀錄 |
| 遠端 CI exact SHA | 待推送驗證，阻擋 PASS |
| 密鑰與範圍 | 提交前 diff／密鑰掃描，僅合成資料，沒有真實密鑰／customer data／社群操作 |

新增依賴0、付費服務0、真實模型呼叫0、真實模型 API 成本USD0。Mock benchmark模型費用USD0.047520是試算，人工費用亦為合成；不是實際帳單。Codex使用量工具未提供。

**P1.5小額真實測試：NO-GO。** 沒有另外支出授權，沒有真實帳戶可用性／計費完整上界核對、durable batch gate、可信 usage/invoice reconciliation；模型品質也尚未實測。完成本單仍不構成商用就緒、正式環境安全認證或真實客戶發布授權。允許後續離線完善 gate／評測工具。

保留限制：只處理固定純文字非串流契約；真實模型可能有 schema／refusal／截斷差異，未知 billing usage 欄位須先對帳；模型alias與價格可能變更；lexical QA不能保證語義／專業宣稱安全；人工synthetic分數不代表模型品質。所有原有 Production Gate 仍適用。
