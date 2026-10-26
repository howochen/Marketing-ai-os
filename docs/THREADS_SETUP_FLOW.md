# Windows Threads 首次設定：Callback 優先

2026-10-26。雙擊專案根目錄 **Setup-Threads.cmd**，依視窗的五階段按鈕操作，不需要編輯環境變數或先閱讀 API 文件。

| 階段 | 視窗動作 | 通過條件 |
|---|---|---|
| 1. 自動檢查 | 等候 Docker／ngrok／HTTPS 檢查；失敗按重新檢查 | 取得當次HTTPS Callback並驗證可達；不要求App憑證 |
| 2. Meta設定 | 複製Callback → 開啟Meta → 保存Threads Redirect → 勾選確認 → 繼續 | 本人明確確認當次網址已在目標Threads App保存；不是官方驗真 |
| 3. 本機憑證 | 輸入Threads專用App ID／Secret；或沿用已有加密憑證 | Secret隱藏、清空輸入後DPAPI保存；不能繞過第二階段 |
| 4. 後端檢查 | 等候設定與TLS核對 | SETUP_READY成立、發布關閉，才提供登入 |
| 5. 官方OAuth | 開MOS → 複製一次性碼登入 → 連接Threads → 同瀏覽器完成官方授權 → 返回精靈驗證 | 新官方API的Threads ID、username、必要scopes、expiry有效才OAUTH_VERIFIED |

Meta後台先沿用既有App；確認支援「存取Threads API」。在Threads設定找Redirect Callback URLs，完整貼上畫面網址並保存。Threads App ID／Secret應使用**Threads專用欄位**，不是Facebook Login憑證；官方collection列出App settings → Basic → Threads App ID／Threads App secret。Meta介面可能調整，以當日Threads專用欄位為準。

Meta帳號登入、MFA、取得Secret與授權同意都由本人操作。精靈不讀Cookie、不代存Meta設定、不使用付費管理API。一般使用者只在MOS點官方OAuth，不需交換Token。

## 續跑與故障

- 已有Vault、資料庫、Fernet key、工作區與App憑證會保留；不刪資料卷或自動重設。中斷後重新雙擊即可。進行中關閉會提示等候有界操作結束。
- ngrok網址變更會清除舊Callback確認、關閉尚未重新確認的Threads HTTP設定，並明確要求更新Meta；不能沿用舊網址的聲明。
- 同網址重跑可沿用確認與憑證，仍需按下確認／繼續，後端會再檢查。更換App前，請返回並確認新App已保存同一Callback。
- Docker未就緒會提示開啟Docker Desktop；ngrok帳戶未配置時，提供官方後台連結與本機隱藏authtoken輸入，同樣保存DPAPI。沒有自動購買或建立帳號。
- 輸入格式、DPAPI寫入或後端檢查失敗，不會自動打開登入；不印原始錯誤、命令輸出或Secret。既有值不因失敗被覆寫。
- 登入碼只在本機視窗顯示，可複製；勿貼聊天或錄影。Secret不進網址、剪貼簿、一般API或Log。Python／Windows記憶體不宣稱可完全抹除。
- 只有顯示官方帳號證據才算OAuth成功；App配置齊備、TLS可達或人勾選保存都不算。沒有帳號時顯示尚未完成，不以Mock補上ID。

預設已取消自動 --mobile。需要手機時才明確執行 `Setup-Threads.cmd --mobile`；`--login`也先檢查SETUP_READY，不能跳過初始化。`--diagnose`、`--non-interactive`、`--stop`等既有管理模式保留。

## 實作與安全

只改善 `scripts/threads_setup.py` 的順序與共用階段函式，增加薄的標準庫Tk視窗 `scripts/threads_setup_ui.py`。Cmd改用 `python -m scripts.threads_setup`，確保共用app／scripts模組的匯入路徑正確。未重建Adapter、認證、OAuth、Token儲存、Docker或資料庫；沒有Migration或新套件。

設定寫入仍持有原生setup.lock。DPAPI沿用原子檔案替換；保存憑證先在副本更新，寫入失敗不改原記憶體資料。TLS驗證、不檢視ngrok請求、代理限制、受限目錄與敏感錯誤遮罩不放寬。模型、發布、手機秘密通道均強制false。

本次真實Windows視窗點擊與Tk／DPAPI測試使用合成資料、隔離Vault及替代基礎設施。操作圖：[Callback與複製](setup-order/screens/callback-copy.jpg)、[確認後的空白憑證頁](setup-order/screens/credentials-empty.jpg)。畫面標示離線驗收，不代表圖中HTTPS或Meta已真正完成設定。

現有真實Docker、ngrok與HTTPS只做唯讀檢查，證據在setup-order/environment.json；沒有對原環境執行新版安裝、寫入原Vault或進行Meta登入。回歸與CI見[測試證據](THREADS_SETUP_ORDER_TESTS.md)。

官方來源查核2026-10-26：[Meta官方Threads collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)、[ngrok官方文件](https://ngrok.com/docs/start)。Meta developers入門頁本次回429／無法擷取，未假稱已在真實Meta後台逐項核對；精靈仍提供官方入口讓本人操作。

本階段真實AI呼叫0、費用USD0、貼文0。沒有取得本人的新官方Threads ID；OAUTH_VERIFIED仍須本人完成流程後由官方API驗證，不代表正式商用就緒。
