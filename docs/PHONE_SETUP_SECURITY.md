# 一次性手機安全初始化：安全設計與審查

日期：2026-10-26。授權只有開發／離線測試，**沒有公開啟用或實際憑證配置授權**。分支 `codex/marketing-ai-os-one-time-phone-setup`；來源 `88750010c067662eb1f523d7d7f9a52724798305`。

## 身分與信任前提

裝置身分是「經現有系統管理員認證註冊的密碼學金鑰」，不是使用者貼上的指紋，也不是 Apple 硬體身分證明。一般 tenant owner／worker 不能註冊裝置或簽發設定權限。

1. 手機必須先有可信的 MOS 系統管理員工作階段；既有 HttpOnly Cookie／CSRF／HTTPS 驗證繼續適用。
2. Safari Web Crypto 產生不可匯出的 P-256 私鑰，僅保留在該來源的 IndexedDB。註冊須簽署60秒 nonce，證明持有私鑰；管理員認證與私鑰證明缺一不可。
3. 後端簽發具期限、來源、tenant、公鑰、操作者的 HMAC 裝置收據。Windows 使用既有 DPAPI Vault 的管理金鑰重新驗真，不能只憑資料庫的 ACTIVE 字樣或公開指紋授權。
4. Windows DPAPI 保管獨立簽發金鑰；手機在受認證註冊時固定其公鑰。後續加密公鑰必須有這個已信任簽發者的簽章，不接受臨時替換的公鑰。

**目前沒有真正已受認證的手機，也沒有可沿用的遠端桌面登入證據。首次可信管理員／手機註冊仍是啟用阻擋項。不能用本次「同意開發」、聊天電子郵件或公開指紋繞過它。** 本階段沒有新增身分平台、沒有假裝已完成首次身分驗證。

## 一次性操作

Windows 簽署的 manifest 固定包含 action、安裝 tenant、裝置、指定 App ID、HTTPS origin、五分鐘期限、RSA3072 公鑰及 DPAPI 簽發者識別。後端最多接受十分鐘授權；Native controller 一次僅有一個待處理操作，未知結果凍結新操作。

手機先驗真 manifest 簽章、來源及裝置，再對 nonce 簽章。只有認證成功才顯示 Secret 欄位。輸入以 AES-256-GCM 加密，完整 manifest 作 AAD；AES key 以 RSA-OAEP-SHA256 包裝。提交簽章綁定 grant、device、manifest hash、nonce、envelope hash。API 僅收到密文，沒有一般 Secret 寫入表單或任意 env／命令介面。

每個 nonce 60秒、成功即消耗；操作最多8次公開請求／3次驗證失敗，超限關閉。來源不符、過期、裝置撤銷或租戶停用時拒絕。DB tenant lock 原子保留狀態；並行提交只有一個成功。SEALED 後公開通道返回410，不能重送。

Windows 使用既有安裝鎖，先持久化 CLAIMING 再向後端領取，超時／崩潰不盲目重領。解密前再次核對管理員裝置收據、手機簽章、原始 manifest、期限及原設定快照。只允許 `app_id`／`app_secret`，多餘欄位或其他 App 一律拒絕；保留原 admin、Fernet、DB、TLS、ngrok 等資料。

既有 DPAPI 原子檔案替換成功後，才產生 Windows 簽署的提交收據。後端無有效提交證明不能標 APPLIED。完成後撤銷本機 release 授權，沿用原 Compose 更新 API；原 Compose 強制 phone channel、發布與模型關閉，因此不留下持續開放的設定入口。部署失敗時保留已存檔事實，交人工處理，不能重新送 Secret 來「重試」。

期限會由每次准入與 Native apply 強制檢查，瀏覽器也會清空欄位；sweep 將過期紀錄關閉、將不明 APPLYING 轉待對帳。失效能力不依賴排程是否準時；有界一次性 worker 結束後不新增常駐服務。

## 密鑰與資訊處理

