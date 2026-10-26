# Threads 三個 Meta Callback：操作與安全界線

查核日期：2026-10-27。原專案已有OAuth Redirect與Owner本地撤銷，**沒有Meta解除安裝或資料刪除接收端**。本次沿用原Adapter、DPAPI、Token加密、Tenant／RLS、內容工作台與發布狀態機，不新增套件。

**現行 Threads 官方契約 NOT_VERIFIED；以下描述本機實作，不代表官方相容性。新端點未部署，正式部署 NO-GO。** 最新隔離還原、升級與回復計畫見[部署前驗證](THREADS_PRIVACY_PREFLIGHT.md)。

## Meta 後台怎麼填

安裝精靈第二階段、`/app/admin`現會列出三個可複製網址。必須使用當次真實公開HTTPS網域：

| Meta欄位 | 對應路徑 |
|---|---|
| Redirect Callback URL | `/threads/oauth/callback` |
| Uninstall／Deauthorize Callback URL | `/threads/privacy/deauthorize` |
| Data Deletion Request Callback URL | `/threads/privacy/data-deletion` |

網址不是同一端點，不要互相混填；ngrok換網址時三個都要更新。精靈的勾選是本人已保存聲明，不是Meta官方驗證。不要把App Secret放到網址或聊天；仍在Windows本機隱藏欄位配置。

Meta的兩個新回呼只接受POST、`application/x-www-form-urlencoded`、單一`signed_request`欄位。GET只顯示介面說明，不會撤銷、刪除或完成驗證。這不是Threads一般Webhooks訂閱，不採用未簽章的hub.challenge作刪除授權。

資料刪除成功收件回傳`url`與`confirmation_code`。Meta／使用者可開該狀態網址；確認碼不包含帳號或Tenant資訊。若顯示REVIEW_REQUIRED，**不代表已全部刪除**。

## 簽章與App範圍

- 使用目前部署的Threads App Secret對原始encoded payload驗證HMAC-SHA256，以constant-time比較；再驗證演算法、數字字串user_id與整數issued_at。若payload帶app_id，必須與配置一致；未帶app_id時由專屬App Secret與資料庫App綁定共同界定範圍。
- 嚴格拒絕重複表單／JSON鍵、異常base64、過大body、缺少或錯誤簽章、錯App及未知過期事件。issued_at接受24小時內、最多未來300秒：這是**本地安全政策，不是Meta送達時限保證**。已收過的有效簽章事件即使晚到，仍只回原收據，不重做刪除。
- 原始signed_request可能帶額外Token，故不保存、不回顯、不記Log；只存事件指紋、payload雜湊、App與匿名化查找鍵、時間、確認碼雜湊及不可改寫的目標清單。
- 公開簽章回呼按同一App／同一已驗證帳號定位所有已綁定Tenant；這是同一帳號的App層級撤銷，不接受客戶端tenant_id指定其他人。其他App或其他使用者不受影響。一般Owner介面仍嚴格只看自己的Tenant。
- 舊連接的App欄位保持NULL，不猜測、不把目前App直接回填到所有舊資料。未綁定的舊連接不能發布／刷新；Owner先用既有「檢查連線」由官方debug_token驗證App與帳號，才可補綁。無法確認的回呼只留下待審紀錄，不執行未驗證刪除。

## 實際處理與不會假裝完成的部分

已驗證範圍會在Tenant交易鎖中清除Token密文、停用發布與refresh，未送出Publication改AUTH_REQUIRED；已在途或結果未知者轉RECONCILIATION_REQUIRED，保留ID／次數。不能保證撤回已送往Meta的外部請求。

Data Deletion另清空可變帳號username／scopes，將本機Threads ID改為刪除標記。人工作品、不可覆寫Revision、Publication證據、Ledger、Audit與備份不會被此回呼任意刪除；已發出的外部Threads貼文也不會由這個接收端自動刪除。上述保留範圍必須逐項審查，所以**本版本不提供COMPLETED或完整清除的聲明**。請求狀態只可能PENDING、RECONCILIATION_REQUIRED、REVIEW_REQUIRED。

收據先持久化、每個連接處理有唯一鍵及Tenant鎖；重複事件、並行重送與中斷恢復不重複操作。新授權晚於舊事件時保留，不用舊事件撤掉新連接。Meta事件只提供秒級時間，本地以同秒視作同一時間範圍；真實送達及重連邊界仍須實測。

沒有全域人為「已刪除」開關。Owner可記錄審查原因（至少20字元）但不改成完整刪除；管理員恢復也只重試已簽章收據內的既有目標，不能自填新帳號或Tenant。

## 管理追蹤

- 狀態頁：回呼回應中的HTTPS `url`；只顯示狀態，不公開帳號、Tenant、目標數量。`Accept: application/json`可讀機器格式。
- Owner：`GET /threads/privacy/actions`、`POST /threads/privacy/actions/{id}/review`，沿用既有登入／CSRF／權限；審查不是清除完成。
- 受信任管理員：`POST /ui/admin/threads/privacy/lookup`，以確認碼查詢既有收據；`POST /ui/admin/threads/privacy/recover`以收據request_hash恢復。普通使用者不能呼叫。
- 狀態確認碼由既有管理金鑰推導，DB只存雜湊；金鑰輪替後舊狀態連結仍可讀，原事件重送若無法重建同碼會停止並要求管理員審查，不重做資料操作。

## 官方查核與真實驗收

[Meta資料刪除官方文件](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback/)、[官方Deauthorize說明](https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow/#deauth-callback)本次查核回429／無法擷取。HMAC與base64url解析對照[Meta官方封存SDK SignedRequest](https://github.com/facebookarchive/php-graph-sdk/blob/5.x/src/Facebook/SignedRequest.php)，以Python標準庫自行實作，沒有引入或複製PHP SDK。

**不能把封存SDK當成當日Threads全部規格的重新認證**。真實Meta的簽章Secret、user_id命名空間、issued_at及回應接受情況，仍須以這個App實際送達驗證；不嘗試多個App Secret或猜測ID映射。格式不符時拒絕處理，不能為了測試成功而降低驗證。

真實驗收步驟：本人在Meta保存三網址並完成本機Secret配置，使用合成／本人測試帳號連接；再由本人在Meta／Threads移除App授權及觸發資料刪除。核對Meta後台動作與伺服器收據時間、App、確認碼、Tenant操作及狀態。這會撤銷該帳號，必須由本人明確操作；本次開發不代按。簽章正確本身只能證明持有App Secret，不能獨立公證實際發送者就是Meta。

本次合成簽章、HTTP與資料庫測試不能替代真實Meta送達。來源分支與現有啟動檔變更保留；Migration0013只新增欄位／兩表／RLS，不刪舊資料。模型與發文、一次性手機通道維持false；實際模型API費用USD0。測試、部署與尚未完成項目見[驗收證據](THREADS_PRIVACY_EVIDENCE.md)。
