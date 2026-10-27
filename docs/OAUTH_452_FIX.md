# MOS-OAUTH-452

Checked 2026-10-27. Real audit: `threads.oauth_failed.LONG_TOKEN.CONTENT_REJECTED.452`.

The official [Meta Postman collection](https://github.com/fbsamples/threads_api/blob/main/postman/threads-api.postman_collection.json) inherits OAuth2 `addTokenTo=queryParams`. Its long exchange is GET `/access_token`, `grant_type=th_exchange_token`, Threads `client_secret`, with the short token supplied by that helper. MOS previously supplied only a Bearer header. Only the long exchange now supplies explicit `access_token` query parameter instead. No short-code replay, automatic retry, refresh or publishing change.

Runtime App ID, Secret, token encryption key and callback match existing Windows DPAPI configuration. Earlier read-only app-credential exchange was accepted; this does not independently prove Threads-specific dashboard identity or the failed short token's app binding. Failed short tokens were not retained. Existing successful-flow identity checks require the configured app ID and matching short-token user ID before encrypted storage. Credential mismatch and upstream causes remain unexcluded until fresh official consent succeeds; 452 alone is not a definitive diagnosis.

Bounded code/subcode, ASCII error type and fbtrace_id are retained in existing audit events linked to the OAuth state. Raw provider messages, URLs, codes, tokens and secrets are not recorded. No schema change or new dependency. Query logging remains disabled.

Mock tests cover official query placement, encrypted storage, 452 and safe diagnostics, one-use state and replay rejection. Real completion requires the user to start a new official OAuth flow. Mock success does not establish real OAuth success. AI, publishing and worker activation remain prohibited.
