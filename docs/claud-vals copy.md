# Vals AI Benchmarks: Public vs. Restricted Availability

**Research date:** 2026-10-16
**Scope:** vals.ai (benchmark pages, methodology, about), the `vals-ai` GitHub organisation (32 public repositories), and third-party coverage.
**Question:** How much of Vals AI's benchmark ecosystem can we download and run on our own machines, and does Vals run the models itself or let labs submit results?

---

## 1. Executive summary

1. **About a third of Vals AI's active benchmarks are fully public, and none of those were built by Vals.** Vals lists 46 benchmarks (30 active, 16 archived), plus 3 active composite indices.
   - **Fully public:** 21 of 46 overall, or 10 of the 30 active.
   - **Public sample only:** 10 of 46 overall, or 7 of the 30 active.
   - **Restricted:** 15 of 46 overall, or 13 of the 30 active.
2. **The fully public ones are third-party or academic benchmarks that Vals runs.** Examples are Terminal-Bench, SWE-bench, IOI, LegalBench and Harvey's Legal Agent Benchmark.
3. **Vals' own "Proprietary" benchmarks are never fully downloadable.** Of the 20 active benchmarks Vals labels proprietary, 7 publish a small sample plus an open harness (about 1–3% of items). The other 13 publish nothing usable.
   - The remaining items sit in a private validation set (licensed by contacting Vals) and a hidden test set (never shared).
   - The test set produces the published leaderboard numbers.
4. **Vals runs the evaluations itself.** Its methodology page says *"we run every model ourselves under the same harness and settings."*
   - I found no programme where labs run Vals' private test sets and submit their own scores.
   - Labs do publish their own numbers elsewhere (model cards), and Vals has publicly shown a case where those numbers differ sharply from its own (section 6).
5. **Running locally is realistic for the public set, with caveats.** The open harnesses are Python plus Docker. They need API keys for the model being tested, and often for search tools and LLM judges. Vals' own harnesses do not document support for self-hosted models. A thin adapter will be needed (section 5).

---

## 2. How Vals structures its data

Vals' methodology page describes three splits for its proprietary benchmarks:

| Split | Who can get it | Used for |
|---|---|---|
| **Public** | Anyone (sample, GitHub or on request) | Transparency, smoke tests |
| **Private validation** | Companies, by licence (contact@vals.ai) | Internal validation and tuning |
| **Test** | Nobody. Kept private "at all times". | The only data behind published leaderboard scores |

Vals states the private validation set is statistically correlated with the test set. The stated purpose is to stop leakage into model training data.

Vals also tags each benchmark on its index page as **Proprietary**, **Industry Partner** (built by a partner such as Harvey, Anthropic or besimple.ai) or **Academic**. The index page applies no "public" or "open" label.

**Examples of sizes (Vals benchmark pages):**

| Benchmark | Public | Private validation | Test |
|---|---|---|---|
| Finance Agent v2 | 27 | 450 | 450 |
| Tax Agent Bench | 5 | 193 | 193 |
| Excel Modeling Benchmark (EMB) | 1 | 51 | 51 |
| CorpFin v2 (archived) | 20 | 340 | 858 |
| MortgageTax (archived) | 20 | 300 | 938 |
| TaxEval v2 (archived) | 20 | 300 | 1,223 |

---

## 3. Classification used in this report

| Tier | Meaning | Local run? |
|---|---|---|
| **Open** | Full dataset publicly downloadable, with a public harness (upstream or Vals) | Yes |
| **Partial** | Only a small public sample (and usually a harness). Scored data is private. | Smoke test only. Scores are not comparable to the leaderboard. |
| **Restricted** | No usable public data or code, or demo examples only | No |

Archived benchmarks (†) are ones Vals no longer runs on new models because scores saturated. Their data may still be downloadable.

---

## 4. Counts

### 4.1 Overall

