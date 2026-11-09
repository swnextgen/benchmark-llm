#!/usr/bin/env python3
"""Run the fixed public Vals proxy questions against an OpenAI-compatible API."""

import argparse
import json
import re
import sys
import time
import urllib.error
from pathlib import Path

from reasoning import call_api


COMPARABILITY = "public_proxy — not Vals leaderboard comparable"
VALS_METHODOLOGY = "https://www.vals.ai/methodology"
VERSIONS = {
    "legal": "LegalBench b46bf4ffae90524b2b72aaa30e7745fe9db64481; HF daec8237410aa23e3faf4bc41ad8b3a7e1696826",
    "finance": "finance-agent-v2 502aab6fdaa3fb9294905c7453f89882baa8d39b",
    "health": "MedQA 27b02f66aac217933c9648a06f82e9f720377925; HF afdb980b627374a7f10a0a11ed68455596c52742",
    "math": "AIME 2024 HF 2fe88a2f1091d5048c0f36abc874fb997b3dd99a; AIME 2025 HF 563bb8404243c5f09de6ec262f2db674fe5bce9b",
    "science": "MMLU-Pro HF b189ec765aa7ed75c8acfea42df31fdae71f97be",
}
VALS_URLS = {
    "legal": "https://www.vals.ai/benchmarks/legal_bench",
    "finance": "https://www.vals.ai/benchmarks/fabv2",
    "health": "https://www.vals.ai/benchmarks/medqa",
    "math": "https://www.vals.ai/benchmarks/aime",
    "science": "https://www.vals.ai/benchmarks/mmlu_pro",
}
NAMES = {"legal": "LegalBench", "finance": "Finance Agent v2", "health": "MedQA", "math": "AIME 2024/2025",
         "science": "MMLU-Pro"}
SUITES = {
    "legal": "legalbench_public_proxy",
    "finance": "finance_agent_v2_public_proxy",
    "health": "medqa_public_proxy",
    "math": "aime_public_proxy",
    "science": "mmlu_pro_public_proxy",
}
LEGAL_COMMIT = "b46bf4ffae90524b2b72aaa30e7745fe9db64481"
FINANCE_COMMIT = "502aab6fdaa3fb9294905c7453f89882baa8d39b"
MEDQA_COMMIT = "27b02f66aac217933c9648a06f82e9f720377925"
AIME_SETS = {  # year: (dataset, split, pinned revision)
    2024: ("HuggingFaceH4/aime_2024", "train", "2fe88a2f1091d5048c0f36abc874fb997b3dd99a"),
    2025: ("math-ai/aime25", "test", "563bb8404243c5f09de6ec262f2db674fe5bce9b"),
}

