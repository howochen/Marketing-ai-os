# P0 成本報告 — MOS-P0-009

日期：2026-10-25 Asia/Taipei。範圍：本機離線驗收及 Docker PostgreSQL；不含付費 API。

本次 Live AI API：**0 calls，實際付費 USD 0**。沒有操作真實社群帳號、購買雲端服務或產生營收。單元測試 ledger 中的成本均為合成資料，不是發票或實際支出。Codex／帳號原有訂閱不屬於這裡的 API 消費；本次 per-task agent token 用量工具不可得，NOT_AVAILABLE。

## 本次量測

| 容器 | CPU 瞬間樣本 | 記憶體 |
|---|---:|---:|
| API | 0.12% | 63.34 MiB |
| PostgreSQL | 2.53% | 50.67 MiB |
| 合計 | 不作月平均推算 | 114.01 MiB |

測試資料庫 8,879,127 bytes（約 8.47 MiB）。原始證據：`p0-009/resources.jsonl`、`p0-009/database-size.txt`。樣本是在離線 suite 後取得，不是負載測試；不含 Docker VM／host、image layers、備份及虛擬磁碟預留空間。前一次驗證的 94.63 MiB 資料仍保留在歷史 P0_EVIDENCE，不覆寫為本次數值。

## 月成本的邊界

本次未新增需付費的軟體服務，新增服務費 USD 0；這不是整台主機總持有成本為零的宣稱。既有主機、網路、Docker／OS 授權與 CI entitlement 必須依實際帳號計算。尚無雲端 region、SKU、備份容量與電力計量資料，不能提供實測月帳單。

全天運行規劃採 730 小時/月：額外電力成本 = 額外 watts ÷ 1000 × 730 × 當地 USD/kWh。純假設 10 W、USD 0.15/kWh，則 USD 1.095/月；並非本機量測支出。付費模型成本必須另計，不包含在 P0 固定 overhead。驗收容器完成後停止，保留測試資料卷供追查。

模型 input/output/cache 單價目前來自 config/models.json 的既有 rate card；本次沒有做外部即時費率確認，也沒有付費收據證明。Token 預估上限不等於實際帳單：reserve 是風險上界，settle 根據 provider usage 計算，discount／region／歷史版本／發票仍需對帳。
