# UI 設計與瀏覽器檢查

使用 design-taste-frontend 的 app-screen 規則；framed-sheet／smb-admin light，seed 880232445，未重新抽方向。採 228px 側欄、白色工作表、低彩度背景與 teal 狀態色；三道獨立關卡為系統配置、本人授權、逐篇公開確認。不加入無資料來源的營運指標。

ROUND 1：一秒可辨識「社群帳號」與目前工作區；內容來自合成 tenant API，清楚標示非真實 OAuth。人工檢查 desktop、tablet、mobile 截圖後，手機版連接按鈕文字換行不佳，改為獨立滿寬操作列。沒有使用模擬成效或假裝已完成的正式發布。

ROUND 2：檢查 1440／768／390 全寬畫面與固定內容預覽。所有 viewport 無水平溢位；側欄在小螢幕改為 menu，對話框使用原生 dialog，表單有 label／焦點／錯誤提示。主按鈕與停用狀態清楚，敏感配置只顯示布林。

人工自評：設計 8/10、易用性 8/10、創意 7/10、內容 9/10（主觀自評，不是使用者研究）。設計技能 inspector 的機器量測與截圖見 pub002/inspect/report.json；12 個登入後頁面響應式 smoke 見 pub002/browser.json。實際畫面位於 pub002/screens/。所有截圖均為合成資料。
