# Meta Threads App 設定教學（繁體中文）

MOS-PUB-002 已新增瀏覽器介面：一般使用者請改用 [UI 操作教學](PUB002_UI_GUIDE.md)，不需執行下列舊版 Swagger／手動 Token 步驟。此文件保留管理員平台設定與底層 API 操作參考。

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

## 平台設定後：一篇貼文的受控操作

以下是日後**帳號持有人已確認帳號與完整公開文字後**的操作，不是本次允許你立即執行的發文腳本。現在沒有Meta App，請停在設定階段。

1. 在HTTPS `/docs` 的連接清單確認OAuth讀到的connection ID、Threads user ID、username、scopes與到期時間。MOCK來源不可用於Live，不要從測試報表複製10001等數值。
2. 透過既有Task／Revision流程準備文字；不需要OpenAI。可把離線草稿用人工Revision改成已同意的測試文字，維持A21要求的hook／CTA與品牌限制。GET `/tasks/{task_id}/revisions`，仔細核對最新版本的after_text；owner以既有approve API指定revision_id。若重新修改，必須重新批准新版本。
3. owner執行 POST `/tasks/{task_id}/publication-request`，body為：

```json
{"platform":"threads","idempotency_key":"replace-with-a-unique-publication-key","revision_id":"APPROVED_REVISION_ID"}
```

4. 管理者只在該次Live已獲持有人同意後，將受控環境MOS_THREADS_PUBLISH_ENABLED=true（HTTP開關也需true）；模型開關繼續false。owner對指定connection執行 POST `/threads/connections/{connection_id}/publishing`，body `{"enabled":true}`。這會再次檢查官方帳號及權限，並不直接發文。
5. 用**原始after_text、不去空白或換行**計算UTF8 SHA256，例如Python `hashlib.sha256(text.encode("utf-8")).hexdigest()`。owner再次確認該帳號與逐字內容，POST `/threads/publications/{publication_id}/authorize`：

```json
{"connection_id":"OFFICIAL_CONNECTION_ID","threads_user_id":"OFFICIAL_THREADS_USER_ID","revision_id":"APPROVED_REVISION_ID","content_sha256":"EXACT_UTF8_SHA256","confirm_public_post":true}
```

以上大寫文字是占位符，不是可用憑證或帳號；必須來自本人官方OAuth與已批准Revision。不要由自動化工具代替持有人決定confirm_public_post。

6. 使用同Tenant worker的MOS Bearer憑證，**明確只執行一次** POST `/threads/publications/{publication_id}/execute`。它可能真的公開內容，不能拿來測試帳號是否有效。owner角色本身不可越權代用worker端點。
7. 檢查回傳publish_status／container_id／published_media_id／verification_status。只有真實OFFICIAL_READBACK_VERIFIED及PUBLISHED_VERIFIED才有系統讀回證據；還要由持有人開啟Meta返回的permalink，在Threads App看見同一篇，才完成工單第二道驗收。
8. RESULT_UNKNOWN／RECONCILIATION_REQUIRED時不要重按execute，不要另建同文工作。已知Media ID但讀回暫失敗時可用 `/reconcile`，它只GET；未知ID則按THREADS_FAILURE_RECOVERY.md人工查明，不能以Container ID當Published ID。
9. 測試結束，將全域發布開關false，並對該connection POST publishing `{"enabled":false}`。需要撤銷時DELETE本地connection，再到Threads設定移除App授權。保留審核／讀回證據，勿把Token貼進報告。

本次沒有執行以上真實發文步驟，沒有任何真實post ID或permalink。定時發布與取消API仍須等立即發布驗收成功後另行開發。
