# Threads 撤銷／資料刪除回呼：驗收

日期2026-10-27。**整體PARTIAL：程式與離線驗收完成；公開部署待核准，Meta真實送達未驗證，完整資料清除仍待保留範圍審查。**

| 項目 | 結果／證據 |
|---|---|
| Windows SQLite全套 | 413 passed、2 skipped、1 deselected；threads-privacy/sqlite.txt |
| Docker PostgreSQL／FORCE RLS | 409 passed、6 skipped、1 deselected；threads-privacy/postgres.txt |
| 新回呼測試 | 27案例；tests/test_threads_privacy.py，真實HTTP／DB、合成HMAC表單，不是Meta送達證據 |
| mypy／漏洞 | 30來源檔通過；沒有已知漏洞；threads-privacy/mypy.txt、audit.txt |
| 靜態檢查 | compileall、node --check、git diff --check通過 |
| 備份還原 | 專用mos-privacy-test，23表指紋一致、0列快照遺失，4項負面檢查；1.080秒備份、13.977秒還原核對；0600／0700；backup-restore.json |
| 原資料保護 | 既有DB先做唯讀備份，保存於既有受限的.threads-local/backups；沒有對原DB遷移、還原或刪除；preservation.json |
| 使用者原有變更 | Setup-Threads.cmd、Start-Content.cmd原始位元組及原Vault密文雜湊均與執行前相同；不將這兩個未提交檔案納入本次提交 |
| 真實公開端點 | 唯讀GET：既有Redirect400（無OAuth state的正常拒絕），新Deauthorize／Data Deletion均404；deployment.json |
| 遠端CI | 交付SHA的GitHub Actions實際結果為準，不能以本機成功代替 |

SQLite略過兩個PostgreSQL專屬RLS測試；Linux PostgreSQL略過六個Windows Cmd／Tk／DPAPI平台案例，Windows CI另驗證。付費Live案例排除。既有Starlette/httpx deprecation warning保留，未擴大升級依賴。

測試涵蓋：錯Secret／App、演算法／格式／時戳、過期與未來事件、重複表單、JSON傳輸拒絕、缺配置拒絕、App／Tenant精確定位、同帳號不同Tenant合法App級撤銷、不同App／使用者不受影響、重放與並行冪等、新授權不被舊事件撤銷、未送出工作阻擋、在途結果保留、舊App綁定待審、狀態確認碼、Owner審查權限、故障恢復、SQL RLS與不可改寫／不得標COMPLETED。

## 部署阻擋與剩餘驗收

自動核准審查拒絕對現有環境執行非互動安裝器，理由：會遷移真實DB、更新Docker設定及公開持續啟用新回呼；目前授權未明確包含正式部署。**沒有改用其他方式繞過、沒有啟用新路由。** 新公開URL目前404，不可先宣稱可接收Meta事件。

等待使用者明確核准：在已有備份下，對既有mos-threads-local套用非破壞性Migration0013、更新API並公開兩個HMAC保護回呼；模型／Threads發文／手機通道繼續false。沒有新套件、付費服務或新常駐Worker。

核准後仍須本人在Meta保存三網址、在Windows安全配置Secret，再由本人移除授權／請求刪除，核對真實Meta事件與收據；未收到這種證據前META_CALLBACK_VERIFIED=false。Meta官方頁本次429，當日Threads特定payload與簽章Secret／ID命名空間尚未實測，不以封存SDK或合成測試冒充現行官方認證。

資料清除只完成可驗證範圍的Token／可變帳號資料；原始作品、不可改寫的發布／稽核證據、在途請求及備份仍需審查。沒有虛構清除完成或刪除無關資料。現階段不代表Meta App Review、Production、完整隱私合規或外部貼文刪除驗收。

重現：`python -m pytest -q --tb=short`；PostgreSQL使用專用`docker compose -p mos-privacy-test --profile test run --build --rm tests`；合成備份以`MOS_DRILL_PROJECT=mos-privacy-test`執行既有backup_drill.py。不可將合成演練專案改成原DB，不刪資料卷。

程式及欄位說明：[操作與安全設計](THREADS_PRIVACY_CALLBACKS.md)。真實AI呼叫0、實際AI API費用USD0；沒有擅自發布、購買服務或啟用手機秘密通道。