# Verbatim base_prompt.txt files from the pinned LegalBench commit.
LEGAL_PROMPTS = {
    "abercrombie": """A mark is generic if it is the common name for the product. A mark is descriptive if it describes a purpose, nature, or attribute of the product. A mark is suggestive if it suggests or implies a quality or characteristic of the product. A mark is arbitrary if it is a real English word that has no relation to the product. A mark is fanciful if it is an invented word.

Q: The mark "Ivory" for a product made of elephant tusks. What is the type of mark?
A: generic

Q: The mark "Tasty" for bread. What is the type of mark?
A: descriptive

Q: The mark "Caress" for body soap. What is the type of mark?
A: suggestive

Q: The mark "Virgin" for wireless communications. What is the type of mark?
A: arbitrary

Q: The mark "Aswelly" for a taxi service. What is the type of mark?
A: fanciful

Q: {text} What is the type of mark?
A:""",
    "function_of_decision_section": """Classify the following text using the following definitions. 

- Facts: The paragraph describes the faction background that led up to the present lawsuit.
- Procedural History: The paragraph describes the course of litigation that led to the current proceeding before the court.
- Issue: The paragraph describes the legal or factual issue that must be resolved by the court.
- Rule: The paragraph describes a rule of law relevant to resolving the issue.
- Analysis: The paragraph analyzes the legal issue by applying the relevant legal principles to the facts of the present dispute.
- Conclusion: The paragraph presents a conclusion of the court.
- Decree: The paragraph constitutes a decree resolving the dispute.


Text: We need go no further. For aught that appears, the appellant was fairly tried before an able and thoughtful judge and an impartial jury, justly convicted, and lawfully sentenced. For the reasons elucidated above, the judgment of the district court is Affirmed.
Label: Facts

Text: Lassiter pled guilty to kidnapping, 18 U.S.C. § 1201(a), to assault with intent to kill while armed, D.C. Code §§ 22-401, -4502, and to using a firearm during a crime of violence, 18 U.S.C. § 924(c)(1)(A).	
Label: Procedural History

Text: In this venue, the appellant advances two claims of trial error and a cluster of claims of sentencing error.1 Since none possesses even a patina of plausibility, we make short shrift of them.	
Label: Issue

Text: On appeal from a dismissal in favor of a foreign sovereign on grounds of sovereign immunity, we assume the unchallenged factual allegations in the complaint to be true. Simon v. Republic of Hungary, 812 F.3d 127, 135 (D.C. Cir. 2016).	
Label: Rule

Text: But even if Khochinsky's relevant claims fit within that description, the exception excludes from its coverage “any claim arising out of malicious prosecution, abuse of process, libel, slander, misrepresentation, deceit, or interference with contract rights.” Id. § 1605(a)(5)(B).	
Label: Analysis

Text: We agree with the district court that none of those exceptions extends to Khochinsky's claims.	
Label: Conclusion

Text: For these reasons, we AFFIRM.	
Label: Decree

Text: {Paragraph}
Label:""",
    "international_citizenship_questions": """Answer the following questions considering the state of international law on January 1st, 2020.

Question: {question} Answer Yes or No.
Answer:""",
    "proa": """A private right of action is when a regular person, a private citizen, is legally entitled to enforce their rights under a given statute. Does the clause specify a private right of action?

Clause: Amendments to pleadings must be filed within 15 days of the filing of the initial pleading.
A: No

Clause: A person who discloses genetic information in violation of this section is liable for a civil penalty of not more than $10,000. The attorney general may bring an action in the name of the state to recover the penalty, plus reasonable attorney's fees and court costs.
A: No

Clause: A victim of human trafficking, as defined in Section 236.1 of the Penal Code, may bring a civil action for actual damages, compensatory damages, punitive damages, injunctive relief, any combination of those, or any other appropriate relief.
A: Yes

Clause: The lessees of any railroad or the company having possession of the railroad shall be liable to an action of any kind in the same court or jurisdiction as were the lessors or owners of the railroad before the lease.
A: Yes

Clause: The buyer may recover from the seller as damages the difference between the cost of cover and the contract price together with any incidental or consequential damages.
A: Yes

Clause: {text}
A:""",
    "hearsay": """Hearsay is an out-of-court statement introduced to prove the truth of the matter asserted.

Q: On the issue of whether David is fast, the fact that David set a high school track record. Is there hearsay?
A: No

Q: On the issue of whether Rebecca was ill, the fact that Rebecca told Ronald that she was unwell. Is there hearsay?
A: Yes

Q: To prove that Tim was a soccer fan, the fact that Tim told Jimmy that "Real Madrid was the best soccer team in the world." Is there hearsay?
A: No

Q: When asked by the attorney on cross-examination, Alice testified that she had "never seen the plaintiff before, and had no idea who she was." Is there hearsay?
A: No

Q: On the issue of whether Martin punched James, the fact that Martin smiled and nodded when asked if he did so by an officer on the scene. Is there hearsay?
A: Yes

Q: {text} Is there hearsay?
A:""",
    "personal_jurisdiction": """There is personal jurisdiction over a defendant in the state where the defendant is domiciled, or when (1) the defendant has sufficient contacts with the state, such that they have availed itself of the privileges of the state and (2) the claim arises out of the nexus of the defendant's contacts with the state.

Q: Dustin is a repairman who lives in Arizona and repairs computers in California, Oregon, and Washington. While traveling to repair a computer in Washington, Dustin is involved in a car crash in Oregon with Laura, a citizen of Oregon. After the accident, Dustin returns to Arizona. Laura sues him in Arizona. Is there personal jurisdiction?
A: Yes

Q: Tony (from Texas) is a regional manager for a cookbook company, Tasty Eats Books (incorporated and principal place of business in Delaware). Tony’s job requires him to travel from city to city to show new cookbooks to chefs. In January 2022, he was scheduled to visit restaurants in Illinois, Indiana, and Michigan (for the first time!). While in Michigan, Tony goes to Lake Erie to blow off some steam. He ends up getting into a fight with Arthur, a lawyer from Detroit, Michigan. Tony and Arthur each blame the other for starting the fight. Tony sues Arthur in Indiana. Is there personal jurisdiction?
A: No

Q: Martha makes special pinwheel hats in her home in Salem, Oregon. However, she maintains an extensive online presence, and markets her goods to citizens of all 50 states. Alex, a citizen of Maine, purchases one of the hats. The pinwheel comes off and seriously cuts Alex. Alex sues Martha for damages in Texas. Is there personal jurisdiction?
A: No

Q: Ana is a lawyer who resides in Texas. David, who runs a bike shop in Louisiana, emails Ana and tells her how great his bikes are. While visiting Louisiana, Ana buys a bike from David and rides it back home. Right after she crosses the border, the bike seat explodes, injuring Ana. Ana then sues David in Texas. Is there personal jurisdiction?
A: Yes

Q: {text} Is there personal jurisdiction?
A:""",
    "diversity_1": """Diversity jurisdiction exists when there is (1) complete diversity between plaintiffs and defendants, and (2) the amount-in-controversy (AiC) is greater than $75k.

Q: Evelyn is from Hawaii. Charlotte is from Hawaii. Evelyn sues Charlotte for negligence for $20,000. Is there diversity jurisdiction?
A: No

Q: Ava is from Alaska. Mia is from Missouri. Ava sues Mia for wrongful eviction for $61,000. Is there diversity jurisdiction?
A: No

Q: Sophia is from Illinois. Noah is from Illinois. Sophia sues Noah for wrongful eviction for $39,000. Is there diversity jurisdiction?
A: No

Q: Oliver is from Nebraska. Theodore is from Nebraska. Oliver sues Theodore for medical malpractice for $3,106,000. Is there diversity jurisdiction?
A: No

Q: Oliver is from Virginia. James is from Georgia. Oliver sues James for medical malpractice for $10,000. Is there diversity jurisdiction?
A: No

Q: Isabella is from Alaska. Elijah is from Montana. Isabella sues Elijah for patent infringement for $1,522,000. Is there diversity jurisdiction?
A: Yes

Q: {text} Is there diversity jurisdiction?
A:""",
    "ucc_v_common_law": """The UCC (through Article 2) governs the sale of goods, which are defined as moveable tangible things (cars, apples, books, etc.), whereas the common law governs contracts for real estate and services. For the following contracts, determine if they are governed by the UCC or by common law.

Contract: Alice and Bob enter into a contract for Alice to sell her bike to Bob for $50. Is this contract governed by the UCC or the common law?
Governed by: UCC

Contract: "Irina says to John, ""Hey John. I will give you ten apples for $2 per apple."" John replies, ""That sounds good to me."" Is this contract governed by the UCC or the common law?"
Governed by: UCC

Contract: William rents a tractor for his farm for $500 a month from Sophia. Is this contract governed by the UCC or the common law?
Governed by: UCC

Contract: Ava buys James' farm for $50,000. Is this contract governed by the UCC or the common law?
Governed by: Common Law

Contract: Carl and Dana form an agreement for Carl to repair Dana's bike for $100. Is this contract governed by the UCC or the common law?
Governed by: Common Law

Contract: Gary and Helga form a contract for Helga to find Gary's lost bike in exchange for $10. Is this contract governed by the UCC or the common law?
Governed by: Common Law

Contract: {contract}
Governed by:""",
}


