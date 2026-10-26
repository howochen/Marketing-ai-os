# 手機遠端完成 Threads 憑證配置

2026-10-26 實際唯讀檢查：TeamViewer 已安裝、執行檔簽章有效、服務 Running／Automatic，且有連外連線；這不代表本人已登入遠端桌面。Chrome Remote Desktop 未偵測到安裝；Windows RDP 停用，沒有改動防火牆或啟用 RDP。

## 優先沿用 TeamViewer

1. iPhone 開啟原有 TeamViewer，登入原本授權這台電腦的帳戶。自行完成帳戶驗證；不把密碼／驗證碼交給 Codex。
2. 在「裝置／電腦與聯絡人」找原 Windows 電腦，選擇遠端控制（實際裝置別名只於本次交接提供，不提交 Git）。若此前有帳戶指派與無人值守授權，可由既有帳戶權限連線；不能用「服務在線」當作已配置無人值守的證據。
3. 若要求未知密碼、本機同意或帳戶不符，就停止並回報狀態，不要傳送密碼。沒有讀取 TeamViewer 密碼、PIN、Token 或包含它們的畫面。
4. 本人確認已看見 Windows 桌面後，由 Codex 開啟既有 `Setup-Threads.cmd` 的可見獨立終端，無輸出重導向／錄製。本人在 `getpass` 隱藏提示輸入 Threads Secret；Codex 不截圖、不讀該終端、不擷取輸入。繼續沿用 DPAPI 與既有安裝器。
5. 輸入完成、離開敏感畫面後，本人通知 Codex。只執行既有 `--diagnose`，取得配置狀態及官方帳號驗證結果。然後由本人在 iPhone Safari 使用既有 `/app/threads` 完成 OAuth；發布與模型開關一直保持 false。

Google 的 Chrome Remote Desktop 首次設定需要本人 Google 授權、設定 PIN，可能需要 Windows 系統授權。沒有已驗證的遠端通道時，不能承諾本人不在場仍可完成這些步驟，也不能替本人繞過驗證。本次沒有新安裝常駐遠端工具。

## 遠端工具無法使用時的方案（提案，尚未建置或啟用）

**此舊提案已被新的安全需求取代。不可只用公開指紋核准裝置。** 本次離線實作改用既有系統管理員認證、私鑰持有證明與可驗真的裝置收據；尚未啟用，見 [最新安全設計與啟用前提](PHONE_SETUP_SECURITY.md)。以下僅保留未採用提案歷史，不是啟用指引。

不開放一般 Secret 表單，不把 bootstrap 密碼／一次性 bearer 放聊天或 URL。可在既有 HTTPS 入口增加**一次性、手機金鑰配對的受限管理交接**：

1. Windows 本機受信任 Codex 操作只開啟一個十分鐘的初始化工作，不開放通用系統管理或 Shell。
2. iPhone Safari 產生僅存在該頁面的不可匯出簽章私鑰。本人把**公開金鑰指紋（不是 Secret）**回覆給 Codex，Windows 才核准精確對應的手機；不得由陌生請求、電子郵件自稱或 agent 自行看到的指紋自動批准。
3. 核准後手機才可進入專用管理頁。只接受 App ID／Secret，使用瀏覽器 Web Crypto 加密給 Windows 的公鑰，並以手機私鑰簽署 server nonce／請求，避免一般表單與重放。Secret 不進 URL、本機儲存、伺服器 log 或聊天。
4. 現有 Docker API 只暫存受限加密信封；Windows 本機初始化器以原有可信管理通道取回、解密，保存 DPAPI，重用 Compose 更新後端。私鑰不進 Docker；不新增 Adapter 或第二個帳本。
5. 限一次成功、短效、不可重放、速率限制、原子消耗；逾時即關閉，發文旗標不可配置為 true。需要先完成認證／跨裝置／並行／失敗／無秘密 log 的實測，才可收真實 Secret。

這個方案尚未實作，不能當作已存在的安全入口。目前優先等待本人確認 TeamViewer 是否可連線，避免為已安裝工具能解決的問題增加新管理介面。

## 本次維護

修復先前唯讀手機登入視窗整段持有 setup.lock，阻擋真正初始化及診斷的問題；GUI 顯示前釋放鎖。殘留明文暫存檔的清理也改到取得鎖後，避免另一個執行個體誤清理進行中的設定。新增 Windows 原生鎖回歸，安裝器27項通過。沒有修改 Threads Adapter 或放寬 OAuth／tenant 權限。

重新診斷：HTTPS、UI、Callback 路徑可用；仍缺後端 App ID／Secret，Meta URI 登錄未確認，官方帳號清單空。OAUTH_VERIFIED=false、PUBLISH_VERIFIED=false，尚未取得真正 Threads ID，沒有發布。

官方參考：[Google iPhone 遠端桌面說明](https://support.google.com/chrome/answer/1649523?co=GENIE.Platform%3DiOS&hl=zh-Hant)、[TeamViewer 無人值守設定](https://www.teamviewer.com/en/global/support/knowledge-base/teamviewer-remote/remote-control/provide-unattended-remote-support/)。
