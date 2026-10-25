# 真實Threads發布驗收

**THREADS_LIVE_PUBLISH：BLOCKED — BLOCKED_BY_PLATFORM_SETUP**。

使用者明確回覆尚未設定Meta App，先完成程式與教學。尚無本人OAuth連接、官方帳號ID或明確要公開的測試文字。沒有真實Threads OAuth、建立、發布或查詢請求；沒有真實公開貼文。

| 證據 | 本次值 |
|---|---|
| 官方帳號ID／username | 未取得；測試10001等均為合成數值 |
| Container ID | 未取得真實值 |
| Published Media ID | 未取得真實值 |
| 發布時間 | 不存在 |
| 真實貼文連結 | 不存在；測試SYNTHETIC網址不是交付成果 |
| 官方讀回驗證 | 尚未執行 |
| Threads App可見性 | 尚無貼文，不能要求使用者假確認 |
| 真實AI API calls／成本 | 0／USD0 |

將來必須依序：持有人完成App／OAuth→確認官方帳號→明確確認一篇完整公開文字→取得既有owner批准Revision→逐篇確認hash與account→由受控worker只執行一次→保存官方Published ID→GET讀回核對→提供實際permalink→使用者在Threads App確認同一篇內容。只有最後ID、讀回、真實連結與使用者App確認全部成立才可宣稱Live Publish VERIFIED。

Mock回應即使格式一致，也只能MOCK_READBACK_PASSED，仍PUBLISHED_UNVERIFIED／verified_at=NULL。Container20001、Media30001僅離線Fixture；不能引用為真實發布成果。尚未執行第二道驗收，因此排程仍阻擋，不擴充其他平台。