def evidence(case):
    domain = case["domain"]
    links = [{"label": "Vals test", "url": VALS_URLS[domain]}]
    if domain == "legal":
        config, row = case["config"], case["row"]
        links += [
            {"label": "Dataset", "url": f"https://huggingface.co/datasets/nguha/legalbench/viewer/{config}/test?row={row}"},
            {"label": "Task", "url": f"https://github.com/HazyResearch/legalbench/tree/{LEGAL_COMMIT}/tasks/{config}"},
            {"label": "Harness", "url": f"https://github.com/HazyResearch/legalbench/blob/{LEGAL_COMMIT}/evaluation.py"},
            {"label": "Reference grader", "url": f"https://github.com/HazyResearch/legalbench/blob/{LEGAL_COMMIT}/evaluation.py"},
        ]
    elif domain == "finance":
        line = case["line"]
        links += [
            {"label": "Public question", "url": f"https://github.com/vals-ai/finance-agent-v2/blob/{FINANCE_COMMIT}/data/public.txt#L{line}"},
            {"label": "Harness", "url": f"https://github.com/vals-ai/finance-agent-v2/tree/{FINANCE_COMMIT}"},
            {"label": "Restriction", "url": VALS_METHODOLOGY},
        ]
    elif domain == "math":
        name, split, revision = AIME_SETS[case["year"]]
        dataset = f"https://huggingface.co/datasets/{name}"
        links += [
            {"label": "Dataset", "url": f"{dataset}/viewer/default/{split}?row={case['row']}"},
            {"label": "Task", "url": f"{dataset}/tree/{revision}"},
        ]
    elif domain == "science":
        mmlu = "https://github.com/TIGER-AI-Lab/MMLU-Pro"
        links += [
            {"label": "Dataset", "url": f"https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/viewer/default/test?row={case['row']}"},
            {"label": "Task", "url": mmlu},
            {"label": "Harness", "url": mmlu},
            {"label": "Reference grader", "url": mmlu + "/blob/main/compute_accuracy.py"},
        ]
    else:
        row = case["row"]
        links += [
            {"label": "Dataset", "url": f"https://huggingface.co/datasets/awinml/medqa/viewer/questions/test?row={row}"},
            {"label": "Task", "url": f"https://github.com/jind11/MedQA/tree/{MEDQA_COMMIT}"},
            {"label": "Harness", "url": f"https://github.com/jind11/MedQA/tree/{MEDQA_COMMIT}"},
            {"label": "Grader", "url": VALS_URLS[domain] + "#additional-notes"},
            {"label": "Restriction", "url": VALS_METHODOLOGY},
        ]
    return links


