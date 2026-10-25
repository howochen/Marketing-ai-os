# P0.5 安全審查

日期：2026-10-25。適用範圍：封閉開發／小規模受控試點，沒有真實客戶或社群帳號。不是公開 production 安全認證。

## 身分可用性結論

既有高熵 bearer hash、單次 10 分鐘 challenge、24 小時 owner/worker、role AND scope、revocation 足以作為此封閉範圍的最小方案，前提是管理員人工核身、安全交付、租戶隔離及 rotation。沒有自創 OAuth。Production 仍需成熟 IdP、MFA/abuse recovery、正式審計與交付服務。

0003 credential.environment 與執行 MOS_ENV 必須一致。P0 舊 credentials 保留但標 legacy，必須重新發行；test key 不會跨入 production。admin header 不能替代 worker bearer，worker 不能 mint worker credentials 或 approve。原有 expiry/revoke/replay/越權 negative tests 全保留。

## 防濫用及部署

Rate limit 用同一 PostgreSQL atomic upsert，SQLite 可測。login/admin 10 次／60 秒／peer，其餘 mutation 120 次；多程序共享，不因 worker restart 清零。失效 DB 回503 fail-closed；過期 counter 24h 清理。外部 X-Forwarded-For 不作 identity，避免任意偽造。反向代理後所有使用者共享 proxy peer 的額度，屬保守試點限制；大規模公開服務需在可信 ingress 做 edge/per-account limits 及容量規劃，不能把本機限流當 DDoS 防護。

Production 啟動檢查強 secret、非已知 test/placeholder、PostgreSQL、HTTPS public URL、顯式非 /0 proxy CIDR、model/live flags=false。Uvicorn --no-proxy-headers；HTTP middleware 只允許直接 TLS 或可信 proxy＋x-forwarded-proto=https。Compose 預設只綁 loopback。這沒有驗證實際 DNS、TLS certificate、proxy firewall 或公網 ingress，Production Gate 必須另實測。

HTTP request body 全程15秒／64KiB；DB connect5秒、statement10秒、lock5秒；provider transport60秒、無自動重試；recovery HTTP15秒且不跟隨 redirect、不讀環境代理。Provider timeout 是 HTTPX transport inactivity/phase timeout，不是能撤回已計費請求的 wall-clock deadline。同步函式不靠粗暴取消後重試，未知結果進待對帳。實際公開 ingress 的 request/concurrency limits 另列部署驗證。

## 紀錄與秘密

app.operations 只允許固定 event/status/count，包含 security.denied/throttled、cost.overrun、task.failed、scheduler.completed/failed；不收自由文字／headers／payload。現有 logging handlers 另套 SecretFilter，遮罩已配置 secrets、Bearer、mos_/sk- token、URL password，包括 exception text。caplog／stdout／stderr／audit／錯誤 response negative tests 通過。新裝的 logging handler、第三方 custom extra fields 或未識別 secret 格式需重新套 filter／審查，不能保證任意未受控 handler 都安全。

備份 archive 包含敏感 hash／業務內容，保持 root-owned 0600/0700，未加入 Git／artifact；Docker admin/root 仍可讀。只上傳 synthetic fingerprints JSON。

## 持續保留的邊界與風險

- RLS 對七張 tenant tables force；runtime 不能 owner/superuser/BYPASSRLS。rate_versions 為非機密共用 read-only card；rate_limits 僅 peer/group hash 與計數，並非匿名化保證。
- API server 與資料庫管理員仍屬信任根；不聲稱防禦完整伺服器被入侵。Migration role 不可交給 API。
- 尚無 live provider/invoice 驗真；VERIFIED 值只為獨立 verifier 的後續契約，現有 API 不提供 promotion。
- 無任何真實社群授權或發布；四平台仍 manual_only；無 webhook 接收器。
- 無外部滲透、OS image CVE scan、正式 DB TLS／secret manager／加密異地備份／持續 RPO 證據。
- 依賴 exact pins 與已測 image digest；Python wheel hashes／供應鏈簽章尚未做完整驗證。

本機 secret-pattern 與提交範圍檢查見 p05/security-scan.txt。掃描不取代人工審查與正式環境測試。
