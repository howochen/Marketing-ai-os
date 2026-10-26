# Threads Callback 優先精靈：驗收證據

2026-10-26。來源56f03b3f694023762ec056d0d71b256ace19eec6；功能分支codex/marketing-ai-os-threads-setup-order。

| 範圍 | 證據 |
|---|---|
| Windows原生視窗點擊 | setup-order/windows-interaction.json；實際按未確認繼續、複製Callback、勾選確認、進入空白憑證頁 |
| 原生Tk／DPAPI | test_threads_setup_order.py的2個Windows程序隔離案例；合成Secret經隱藏欄位保存至真正DPAPI，確認密文無明文、原key保留、後端失敗不開登入、同一Tk的Toplevel登入視窗可正常關閉 |
| Callback順序與續跑 | 無App憑證先產生URI、網址變更清除確認、同網址保留狀態、必須明確確認、保存失敗不覆寫、格式拒絕、Cmd不再預設mobile |
| 安裝器聚焦回歸 | setup-order/focused.txt：44案例通過，包括既有27案及新增17案／參數案例 |
| SQLite完整回歸 | **385 passed／2 skipped／1 deselected**，254.16秒；setup-order/sqlite.txt |
| PostgreSQL完整回歸 | **382 passed／5 skipped／1 deselected**，285.32秒；setup-order/postgres.txt；實際Docker建置與非特權RLS角色 |
| 型別／編譯／漏洞 | setup-order/mypy.txt、audit.txt；既有mypy29來源模組通過、compileall包含新Tk模組；沒有已知依賴漏洞、沒有新套件 |
| 既有真實環境 | setup-order/environment.json：唯讀Docker／ngrok／TLS，原服務schema0012，HTTPS與Callback所需上游可用；未對原環境執行新版安裝或寫Vault |

本次新增17個案例／參數組合：14個新的順序／GUI案例，以及既有官方身份測試新增3個scopes負面組合。Windows GUI測試使用真正Tk與DPAPI，但Docker、ngrok、Meta與帳號資料均隔離／替代；這不是官方OAuth完成證據。

SQLite的2個略過為PostgreSQL RLS專屬案例；Linux PostgreSQL除原3個Windows專屬略過，再略過2個新Windows Tk／DPAPI案例，由Windows CI補足。1個Live付費案例持續排除。Starlette/httpx既有deprecation warning未因此大幅升級依賴。

真實Windows GUI操作由computer-use技能只選定標記「離線Windows互動驗收」的自有測試視窗，沒有操作Chrome設定檔、Meta登入／MFA或真實Secret。截圖只保存Callback與空白憑證頁；沒有填入Secret後的截圖。透過真實Windows元件的隱藏輸入到DPAPI由隔離測試驗證，不要求本人提供測試憑證。

修正過程發現並處理：Docker測試映像未帶Cmd入口；同程序反覆建立Tk根視窗可能受到Tcl狀態影響。登入改為父視窗Toplevel，GUI案例各有獨立Tcl程序。失敗的測試輸出不當作通過證據，最終錄檔由重新執行取代。

## 重現

- Windows：`.venv\Scripts\python -m pytest -q --tb=short`；聚焦 `tests/test_threads_setup.py tests/test_threads_setup_order.py`。
- PostgreSQL：使用專用合成密碼，`docker compose -p mos-setup-order-test --profile test run --build --rm tests`。不改成原mos-threads-local，不刪資料卷。
- 視窗：`python tests/threads_wizard_fixture.py`。只供本機離線驗收，標示合成資料，不執行真實Docker/ngrok/OAuth，禁止填真正Secret。
- 一般使用者：直接雙擊Setup-Threads.cmd，不需執行上述測試命令。實際執行安裝器會按既有方式啟動專用服務、產生HTTPS並等待Meta人工交接；本次測試沒有替本人完成這些寫入／同意。

GitHub Actions驗證最終SHA的Windows、SQLite、PostgreSQL／Docker、型別、漏洞及合成備份還原；以最終交付連結的實際結果為準。本次沒有新Migration或新備份工具，沿用既有21表備份檢查。

**OAUTH_VERIFIED未取得新的本人證據，PUBLISH_VERIFIED=false**。真實AI呼叫0、實際AI費用USD0、貼文0。免費Meta與ngrok文件／健康檢查不等於成功授權；模型、發文、一次性手機秘密通道仍關閉。此交付改善安裝體驗，不宣稱Production就緒。
