# MOS-PUB-001 最終驗收

**THREADS_INTEGRATION：PARTIAL（本機程式驗收通過；遠端CI待核，平台與當日政策仍有阻擋）**。
**THREADS_LIVE_PUBLISH：BLOCKED — BLOCKED_BY_PLATFORM_SETUP**。

來源分支codex/marketing-ai-os-p1-4-live-readiness與SHA ecfe2b95c67efdae432b1129b18fd3c803bf2cc8已核對且工作目錄乾淨；新分支codex/marketing-ai-os-threads-publisher，保留所有來源歷史，不修改main/develop。

已實作真實HTTPS Threads adapter、owner發起OAuth、加密／可本地撤銷Token連接、官方me/debug驗證、指定帳號及版本hash公開確認、確定性A13兩階段POST、持久化marker、只GET讀回／待對帳、原Recovery整合、原生RLS／資料庫防覆寫。真實adapter預設停用；普通測試／CI不能啟用。其他平台保留ManualAdapter，沒有新增模型呼叫。

完整證據：THREADS_OFFICIAL_API_RESEARCH／META_APP_SETUP／OAUTH_SETUP／PUBLISH_ARCHITECTURE／LIVE_VERIFICATION／FAILURE_RECOVERY／TEST_EVIDENCE及threads/。其中META_APP_SETUP是繁體中文後台與操作流程。

仍缺：Meta App及本人連接、最新Changelog/App Review與當日帳號限制補核、正式Token和真正公開內容確認、真實Published ID／讀回／permalink／使用者App目視確認。主站429與官方.com/.net來源差異已明列，不猜最新版本、審查通過或帳號權限。Provider端撤銷需使用者到平台設定操作，本版只驗證本地撤銷；不虛構DELETE契約。這些缺口不得以Mock補成Contract Ready／Live Verified。

排程明確暫緩：工單第9節要求真實立即發布成功後才開發，因此尚無排程／取消API；不是以單元測試假裝前提完成。程式保留在待授權狀態，不自行公開發文。

新增直接依賴cryptography50.0.2，及固定transitive cffi2.1.1/pycparser3.12；授權、必要性及漏洞掃描見研究／測試文件。新增付費服務0、真實Threads發布0、真實AI API calls0、AI實際費用USD0；Codex Token用量工具未提供。使用現有本機Docker與GitHub Actions，未查帳戶Actions配額或主機帳單。未進行正式環境安全／市場成效驗證。

本機：SQLite275／PostgreSQL276 passed，新增37項；mypy22、compile、漏洞掃描、Docker及18表備份還原PASS。最終SHA／origin推送及遠端CI會在交付回報逐一核對；外部平台缺口不因測試成功改判完成。
