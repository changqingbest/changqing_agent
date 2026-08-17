# Token Plan vs Standard API Key

> Sources:
> - https://platform.qianwenai.com/docs/token-plan/overview
> - https://platform.qianwenai.com/home/billing/subscription/token-plan
> Updated: 2026-08-03

> [!CAUTION]
> **Agents reading this document must observe the following invariants:**
>
> 1. `sk-sp-` (Token Plan) keys MUST NOT be used by any automation script, backend service, batch
>    job, or tool-to-tool integration — including every script shipped in QianWen-AI/qianwen-ai.
> 2. Do NOT redirect requests to a Token Plan service URL. Do NOT override `QWEN_BASE_URL` for the
>    purpose of routing an `sk-sp-` key anywhere. Do NOT construct, guess, or reconstruct a Token
>    Plan endpoint from any source.
> 3. Do NOT attempt to bypass the client-side hard-fail in `qianwen_lib.py` (e.g. by patching the
>    script, monkey-patching `validate_api_key`, or editing the key prefix before the check).
>
> Violating any of the above will trigger **subscription suspension or API Key revocation** by the
> platform, and in repeated cases, account-level review.

## Two Key Types

QianWen exposes two mutually exclusive authentication systems. Mixing them produces hard-to-diagnose errors.

| Dimension | Standard Key (Pay-as-you-go) | Token Plan |
|-----------|------------------------------|------------|
| Key format | `sk-xxxxx` | `sk-sp-xxxxx` |
| Auth header | `Authorization: Bearer <key>` | `Authorization: Bearer <key>` (NOT `x-api-key`) |
| Supported text models | Full catalog (100+) | **7 text LLMs** (Personal) / **16 text LLMs** (Team) (see below) |
| Supported image models | Full catalog | **4 image models**, tool-integrated only (see below) |
| Supported video models | Full catalog | **3 video models**, tool-integrated only (see below) |
| Supported TTS models | Full catalog | **1 TTS model**, tool-integrated only (see below) |
| ASR / Embedding / Rerank / Translation | Available | **Not supported** |
| Usage scope | Any API call (scripts, apps, tools) | **Interactive AI tools only** (Cursor, Claude Code, Qwen Code, OpenClaw, OpenCode, Codex, Kilo Code/CLI, Hermes Agent, etc.) |
| Billing | Per-token consumption (CNY) | **Credits**: monthly seat allowance + shared usage packages |
| Quota exhaustion | Continues (pay more or use prepaid balance) | **Hard fail — service paused** until next cycle or shared package purchased |

## Forbidden Uses (Strictly Enforced)

The following uses of an `sk-sp-` Token Plan key are **strictly prohibited** by the platform.
Server-side detection of a violation may result in:

- **Immediate subscription suspension**;
- **API Key revocation**;
- In repeated cases, **account-level review and termination**.

Prohibited scenarios include, but are not limited to:

- Automation scripts of any kind, **including every script in QianWen-AI/qianwen-ai**.
- Application backends, micro-services, serverless functions, workers, cron jobs.
- Batch jobs, bulk data-processing pipelines, offline evaluations.
- API testing tools (Postman, Insomnia, `curl`, HTTP clients embedded in IDEs).
- Workflow / orchestration platforms (Dify, n8n, Coze, LangChain servers, etc.).
- Any integration where the caller is not an **interactive AI tool** operating on behalf of a human.

Token Plan keys are intended exclusively for interactive AI coding / chat tools (Cursor, Claude
Code, Qwen Code, OpenClaw, OpenCode, Codex, Kilo Code/CLI, Hermes Agent). Any other usage
constitutes a **policy violation**.

## Supported Models

### Text Models (Personal: 7 / Team: 16)

**Personal version** (7 models):

