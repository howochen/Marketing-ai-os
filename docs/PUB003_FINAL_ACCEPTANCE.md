# MOS-PUB-003 驗收與交付

2026-10-26，結論 **PARTIAL**。已完成可重跑 Windows 安裝精靈，並實際建立 HTTPS 開發連線環境；尚未取得真正 Threads 帳號 ID，不能報 OAUTH_VERIFIED 或完整成功。

來源：`codex/marketing-ai-os-threads-connect-ui`／`87bc3c32ba578bc8e0a8d1923e7c61fe424cb42b`。新分支 `codex/marketing-ai-os-threads-auto-setup`。來源、main、develop 與既有部署資料均未修改。

| 項目 | 實測結果 |
|---|---|
| LOCAL_SETUP_READY | true：獨立 Docker PostgreSQL、schema0010、TLS upstream、真實 ngrok HTTPS、公開 UI 與 callback 已通 |
| SETUP_READY | false：缺 App ID／Secret、Meta 後台 URI 登錄確認 |
| OAUTH_VERIFIED | false：沒有本人官方登入，沒有取得真正 Threads ID；accounts=[] |
| PUBLISH_VERIFIED | false：未發布，發布開關 false；沒有 Published ID 或實際貼文連結 |
| Production | NO-GO；這是受控開發環境 |

真實環境證據：pub003/actual-environment.txt、repeatability.json、private-acl.json、public-tls.json。實際開發網域只保留在本機 `.threads-local/status.json`；Git 證據遮蔽網域，未用 Mock 代替上述網路檢查。Windows 預設 CA 曾選到過期憑證鏈，改重用現有 HTTPX 的嚴格 CA 驗證後實際 HTTP200；未繞過功能性 TLS 檢查。

重跑驗證保留 DB／admin／Fernet 金鑰及 tenant；實際執行停止／重啟 ngrok，網址改變時後端 Callback 自動更新。Meta 後台仍需本人登錄新 URI，不能宣稱已自動完成。公開 OAuth 空 callback 回400是安全防護正確，不是 OAuth 成功。

測試位置：tests/test_threads_setup.py（Windows DPAPI、環境覆寫防護、私有 TLS 暫存、既有 volume 不接管、ngrok 初始化、Mock 排除與官方新驗證、用後撤銷 Credential、TLS 失敗關閉）；tests/test_social_ui.py、test_threads_publisher.py 與既有全套不退步。完整輸出在 pub003/sqlite.txt／postgres.txt，型別與漏洞在 pub003/mypy.txt／audit.txt。

最終本機數字：Windows SQLite 312 passed／1 skipped（PG RLS）／1 deselected（Live）；Linux PostgreSQL 312 passed／1 skipped（Windows DPAPI）／1 deselected。安裝器 Windows 24 passed。mypy 25 modules 成功；pip-audit 無已知漏洞；compileall、diff --check 通過。實際產生的安裝秘密與全部 Git 候選檔案逐一比對無匹配，見 pub003/secret-scan.json。

Docker 測試首次發現 test image 未帶安裝器 module，已於 test stage 補單一檔案並重新完整通過；沒有把安裝器、vault 或秘密帶入 runtime image。CI 新增 windows-installer job，僅跑離線單元測試。Linux 刻意略過 Windows DPAPI；SQLite 另略過 PostgreSQL 強制 RLS；付費 Live 測試始終 deselected。CI 最終 SHA 的成功與連結以交付時的 GitHub 結果為準，不預先宣稱成功。

使用 [Setup-Threads.cmd](../Setup-Threads.cmd)；詳細 [首次安裝與故障排查](PUB003_FIRST_RUN.md)、[安全與選型](PUB003_SECURITY.md)、[Meta 瀏覽器交接規格](pub003/meta-handoff.json)。本人輸入 App ID／Secret、保存 URI 後，正常 UI 即可走官方 OAuth；後續 `--diagnose` 必須實際官方驗證帳號／scopes／到期時間才通過。本人登入、MFA、政策與審查不得自動偽造。

新增套件／框架／付費服務：0。真實 AI 模型呼叫0、實際模型 API 費用 USD0。真實 Meta API 呼叫0、公開發文0；ngrok 僅使用既有帳戶與預設免費方案相容命令，沒有購買／升級；該帳戶的方案和實際流量帳務未取得驗證。Codex 本任務 Token 數工具未提供。
