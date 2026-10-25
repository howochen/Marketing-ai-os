# P1.2 未來真實模型 Benchmark 規格

版本 `p12-benchmark-1`，資料 `agents/A09/evals/p12/benchmark.json`。從 P1.1 六產業各選 tone／audience 兩個正向 source case，共12例，保存原固定 ID／資料版本、虛構品牌需求、客群、Threads 目標、constraints、rubric 與預期成本欄位。兩例增加明確繁體中文要求；audience 例改為提問邀請回覆，adaptation 有記錄，不偷改舊60例資料集。

未來比較兩個經官方文件確認的 API ID：**gpt-6-luna 與 gpt-6.1-sol**，分別作低成本／較高能力定位的候選；不是用價格判定勝負。本次未實際呼叫或評比它們。Anthropic 新模型只做文件研究，不加入隱含 fallback。

硬性 QA 沿用 A21 schema／長度／Hook／CTA／必要與禁止詞／明確品牌限制／不可信輸入／虛假成效／產業宣稱；任何硬性失敗即不合格，不能被高人工總分抵銷。人類另依 `a09-rubric-1` 八維0–5評分，必須提供 reviewer、來源及完整維度。沒有分數填 null／UNEVALUATED；不接付費 AI judge。

人工修訂記錄：每次保留 immutable Revision ID、reason、前後文與 diff。以 monotonic timer 計 active start/end，暫停等待不計，保存整數 active seconds 與 revision count；沒有測量就 null，不能填0偽裝沒花時間。試驗評分宜隱藏模型名、固定順序／隨機順序種子、保留評分理由；總成本包含被拒絕稿件與修訂成本，不能只統計成功篇數。

`app/benchmark.py` 接受每篇 case/model、usage、rate snapshot、source、硬性 QA、人工分數來源、修訂次數／秒數與可選人工成本時薪。產出：

- 每篇 input／cached／cache-write／output／reasoning（subset）計量與來源。
- 每篇模型費用、各模型總費用、QA 通過率、人工平均及已評篇數。
- 每篇與整體修訂次數／active seconds；未測資料維持未知。
- 每篇合格文案總成本：全部嘗試的模型費用＋全部人工修訂成本，除以合格篇數，向上取整 micro-USD；缺人工成本／時間或合格數為0時 null。
- 兩模型成本、QA 通過率及人工平均差值；缺人工評分不填品質差值。

此版本可供 review 的資格門檻是硬性 QA pass＋完整人工總分≥24/40＋claim_safety≥3；仍不構成 owner approval 或發布權限。模型 Token／來源與 invoice 欄位分離，不能以費率試算冒充 invoice。

Mock 演練：[mock-benchmark.json](p12/mock-benchmark.json)，12×2=24篇，token-shaped usage 全部來自固定 Mock HTTP，人工32/40與每篇一次／60秒修訂都是 HUMAN_SYNTHETIC 測試輸入，不是人類實際花費或模型真實結果。QA 格式測試24/24；兩模型每篇模擬成本190／3,770 micro-USD、合計2,280／45,240；以合成 USD1/時，人工向上取整每篇16,667，總成本每合格篇16,857／20,437 micro-USD。報表差值只驗證算術，不能拿來宣布 Sol／Luna 品質優劣、繁體中文能力或市場成效。

重現：`pytest -q tests/test_provider_readiness.py::test_benchmark_12_cases_two_models_and_arithmetic`。真正模型品質報表必須另經 Live Gate、人類支出授權、可靠成本上界及真實人工評測後才能產生。
