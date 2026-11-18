"""
Build the built-in cases from the hand-written blanks in case_blanks.py.

    python build_cases.py

For each case it writes cases/<id>.json and evals/<id>.json, using the same
sentence templates and the same checks as generate_case.py. No model is
needed. Run it again after changing a blank or a template.
"""

import json
import random
import sys

from case_blanks import CASES
from generate_case import CASES_DIR, EVALS_DIR, Rejected, build_case, build_rules, check_case


def main():
    failed = 0
    for blank in CASES:
        rooms = blank["rooms"]
        slots = {
            "K": dict(blank["k"], alibi_room=rooms["records_room"], destroy_room=rooms["fire_room"], trace_room=rooms["clothes_room"]),
            "W": dict(blank["w"], work_room=rooms["work_room"]),
            "F": dict(blank["f"], real_room=rooms["social_room"], record_room=rooms["notes_room"]),
            "O": blank["o"],
        }
        people = {key: blank[key] for key in "KWFO"}
        case = build_case(blank["world"], people, people["K"], people["W"], people["F"], people["O"],
                          slots, random.Random(blank["seed"]), blank["id"], blank["number"])
        case["generated"] = False
        case["curated"] = True
        try:
            shortest = check_case(case)
        except Rejected as error:
            failed += 1
            print(f"FAILED  {blank['id']}: {error}")
            continue
        with open(CASES_DIR / f"{blank['id']}.json", "w", encoding="utf-8") as f:
            json.dump(case, f, indent=2, ensure_ascii=False)
        with open(EVALS_DIR / f"{blank['id']}.json", "w", encoding="utf-8") as f:
            json.dump(build_rules(case), f, indent=2, ensure_ascii=False)
        print(f"ok      {blank['number']}  {case['title']:<22} shortest solution {shortest} actions")
    if failed:
        sys.exit(f"\n{failed} case(s) failed their checks and were not written.")


if __name__ == "__main__":
    main()
