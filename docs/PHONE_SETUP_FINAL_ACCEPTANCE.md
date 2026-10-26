# 一次性手機初始化：交付判定

日期：2026-10-26。離線開發及隔離驗收完成；**公開啟用 NO-GO，尚未部署**。

重用既有 Windows DPAPI、Docker、Threads OAuth、管理員認證及租戶隔離。沒有新增依賴、付費服務、登入平台或 Threads Adapter。實作限於指定 App ID／Secret，不能寫入任意環境變數或執行管理指令。

受認證管理員先註冊手機不可匯出 P256 key，再由 Windows authority 簽發5分鐘、指定裝置及 App 的一次性授權。手機驗證已釘選 authority 的簽章後，使用 RSA-OAEP／AES-GCM 加密；Windows獨立驗證裝置簽章、解密、原子寫入DPAPI並回傳簽署收據。nonce、次數限制、狀態鎖、稽核及未知結果凍結防止重放和盲目重試。這是管理員認證的註冊金鑰身分，**不是 Apple 硬體 attestation**。

| 離線驗收 | 結果 |
|---|---|
| Windows SQLite | 344通過，2平台專屬略過，1 Live排除 |
| Docker PostgreSQL／RLS | 343通過，3 Windows專屬略過，1 Live排除 |
| 新增手機安全案例 | 30案例，含並行、過期、越權、換鑰、重放及故障注入 |
| 瀏覽器到真實 Windows DPAPI | 合成資料PASS；不可匯出key、換鑰拒絕、既有key保留 |
| mypy／漏洞掃描 | 28來源檔通過／沒有已知漏洞 |
| 隔離備份還原 | 20表一致，0列遺失；4個負面檢查通過 |
| 原環境 | Vault雜湊未變；未部署、未遷移原DB；通道／模型／發文仍關閉 |

完整證據：[測試](PHONE_SETUP_TEST_EVIDENCE.md)、[設計及啟用步驟](PHONE_SETUP_SECURITY.md)。遠端CI須以交付SHA實際紀錄為準。

本階段沒有真實App憑證輸入、真實iPhone Safari驗收或Meta授權；**OAUTH_VERIFIED=false，PUBLISH_VERIFIED=false**，沒有取得真正Threads ID。真實模型呼叫0次、實際模型費用USD0，沒有新增付費服務。合成加解密測試不等於真實OAuth成功。

未來啟用前仍須使用者另行同意、建立可信的首次手機管理員認證／安全交接、固定HTTPS origin、核對代理、備份原DB並部署0011。不能以公開指紋或聊天中的裝置ID取代認證，也不能只開環境變數就略過授權流程。完成憑證寫入後關閉通道，再由使用者操作既有OAuth按鈕；不得自動發布。

剩餘風險：可信網站的XSS、已遭控制的手機／Windows或管理員可破壞信任；Safari key保存及真實裝置仍待實測。跨DPAPI／資料庫交易不能保證原子性，未知結果必須人工對帳。此驗收不代表正式商用安全性。
