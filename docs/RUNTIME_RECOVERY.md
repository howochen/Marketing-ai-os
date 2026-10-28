# MOS Windows 運行環境恢復

2026-10-28；只修正既有運行環境，沒有重建 API、OAuth、資料庫或金鑰。

使用者另行批准將公開入口與 MOS Callback 改為 `https://metathetic-nonlyric-lana.ngrok-free.dev`。ngrok 已接受此網域並實際恢復同一 HTTPS 入口，沒有購買服務。Meta 後台沒有代改，使用者仍須保存新的 `/threads/oauth/callback`；既有 @boomajbeauty Token 保留且官方 GET profile/debug 驗證有效。

## 已安裝

- Docker Desktop：原生 AutoStart 會被應用程式回寫為 false，因此不依賴直接編輯其設定。由同使用者的 Windows 登入 Task 在引擎未就緒時啟動 Docker，另保留 HKCU Run 備援；無需系統管理員永久憑證。
- API、原 PostgreSQL 容器：`on-failure:3`。Task 只啟動登錄的原容器，檢查 ID、映像與 Volume；不 build、不 migrate、不 compose up、不啟用 Worker。
- Windows Task `MOS Runtime Recovery`：目前使用者登入及每2分鐘觸發、同時只執行一份、單次最多5分鐘。DPAPI 僅在使用者登入後以原身分解密。安裝的 helper 固定複製到 `.threads-local/runtime-recovery/installed`，不依賴目前 Git 分支是否保留該檔。
- 每項恢復每小時最多3次，超限持久化暫停；單純重啟 Task 不會清空限制。修復並手動啟動服務後，成功健康檢查才解除暫停。失敗狀態顯示於 Task 結果及桌面「MOS 自動恢復狀態」捷徑。
- ngrok 只恢復核准網址，沒有隨機網址 fallback；關閉流量檢視與日誌，保留上游 TLS 驗證。啟動設定在原私有 ACL 目錄短暫產生，讀取後移除；Token 不進命令列、Git 或狀態。
- 公開健康檢查最多每15分鐘一次，外部網路故障不觸發重啟風暴。
- 既有安裝器重用已配置的 `.ngrok-free.dev`，不重新隨機分配。

## 實際驗收

- 故障注入：API 被中斷後恢復；ngrok 程序停止後，由安裝的 Windows Task 恢復同一固定網域。
- 恢復前後 Vault bytes、Threads Token 密文相符；API 映像保留、原 PostgreSQL Volume 保留。
- 新 HTTPS `/ready` 實際回應 Schema0015；Task `LastTaskResult=0`。
- 既有 Token 新程序解密及官方唯讀 profile/debug 驗證成功，仍是 @boomajbeauty，含 threads_basic／threads_content_publish；沒有刷新或改寫 Token。
- 恢復與原安裝器隔離回歸49 passed。沒有付費模型呼叫、貼文、持續 Worker。
- **未實際重開整台 Windows**；已安裝 AtLogon 並執行相同 Task 動作。需要 Windows 使用者登入，關機、睡眠、斷電、斷網或 ngrok 故障時無法保證外部可用。免費網域不等於正式營運 SLA。

## 復原與維護

`.threads-local/runtime-recovery` 以既有使用者／SYSTEM ACL 保護，包含 Vault 與 API 設定的 DPAPI 備份、原 Docker 設定備份、非秘密狀態及故障演練結果。舊 API 容器保留為 `mos-api-before-fixed-runtime`（已停止），沒有移除任何資料卷。

停止恢復可停用 Windows Task；回復網域需要另行核對 MOS／Meta Callback，不自動改回舊網域。未來重新建立容器或升級映像後，Task 會拒絕未登錄容器，須由受信任操作人重新核對設定；不為了方便接受任意映像。
