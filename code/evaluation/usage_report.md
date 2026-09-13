# Usage Report

Run: `python3 code/main.py --refresh` over 250 requests in `dataset/requests.csv`.

Only two steps call a model: interpreting messages and reading images for blank amounts. Every number in `output.csv` is computed deterministically, and explanations are templated, so model usage scales with the evidence, not with the number of requests.

## Per model

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Est. cost (USD) |
|---|---|---:|---:|---:|---:|---:|
| Anthropic | `claude-opus-5` | 209 | 335,077 | 10,040 | 345,117 | 1.9264 |
| **All** | | **209** | **335,077** | **10,040** | **345,117** | **1.9264** |

## Per step

| Step | Calls | Input tokens | Output tokens | Est. cost (USD) |
|---|---:|---:|---:|---:|
| image | 11 | 23,242 | 371 | 0.1255 |
| message | 198 | 311,835 | 9,669 | 1.8009 |

## Per request

- Average tokens per request: 1,380.5
- Average estimated cost per request: $0.00771
- Cached extractions reused (no call made): 0

Costs use list prices per million tokens: `claude-opus-5` $5 input / $25 output, `claude-opus-4-8` $5 input / $25 output.
