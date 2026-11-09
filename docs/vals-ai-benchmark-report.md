# Vals AI Benchmarks: Availability Summary

Research date: 2026-10-16 · Source: [vals.ai/benchmarks](https://www.vals.ai/benchmarks), [github.com/vals-ai](https://github.com/vals-ai) (32 public repos)

**Totals: 46 benchmarks (30 active, 16 archived) + 3 active indices.**
- Fully public: 20 total (9 active)
- Sample only: 11 total (8 active)
- Restricted: 15 total (13 active)

## Master table

Access: **Public** = full dataset downloadable · **Sample** = small public slice, rest private · **Restricted** = nothing usable public.
Local run: **Y** = yes · **Y (gated)** = free after a click-through agreement · **Y\*** = sample only · **N** = no.
"Runnable by us" counts only test cases we can download and run without asking Vals (0 = none). Items available only on request or by licence are not counted.
`—` = not confirmed. † = archived.

| Domain (# benchmarks) | Benchmark | Test cases (total) | Runnable by us (no request) | Access | Status | Licence | Local run | Link |
|---|---|---|---|---|---|---|---|---|
| **Legal (4)** | Legal Research Bench | 208 | 5 | Sample | Active | MIT (harness) | Y\* | [GitHub](https://github.com/vals-ai/legal-research-bench) |
| | Harvey Legal Agent Bench (HLAB) | ~1,250 (Vals run repo) | ~1,250 | Public | Active | MIT | Y | [GitHub](https://github.com/harveyai/harvey-labs) |
| | LegalBench | 162 tasks | 162 tasks | Public | Active | CC BY 4.0 (dataset); per-task source licences | Y | [GitHub](https://github.com/HazyResearch/legalbench) |
| | CaseLaw v2† | 404 (300 val + 104 test) | 0 | Restricted | Archived | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/case_law_v2) |
| **Finance & Tax (6)** | Finance Agent v2 | 927 | 27 | Sample | Active | MIT (harness) | Y\* | [GitHub](https://github.com/vals-ai/finance-agent-v2) |
| | Excel Modeling (EMB) | 103 | 1 | Sample | Active | None stated | Y\* | [GitHub](https://github.com/vals-ai/emb-public-dataset) |
| | Tax Agent Bench | 391 | 5 | Sample | Active | MIT (harness) | Y\* | [GitHub](https://github.com/vals-ai/tax-agent-bench) |
| | CorpFin v2† | 1,218 | 0 (20 on request) | Sample | Archived | — | N | [Vals](https://www.vals.ai/benchmarks/corp_fin_v2) |
| | MortgageTax† | 1,258 | 0 (20 on request) | Sample | Archived | — | N | [Vals](https://www.vals.ai/benchmarks/mortgage_tax) |
| | TaxEval v2† | 1,543 | 0 (20 on request) | Sample | Archived | — | N | [Vals](https://www.vals.ai/benchmarks/tax_eval_v2) |
| **Medical & Mental Health (4)** | MedCode | 2,755 codes | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/medcode) |
| | MedScribe | — | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/medscribe) |
| | SAFE-Teen | 106 scenarios | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/mental-health) |
| | MedQA† | 1,273 (original test set) | 1,273 | Public | Archived | MIT | Y | [GitHub](https://github.com/jind11/MedQA) |
| **Math (4)** | ProofBench v1.1 | 200 (Vals page) | 2 | Sample | Active | None stated | Y\* | [GitHub](https://github.com/vals-ai/proof-bench) |
| | AIME† | — | 30 (2024 set) | Public | Archived | — | Y | [HuggingFace](https://huggingface.co/datasets/HuggingFaceH4/aime_2024) |
| | MATH 500† | 500 | 500 | Public | Archived | — | Y | [HuggingFace](https://huggingface.co/datasets/HuggingFaceH4/MATH-500) |
| | MGSM† | — | — | Public | Archived | — | Y | [GitHub](https://github.com/google-research/url-nlp/tree/main/mgsm) |
| **Science & Robotics (7)** | Terminal-Bench Science | 70 | 70 | Public | Active | Apache-2.0 | Y | [GitHub](https://github.com/harbor-framework/terminal-bench-science) |
| | BioMysteryBench (Anthropic) | — | — | Public (gated) | Active | CC BY 4.0 (no model training) | Y (gated) | [HuggingFace](https://huggingface.co/datasets/Anthropic/BioMysteryBench-full) |
| | MysteryMechanism | 222 | 0 (3 examples shown) | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/mysterymechanism) |
| | Robo-bench | 24 | 0 (3 named public) | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/robo_bench) |
| | GPQA Diamond† | 198 | 198 | Public (gated) | Archived | CC BY 4.0 | Y (gated) | [HuggingFace](https://huggingface.co/datasets/Idavidrein/gpqa) |
| | MMLU-Pro† | 12,032 (upstream) | 12,032 | Public | Archived | MIT | Y | [HuggingFace](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro) |
| | MMMU Pro† | 1,730 (upstream) | 1,730 | Public | Archived | Apache-2.0 | Y | [HuggingFace](https://huggingface.co/datasets/MMMU/MMMU_Pro) |
| **Education (1)** | SAGE | — | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/sage) |
| **Voice (1)** | VoiceCodeBench | 300 clips | 300 clips | Public | Active | MIT (text); audio: no voice cloning | Y | [HuggingFace](https://huggingface.co/datasets/besimple-ai/voice-code-bench) |
| **Coding (12)** | Vibe Code Bench v1.1 | — | 0 | Restricted (access plan pending) | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/vibe-code) |
| | Vibe Code Bench 1-100 | 100 apps / 939 requests | 1 app | Sample | Active | None stated | Y\* | [GitHub](https://github.com/vals-ai/vcb-1-100-public-dataset) |
| | Code Migration | 130 migrations | 6 repos | Sample | Active | None stated | Y\* | [GitHub](https://github.com/vals-ai/code-migration-public) |
| | ProgramBench | 200 | 200 | Public | Active | MIT | Y | [GitHub](https://github.com/facebookresearch/ProgramBench) |
| | Terminal-Bench 4.0 | 66 | 66 | Public | Active | Apache-2.0 | Y | [GitHub](https://github.com/harbor-framework/terminal-bench) |
| | SkillsBench | — | — | Public | Active | Apache-2.0 | Y | [GitHub](https://github.com/benchflow-ai/skillsbench) |
| | IOI | 18 problems (2024–26) | 12 problems (2024–25, Vals repo) | Sample | Active | None stated | Y\* | [GitHub](https://github.com/vals-ai/ioi-agent) |
| | SWE-bench Multimodal | 480 test + 100 dev | 580 | Public | Active | MIT | Y | [GitHub](https://github.com/SWE-bench/SWE-bench) |
| | Terminal-Bench 2.1† | 89 | 89 | Public | Archived | Apache-2.0 | Y | [GitHub](https://github.com/harbor-framework/terminal-bench-2-1) |
| | Terminal-Bench 2.0† | 89 | 89 | Public | Archived | Apache-2.0 | Y | [GitHub](https://github.com/harbor-framework/terminal-bench-2) |
| | SWE-bench Verified† | 500 | 500 | Public | Archived | MIT | Y | [GitHub](https://github.com/SWE-bench/SWE-bench) |
| | LiveCodeBench† | 1,000+ (v6) | 1,000+ | Public | Archived | MIT | Y | [GitHub](https://github.com/LiveCodeBench/LiveCodeBench) |
| **Cybersecurity (2)** | CyberBench v1.1 | 116 (60 PoC + 56 patch) | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/cyber) |
| | SRE Bench | 262 instances | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/srebench) |
| **Games & Computer Use (3)** | CUA-bench | 6 games | 0 (3 games named, no harness) | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/cua_bench) |
| | Time Horizon Index: KSP | 30 missions | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/time_horizon_index) |
| | Poker Agent | 20,000 hands, 17 models | 0 (code "soon") | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/poker_agent) |
| **Social Mobility (2)** | Public Benefits Bench v1.1 | 459 scenarios (230 test) | 0 | Restricted | Active | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/public-benefits-bench) |
| | Public Benefits Bench v1† | — | 0 | Restricted | Archived | Proprietary | N | [Vals](https://www.vals.ai/benchmarks/public-benefits-bench-v1) |

Notes:
- "Y" does not mean offline. Many harnesses need API keys (model, Tavily, SEC-API, CourtListener) or LLM judges.
- Vals' own harnesses do not document self-hosted models, so expect a small adapter.
- Sample-only runs are smoke tests. They cannot be compared with the Vals leaderboard.
- Finance Agent v2's 27 public questions ship with their rubric ([data/public.csv](https://github.com/vals-ai/finance-agent-v2/blob/main/data/public.csv)), but scoring needs Vals' judge and search tools.

## Key terms

| Term | Meaning |
|---|---|
| **Index** | Vals' name for a headline score. The Vals Index blends 8 benchmarks into one number. The RSI Index and Web Search Index are single evaluations that carry the name. The Multimodal Index is archived. |
| **Vals Index** | Finance 8.0, Coding 5.6, Legal 1.2, Tax 0.5, weighted by each sector's share of GDP, so one number reflects economic weight. The formula is public, but most inputs are private, so outsiders cannot reproduce it. ([page](https://www.vals.ai/benchmarks/vals_index)) |
| **Vals RSI Index** | RSI = Recursive Self-Improvement. It tests whether a model can do the research that builds the next model: compression, LLM training, harness engineering, post-training. ([page](https://www.vals.ai/benchmarks/rsi_index)) |
| **Web Search Index** | One research agent where only the web-search tool changes, run on the Finance Agent v2 and Legal Research questions. ([page](https://www.vals.ai/benchmarks/web_search), [repo](https://github.com/vals-ai/web-search-agent-public)) |
| **Public / Private validation / Test** | Vals' three splits. Public is open (a small sample). Private validation is licensed to companies by contacting contact@vals.ai. Test is never shared and produces all published scores. ([methodology](https://www.vals.ai/methodology)) |
| **Proprietary / Industry Partner / Academic** | Vals' origin tags. Proprietary means built by Vals. Industry Partner means built by a company such as Harvey or Anthropic. Academic means from a university or open project. |
| **Archived** | Vals no longer runs it on new models because scores saturated. Old results are kept. |
| **Harness** | The code that gives a model its tools and prompts and scores the output. |
| **Valkyrie** | Vals' open-source (AGPL-3.0) system for running agent benchmarks at scale. It uses Vals-hosted or self-hosted AWS infrastructure with cloud sandboxes, so it is not a local-only tool. ([docs](https://docs.valkyrie.vals.ai/introduction/what-is-valkyrie), [repo](https://github.com/vals-ai/Valkyrie)) |

## Who runs the evaluations?

Vals runs every model itself under its own fixed harness. Its methodology says: *"we run every model ourselves under the same harness and settings."* I found no programme where labs run the private tests and submit their own scores. Labs and enterprises are paying customers who license the validation sets for internal use. ([methodology](https://www.vals.ai/methodology), [about](https://www.vals.ai/about), [Sacra](https://sacra.com/c/vals-ai/))

## Caveats

- Counts and labels come from Vals pages and upstream sources checked on 2026-10-16. Some Vals pages were truncated.
- Counts marked "upstream" are the original dataset sizes. Vals may run a subset.
- The ProofBench total (200) comes from Vals' page. Its repo shows only 2 sample problems.

## Local proxy suite (about 70 minutes, no Docker)

`BENCHMARK_TYPE=vals-public` runs 60 pinned public question-and-answer tasks one after another against any OpenAI-compatible endpoint. Each task is one chat request whose reply is checked against an answer key or rubric, so it needs only Python and the API: no Docker, Harbor or SWE-bench. Every result is labelled **`public_proxy — not Vals leaderboard comparable`** and links to the exact public task, the Vals page and the pinned upstream version.

| Domain | Source | Vals status | Cases | Cap per case |
|---|---|---|---:|---:|
| Legal | LegalBench (8 task types) | Active | 16 | 120 s |
| Finance & Tax | Finance Agent v2 public questions | Active | 14 | 420 s |
| Medical | MedQA | Archived | 12 | 120 s |
| Math | AIME 2024 and 2025 | Archived | 9 | 420 s |
| Science | MMLU-Pro (engineering, physics, chemistry, biology) | Archived | 9 | 240 s |

Schedule: typical 65–75 minutes on a responsive model, with a 100-minute hard limit plus about a minute of preflight. LegalBench 16 cases; Finance Agent v2 14 public questions (closed-book, rubric-judged); archived MedQA 12 original public cases; archived AIME 9 problems; archived MMLU-Pro 9 questions. Finance (about 2–3 minutes per question, including the judge calls), AIME and the engineering questions take most of the time; a faster or slower model shifts the total. Timings come from calibration runs on `ornith-1.5-A3B`.

Scoring notes:
- **LegalBench:** pinned upstream base prompts, verbatim, for abercrombie, function_of_decision_section, international_citizenship_questions, proa, hearsay, personal_jurisdiction, diversity_1 and ucc_v_common_law. The local matcher accepts a label as the last line or opening the first line and ignores a short prefix such as `Answer:`, `A:` or `Governed by:`. It is not LegalBench's official `evaluation.py`.
- **Finance Agent v2:** closed-book, with no web or EDGAR tools, so facts after the model's knowledge cutoff cannot be met. An LLM judge checks each answer criterion by criterion against the public rubric ([data/public.csv](https://github.com/vals-ai/finance-agent-v2/blob/502aab6fdaa3fb9294905c7453f89882baa8d39b/data/public.csv)). It defaults to the model under test; set `VALS_JUDGE_BASE_URL`, `VALS_JUDGE_MODEL` and `VALS_JUDGE_API_KEY` for an independent judge. Pass means a score of 40% or more, a threshold chosen for this proxy rather than taken from Vals; the Finance headline is the mean score (severity-weighted share of criteria met), shown in the report beside the pass rate. Vals' own judge and tools are not used.
- **MedQA:** the original public test set. Vals' bias-injected variants are not published.
- **AIME:** two problems from AIME 2024 and seven from 2025 (diagrams and data-artifact problems excluded). Vals' own AIME benchmark uses both years. The reply must end in `\boxed{}`; integer answers compare as integers, so `025` equals `25`.
- **MMLU-Pro:** zero-shot, letters A–J, graded from the last `Answer: [letter]` (or `answer is (X)`) line. Five computational engineering questions, plus physics, chemistry and biology.
- **Caps:** replies are capped at 4,096 tokens (10,240 finance, 8,192 science, 16,384 AIME). A reply cut off at the cap scores `fail` and is never graded from its partial reasoning. Finance runs at `medium` reasoning effort unless `OPENAI_REASONING_EFFORT` or `VALS_FINANCE_REASONING_EFFORT` is set, because a thinking model with no limit can spend the whole cap reasoning and return an empty reply. On the calibration run, three engineering items, two AIME 2025 problems and two Finance answers were cut off at lower caps, which is why these are higher.

```bash
BENCHMARK_PROFILE=advanced BENCHMARK_TYPE=vals-public \
OPENAI_BASE_URL=http://127.0.0.1:8000/v1 OPENAI_MODEL=my-model \
./benchmark/run.sh --preflight    # then run again without --preflight
```

Not covered: coding (Terminal-Bench and SWE-bench have their own modes in this harness and need Docker), Education, Cybersecurity, Games & Computer Use and Social Mobility (no public data), and Voice (needs an audio-capable model). Active Terminal-Bench 4.0 is too hard for a short run: Vals puts the median task at about 4 expert-hours with an 8-hour agent limit.

Four to sixteen cases per domain gives a 95% interval of roughly ±25–50 points, so treat each domain as an indicator, not a ranking.