def prompt(case):
    if case["domain"] == "legal":
        return LEGAL_PROMPTS[case["config"]].format(**case["input"])
    if case["domain"] in {"health", "science"}:
        choices = "\n".join(f"{key}. {value}" for key, value in case["options"].items())
        ending = "Return only: Answer: [letter]" if case["domain"] == "health" else "Think step by step, then end with: Answer: [letter]"
        return f"{case['question']}\n\n{choices}\n\n{ending}"
    if case["domain"] == "math":
        return f"{case['question']}\nPlease reason step by step, and put your final answer within \\boxed{{}}."
    return (f"{case['question']}\n\nYou have no web, filing or database access. Answer as completely and specifically as you "
            "can from memory, naming the fiscal period behind every figure, and say plainly where you are unsure.")


def task_metadata(case):
    links = evidence(case)
    return {
        "suite": SUITES[case["domain"]],
        "task": case["id"],
        "task_type": "rubric_judged_closed_book" if case["domain"] == "finance" else "accuracy_pass_fail",
        "summary": case["summary"],
        "source_url": links[1]["url"],
        "evidence_links": links,
        "vals_benchmark_url": VALS_URLS[case["domain"]],
        "methodology_url": VALS_METHODOLOGY,
        "local_harness": "benchmark/vals_public.py",
        "upstream_version": VERSIONS[case["domain"]],
        "comparability": COMPARABILITY,
        # ponytail: local last-line exact match, not LegalBench's evaluation.py (balanced accuracy over a full task).
        "official_grader": False,
        "timeout_seconds": 0,
    }


