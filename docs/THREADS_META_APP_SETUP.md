# Meta Threads App 設定教學（繁體中文）

目前狀態：使用者回覆「尚未設定；先完成程式與操作教學」。因此 **BLOCKED_BY_PLATFORM_SETUP**，本文件不是公開發文授權。Meta後台標籤可能調整；本次主站429，請以帳號當日實際後台及官方提示為準，不假設App Review或任意測試帳號已獲准。

1. 以帳號持有人自己的Meta開發者帳號登入 developers.facebook.com，完成後台要求的註冊／身分或安全步驟。到「我的應用程式」建立App，選擇提供Threads API存取的use case。若沒有Threads選項或帳號資格不足，先停止並處理Meta資格，不改用Instagram/Facebook或非官方登入。
2. 進入Threads use case的設定／基本資料，取得**Threads專用**App ID與App Secret；官方範例提醒它們可能不同於一般App ID/Secret。Secret只能設定在後端受控環境／密鑰來源，不貼到聊天、前端、Swagger輸入或Git。
3. 準備自己控制的HTTPS服務，例如 https://your-controlled-host。FastAPI在本機127.0.0.1:8000，由安全反向代理提供TLS。不要直接公開HTTP8000。callback固定為 `https://your-controlled-host/threads/oauth/callback`，不加query、fragment或結尾斜線；把同一字串加入Meta「Redirect Callback URLs／有效OAuth重新導向URI」欄位。
4. 設定App需要的網站／隱私政策及資料刪除指引等後台必填欄位；提供真實可用網址，不填虛構審查資料。確認App模式、管理員／開發者／Threads測試人員角色；如果後台提供邀請，邀請實際Threads帳號並由持有人到Threads設定接受。角色、測試及access tier的當日限制需自行確認，不能假設任何帳號都能測。
5. 只要求 `threads_basic` 與 `threads_content_publish`。先檢查後台是否允許自己的App角色／指定測試帳號取得它們。若需要Advanced Access、App Review或商家驗證，按後台流程辦理；本專案沒有代為提交，也沒有聲稱通過。
6. 正式對其他使用者開放前，按當日要求提交用途說明、隱私／刪除政策、可重現測試與螢幕錄影。演示完整OAuth、指定Revision人工核准、帳號與文字確認、兩階段發布及真實讀回。不要以Mock影片、Container ID或HTTP200當成已實際發文的證據。
7. 把設定放入後端環境：MOS_ENV=test、MOS_THREADS_APP_ID、MOS_THREADS_APP_SECRET、MOS_THREADS_REDIRECT_URI、MOS_THREADS_TOKEN_KEY。Fernet key由管理者在受控終端產生並存到外部密鑰來源；不要使用範例固定key。備份加密key必須與資料庫備份分開保管。遺失key需重新授權，不可把Token改存明文。
8. 先維持 MOS_MODEL_CALLS_ENABLED=false、MOS_LIVE_TESTS=false、MOS_THREADS_PUBLISH_ENABLED=false。準備好並由本人開始OAuth時，才由管理者把 MOS_THREADS_HTTP_ENABLED=true；這讓官方身分交換／查詢可執行，**不代表公開發文已核准**。CI與一般pytest即使誤設true也拒絕真實transport。
9. 透過同一HTTPS網域的 `/docs` 使用既有MOS owner Bearer憑證。執行POST /threads/oauth/start，瀏覽器收到Secure/HttpOnly/SameSite=Lax cookie；再在**同一瀏覽器**開回傳authorization_url，登入本人Threads並確認授權。不可用curl取得start後把URL貼到沒有該cookie的瀏覽器；那樣callback應被拒絕。前端若日後新增，可用same-origin fetch開始同一流程。
10. callback只回連接metadata與官方讀到的帳號ID／username／到期時間／scopes，不回Token。核對確實是預期帳號。若沒有取得正確grants或平台拒絕，依錯誤重新設定，不用合成帳號補齊。初次連接與重新授權均預設account publishing_enabled=false。

完成以上設定後仍須回到工單第二道驗收：由持有人確認**指定帳號及一篇確定要公開的文字**，另行明確執行一次。沒有這項確認，本次程式工作不可自行發文。
