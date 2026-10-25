# OpenAI provider verification — 2026-10-26

Today OpenAI Docs were searched and the official pages below actually opened. Public documentation confirms API aliases `gpt-6-luna` and `gpt-6.1-sol`; it does not confirm this user's account access. **ACCOUNT_ACCESS_NOT_VERIFIED**: no account credential was obtained and no account/model probe or paid generation was performed.

| Standard short-context USD / million tokens | Input | Output | Cached read | 30m write | 12h write |
|---|---:|---:|---:|---:|---:|
| gpt-6-luna | 0.10 | 0.50 | 0.01 | 0.125 | 0.25 |
| gpt-6.1-sol | 2.00 | 10.00 | 0.10 | 2.50 | 5.00 |

Source: [official pricing](https://developers.openai.com/api/docs/pricing), checked 2026-10-26, Standard/Short selection. Flex/Batch/Fast/Ultrafast tables differ. Regional/FedRAMP uplift and long-context prices must not be silently ignored. These match frozen P12 cards; historical rate hashes/effective_at remain unchanged. Check date is not a provider-announced price-effective date: the latter was not established. A changed price requires a new immutable RateVersion, never a historical update.

[Model Luna](https://developers.openai.com/api/docs/models/gpt-6-luna) and [Model Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol): Responses/text and structured outputs supported; published context 1.05M, max output128K. Local contract remains input4096/output1024, low reasoning, standard service, no tools. Aliases may change. Multilingual capability is not proof of Traditional Chinese Threads marketing quality; smoke/12-case human assessment remain unexecuted.

[Responses reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs): text.format strict JSON schema, max_output_tokens, usage/id/status/incomplete_details. JSON schema success never implies QA/approval. Refusal, truncation, invalid JSON and unknown billing feature require review; no fallback or blind resend.

[Caching](https://developers.openai.com/api/docs/guides/prompt-caching): input total includes reads/writes, so ordinary=input-cached-write. TTL write details must reconcile. [Reasoning](https://developers.openai.com/api/docs/guides/reasoning): reasoning is included in output and maximum output, not added twice; incomplete generation can consume billable reasoning even without a usable draft. Cache TTL parameter/account applicability must be rechecked before spending; no assumption that every priced TTL is available to this account.

[API overview](https://developers.openai.com/api/reference/overview): response id differs from x-request-id and client X-Client-Request-Id; the latter is traceability, not an external exactly-once guarantee. [Error codes](https://developers.openai.com/api/docs/guides/error-codes): invalid/auth/access/429 classified separately from server/network ambiguity. [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits): request/token/project limits depend on organization/model/tier; account settings/headers are required to confirm actual limits, not a guessed fixed RPM.

[Input counting reference](https://developers.openai.com/api/reference/cli/resources/responses/subresources/input_tokens/methods/count): complete supported input/text/schema/tools/reasoning counting contract. No real count request was sent. Mock count333 is not a real token count. Reliable pre-send upper bound is **NOT VERIFIED for the actual account**; live_cost_bound_verified stays false. Request/tool pricing ambiguity blocks sending.