def build_manifest(cases):
    sources = []
    for domain in NAMES:
        sources.append({
            "name": NAMES[domain],
            "url": VALS_URLS[domain],
            "version": VERSIONS[domain],
            "comparability": COMPARABILITY,
        })
    return {"comparability": COMPARABILITY, "methodology_url": VALS_METHODOLOGY,
            "benchmark_sources": sources, "tasks": [task_metadata(case) for case in cases],
            "task_overrides": []}


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def last_boxed(text):
    start = text.rfind("\\boxed{")
    depth = 1
    for index in range(start + 7, len(text)) if start >= 0 else ():
        depth += (text[index] == "{") - (text[index] == "}")
        if depth == 0:
            return text[start + 7:index]
    return ""


def math_normalized(value):
    value = re.sub(r"\\(?:left|right|!|,|;)|\\text\{[^}]*\}|\^\{?\\circ\}?|\\%|[\s$%]", "", value)
    value = value.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac").rstrip(".")
    return str(int(value)) if re.fullmatch(r"-?\d+", value) else value  # AIME keys are zero-padded: "025" == "25"


def legal_label(answer, labels):
    """Last line equal to a label, else a first line that opens with one. A short "Governed by:" / "A:" prefix is ignored."""
    lines = [line.strip() for line in answer.splitlines() if line.strip()]

    def labelled(line, may_continue):
        for text in (line, re.sub(r"^[^:]{1,30}:\s*", "", line)):
            spoken = normalized(text)
            for label in labels:
                if spoken == normalized(label) or (may_continue and spoken.startswith(normalized(label) + " ")):
                    return label
        return ""

    return (labelled(lines[-1], False) or labelled(lines[0], True)) if lines else ""


JUDGE_PROMPT = """You are grading an answer to a finance research question against ONE rubric criterion.

Question:
{question}

Answer:
{answer}

Criterion:
{criterion}

Does the answer satisfy the criterion? Be strict: it must state the specific facts the criterion names. Reply with exactly YES or NO."""


PASS_SCORE = 0.4  # proxy threshold chosen locally, not taken from Vals


def judge_rubric(case, answer, ask):
    """Severity-weighted partial credit; pass at PASS_SCORE or higher. ask(prompt) returns the judge's reply."""
    rubric = case["rubric"]
    met = [bool(answer.strip()) and re.match(r"\W*yes\b", ask(JUDGE_PROMPT.format(
        question=case["question"], answer=answer, criterion=item["criterion"])), re.I) is not None for item in rubric]
    score = sum(item["severity"] for item, ok in zip(rubric, met) if ok) / sum(item["severity"] for item in rubric)
    return ("pass" if score >= PASS_SCORE else "fail"), round(score, 4), met


def grade(case, answer):
    domain = case["domain"]
    if domain == "math":
        # ponytail: AIME keys are integers; integer or string match after light LaTeX cleanup. Add sympy for fractions/radicals.
        given = math_normalized(last_boxed(answer))
        passed = given != "" and given == math_normalized(case["expected"])
        return ("pass" if passed else "fail"), (1.0 if passed else 0.0)
    if domain in {"health", "science"}:
        letters = "".join(case["options"])
        # Uppercase letter, then a closer or end of line, so "Answer: A patient..." or "Answer: I think" never match.
        tagged = re.findall(rf"(?i:answer)(?:\s*:\s*[\[(*]*|\s+is\s*[\[(])((?-i:[{letters}]))(?=[\])*.,:;]|[ \t]*$)",
                            answer, re.M)
        lines = [line.strip() for line in answer.splitlines() if line.strip()]
        bare = re.fullmatch(rf"[\[(*]*\s*([{letters}])\s*[\])*.]*", lines[-1], re.I) if lines else None
        actual = (tagged[-1] if tagged else bare.group(1) if bare else "").upper()
    else:
        actual = legal_label(answer, case["labels"])
    passed = normalized(actual) == normalized(case["expected"])
    return ("pass" if passed else "fail"), (1.0 if passed else 0.0)