| | Total | Open | Partial | Restricted |
|---|---:|---:|---:|---:|
| **All benchmarks** | 46 | 21 (46%) | 10 (22%) | 15 (33%) |
| **Active only** | 30 | 10 (33%) | 7 (23%) | 13 (43%) |
| Active, Vals-built ("Proprietary", 20) | 20 | 0 | 7 | 13 |
| Active, third-party (Industry Partner 3 + Academic 7) | 10 | 10 | 0 | 0 |

The Vals Index, Vals RSI Index and Web Search Index are weighted aggregates of the above. The Vals Multimodal Index is archived. Their formula is public, but Vals says most of their inputs are private benchmarks "that no other party has full access to," so the scores cannot be reproduced from outside.

### 4.2 By domain (Open / Partial / Restricted)

| Domain | All | Active only |
|---|---|---|
| Legal | 4: 2 / 1 / 1 | 3: 2 / 1 / 0 |
| Finance and tax | 6: 0 / 6 / 0 | 3: 0 / 3 / 0 |
| Medical and mental health | 4: 1 / 0 / 3 | 3: 0 / 0 / 3 |
| Math | 4: 3 / 1 / 0 | 1: 0 / 1 / 0 |
| Science (incl. robotics) | 7: 5 / 0 / 2 | 4: 2 / 0 / 2 |
| Education | 1: 0 / 0 / 1 | 1: 0 / 0 / 1 |
| Voice | 1: 1 / 0 / 0 | 1: 1 / 0 / 0 |
| Coding and software engineering | 12: 9 / 2 / 1 | 8: 5 / 2 / 1 |
| Cybersecurity | 2: 0 / 0 / 2 | 2: 0 / 0 / 2 |
| Games and computer use | 3: 0 / 0 / 3 | 3: 0 / 0 / 3 |
| Social mobility | 2: 0 / 0 / 2 | 1: 0 / 0 / 1 |
| **Total** | **46: 21 / 10 / 15** | **30: 10 / 7 / 13** |

Domains follow Vals' own category headings. Finance is entirely Partial and Coding is the most open.

---

## 5. Benchmark-by-benchmark inventory

† = archived. "Vals" = built by Vals (Proprietary). Item counts are those stated on Vals' pages. "Not stated" means the page did not say.

### Legal
| Benchmark | Tier | What is actually public |
|---|---|---|
| Legal Research Bench | Partial | 5 sample questions plus agent harness, MIT (`vals-ai/legal-research-bench`). Scored set private (208 tasks per the Web Search Index page). |
| Harvey's Legal Agent Benchmark (HLAB) | Open* | Harvey's public dataset and harness, MIT (`harveyai/harvey-labs`). Vals' repo `harvey-labs-public-dataset-runs` holds Vals' outputs for 14 models on about 1,250 public tasks. The Vals leaderboard uses a separate held-out set. *Task counts: Harvey's repo badge says 2,010, Vals' run files show about 1,250, and I could not reconcile them. |
| LegalBench | Open | Public academic dataset of crowd-sourced legal reasoning tasks (Vals page gives no count or link). |
| CaseLaw v2† | Restricted | Fully private (300 validation, 104 test). Canadian case law, built with Jurisage. |

### Finance and tax
| Benchmark | Tier | What is actually public |
|---|---|---|
| Finance Agent v2 | Partial | 27 questions plus harness, MIT (`finance-agent-v2`). 450 validation (licence) and 450 test (private). Harness needs Tavily, SEC-API and Tiingo keys. |
| Excel Modeling Benchmark (EMB) | Partial | 1 task (`emb-public-dataset`, no licence file): inputs, gold workbook, rubric. 51 validation (licence) and 51 test. |
| Tax Agent Bench | Partial | 5 questions plus harness, MIT (`tax-agent-bench`). 193 validation (licence) and 193 test. The README says no Vals account is needed to run locally. |
| CorpFin v2† | Partial | 20-sample public set on request by email. 340 validation purchasable, 858 test. The SDK repo (MIT) holds no data. |
| MortgageTax† | Partial | 20 on request, 300 validation purchasable, 938 test. Documents from Vontive. |
| TaxEval v2† | Partial | 20 on request, 300 validation purchasable, 1,223 test. |

