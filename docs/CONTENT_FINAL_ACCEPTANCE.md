# MOS-CONTENT-001：交付驗收

**本機人工內容工作流完成，離線回歸通過；實體iPhone Safari與正式部署未驗證。**

入口：雙擊 `Start-Content.cmd`，使用本機一次性登入碼開啟 `/app/content`。不需Swagger或操作API，即可完成「建立任務 → 人工撰寫 → 修訂 → QA → Owner核准 → 保存待發布計畫」。重用既有Task、Revision、QA、RBAC、Audit、Publication與前端。

已完成：需求表單、人工首版、既有文案快照、不可覆寫Revision、比較／還原另存、併發衝突保留輸入、逐項QA及語意UNEVALUATED、精確批准／撤銷審計、時區與計畫、等待帳號與待重核標示、繁中手機尺寸UI。

驗收：SQLite368通過、PostgreSQL367通過；新增24案例；mypy29來源檔、Docker、漏洞掃描與21表備份還原通過。[完整測試](CONTENT_TEST_EVIDENCE.md)、[API／Migration／安全設計](CONTENT_IMPLEMENTATION.md)、[繁體中文教學](CONTENT_WORKBENCH_GUIDE.md)。最終Commit與遠端CI實際結果列在交付回報，不能以本機成功代替遠端結果。

Migration0012只新增nullable brief與append-only計畫表，保留0011舊資料；沒有遷移原服務DB、修改DPAPI、OAuth或ngrok。原來源分支7504ae1保留。新分支codex/marketing-ai-os-content-workbench。

限制：需求在第一個Revision後鎖定；變更品牌限制需新任務。列表最多200筆。舊任務無輸出時不製造文案。計畫修正需另存，歷史保留。未儲存文字遇瀏覽器崩潰可能遺失；衝突不自動合併。Localhost不能由iPhone直接存取，手機HTTPS須管理員另行受控部署及驗證，這次沒有自動公開。

人工工作流真實AI呼叫0、模擬生成0、實際API成本USD0；測試回歸保留原有Mock測試，但不是實際模型帳單。沒有新增付費服務；tzdata原已鎖定，本次明列runtime以支援Windows時區。

模型／Threads發布／一次性手機通道均保持關閉；發布計畫不是自動發布。沒有宣稱真實AI品質、Threads發文、法規合規或商用營運成功。完成此階段後停止，不自動進入下一階段。