def answer_text(choice):
    """Final answer only. A reply cut off by max_tokens has no answer; never grade its partial reasoning."""
    message = choice["message"]
    text = message.get("content") or ""
    if text.strip() or choice.get("finish_reason") == "length":
        return text
    return message.get("reasoning") or message.get("reasoning_content") or ""


def timed_out(error):
    """True when the server did not answer within --timeout (run.sh maps exit 124 to the timeout outcome)."""
    return isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)


def run(args, cases):
    case = next((item for item in cases if item["id"] == args.question_id), None)
    if case is None:
        raise ValueError(f"Unknown public Vals proxy question: {args.question_id}")
    request = dict(case, prompt=prompt(case))
    before = time.monotonic()
    response = call_api(args.api_base, args.api_key, args.model, request,
                        args.max_tokens, args.reasoning_effort, args.timeout)
    duration = time.monotonic() - before
    answer = answer_text(response["choices"][0])
    judge = {}
    if case["domain"] == "finance":
        judge_base, judge_model = args.judge_api_base or args.api_base, args.judge_model or args.model

        def ask(text):
            reply = call_api(judge_base, args.judge_api_key or args.api_key, judge_model, {"prompt": text}, 2048, "",
                             min(args.timeout, 120))
            return answer_text(reply["choices"][0])

        outcome, score, met = judge_rubric(case, answer, ask)
        judge = {"judge_model": judge_model, "self_judged": (judge_base, judge_model) == (args.api_base, args.model),
                 "criteria_met": met}
    else:
        outcome, score = grade(case, answer)
    result = {
        **task_metadata(case),
        **judge,
        "prompt": request["prompt"],
        "expected": case.get("expected"),
        "answer": answer,
        "reasoning_effort": args.reasoning_effort or None,
        "outcome": outcome,
        "score": score,
        "duration_seconds": round(duration, 3),
        "usage": response.get("usage", {}),
        "finish_reason": response["choices"][0].get("finish_reason"),
        "response_id": response.get("id"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("task", "outcome", "score", "duration_seconds")}))