### Medical and mental health
| Benchmark | Tier | What is actually public |
|---|---|---|
| MedCode | Restricted | Nothing found (2,755 codes, Harvard and Protege partners). |
| MedScribe | Restricted | Nothing found (100 rubrics, synthetic transcripts, Protege). |
| SAFE-Teen | Restricted | Nothing found (106 scenarios). A `petri` fork exists in the org (tooling, not data). |
| MedQA† | Open | Public academic dataset. |

### Math
| Benchmark | Tier | What is actually public |
|---|---|---|
| ProofBench v1.1 | Partial | `vals-ai/proof-bench` (no licence file) contains 2 sample Lean problems. **Conflict:** the Vals page says a 100-problem public split and a 100-problem private split exist, while the repo README says only samples are public. |
| AIME†, MATH 500†, MGSM† | Open | Public academic datasets. |

### Science (including robotics)
| Benchmark | Tier | What is actually public |
|---|---|---|
| Terminal-Bench Science | Open | 70 tasks, `harbor-framework/terminal-bench-science`. |
| BioMysteryBench | Open? | Anthropic's benchmark (reported 99 questions). Vals' page says the materials are CC BY 4.0 with a no-model-training restriction. **I did not find the download location.** |
| MysteryMechanism | Restricted | 222 mechanisms. Only 3 frozen examples are shown on the page, no download. |
| Robo-bench | Restricted | 24 tasks. 3 are named public, 21 held out, no download or licence. |
| GPQA Diamond† (198 q), MMLU-Pro†, MMMU / MMMU-Pro† | Open | Public academic datasets. |

### Education, voice
| Benchmark | Tier | What is actually public |
|---|---|---|
| SAGE | Restricted | Public "Calculus" split points to CollegeBoard's published AP free-response questions and is excluded from the score. The private validation set is licensable. |
| VoiceCodeBench | Open | 300 clips on Hugging Face (`besimple-ai/voice-code-bench`), MIT. Built by besimple.ai. |

### Coding and software engineering
| Benchmark | Tier | What is actually public |
|---|---|---|
| Vibe Code Bench v1.1 | Restricted | The page says an "access plan" will roll out "in the coming weeks" (interest form). Only an OpenHands scaffold fork is public. |
| Vibe Code Bench 1-100 | Partial | 1 sample app (`vcb-1-100-public-dataset`, 6 iterations). The page lists 50 validation and 50 test scenarios, 100 app arcs in all. |
| Code Migration | Partial | 6 sample repos (`code-migration-public`) of the 40 scored (30 CLI repos migrated into 4 languages, plus 10 COBOL). Hidden behaviour tests. |
| ProgramBench | Open | 200 public tasks (programbench.com). Hidden behavioural tests. |
| Terminal-Bench 4.0 | Open | 66 tasks, tbench.ai and Harbor Hub. |
| SkillsBench | Open | `benchflow-ai/skillsbench`. Vals integrated it into Valkyrie with BenchFlow. |
| IOI | Open* | 18 problems (2024–2026). Statements are public, and official test data is withheld from the agent during a run. *Vals' `ioi-agent` repo needs a Vals model proxy and has no licence. |
| SWE-bench Multimodal | Open | 480 test and 100 dev tasks. Vals' service pulls both from Hugging Face. |
| Terminal-Bench 2.0†, 2.1† | Open | 89 tasks each. |
| SWE-bench Verified† | Open | 500 tasks (Hugging Face `SWE-bench/SWE-bench_Verified`). |
| LiveCodeBench† | Open | 1,000+ problems (v6) from LeetCode, AtCoder and Codeforces. |

### Cybersecurity
| Benchmark | Tier | What is actually public |
|---|---|---|
| CyberBench v1.1 | Restricted | 60 proof-of-concept and 56 patch tasks. No public sample found. |
| SRE Bench | Restricted | 262 instances. No data. A paper is "forthcoming". |

### Games and computer use
| Benchmark | Tier | What is actually public |
|---|---|---|
| CUA-bench | Restricted | 6 commercial games. 3 named public (Minecraft, SUPERHOT, eFootball), no harness release. |
| Time Horizon Index: KSP | Restricted | 30 missions. Nothing public. |
| Poker Agent | Restricted | Page says code will be "released soon on Github". |

