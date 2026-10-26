# MOS-PUB-002 最終驗收

結論：**PARTIAL**。離線 UI 與本機安全回歸完成；沒有 Meta App／本人官方 OAuth／真實貼文證據，不能報完整實際整合 PASS。

| 狀態 | 判定 |
|---|---|
| UI_READY | PASS（可操作瀏覽器介面、工作區登入、官方 OAuth 入口、帳號管理、管理員精靈、版本發布確認；外部流程由 Mock 驗證） |
| OAUTH_VERIFIED | NOT_VERIFIED／BLOCKED_BY_PLATFORM_SETUP，未取得本人真實帳號 ID |
| PUBLISH_VERIFIED | NOT_VERIFIED，未發文、無真正 Published Media ID／讀回／連結 |
| Production | NO-GO，正式身分、安全、平台審查與真實整合尚缺驗證 |

來源分支及 SHA：`codex/marketing-ai-os-threads-publisher`／`2d653c0475fa840ca7ce0458ee601f3c3869f4b9`；交付分支 `codex/marketing-ai-os-threads-connect-ui`。不修改 main、develop 或來源分支。最終 SHA 以本檔所在 Git 提交及交付回報為準；遠端推送與 CI 不在執行前宣稱成功。

新增最小原生 UI、HttpOnly 工作階段及 CSRF、管理員診斷、現有發文流程的 owner／worker 編排、持久化有界憑證維護、非破壞性 migration 0010。重用所有現有 Adapter、Token 加密、帳號、OAuth、RLS、A21、Revision、Publication、防重複、Recovery、Scheduler。沒有新增發布排程、Agent 框架或第二套帳本。

驗收細節：[測試證據](PUB002_TEST_EVIDENCE.md)、[安全審查](PUB002_SECURITY_REVIEW.md)、[介面及繁中操作教學](PUB002_UI_GUIDE.md)、[設計審查與畫面](PUB002_DESIGN_REVIEW.md)。新增13測試；SQLite 288、PostgreSQL 289 項通過；mypy、漏洞、Docker、備份還原及瀏覽器均已本機通過。最終遠端 CI 需另核對交付 SHA。

尚缺：受控公開 HTTPS、Threads 專用 App ID／Secret、加密 key／密鑰保管、精確 Redirect URI、測試帳號角色與權限、依實際後台要求的 App Review／政策設定；再由持有人親自 OAuth，核對帳號並另行明確確認一篇公開文字。公開官方資料及合成 metadata 均不能證明帳號權限已開通。

真實 AI 模型呼叫 **0 次、USD 0**；真實 Threads OAuth／發布呼叫 **0 次**；新增付費服務 **0**；Python／npm 新依賴 **0**。預覽草稿／Token／費用來自既有 Mock，不是供應商帳單。新增本地字型採 SIL OFL；重用現有 API／scheduler，只有暫時的隔離測試容器與預覽程序。工具未提供本任務精確 Codex Token 用量。

後續 GO 僅限完成 Meta 設定後的受控本人 OAuth 驗收；公開發文仍需持有人指定帳號與文字的明確同意。不可將 UI_READY 當作官方 OAuth、發文或商用安全通過。
