# Threads 官方 API 查核

查核日：2026-10-26（Asia/Taipei）。只讀公開官方文件，沒有使用帳號、App Secret 或 Provider Token，也未呼叫任何真實 Threads API。

主要文件 https://developers.facebook.com/docs/threads 、Changelog https://developers.facebook.com/docs/threads/changelog ，以及 authorization/posts/overview 子頁在本次工具中皆回傳429。**不能宣稱已核對最新 Changelog、全部 App Review 政策或帳戶可用權限。**

已實際讀取的官方備援來源：

- [Meta 官方 Postman collection](https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api)：建立、發布、OAuth code/long token/refresh。
- [Meta 官方範例](https://github.com/fbsamples/threads_api)：Threads 專用 App ID/Secret、HTTPS redirect。
- [官方範例原始碼](https://raw.githubusercontent.com/fbsamples/threads_api/main/src/index.js)：目前 API host為graph.threads.com、授權站www.threads.com；舊官方 Postman變數仍是graph.threads.net/www.threads.net。實作固定使用現行範例.com，不跟隨redirect、不自行跨host重試。
- [官方 collection 原始 JSON](https://raw.githubusercontent.com/fbsamples/threads_api/main/postman/threads-api.postman_collection.json)：quota/config、container狀態、profile/media欄位與debug契約。
- [官方設定範例](https://raw.githubusercontent.com/fbsamples/threads_api/main/.env.template)：Graph版本可省略以使用App預設，v1.0只是可選範例。實作不猜最新版本，省略path版本；實際App版本／host可用性仍須setup時確認。

| 操作 | 實作的官方契約 |
|---|---|
| 授權 | www.threads.com/oauth/authorize；client_id/redirect_uri/response_type=code/scope/state |
| 交換 | POST graph.threads.com/oauth/access_token；後端form傳client_id/client_secret/code/grant_type=authorization_code/redirect_uri |
| 長效Token | GET /access_token；th_exchange_token、client_secret、Bearer短效Token；不將URL寫Log |
| 更新 | GET /refresh_access_token；th_refresh_token，僅未過期且本地至少24h長效Token；回應重新驗證 |
| 最小權限 | threads_basic、threads_content_publish；不要求insights/delete等無關scope |
| 身分 | GET /me?fields=id,username；GET /debug_token?input_token=...；嚴格核對app_id/user_id/is_valid/scopes/expires_at，不以授權URL中請求的scopes冒充實際grant |
| 建立 | POST /{threads-user-id}/threads，media_type=TEXT、text；**不傳auto_publish_text** |
| 狀態 | GET /{container-id}?fields=id,status,error_message；FINISHED才准發布；IN_PROGRESS保留容器，ERROR/EXPIRED轉人工，PUBLISHED無media ID轉待對帳 |
| 發布 | POST /{threads-user-id}/threads_publish，creation_id；回傳id另存published_media_id，不能用container_id代替 |
| 驗證 | GET /{published-media-id}，id/owner/username/text/permalink/timestamp/media_type；精確核對帳號、文字與合法HTTPS連結才可能真實verified |
| 額度 | GET /{user-id}/threads_publishing_limit?fields=quota_usage,config；使用即時quota_total，不硬編碼每日額度。官方範例250/86400秒只是範例，非本帳戶保證 |

本地撤銷會刪除密文並停用帳號。因最新Provider端撤銷契約未核實，不發明DELETE端點；使用者須在Threads已連接App設定移除權限，回傳provider_revocation_verified=false。App Review／Standard或Advanced access、當日測試帳號資格、實際API版本及debug回應可用性是尚待平台設定驗證的項目。

## 依賴必要性與授權

新增直接依賴 cryptography50.0.2（2026-09-30，PyCA，Apache-2.0 OR BSD-3-Clause），[PyPI官方metadata](https://pypi.org/project/cryptography/50.0.2/)與[Fernet官方文件](https://cryptography.io/en/latest/fernet/)已查核；使用認證加密，不自製演算法。固定transitive cffi2.1.1（MIT-0）／pycparser3.12（BSD-3-Clause），以安裝metadata核對。現有Python標準庫沒有適當Token認證加密；外部KMS可替代，但未配置且不為本單新增付費服務。重用HTTPX／Pydantic／SQLAlchemy，無Threads SDK或大型框架。完整掃描見threads/dependency-audit.txt；掃描不是供應鏈或Production安全保證。

來源追溯：官方sample src/index.js最後變更583bfaa9a7272b7d7c574446e97f38e483a8c6ca，collection最後變更3dad45605cb16bea65f102f9b9173b177817e3dd，兩者日期2026-03-24。這是執行當日讀取的官方範例，不表示它包含當日全部正式政策；對應metadata保存在threads/official-*-source.json。主站與Changelog的429仍是最新政策驗證缺口。