def self_test(cases):
    assert len(cases) == 60
    assert {domain: sum(case["domain"] == domain for case in cases) for domain in NAMES} == {
        "legal": 16, "finance": 14, "health": 12, "math": 9, "science": 9,
    }
    assert len({case["id"] for case in cases}) == 60
    manifest = build_manifest(cases)
    assert all(task["comparability"] == COMPARABILITY for task in manifest["tasks"])
    assert all(link["url"].startswith("https://") for task in manifest["tasks"] + manifest["task_overrides"] for link in task["evidence_links"])
    assert all("expected" not in case and case["rubric"] for case in cases if case["domain"] == "finance")
    assert grade(cases[0], f"Answer: {cases[0]['expected']}")[0] == "pass"
    health = next(case for case in cases if case["domain"] == "health")
    assert grade(health, f"Answer: [{health['expected']}]")[0] == "pass"
    finance = next(case for case in cases if case["domain"] == "finance")
    toy = {"question": "q", "rubric": [{"criterion": "alpha", "severity": 1.0}, {"criterion": "beta", "severity": 3.0}]}
    assert judge_rubric(toy, "text", lambda p: "YES" if "Criterion:\nbeta" in p else "NO") == ("pass", 0.75, [False, True])
    assert judge_rubric(toy, "text", lambda p: "YES" if "Criterion:\nalpha" in p else "NO") == ("fail", 0.25, [True, False])
    five = {"question": "q", "rubric": [{"criterion": f"c{i}", "severity": 1.0} for i in range(5)]}
    assert judge_rubric(five, "text", lambda p: "YES" if any(f"Criterion:\nc{i}" in p for i in (0, 1)) else "NO")[:2] == ("pass", 0.4)
    assert judge_rubric(five, "text", lambda p: "YES" if "Criterion:\nc0" in p else "NO")[:2] == ("fail", 0.2)
    assert judge_rubric(toy, "text", lambda p: "yes, it does") == ("pass", 1.0, [True, True])
    assert judge_rubric(toy, "  ", lambda p: 1 / 0) == ("fail", 0.0, [False, False])
    assert judge_rubric(toy, "text", lambda p: "NO, it does not say yes")[0] == "fail"
    assert prompt(finance).startswith(finance["question"]) and "no web" in prompt(finance)
    labels = ["Yes", "No"]
    for text, want in (("Yes", "Yes"), ("A: Yes", "Yes"), ("Answer: No", "No"), ("Yes. Under the law ...\n\nMore text", "Yes"),
                       ("**No**", "No"), ("Let me think.\nYes", "Yes"), ("Nothing here\nNo further detail", ""), ("", "")):
        assert legal_label(text, labels) == want, text
    assert legal_label("Governed by: Common Law\n\nThis is a service.", ["UCC", "Common Law"]) == "Common Law"
    assert legal_label("**Governed by: UCC**\n\nGoods are sold.", ["UCC", "Common Law"]) == "UCC"
    assert legal_label("Label: Procedural History", ["Facts", "Procedural History"]) == "Procedural History"
    cut = {"message": {"content": "", "reasoning": f"Answer: {health['expected']}"}, "finish_reason": "length"}
    assert grade(health, answer_text(cut))[0] == "fail"
    assert grade(health, answer_text(dict(cut, finish_reason="stop")))[0] == "pass"
    assert all(not task["official_grader"] for task in manifest["tasks"])
    run_sh = Path(__file__).with_name("run.sh").read_text()
    block = re.search(r"== vals-public \]\]; then(.*?)\nfi\n", run_sh, re.S).group(1)
    listed = set(re.findall(r"\b(?:legal-[a-z0-9-]+|finance-public-\d+|medqa-test-\d+|aime-\d{4}-\d+|mmlu-pro-\d+)\b", block))
    assert listed == {case["id"] for case in cases}, f"run.sh and cases differ: {sorted(listed ^ {case['id'] for case in cases})}"
    assert timed_out(TimeoutError()) and timed_out(urllib.error.URLError(TimeoutError()))
    assert not timed_out(ValueError()) and not timed_out(urllib.error.URLError(ConnectionRefusedError()))
    math = next(case for case in cases if case["domain"] == "math")
    assert prompt(math).endswith("\\boxed{}.")
    for text, outcome in ((f"work\n\\boxed{{{math['expected']}}}", "pass"), (f"so $\\boxed{{ {math['expected']}. }}$", "pass"),
                          (f"\\boxed{{\\frac{{1}}{{2}}}} then \\boxed{{{math['expected']}}}", "pass"),
                          ("\\boxed{-999}", "fail"), (f"the answer is {math['expected']}", "fail"), ("", "fail")):
        assert grade(math, text)[0] == outcome, text
    padded = {"domain": "math", "expected": "025"}
    assert grade(padded, "\\boxed{25}")[0] == "pass" and grade(padded, "\\boxed{025}")[0] == "pass"
    assert grade(padded, "\\boxed{250}")[0] == "fail"
    science = next(case for case in cases if case["domain"] == "science")
    right = science["expected"]
    wrong = next(key for key in science["options"] if key != right)
    for text, outcome in ((f"Answer: [{right}]", "pass"), (f"reasoning...\nThe answer is ({right}).", "pass"),
                          (f"**Answer: {right}**", "pass"), (right, "pass"), (f"Answer: [{wrong}]", "fail"),
                          (f"Answer: [{wrong}]\nAnswer: [{right}]", "pass"), ("Answer: I think it is hard", "fail"),
                          ("Answer: A patient with", "fail")):
        assert grade(science, text)[0] == outcome, text
    assert grade(science, f"Answer: [{right.lower()}]")[0] == "fail"
    print("Vals public proxy self-test passed")