| 資料 | 位置 |
|---|---|
| 裝置簽章私鑰 | 手機不可匯出 CryptoKey／同來源 IndexedDB，不上傳 |
| 設定簽發私鑰、單次解密私鑰 | Windows 既有 DPAPI Vault namespace；成功後移除單次解密 key |
| App Secret | 手機輸入的短暫記憶體→加密信封→Windows 記憶體→DPAPI；Compose 執行時仍需受控後端環境 |
| 後端新資料表 | 公開金鑰、授權、nonce、計數、簽章及密文；不存明文 Secret |
| 審計 | 沿用 append-only Audit；記錄註冊、授權、挑戰、拒絕、封存、claim、提交／待對帳；其他錯誤只有結構化狀態，不寫 URL／body |

Migration0011 只新增兩表與 immutable trigger，沿用 PostgreSQL FORCE RLS；不改帳本或舊資料。`MOS_PHONE_SETUP_ENABLED=false` 是預設，原 Compose 亦固定 false；Native controller 另需 DPAPI 中的 release 核准，僅設定一個 host env 不會公開它。本次沒有修改實際 Vault、沒有遷移實際 DB、沒有更新實際 API 容器。

前端 CSP self-only、禁止 framing／原生表單提交，無第三方 JS、分析或遠端字型。Secret 不進網址、localStorage、IndexedDB、一般 API 回應、Log 或截圖；在提交、失敗、到期與離頁時清空輸入。JavaScript／OS 記憶體、pagefile、備份不能宣稱完全抹除。

## 攻擊審查與限制

已測：匿名／owner／worker 越權、偽造裝置收據、換簽發／加密公鑰、錯來源、重放 nonce、期限、撤銷、次數耗盡、並行提交、錯 App／額外環境變數、密文竄改、Native 再驗手機簽章、DPAPI 寫入失敗、claim 不明結果凍結、不可偽造提交成功、RLS、不可覆寫 manifest、Log／回應不回顯敏感 body。安全審查為程式與故障測試，**不是獨立滲透測試或商用認證**。

剩餘風險：

- Web Crypto 的不可匯出是瀏覽器政策，不是 Apple Secure Enclave／WebAuthn attestation；實體 iPhone、Safari 儲存及 OS 備份行為未驗收。不能宣稱硬體防複製。
- 初次登入／註冊仍需可信管理員管道。現有共用管理金鑰能辨識管理角色與簽發 key，不能逐一識別不同人；洩漏、受信任來源 XSS、被控制的手機／Windows 不在此協定可消除範圍。
- 信任 TLS、既有 origin 與執行程式。簽章可拒絕傳輸途中換鑰，不能保證遭入侵的同來源 JS 不竊取鍵盤輸入。ngrok 是第三方流量處理者；不宣稱第三方零保留。
- ngrok origin 改變時必須重新受信任註冊，不自動搬移裝置 key。公開操作 ID 不是 bearer，但知道 ID 的人可能耗盡次數造成拒絕服務，不能取得 Secret。
- DB、網路與 DPAPI 不是跨系統原子交易。未知 claim／部署結果保留紀錄並停止自動重試，需管理員對帳；不保證外部 exactly-once。
- App 憑證只驗證授權範圍與格式，未呼叫 Meta 判定真實有效性；OAuth／真正 Threads ID 仍須本人後續驗收。

## 未來啟用步驟（本次不可執行）

1. 使用者另行明確核准公開一次性通道；完成首次可信手機管理員認證與穩定 HTTPS origin。
2. 備份實際資料，審查並遷移0011；同一 Windows 身分準備 DPAPI authority，後端只取得公鑰。另行受控部署覆寫 phone flag，不改發布／模型 false。
3. 由已認證管理員註冊手機並驗真收據；Windows 用 `issue_authorization(device_id, app_id)` 簽發唯一指定操作。release 核准只能由受信任本機控制，不接受網頁輸入。
4. 啟動有界 `wait_and_consume(grant_id)`，本人用 Safari 配對與輸入。worker 保存、回報簽章收據並用原 Compose 關閉入口；確認 readiness 與實際配置，不重送不明結果。
5. 本人才使用既有 `/app/threads` 完成官方 OAuth；只有官方 API 的真實 ID、username、scopes／expiry 驗真後才 OAUTH_VERIFIED。發文仍不得開啟。

目前 **公開啟用 NO-GO**，既無另行核准，也未完成真實手機可信註冊。
