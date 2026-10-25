# P0.5 開源與成熟方案審查

查核日2026-10-25。優先重用現有 FastAPI、Pydantic、SQLAlchemy、PostgreSQL、Alembic、HTTPX、pytest、pip-audit；沒有新增 runtime 第三方 library、Redis、IdP、queue、付費服務。

| 領域 | 現有／免費方案 | 付費或較重方案 | 決定 |
|---|---|---|---|
| 限流 | 既有 DB 的 atomic upsert，共用跨程序計數；SlowAPI 0.1.10/MIT，官方 PyPI 列2026-06-13 release及 Redis/memcached/memory backends | managed Redis/WAF，費用依實際供應商方案 | 小規模試點採既有 DB，免加 runtime 依賴及 cache 維運；公開大流量再評估 edge limits/SlowAPI |
| 身分 | 現有環境限定 bearer；Keycloak 開源 Apache-2.0、官方26.8.1 release，標準OIDC/SAML | Supabase Auth hosted Free/Pro，見下表 | 此階段不部署 IdP；Production Gate 再用成熟 protocol 接入，不自行造 OAuth |
| 回收 | 一個 stdlib Event loop＋既有 HTTPX，重用冪等 endpoint；OS/service restart | Celery/Redis、Kafka、Kubernetes | 目前不需 queue framework；每個 tenant 明確 worker，排程本身不生成 AI |
| 備份 | 既有 pg_dump/pg_restore、stdlib assert drill，免授權費但有維運成本 | managed PITR／異地備份，需報價 | 本次 synthetic 快照演練；正式加密 retention/PITR 留 Gate |
| 型別 | compileall 只查語法；mypy 2.4.0/MIT，官方 PyPI 列 stable且2026-10-01 release | 商業SAST／完整企業安全平台 | 新增唯一直接 dev dependency mypy，對五模組 strict annotated definitions/check_untyped_defs；不重構全專案 |

## 新套件明細與版本固定

- mypy 2.4.0 MIT；只在 development/test image。
- resolver 帶入 mypy_extensions 1.1.0 MIT、librt 0.16.0 MIT、ast_serialize 0.13.1 MIT、pathspec 1.1.1 MPL-2.0。版本、license metadata及上游 URL 保存 p05/new-dependencies.json；pathspec 已讀 wheel 內 LICENSE 確認 MPL-2.0。僅作未修改之開發工具依賴，分發時保留上游 notices；沒有把它引入 runtime API。
- 其他既有依賴的來源見 DEPENDENCIES.md。constraints.txt 固定本次 resolver，direct pins 與 image digest 固定已測版本；pip-audit 本次零已知漏洞。
- CI 新增 GitHub 維護的 upload-artifact v4（MIT，非 Python runtime 依賴），只保存 synthetic backup evidence JSON，不上傳敏感 archive。

官方來源：[mypy](https://pypi.org/project/mypy/)、[SlowAPI](https://pypi.org/project/slowapi/)、[Keycloak](https://www.keycloak.org/)、[Keycloak license](https://github.com/keycloak/keycloak/blob/main/LICENSE.txt)。保留原工具鏈，不為引入工具而擴張架構。

## 商用身分候選（尚未接入／購買）

| 方案 | 免費與成本邊界 | 後續接入方式／取捨 |
|---|---|---|
| Keycloak self-host | 開源授權本身免費；主機、patch、備份、MFA delivery與人力不免費 | 標準 Authorization Code + PKCE，驗證 issuer/audience/expiry、JWKS rotation、state/nonce，再做本地 tenant/role mapping。能力完整但多一個需維運的服務，先不部署 |
| Supabase Auth | 官方當日 Free USD0/月、50,000 MAU；Pro 起USD25/月、含100,000 MAU，另有使用量/功能費用。Free inactivity pause 等限制，delivery/SMS成本另看供應商 | 以其已驗證的登入/JWT，保留本地 tenant scope、worker separation、revocation policy。不能把 free tier 當 production SLA |
| 現有 bearer pilot | 無新增授權／服務費；僅閉門人工核身及安全交付 | 能滿足受控開發，不能宣稱已具 MFA、公開帳號復原或企業身分功能 |

價格來源：[Supabase 官方方案](https://supabase.com/pricing)。此為查核日資料，不是購買建議或固定報價；選定服務時再次確認條款。正式接入前需做 threat model、tenant identity mapping、失效／撤銷／MFA測試及production proxy驗證。