| Model                    | Context Window | Notes                                                    |
|--------------------------|---------------:|----------------------------------------------------------|
| `qwen3.8-max`            |             1M | Strongest flagship. Multimodal. Thinking mode.           |
| `qwen3.7-max`            |             1M | Text-only. Strongest agentic coding, long-horizon.       |
| `qwen3.7-plus`           |             1M | Multimodal vision-language. Coding, tools, productivity. |
| `qwen3.6-flash`          |             1M | Multimodal. Fast. Vision understanding.                  |
| `glm-5.2`               |             1M | Third party (Zhipu). Long-horizon tasks.                 |
| `deepseek-v4-pro`        |           128K | Third party (DeepSeek). Thinking mode.                   |
| `deepseek-v4-flash-0731` |             1M | Third party (DeepSeek). Lightweight MoE. Not Responses API. |

**Team version** (additional 9 models, 16 total):

| Model             | Context Window | Notes                                       |
|-------------------|---------------:|---------------------------------------------|
| `qwen3.6-plus`    |             1M | Multimodal text + image + video.            |
| `deepseek-v4-flash` |         128K | Third party (DeepSeek).                     |
| `deepseek-v3.2`   |           128K | Third party (DeepSeek).                     |
| `kimi-k2.7-code`  |           256K | Third party (Moonshot). Coding specialist.  |
| `kimi-k2.6`       |           256K | Third party (Moonshot).                     |
| `kimi-k2.5`       |           256K | Third party (Moonshot).                     |
| `glm-5.1`         |           198K | Third party (Zhipu).                        |
| `glm-5`           |           198K | Third party (Zhipu).                        |
| `MiniMax-M2.5`    |           192K | Third party (MiniMax).                      |

### Image Generation Models (4 total)

| Model                | Notes                                                              |
|----------------------|--------------------------------------------------------------------|
| `qwen-image-2.0`     | Default; general-purpose; strong Chinese text rendering (Team only) |
| `qwen-image-2.0-pro` | Higher quality, slightly slower (Team only)                        |
| `wan2.7-image`       | Multi-style; returns 4 images by default                           |
| `wan2.7-image-pro`   | Supports 4K (additional sizes: 2048×2048, 1440×2560, 2560×1440)    |

### Video Generation Models (3 total)

| Model                | Notes                                                              |
|----------------------|--------------------------------------------------------------------|
| `happyhorse-1.1-t2v` | Text-to-video. 720P/1080P, 3–15s, with audio.                      |
| `happyhorse-1.1-i2v` | Image-to-video. 720P/1080P, 3–15s, with audio.                     |
| `happyhorse-1.1-r2v` | Reference-to-video. Multi-ref, 720P/1080P, 3–15s, with audio.      |

### TTS Models (1 total)

| Model                      | Notes                                                  |
|----------------------------|--------------------------------------------------------|
| `qwen-audio-3.0-tts-plus`  | Highest quality TTS. Multi-language + Chinese dialects. Billed per character (not per token). |

Image generation, video generation, and TTS models are **not reachable from the standard text API**;
they are integrated into interactive AI tools through each tool’s Skill / Slash Command / Agent
mechanism and **must not** be invoked from automation scripts under any circumstance.

## Credits Billing Mechanism