### Social mobility
| Benchmark | Tier | What is actually public |
|---|---|---|
| Public Benefits Bench v1.1 | Restricted | 459 SNAP scenarios (230 test). No public split stated. |
| Public Benefits Bench v1† | Restricted | Same. |

---

## 6. What the `vals-ai` GitHub organisation contains

32 public repositories (checked via the GitHub API on 2026-10-16). Private repositories would not appear.

| Group | Count | Repos |
|---|---:|---|
| Benchmark harnesses and public samples | 14 | `finance-agent`, `finance-agent-v2`, `legal-research-bench`, `tax-agent-bench`, `corp-fin-vals-sdk`, `ioi-agent`, `proof-bench`, `web-search-agent-public`, `VibeCodeBench-Openhands-Scaffold`, `emb-public-dataset`, `vcb-1-100-public-dataset`, `code-migration-public`, `harvey-labs-public-dataset-runs`, `vibe-code-bench-cais-2026-artifacts` |
| Infrastructure | 11 | `Valkyrie` (AGPL-3.0), `model-library` (MIT), `benchmark-runtime`, `create-benchmark-service`, `create-benchmark-runner`, `SWEBenchBenchmarkService`, `terminal-bench-benchmark-service`, `skillsbench-benchmark-service`, `public-agent-registry`, `public-benchmark-services-registry`, `valsai-github-action` |
| Agent packages | 3 | `fabv2_agent-v1.0.0`, `proof_bench_agent-v1.0.0`, `terminus2-v1.0.0` |
| Forks | 3 | `blueprint`, `petri`, `skillsbench` |
| Org profile | 1 | `.github` |

**Licensing points for a client report**
- **Most-starred repos:** `finance-agent` (165 stars), `finance-agent-v2` (71), `Valkyrie` (49), `model-library` (27).
- **MIT:** `finance-agent`, `finance-agent-v2`, `legal-research-bench`, `tax-agent-bench`, `corp-fin-vals-sdk`, `web-search-agent-public`, `model-library`, `public-agent-registry`.
- **AGPL-3.0:** Valkyrie, so it is copyleft. Check with legal before embedding it in a product.
- **No licence file:** `ioi-agent`, `proof-bench`, `emb-public-dataset`, `vcb-1-100-public-dataset` and `code-migration-public`. Without a licence, reuse rights are not granted by default.
- **Data in repos is small:** `finance-agent-v2` has 27 questions, and `legal-research-bench` and `tax-agent-bench` have 5 each in `data/public.json`.

**Valkyrie** is Vals' open-source orchestrator for agentic benchmarks (docs at docs.valkyrie.vals.ai).
- It runs against Vals-hosted infrastructure or a self-hosted AWS deployment, with cloud sandboxes (Daytona or Modal).
- It is therefore not "run offline on a laptop".
- Public benchmark services in the registry are SWE-bench (Verified and Multimodal), Terminal-Bench (2.0, 2.1, 4.0) and SkillsBench.

---

## 7. Can we run these locally with our own model?

**What works well**
- Upstream open benchmarks (SWE-bench, Terminal-Bench / Harbor, ProgramBench, SkillsBench, LegalBench, VoiceCodeBench, HLAB public tasks) have their own harnesses and do not depend on Vals.
- Vals' `tax-agent-bench` README states that no Vals account is needed to run locally. It needs only the provider key for the model under test and a Tavily key.
- Vals' `SWEBenchBenchmarkService` and `terminal-bench-benchmark-service` run on a standard Docker setup.

**Constraints**
1. **Self-hosted models are not documented.**
   - `model-library` lists hosted providers only (OpenAI, Anthropic, Google, Together, Fireworks, Mistral, Cohere, Amazon Bedrock, Azure OpenAI, DeepSeek and others).
   - The Vals harness READMEs say to modify `get_custom_model` to run your own model.
   - Expect a small adapter, for example an OpenAI-compatible endpoint. I did not test this.