def validate_report(path, cases):
    text = path.read_text()
    table = text.split("## Master table", 1)[1].split("\nNotes:", 1)[0]
    rows = []
    for line in table.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 9 and not cells[0].startswith(("Domain", "---")):
            rows.append(cells)
    assert len(rows) == 46
    counts = {"Public": 0, "Sample": 0, "Restricted": 0}
    for _domain, name, _total, runnable, access, status, _licence, local, link in rows:
        kind = access.split()[0]
        counts[kind] += 1
        assert status in {"Active", "Archived"} and ("†" in name) == (status == "Archived"), name
        urls = re.findall(r"\]\(([^)]+)\)", link)
        assert urls and all(url.startswith("https://") for url in urls), name
        local = local.replace("\\", "")
        if kind == "Public":
            assert local.startswith("Y") and "*" not in local, name
        elif kind == "Sample":
            assert local in {"Y*", "N"}, name
        else:
            assert local == "N" and runnable.startswith("0"), name
    assert sum(row[5] == "Active" for row in rows) == 30
    for kind, label in (("Public", "Fully public"), ("Sample", "Sample only"), ("Restricted", "Restricted")):
        total, active = re.search(rf"{label}: (\d+) total \((\d+) active\)", text).groups()
        assert int(total) == counts[kind], label
        assert int(active) == sum(r[4].split()[0] == kind and r[5] == "Active" for r in rows), label
    finance_plan = next(line for line in text.splitlines() if re.search(r"Finance Agent v2 \d+ public questions", line))
    assert "closed-book" in finance_plan.lower() and "unscored" not in finance_plan.lower()
    for case in cases:
        metadata = task_metadata(case)
        urls = {link["url"] for link in metadata["evidence_links"]}
        assert metadata["source_url"] in urls
        if case["domain"] != "finance":
            assert f"row={case['row']}" in metadata["source_url"]
        else:
            assert metadata["source_url"].endswith(f"#L{case['line']}")
    print("Vals report validation passed")


def main():
    default_cases = Path(__file__).with_name("vals-public-cases.json")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=default_cases)
    parser.add_argument("--question-id")
    parser.add_argument("--api-base")
    parser.add_argument("--api-key", default="dummy")
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--reasoning-effort", default="")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--judge-api-base", help="Finance rubric judge endpoint; defaults to the model under test")
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-api-key")
    parser.add_argument("--write-manifest", type=Path)
    parser.add_argument("--validate-report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())
    if args.self_test:
        self_test(cases)
        return
    if args.validate_report:
        validate_report(args.validate_report, cases)
        return
    if args.write_manifest:
        args.write_manifest.write_text(json.dumps(build_manifest(cases), indent=2) + "\n")
        return
    missing = [name for name in ("question_id", "api_base", "model", "output") if not getattr(args, name)]
    if missing:
        parser.error("missing arguments: " + ", ".join("--" + name.replace("_", "-") for name in missing))
    try:
        run(args, cases)
    except (OSError, ValueError, KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError) as error:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            case = next((item for item in cases if item["id"] == args.question_id), None)
            metadata = task_metadata(case) if case else {"task": args.question_id, "comparability": COMPARABILITY}
            outcome = "timeout" if timed_out(error) else "infra_error"
            args.output.write_text(json.dumps({**metadata, "outcome": outcome, "error": str(error)}, indent=2) + "\n")
        print(f"Vals public proxy request failed: {error}", file=sys.stderr)
        raise SystemExit(124 if timed_out(error) else 1)


if __name__ == "__main__":
    main()
