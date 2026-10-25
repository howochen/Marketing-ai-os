# P1.1 離線品質評估

資料版本 `a09-industry-evals-1`，rubric `a09-rubric-1`，固定 ID，無模型評審。原始資料與每筆判定理由見 `agents/A09/evals/v1_1/cases.json`；機器結果見 [eval-results.json](p11/eval-results.json)。

| 產業 | 案例 | 預期判定符合 | 文案通過硬性 QA |
|---|---:|---:|---:|
| 美容／頭皮 beauty_scalp | 10 | 10/10 | 3/10 |
| 餐飲 food | 10 | 10/10 | 3/10 |
| 租屋／不動產 real_estate | 10 | 10/10 | 3/10 |
| 電商 ecommerce | 10 | 10/10 | 3/10 |
| 教育 education | 10 | 10/10 | 3/10 |
| B2B b2b | 10 | 10/10 | 3/10 |
| 合計 | 60 | 60/60（100%） | 18/60（30%） |

每產業包含品牌語氣、客群、Hook、CTA、禁止詞、資訊不足、不可信輸入、誇大宣稱、剛好達長度上限、超出上限。42 個預期不合格文案被拒絕，18 個通過格式／詞彙規則；100% 指測試契約符合率，30% 指刻意混合負面案例的 QA 通過率，兩者都不是市場成效或真實文案品質。

第一層沿用 A21 確定性 QA：Pydantic schema／必要欄位、Hook／CTA 存在、長度、品牌禁止／必要詞、虛構發布／成效宣稱、系統冒充、Prompt Injection、資訊不足及選定產業的專業宣稱詞。硬性失敗不可批准，40/40 人工分數也不能解除。另有六產業專業宣稱負面案例，以及六產業各一次正常／不可信輸入的實際 Mock Runtime 測試。

第二層八維度皆接受嚴格整數 0–5 人工輸入：Hook、共鳴、品牌語氣、清晰度、CTA、平台原生感、創意、宣稱風險。人工評分記錄 HUMAN、rubric 版本、actor、理由及時間；它是授權使用者的輸入，不代表已認證專業評審。未輸入人工分數的主觀維度為 UNEVALUATED/null。四個 RULE 維度只是同一組格式／安全檢查的粗略 0/5 proxy，最高可評 20，不能被讀成完整 40 分語義品質。各維度說明及共用 0–5 anchors 在 rubric.json，沒有 AI 自動評審。

按需載入實測：[skill-context.json](p11/skill-context.json)。選定 beauty_scalp 的 prompt build 共讀 4 檔（A09、Threads、該產業 JSON／MD），其中產業 2 檔；假設讀全部六產業則產業為 12 檔。選定產業 MD 569 UTF-8 bytes，六份 MD 合計 3,481 bytes；示例 prompt 2,302 bytes。這是檔案／byte 比較，並非真實 Provider Token 節省量。QA 另按需讀同一產業 JSON，未讀其他五個產業。未知舊版自由文字產業不猜測別名，只沿用通用 QA，必須人工查證適用規則。

人工修訂可重現示例：[human-revision-example.json](p11/human-revision-example.json)。執行 `pytest -q tests/test_quality_revisions.py` 重建，示例去除隨機識別碼及時間，只保留合成文字、原因、diff 與 QA 結果；實際 DB 版本仍保存完整識別與時間。沒有證明成交率、廣告效果或正式商用品質。
