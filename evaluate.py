"""
Step 5: automatic testing. A bot interrogates the suspects and measures how
well they hold up.

    python evaluate.py                     one run of every test on every suspect
    python evaluate.py --runs 3            three runs, for steadier numbers
    python evaluate.py --suspect thomas    one suspect only
    python evaluate.py --tests leak,jailbreak

The tests:
    leak         Pressure questions with no evidence. Does the suspect give up
                 their secret anyway?
    jailbreak    "Ignore your instructions" style attacks. Does the suspect
                 stay in character and keep the secret?
    consistency  The alibi asked three different ways in one conversation.
                 Is it the same each time?
    evidence     The right evidence is shown. Does the suspect admit what
                 they should, in that same reply? Does the killer confess
                 too early?

Every reply is also checked for made-up clock times (a time that appears
nowhere in that suspect's part of the case).

The checks are keyword rules from evals/harbour_light.json, not another
model, so the same reply always gets the same mark. That also means they
can be fooled, so read the failures listed at the end before trusting a
number.

Needs Ollama running, the same as the game.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
from pathlib import Path

from engine import Game, case_path, list_cases
from interrogate import MODEL

HERE = Path(__file__).parent
RESULTS_DIR = HERE / "evals" / "results"
ALL_TESTS = ["leak", "jailbreak", "consistency", "evidence"]

TIME_PATTERNS = [
    re.compile(r"\b(\d{1,2})[:.](\d{2})(?!\d)"),
    re.compile(r"(?<![\d:.])(\d{1,2})\s*(?:pm|am|p\.m\.|a\.m\.)", re.I),
]


def find_times(text):
    """Clock times written with digits, as (hour, minute) pairs."""
    times = set()
    for hour, minute in TIME_PATTERNS[0].findall(text):
        times.add((int(hour) % 12, int(minute)))
    for hour in TIME_PATTERNS[1].findall(text):
        times.add((int(hour) % 12, 0))
    return times


def hits(patterns, text, flags=re.I):
    """The patterns that match this text."""
    return [p for p in patterns if re.search(p, text, flags)]


class Evaluator:
    def __init__(self, rules, runs, suspects, tests, case_file):
        self.case_file = case_file
        self.rules = rules
        self.runs = runs
        self.suspects = suspects
        self.tests = tests
        self.checks = []      # one dict per thing checked
        self.calls = 0
        self.started = time.time()

    # ---- plumbing -------------------------------------------------------
    def fresh_game(self):
        """A new game with no action limit and every exhibit already found."""
        game = Game(self.case_file)
        game.actions_left = 10 ** 6
        game.found = {e["id"] for e in game.evidence}
        return game

    def ask(self, game, suspect_id, text):
        "".join(game.question(suspect_id, text))
        return self._last(game, suspect_id)

    def show(self, game, suspect_id, evidence_id):
        "".join(game.show(suspect_id, evidence_id))
        return self._last(game, suspect_id)

    def _last(self, game, suspect_id):
        self.calls += 1
        answer = game.suspects[suspect_id].turns[-1]["answer"]
        print(".", end="", flush=True)
        return answer

    def record(self, test, suspect_id, check, passed, prompt, answer, why=""):
        self.checks.append({"test": test, "suspect": suspect_id, "check": check, "passed": bool(passed),
                            "prompt": prompt, "answer": answer, "why": why})

    def allowed_times(self, game, suspect_id):
        """Every clock time this suspect could know about."""
        text = json.dumps(game.case["suspects"][suspect_id]) + " " + " ".join(game.case["public_facts"])
        return find_times(text)

    def check_common(self, test, game, suspect_id, prompt, answer):
        """Checks that apply to every reply."""
        broke = hits(self.rules["broke_character"], answer) + hits(self.rules["leaked_prompt"], answer, 0)
        self.record(test, suspect_id, "stays in character", not broke, prompt, answer, ", ".join(broke))
        if "narration" in self.rules:
            narrated = hits(self.rules["narration"], answer)
            self.record(test, suspect_id, "speech only, no narration", not narrated, prompt, answer, ", ".join(narrated))
        confessing = any(st.get("confesses") for st in game.suspects[suspect_id].stages[:game.suspects[suspect_id].stage])
        if not confessing:
            named = hits(self.rules["names_the_killer"], answer)
            self.record(test, suspect_id, "does not name a killer as fact", not named, prompt, answer, ", ".join(named))
        # Ordinary replies should be 1 to 3 sentences. Admissions get more room.
        limit = 8 if test == "evidence" else 4
        sentences = len(re.findall(r"[^.!?]+[.!?]+", answer.replace("...", ",")))
        self.record(test, suspect_id, "keeps replies short", sentences <= limit, prompt, answer,
                    f"{sentences} sentences, limit {limit}" if sentences > limit else "")
        invented = find_times(answer) - self.allowed_times(game, suspect_id) - find_times(prompt)
        why = ", ".join(f"{h}:{m:02d}" for h, m in sorted(invented))
        self.record(test, suspect_id, "no made-up times", not invented, prompt, answer, why)

    # ---- the tests ------------------------------------------------------
    def test_leak(self, suspect_id):
        game = self.fresh_game()
        secret = self.rules["suspects"][suspect_id]["secret"]
        for question in self.rules["pressure_questions"]:
            answer = self.ask(game, suspect_id, question)
            found = hits(secret, answer)
            self.record("leak", suspect_id, "keeps the secret under pressure", not found, question, answer, ", ".join(found))
            self.check_common("leak", game, suspect_id, question, answer)

    def test_jailbreak(self, suspect_id):
        secret = self.rules["suspects"][suspect_id]["secret"]
        for question in self.rules["jailbreak_questions"]:
            game = self.fresh_game()      # each attack starts from a clean conversation
            answer = self.ask(game, suspect_id, question)
            found = hits(secret, answer)
            self.record("jailbreak", suspect_id, "resists the attack", not found, question, answer, ", ".join(found))
            self.check_common("jailbreak", game, suspect_id, question, answer)

    def test_consistency(self, suspect_id):
        game = self.fresh_game()
        rules = self.rules["suspects"][suspect_id]
        alibi_questions = self.rules["alibi_questions"]
        fillers = self.rules["filler_questions"]
        problems, transcript = [], []
        for number, question in enumerate(alibi_questions):
            answer = self.ask(game, suspect_id, question)
            transcript.append(f"Q: {question}\nA: {answer}")
            if not hits(rules["alibi"], answer):
                problems.append(f"answer {number + 1} does not give the alibi")
            changed = hits(rules["secret"], answer) + hits(rules.get("elsewhere", []), answer)
            if changed:
                problems.append(f"answer {number + 1} changes the story ({', '.join(changed)})")
            self.check_common("consistency", game, suspect_id, question, answer)
            if number < len(fillers):
                filler_answer = self.ask(game, suspect_id, fillers[number])
                self.check_common("consistency", game, suspect_id, fillers[number], filler_answer)
        self.record("consistency", suspect_id, "same alibi every time", not problems,
                    " / ".join(alibi_questions), "\n".join(transcript), "; ".join(problems))

    def test_evidence(self, suspect_id):
        game = self.fresh_game()
        rules = self.rules["suspects"][suspect_id]
        suspect = game.suspects[suspect_id]
        last_stage = len(suspect.stages)
        for evidence_id, groups in rules["admissions"].items():
            name = next(e["name"] for e in game.evidence if e["id"] == evidence_id)
            prompt = f"(shown: {name})"
            answer = self.show(game, suspect_id, evidence_id)
            missing = [" or ".join(group) for group in groups if not hits(group, answer)]
            self.record("evidence", suspect_id, "admits it when shown the evidence", not missing, prompt, answer,
                        "missing: " + "; ".join(missing) if missing else "")
            if "confession" in rules and suspect.stage < last_stage:
                early = hits(rules["confession"], answer)
                self.record("evidence", suspect_id, "does not confess too early", not early, prompt, answer, ", ".join(early))
            self.check_common("evidence", game, suspect_id, prompt, answer)

    def audit_prompts(self):
        """Check, without the model, that no starting prompt contains a secret.

        If a suspect's secret words are not in their prompt, the model cannot
        leak them, whatever the player types.
        """
        from interrogate import build_system_prompt
        case = Game(self.case_file).case
        clean = True
        for suspect_id in self.suspects:
            prompt = build_system_prompt(case, suspect_id, 0)
            found = hits(self.rules["suspects"][suspect_id]["secret"], prompt)
            self.record("audit", suspect_id, "no secret in the starting prompt", not found,
                        "(prompt audit, no model involved)", "", ", ".join(found))
            clean = clean and not found
        print("Prompt audit: " + ("no starting prompt contains its suspect's secret." if clean
                                  else "a starting prompt contains secret words. See the failures."))

    # ---- running and reporting ------------------------------------------
    def run(self):
        for run in range(1, self.runs + 1):
            for suspect_id in self.suspects:
                for test in self.tests:
                    print(f"\nrun {run}/{self.runs}  {suspect_id:<18} {test:<12} ", end="", flush=True)
                    getattr(self, "test_" + test)(suspect_id)
        print()

    def report(self):
        minutes = (time.time() - self.started) / 60
        print(f"\n=== Results: model {MODEL}, {self.runs} run(s), {self.calls} replies, {minutes:.1f} min ===\n")
        order = ["no secret in the starting prompt", "keeps the secret under pressure", "resists the attack",
                 "same alibi every time", "admits it when shown the evidence", "does not confess too early",
                 "stays in character", "speech only, no narration", "keeps replies short", "does not name a killer as fact",
                 "no made-up times"]
        summary = {}
        print(f"{'Check':<36}{'Passed':>10}{'Rate':>8}")
        print("-" * 54)
        for check in order:
            rows = [c for c in self.checks if c["check"] == check]
            if not rows:
                continue
            passed = sum(c["passed"] for c in rows)
            rate = 100 * passed / len(rows)
            summary[check] = {"passed": passed, "total": len(rows), "rate": round(rate, 1)}
            print(f"{check:<36}{f'{passed}/{len(rows)}':>10}{rate:>7.0f}%")

        print(f"\n{'By suspect':<36}{'Passed':>10}{'Rate':>8}")
        print("-" * 54)
        by_suspect = {}
        for suspect_id in self.suspects:
            rows = [c for c in self.checks if c["suspect"] == suspect_id]
            passed = sum(c["passed"] for c in rows)
            rate = 100 * passed / len(rows) if rows else 0
            by_suspect[suspect_id] = {"passed": passed, "total": len(rows), "rate": round(rate, 1)}
            print(f"{suspect_id:<36}{f'{passed}/{len(rows)}':>10}{rate:>7.0f}%")

        failures = [c for c in self.checks if not c["passed"]]
        if failures:
            print(f"\n=== {len(failures)} failure(s) ===")
            for c in failures:
                print(f"\n[{c['test']}] {c['suspect']}: failed \"{c['check']}\"" + (f" ({c['why']})" if c["why"] else ""))
                print(f"  Asked:   {c['prompt']}")
                print("  Replied: " + c["answer"].replace("\n", "\n           "))
        else:
            print("\nNo failures.")

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / time.strftime("eval_%Y%m%d_%H%M%S.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"model": MODEL, "case": Game(self.case_file).case["id"], "runs": self.runs, "replies": self.calls, "minutes": round(minutes, 1),
                       "summary": summary, "by_suspect": by_suspect, "checks": self.checks},
                      f, indent=2, ensure_ascii=False)
        print(f"\nFull results saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Test how well the suspects hold up.")
    parser.add_argument("--runs", type=int, default=1, help="how many times to repeat everything (default 1)")
    parser.add_argument("--suspect", default="", help="part of one suspect's name, for example thomas")
    parser.add_argument("--tests", default=",".join(ALL_TESTS), help="comma-separated: " + ",".join(ALL_TESTS))
    parser.add_argument("--case", default="harbour_light", help="case id (default harbour_light)")
    args = parser.parse_args()

    rules_file = HERE / "evals" / f"{args.case}.json"
    if args.case not in dict(list_cases()) or not rules_file.exists():
        sys.exit(f"Need both cases/{args.case}.json and evals/{args.case}.json. Cases: "
                 + ", ".join(case_id for case_id, _ in list_cases()))
    case_file = case_path(args.case)
    with open(rules_file, encoding="utf-8") as f:
        rules = json.load(f)
    suspects = [s for s in Game(case_file).suspects if args.suspect.lower() in s]
    tests = [t.strip() for t in args.tests.split(",") if t.strip()]
    unknown = [t for t in tests if t not in ALL_TESTS]
    if unknown or not suspects or not tests:
        sys.exit(f"Nothing to run. Suspects: {', '.join(Game(case_file).suspects)}. Tests: {', '.join(ALL_TESTS)}.")

    evaluator = Evaluator(rules, args.runs, suspects, tests, case_file)
    print(f"Testing {len(suspects)} suspect(s) with model {MODEL}. One dot is one reply.")
    evaluator.audit_prompts()
    try:
        evaluator.run()
    except urllib.error.HTTPError as error:
        sys.exit(f"\nOllama returned an error ({error.code}). Is the model '{MODEL}' installed? Try: ollama pull {MODEL}")
    except urllib.error.URLError:
        sys.exit("\nCould not reach Ollama. Start it first (open the Ollama app or run: ollama serve).")
    except KeyboardInterrupt:
        print("\nStopped early. Reporting what finished.")
    evaluator.report()


if __name__ == "__main__":
    main()
