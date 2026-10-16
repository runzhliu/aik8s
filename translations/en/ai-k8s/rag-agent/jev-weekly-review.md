---
title: "Jev Weekly Review"
description: "Continuously tracking versions, independent evaluations, community weights, and Agent applications of Jev and the System One decision model, preserving results and judgments by week"
status: evolving
last_reviewed: 2026-10-06
---

# Jev Weekly Review

Jev turns one class of tasks in language understanding into a standalone interface: given a state and a question, it returns a finite set of options with their probabilities, letting programs classify, route, or verify based on that. It eliminates the need to generate a full answer, but whether it improves system efficiency still depends on whether the judgments are accurate, whether the probabilities are trustworthy, and whether downstream consumers use the results correctly.

This feature continuously tracks progress on Jev and related System One decision models. Each issue covers Wednesday through the following Tuesday, with the latest issue placed first; historical reviews preserve the versions and conclusions from the time. For the base interface, deployment boundaries, and evaluation methodology, see [Jev System One Decision Model Overview](jev-system-one-model-overview.md).

## Review Index

| Period | Highlights |
| --- | --- |
| [September 30 to October 6, 2026](#week-2026-10-06) | Independent evaluations begin to constrain cost and calibration claims; community applications shift toward concrete workflows |

## September 30 to October 6, 2026 { #week-2026-10-06 }

The most notable developments this week are newly published independent research and the community beginning to document real-world effects after integration. The official model page still lists `jev-1.13.0`; the security decision model, vision decision weights, and Agent plugins that appeared in the ecosystem are research or community projects respectively, and should not be conflated as a single model upgrade to Jev. [Official model page](https://docs.typesafe.ai/models)

### Official Model and SDK Status

As of this issue, the official public information is as follows. The Software Development Kit (SDK) version and model version are recorded separately; a client update does not mean the server-side model has changed.

| Item | Current Status | Notes for Application |
| --- | --- | --- |
| Stable model | `jev-1.13.0` | Decision thresholds should be bound to a specific model version |
| Floating aliases | `jev-latest`, `jev-preview` both point to 1.13.0 | There is currently no separate Preview model officially |
| Input | Text, organizable as strings, JSON objects, or text arrays | Official Jev does not directly accept images, audio, or video |
| Context | 64K tokens total per request; state plus longest question must not exceed 32K | Multiple questions sharing state must still satisfy both budgets |
| Pricing | $0.042 per million input tokens, output free | This is the per-token price; a complete task also includes post-processing and verification costs |
| Published limits | 100K tokens/s, 80 requests/s | Official documentation states these are dynamically adjusted; handle rate limiting and read retry hints |

Specifications and aliases are from [TypeSafe model documentation](https://docs.typesafe.ai/models). Production systems should save the actual model ID from response payloads; after floating aliases change, previously tuned thresholds may no longer apply.

The official Python SDK's latest release is **0.7.2, released September 26**, adding an optional HTTP/2 dependency and usage instructions; the JavaScript/TypeScript SDK's latest release is **0.6.0, released September 15**. Both are the version baselines for this issue and are not new releases from this week. [Python SDK Releases](https://github.com/typesafe-ai/typesafe-sdk-python/releases), [JavaScript SDK Releases](https://github.com/typesafe-ai/typesafe-sdk-js/releases)

### Independent Evaluations Begin to Yield More Specific Conclusions

On October 5, Steven Denney and Matthew DiGiuseppe published the preprint *JEV versus LLMs: Accuracy, Cost and Calibration on Seven Political Science Replications*, comparing Jev, models from existing research, and human annotation, as well as GPT-6 Luna and Qwen3.8-27B. Its importance lies in placing cost and probability calibration back into concrete tasks, rather than only comparing interface prices. [Paper](https://arxiv.org/abs/2610.06625)

| Dimension | Results Reported in the Paper | How to Interpret |
| --- | --- | --- |
| Task capability | Jev matches or approaches both comparison models across multiple tasks | Supports its use for some text annotation tasks; cannot be extrapolated to all Agent decisions |
| Cost | At OpenAI Batch pricing, no cost advantage over GPT-6 Luna was found | Online low-latency calls and offline batch processing should be compared separately |
| Probability calibration | On single queries, better than GPT-6 Luna's token probabilities, but not consistently better than Qwen3.8-27B | Calibration advantage is affected by task and comparison methodology |
| Ease of use | Option probabilities are easy to read and parse | Engineering convenience has value, but does not equal higher accuracy |

The above are the results of this preprint under its research setup. The second version on October 6 only corrected author-order metadata; it is not a new round of experiments. [Paper version history](https://arxiv.org/abs/2610.06625)

As background, *Evaluating and Benchmarking the System One Model Jev*, published September 29, covers 37 datasets, uses Jev 1.13.0 to complete 346,009 requests, and reports costs under $10. Comparison models read the next-token probability of candidate answers on the same requests; Jev outperforms Qwen3.8-27B on 27 datasets and Gemma-4-E4B on all 37 datasets. [Paper](https://arxiv.org/abs/2609.37647)

This earlier study also provides a practical detail: although binary probabilities rank well, a fixed 0.5 threshold may perform poorly. On the UNFAIR-ToS task, after adjusting the threshold using training data, micro-F1 improved from **0.50 to 0.75**. Micro-F1 is the F1 score computed from prediction counts aggregated across all classes; this change illustrates that there is still a step of validation between "returning probabilities" and "can execute directly at the default threshold." [Same paper](https://arxiv.org/abs/2609.37647)

The two studies use different tasks, comparison methodologies, and pricing bases. Together they remind us that strong results on general benchmarks need to be further grounded in business labels, error costs, and workflows. For real-time routing, latency may matter more than API cost; for overnight batch annotation, batch pricing and manual rework volume are more worth comparing.

### SecJev Explores Domain-Specific Decision Models

*SecJev: Bringing Security Expertise to System One Decision Models*, published October 2, proposes security-domain decision models ranging from 0.8B to 9B. It is based on Kev's single-forward candidate scorer and covers tool outputs, traffic, authentication, and other scenarios, building training and evaluation materials from 14 tasks across 8 source categories. **This is a Jev-like research project, not a fine-tune of official Jev weights.** [SecJev paper](https://arxiv.org/abs/2610.03073)

The authors report that SecJev-0.8B exceeds the general-purpose Kev-9B by **20.51 percentage points** in macro-average accuracy on their tasks, but false-positive variation remains under new traffic collection conditions. This suggests directions worth continued validation: combining explicit security policies with domain data may allow small models to make effective judgments; after switching to a different source or collection environment, false-positive rates still need to be re-measured. [SecJev paper](https://arxiv.org/abs/2610.03073)

For security workflows, beyond average accuracy, one must separately observe false negatives, false positives, and manual review volume. Models can assist in triaging events or identifying suspicious inputs, but final permissions and execution scope should still be controlled by deterministic policies.

### Community Ecosystem Begins to Cover Concrete Workflows

The following records project status as of this week; repository updates are not equated with formal version releases.

| Project | What It Provides | Use Cases Worth Watching | Current Boundaries |
| --- | --- | --- | --- |
| [Spring AI TypeSafe](https://github.com/spring-ai-community/spring-ai-typesafe) | Java client and Spring AI integration, current documentation version 0.4.0 | Answer evaluation, content checking, retrieved-document filtering, tool selection | Community integration; business effects still need validation after connecting the interface |
| [DSH Jev Plugin](https://github.com/luobosibing2/dsh-jev-plugin) | Decision plugin for DeepSeek Harness | Skill and file ranking, task checking, log filtering | Independent community project, 12 features disabled by default; the main model continues to plan and execute tools |
| [Vev](https://github.com/Xiaooolong/vev) | 4B and 9B text and vision decision models based on Qwen3.5 | Self-hosted research, UI state judgment, image rule checking | Research preview; interface compatibility does not imply identical decision behavior |

The Spring AI integration is worth noting because it places judgments into existing application pipelines: filtering materials after retrieval, checking criteria after generation, and filtering tools before invocation. The 0.4.0 changelog also fixes tool-selection behavior, avoiding padding the result count with tools that Jev judged as zero probability. This detail reflects the importance of downstream logic: if the model excludes a candidate, the application code should preserve that result. [Spring AI changelog](https://spring-ai-community.github.io/spring-ai-typesafe/latest-snapshot/changes/)

The DSH plugin, meanwhile, records "returning a judgment" and "the judgment producing an effect" separately. Its documentation explicitly distinguishes answers, adoptions, permission grants, and execution results, and discloses cases where context truncation affected judgments. This is more helpful for evaluating Agent integration than merely recording API success counts; the limited existing samples are not yet sufficient to estimate average benefits on natural tasks. [Plugin documentation and validation boundaries](https://github.com/luobosibing2/dsh-jev-plugin)

Vev weights are already available on Hugging Face, including [vev-4b](https://huggingface.co/CountingSheep/vev-4b) and [vev-9b](https://huggingface.co/CountingSheep/vev-9b), usable for research-local probabilistic decision services. The licenses must be distinguished carefully: **code is Apache-2.0, model weights are CC BY-NC 4.0, non-commercial use only**. Its image support does not mean official Jev has gained vision capabilities, nor can the two models' probabilities and thresholds be directly interchanged on that basis. [Vev model and license documentation](https://github.com/Xiaooolong/vev)

### A Skill-Routing Case Exposes Evaluation Difficulties

`jev-skill-router` The author published a one-week observation after integrating with Claude Code. The experiment actually took place from **September 21 to 28**, using Japanese prompts, 52 to 66 skills, and Jev 1.13.0; it is an earlier case discussed in this issue. [Author's experiment log](https://github.com/shimo4228/jev-skill-router)

| Recorded Item | Count |
| --- | ---: |
| Number of judgments | 1,242 |
| Number of times a skill suggestion was given | 539 |
| Number of times the suggested skill was invoked within 30 minutes in the same session | 28 |
| Proportion of suggestions followed by a corresponding invocation | Approximately 5.2% |

The author ultimately removed this router and switched to a research pipeline where steps are fixed in Python, letting Jev judge whether new papers or repositories are relevant and letting the generative model handle note-writing. The fixed flow makes the impact of a single judgment on downstream processing easier to observe. [Project description](https://github.com/shimo4228/jev-skill-router)

**28/539 must not be interpreted as the model having only 5.2% accuracy.** The experiment was in Shadow Mode by default, meaning judgments were only recorded and not injected into the main model as suggestions; "the same skill was invoked later" measures behavioral correspondence. It does not prove that suggestions caused the invocations, nor that all unsuggested invocations were wrong.

This case reveals how integration method affects evaluation. An autonomous Agent is already selecting skills; after adding a suggester, one must simultaneously track the suggestion content, whether it was displayed, whether it was adopted, and the final task outcome. If only model outputs are recorded, it is difficult to tell whether the added invocation saved time or introduced more interference.

### Currently Better to Start with Measurable Judgments

Based on these studies and cases, I lean toward first selecting stages where inputs are stable, candidate sets are clear, and outcomes are easy to verify. For example:

| Scenario | Judgment Jev Handles | Control the Application Retains | Primary Metrics to Observe |
| --- | --- | --- | --- |
| Document filtering | Whether a material helps answer the question | Keep original documents and retrieval results; can fall back to the original flow | Relevant-material recall, false-removal rate, downstream answer quality |
| Ticket routing | Which handling group to assign to, or whether uncertain | Low-confidence items go to humans; no automatic permission expansion | Routing accuracy, human-handoff rate, rework count |
| Result checking in fixed flows | Whether each acceptance criterion is met | Completion confirmed by tests or an independent verifier | Defect detection rate, false-block rate, extra retry count |
| Agent skill or tool filtering | Which candidates are relevant, or whether none apply | Allow returning no match; preserve fallback paths | Selection accuracy, actual adoption rate, task success rate |

When experimenting, first fix the task set, main model, input materials, and timeout budget, then compare the original flow against the flow with judgments added. A single correct judgment is only an intermediate result; the final question is whether task success rate, total time, human intervention, and cost actually improve.

Cost should also be calculated per complete task: decision API, main model calls, extra retries, and human review all count, then divided by the number of successful tasks. Otherwise, a cheap judgment interface may make the entire pipeline more expensive by increasing misjudgments and rework.

### What to Watch in the Next Issue

- **Official model changes**: Whether stable and Preview versions separate, and whether model aliases, pricing, limits, and language capabilities change.
- **Independent re-testing**: Accuracy, probability calibration, error categories in Chinese and real business tasks, plus fair cost and latency comparisons.
- **Self-hosted ecosystem**: Changes in community weights, commercial-use licenses, and inference implementations, especially capability and threshold differences beyond the interface.
- **Agent application results**: Continuing from connection and demos to adoption, task success, recovery, and rework, distinguishing simulated tests from real-service measurements.

Each subsequent week, a new issue will be added at the same address, preserving historical results. If an existing conclusion needs correction, the correction date and reason will be noted in the corresponding week, rather than overwriting old experiments with new-version results.
