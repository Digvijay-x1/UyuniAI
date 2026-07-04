# Open-Source Models with Structured Output Support

This document lists the **open-source / open-weight** models that support **structured output** i.e. constraining the model's response to a JSON schema, which is exactly what Pydantic emits via `BaseModel.model_json_schema()` and what libraries like `instructor` / the OpenAI SDK's `response_format` use.

**Mode legend**
- `json_schema` — native strict structured output (best; direct Pydantic schema).
- `json_object` — JSON mode (returns valid JSON; matching your schema is not guaranteed. So don't use them).

---

## Supported models

| # | Model ID | Family | Mode | Notes |
|---|----------|--------|------|-------|
| 1 | `qwen/qwen3.7-max` | Qwen | json_schema | |
| 2 | `qwen/qwen3.7-plus` | Qwen | json_schema | |
| 3 | `qwen/qwen3.6-plus` | Qwen | json_schema | |
| 4 | `qwen3.6-flash` | Qwen | json_schema | |
| 5 | `qwen/qwen3.5-flash` | Qwen | json_schema | |
| 6 | `qwen/qwen3.5-plus-02-15` | Qwen | json_schema | |
| 7 | `qwen/qwen3.5-9b` | Qwen | json_schema | |
| 8 | `qwen/qwen3.5-35b-a3b` | Qwen | json_schema | needs larger `max_tokens` (reasoning) |
| 9 | `qwen/qwen3.5-122b-a10b` | Qwen | json_schema | |
| 10 | `qwen/qwen3.5-397b-a17b` | Qwen | json_schema | needs larger `max_tokens` (reasoning) |
| 11 | `qwen/qwen3-coder-next` | Qwen | json_schema | |
| 12 | `qwen3.5-omni-plus` | Qwen | json_schema | returned a JSON array wrapping the object |
| 13 | `deepseek/deepseek-v4-pro` | DeepSeek | json_object | strict `json_schema` returned "unavailable"; JSON mode works |
| 14 | `deepseek/deepseek-v4-flash` | DeepSeek | json_object | same as above |
| 15 | `z-ai/glm-5` | GLM (Z-AI) | json_schema | |
| 16 | `z-ai/glm-5.2` | GLM (Z-AI) | json_schema | |
| 17 | `z-ai/glm-5.1` | GLM (Z-AI) | json_schema | |
| 18 | `z-ai/glm-5-turbo` | GLM (Z-AI) | json_schema | |
| 19 | `z-ai/glm-4.7` | GLM (Z-AI) | json_schema | |
| 20 | `z-ai/glm-4.6` | GLM (Z-AI) | json_schema | |
| 21 | `z-ai/glm-4.6v` | GLM (Z-AI) | json_schema | |
| 22 | `z-ai/glm-4.5-air` | GLM (Z-AI) | json_schema | |
| 23 | `moonshotai/kimi-k2.7-code` | Kimi (Moonshot) | json_schema | |
| 24 | `moonshotai/kimi-k2.6` | Kimi (Moonshot) | json_schema | |
| 25 | `moonshotai/kimi-k2.5` | Kimi (Moonshot) | json_schema | |
| 26 | `openai/gpt-oss-120b` | GPT-OSS (open weights) | json_schema | |
| 27 | `mistralai/mistral-medium-3-5` | Mistral | json_schema | |
| 28 | `mistralai/mistral-small-2603` | Mistral | json_schema | |
| 29 | `mistralai/devstral-2512` | Mistral | json_schema | |
| 30 | `mistralai/voxtral-small-24b-2507` | Mistral | json_schema | |
| 31 | `nvidia/nemotron-3-super-120b-a12b` | Nemotron (NVIDIA) | json_schema | |
| 32 | `xiaomi/mimo-v2.5-pro` | MiMo (Xiaomi) | json_schema | |
| 33 | `xiaomi/mimo-v2.5` | MiMo (Xiaomi) | json_schema | |
| 34 | `minimax/minimax-m2.7` | MiniMax | json_schema | |
| 35 | `minimax/minimax-m2.7-highspeed` | MiniMax | json_schema | |
| 36 | `minimax/minimax-m2.5` | MiniMax | json_schema | |
| 37 | `minimax/minimax-m2.1` | MiniMax | json_schema | |
| 38 | `minimax/minimax-m2.1-highspeed` | MiniMax | json_schema | |
| 39 | `minimax/minimax-m2-her` | MiniMax | json_object | requires `max_tokens <= 2048` |
| 40 | `MiniMax-M3` | MiniMax | json_schema | valid JSON, wrapped in `<think>` tags + ```` ```json ```` fence |
| 41 | `stepfun/step-3.7-flash` | StepFun | json_schema | |
| 42 | `sakana/fugu-ultra` | Sakana | json_schema | |


---


*last updated on 2026-07-05. Model behaviour may change over time.*