2. **"Local" is not "offline".** Several harnesses call external services:
   - Finance Agent v2 needs Tavily, SEC-API and Tiingo.
   - Legal Research Bench needs Tavily and CourtListener.
   - HLAB scoring uses two LLM judges (GPT-5.5 and Claude Sonnet 4.6 per Vals' page), so judge costs apply.
3. **Compute and sandboxing.** SWE-bench and Terminal-Bench run many Docker tasks. Vals itself uses cloud sandboxes at scale.
4. **Public samples are tiny.** For Finance Agent v2 that is 27 of 927 items (about 3%). Tax Agent Bench is 5 of 391 (about 1%). EMB is 1 of 103.
5. **Scores are not comparable to Vals' leaderboard.** Vals fixes the harness, tools, judges and the hidden test set. A run on the public sample is a smoke test. Comparable numbers need the licensed private validation set (pricing not published).
6. **Gated platform parts.**
   - The `finance-agent-v2` and `legal-research-bench` READMEs describe Vals platform access as "gated and requires approval".
   - Whether the public question file works without platform keys, I did not verify.

---

## 8. Does Vals run all the evaluations itself?

**Short answer: yes, as far as public evidence shows. Vals runs the models. Labs do not run Vals' private tests and submit results.**

| Evidence | Source |
|---|---|
| "we run every model ourselves under the same harness and settings"; models accessed through API providers; a fixed harness Vals controls | Vals methodology page |
| Positions itself as "the independent evaluator of artificial intelligence". Scores come from "our privately held test sets". | Vals about page |
| The test set is private "at all times" and is the only data behind published results | Vals methodology page |
| For HLAB (Harvey's benchmark), Vals swapped in its own model library, ran it on Valkyrie and used its own judges and a bug fix | Vals HLAB page |
| For agentic runs, models run inside vendor-native agents (the page names Claude Code and Codex) or custom scaffolds. Vals runs those itself. | Vals methodology page |
| A Vals audit post (2026-09-15) shows Google's model card reporting 88.8% (human-solvable) on BioMysteryBench, while Vals' own runs gave 71.7%. Vals attributes the gap to the model searching for answers online. | Vals blog, "AI Cheating is on the Rise" |

**Where labs and companies do touch Vals**
- Vals sells to "foundation model labs and enterprises" through negotiated contracts. The private validation sets are licensed "for their own internal validation".
  - That is a customer relationship, and it does not publish scores.
  - The public benchmarks act as a "top-of-funnel trust asset" (Sacra).
- Vals' own site says leading labs use it to test models before release.
  - I could not verify the terms or whether any pre-release evaluation is published.
- A Pondero article citing TechCrunch says OpenAI, Anthropic, Google, Meta and xAI all cite Vals in model cards. I did not check those cards directly.
- Several benchmarks are built by outside parties (Harvey, Anthropic, besimple.ai, ProgramBench team, BenchFlow, academic groups). Vals still runs the models.
- Vals also evaluates end-user products (for example legal research tools) against its private task sets, and some scaffolds are "provided by the teams we work with".

**Open questions and independence caveats**
- Vals publishes no conflict-of-interest policy. The methodology page lists no safeguards beyond "we control the harness and run the models ourselves."
- Vals has raised $45M in total. A $40M Series A (Aug 2026) was led by Andreessen Horowitz, per Sacra and Pondero.
- Pondero notes private tests are harder to audit independently. Vals' credibility rests on its domain-expert partners and track record, not a publicly verifiable methodology.

---

## 9. Suggested positioning for the client

> We already run benchmarking scripts locally. Vals AI's public resources let us extend that with a recognised external benchmark set and compare against published results where the benchmark is open.

**Proposed approach**
1. **Tier 1, run now (fully public).**
   - **Coding:** Terminal-Bench 4.0 (66 tasks), SWE-bench Verified and Multimodal, ProgramBench (200), SkillsBench.
   - **Other domains:** Terminal-Bench Science (70), LegalBench, HLAB public tasks, VoiceCodeBench (300 clips).
   - **Comparison:** Vals has published results for these, so our results can be compared directly. Use the same harness and settings as Vals' page.
2. **Tier 2, smoke tests only.** Finance Agent v2 (27 questions), Tax Agent Bench (5), Legal Research Bench (5), EMB (1 task), VCB 1-100 (1 app), Code Migration (6 repos). They validate the pipeline but are not statistically meaningful.
3. **Tier 3, requires Vals.** For comparable finance, tax, legal-research, EMB or code-migration scores, license the private validation sets via contact@vals.ai. Pricing is not public and is negotiated.
4. **Engineering tasks.** Build an adapter so Vals' harnesses can call our locally hosted model. Budget for tool API keys and judge-model costs. Check licences (section 6) before reusing code.

**Domain coverage we can offer today:** coding (strong), legal and math/science (some), voice (one benchmark), finance and tax (sample only), medical, cybersecurity, games and social mobility (none).

---

## 10. Limits of this research

- Dates, counts and labels come from Vals pages as fetched on 2026-10-16. The pages change often, and several were truncated when fetched, so a few items read "not stated" or "unverified".
- Item counts for academic datasets (GPQA, MMLU-Pro, MMMU, LegalBench and others) are not on Vals' pages, so they are not listed. Check upstream sources before quoting them.
- I could not confirm the BioMysteryBench download location, the ProofBench public-split size, or the HLAB public-task count (section 5).
- Funding and "labs cite Vals" claims rely on secondary sources (Sacra, Pondero citing TechCrunch).
- Tier assignment is a judgement based on what is publicly downloadable. If a lab or partner has non-public access, I would not have seen it.

---

## 11. Sources

**Vals AI**
- Home: https://www.vals.ai/
- Benchmark index: https://www.vals.ai/benchmarks
- Methodology: https://www.vals.ai/methodology
- About: https://www.vals.ai/about
- Blog (cheating audit): https://www.vals.ai/blogs/cheating-on-the-rise
- Benchmark pages used: `fabv2`, `emb`, `tax_agent_bench`, `legal_research`, `hlab`, `legal_bench`, `corp_fin_v2`, `mortgage_tax`, `tax_eval_v2`, `case_law_v2`, `proof_bench`, `vibe-code`, `vcb-1-100`, `code-migration`, `cyber`, `srebench`, `medcode`, `medscribe`, `mental-health`, `sage`, `mysterymechanism`, `robo_bench`, `cua_bench`, `public-benefits-bench`, `biomysterybench`, `voice-code-bench`, `terminal-bench-science`, `programbench`, `skillsbench`, `ioi`, `terminal-bench-4`, `terminal-bench-2-1`, `swebench`, `swebench-multimodal`, `lcb`, `gpqa`, `mmlu_pro`, `web_search`, `vals_index`, `poker_agent`, `time_horizon_index` (all under https://www.vals.ai/benchmarks/)
- Valkyrie docs: https://docs.valkyrie.vals.ai/introduction/what-is-valkyrie
- Platform docs: https://docs.vals.ai

**GitHub**
- Organisation: https://github.com/vals-ai (repository list via the GitHub API)
- Harness READMEs read: `Valkyrie`, `finance-agent`, `finance-agent-v2`, `legal-research-bench`, `tax-agent-bench`, `corp-fin-vals-sdk`, `ioi-agent`, `proof-bench`, `emb-public-dataset`, `vcb-1-100-public-dataset`, `web-search-agent-public`, `harvey-labs-public-dataset-runs`, `public-agent-registry`, `public-benchmark-services-registry`, `SWEBenchBenchmarkService`, `terminal-bench-benchmark-service`, `model-library`
- Harvey Labs: https://github.com/harveyai/harvey-labs
- Terminal-Bench Science: https://github.com/harbor-framework/terminal-bench-science

**Third party**
- Sacra, Vals AI analysis: https://sacra.com/c/vals-ai/
- Pondero, Series A: https://pondero.ai/news/2026-09-20-vals-ai-series-a/
- Finance Agent paper: https://arxiv.org/pdf/2508.00828