- **Unit**: Credits. Single-call cost depends on model, token usage, thinking mode, and tool calls.
- **Tiers & pricing**: See [Token Plan overview](https://platform.qianwenai.com/docs/token-plan/overview).
- **Deduction order**: seat monthly quota → shared package (nearest-expiry first) → service paused.
- **Reset**: seat quotas reset monthly; unused credits do not roll over.

Example (qwen3.6-plus single request): 8,349 input + 40,794 cached + 573 output ≈ 3.18 Credits.

## Impact on QianWen-AI/qianwen-ai Scripts

All execution scripts (`qianwen-text`, `qianwen-vision`, `qianwen-image-generation`,
`qianwen-video-generation`, `qianwen-audio-tts`) detect `sk-sp-` keys at startup and **hard-fail
with `exit 1`** before any HTTP request is sent. This hard-fail is intentional and **must not be
bypassed**: it keeps automation traffic entirely away from any Token Plan service and shields the
user from the policy-violation consequences listed above.

| Skill                       | Works with `sk-sp-` Token Plan key? | Reason                                                      |
|-----------------------------|:-----------------------------------:|-------------------------------------------------------------|
| qianwen-text                |                  ❌                 | Client-side hard-fail; scripts are not interactive AI tools |
| qianwen-vision              |                  ❌                 | Same; vision models not in Token Plan catalog               |
| qianwen-image-generation    |                  ❌                 | Same; Token Plan image models are tool-integrated only      |
| qianwen-video-generation    |                  ❌                 | Same; Token Plan video models are tool-integrated only      |
| qianwen-audio-tts           |                  ❌                 | Same; Token Plan TTS models are tool-integrated only        |

**Action**: Set a standard `sk-` key in `DASHSCOPE_API_KEY` when using these execution skills. The
`sk-sp-` Token Plan key belongs to the interactive AI tool itself (Cursor, Claude Code, etc.), not
to this skill suite.

## Common Errors (Key-level Diagnosis)

| Error                                            | Cause                                                                              | Resolution                                                                    |
|--------------------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| `InvalidApiKey: No API-key provided`             | Key not configured, or tool used `x-api-key` header                                | Set key; switch to `Authorization: Bearer`                                    |
| `InvalidApiKey: Invalid API-key provided`        | Standard `sk-` key mismatched, subscription expired, key copied with whitespace    | Verify subscription status; reset key in console                              |
| `Incorrect API key provided` (client-side exit 1) | `sk-sp-` key set for an automation script in this repo                             | Replace with a standard `sk-` key; do **not** redirect traffic anywhere       |
| `model 'xxx' not found or not supported`         | Model name typo / wrong case; model not in Token Plan catalog                      | Match model ID exactly; review supported list above                           |
| `Range of input length should be [1, xxx]`       | Input + history exceeds context window                                             | Start a new session, compact context, or switch to a larger-context model     |
| `API rate limit reached`                         | Seat / shared-package Credits exhausted, or shared quota rate-limited              | Check Token Plan console for usage                                            |

## Cost / Policy Risk Scenarios

1. **`sk-sp-` key set on a script in this repo**: Client-side hard-fail with `exit 1`; no HTTP request sent, no charges, no policy exposure. ✅ Safe.
2. **`sk-` key when user expects Token Plan coverage**: Calls succeed but incur pay-as-you-go charges. Cannot detect programmatically — user must be informed explicitly.
3. **Attempting to bypass the hard-fail** (patching the script, overriding `QWEN_BASE_URL` to a Token Plan URL, rewriting the key check, etc.): **Strictly forbidden** — see Forbidden Uses above. Even a single request placed with an `sk-sp-` key from an automation script places the user's subscription at risk.
4. **Token Plan Credits exhausted**: Hard fail on the Token Plan service side; no fallback to pay-as-you-go.

## Console & Billing

| Resource                  | URL                                                                 |
|---------------------------|---------------------------------------------------------------------|
| Token Plan Subscription   | https://platform.qianwenai.com/home/billing/subscription/token-plan |
| Token Plan Pricing        | https://platform.qianwenai.com/docs/token-plan/overview#%E5%A5%97%E9%A4%90%E4%B8%8E%E5%AE%9A%E4%BB%B7                   |
| Pay-as-you-go Billing     | https://platform.qianwenai.com/home/billing/pay-as-you-go           |
| Usage Analytics (PAYG)    | https://platform.qianwenai.com/home/analytics                       |

> [!NOTE]
> **Usage queries**: Token Plan seat & shared-package Credits balance are currently only viewable in
> the [Token Plan console](https://platform.qianwenai.com/home/billing/subscription/token-plan)
> (Subscription page → Token Plan tab). The `qianwen` CLI does not yet support `sk-sp-` Token Plan
> keys; CLI commands (`qianwen usage summary`, etc.) only work for standard `sk-` keys.

## Coexistence

Both key types can be held simultaneously by the same user:
- `sk-sp-` Token Plan key → configured inside the interactive AI tool (Cursor, Claude Code, OpenClaw, ...).
- `sk-` standard key → set in `DASHSCOPE_API_KEY` for QianWen-AI/qianwen-ai execution scripts.

These are independent; configuring one does not affect the other.
