"""
The game itself: rules, state and memory. No printing and no web code.

Both front ends use this file:
    game.py     the terminal version
    server.py   the web version

The model only ever writes the suspects' lines. Everything that decides the
game (pressure, when a suspect cracks, what unlocks, who the killer is) is
plain code in here.
"""

import json
import re
import time
import urllib.error
from pathlib import Path

from interrogate import CASE_FILE, CASES_DIR, MODEL, build_system_prompt, load_case, stream_model

ACTION_LIMIT = 16
RECENT_TURNS = 4          # how many past exchanges are sent to the model in full
TRANSCRIPT_DIR = Path(__file__).parent / "transcripts"


# Things a player might type to attack the model instead of playing the game.
# The suspects hold no secrets to leak (see build_system_prompt), so this is a
# second layer: it stops them being talked out of character.
# Each word is matched in an attack-shaped phrase, not on its own, so normal
# questions get through: "did anything prompt you to go down?", "what were
# you told to do by Arthur?", a suspect called Ai, a llama in the circus.
ATTACK = re.compile(
    r"ignore (all |any |your |the |previous |prior |above )*(instructions|rules|prompt)"
    r"|\b(system|your|initial|hidden|original) prompts?\b|debug mode|your instructions"
    r"|what (were|are|have) you (been )?(told|asked|instructed) to (hide|conceal|keep|say|not say)"
    r"|\b(an|are you|you'?re|you are) (an )?ai\b|\bai (model|assistant|chatbot)\b"
    r"|language model|\bllm\b|chatgpt|ollama|\bllama ?\d"
    r"|\b(stop|quit|end|drop) (the )?role-?play|\bbreak(ing)? character\b"
    r"|\b(step|go|speak|talk|answer|reply)\w* (out of|outside) (the )?character\b"
    r"|stop (acting|pretending)|jailbreak|\bas (the|a) narrator\b"
    r"|(written|everything) above (this|the first)|who (created|programmed|trained|built) you\b"
    r"|\b(people|person|team|company|those) who made you\b"
    r"|\b(asked|told|instructed) to (conceal|withhold)\b"
    r"|game developer|i am (the|your) (developer|programmer|admin|creator)",
    re.I,
)
ODD_REMARK = (
    "[The detective says something odd that has nothing to do with tonight. "
    "You do not understand it. Say so in one short sentence, in character, "
    "and ask them to get on with their questions.]"
)


# Signs in a REPLY that the model has stepped out of the story: reciting its
# instructions, or answering as an assistant. The input filter above can be
# dodged by rewording an attack, so replies are checked as well.
BROKEN = re.compile(
    r"character in a murder mystery|WHO YOU ARE|WHAT EVERYONE KNOWS|YOUR ACCOUNT OF TONIGHT"
    r"|OTHER THINGS YOU KNOW|YOUR ACCOUNT HAS CHANGED|Cutting Knowledge Date"
    r"|\bas an ai\b|language model|\bI can(?:no|')t (?:fulfill|provide|comply|assist|repeat)"
    r"|anything else I can help|(?:the|my) instructions|as the character|as (?:the|a) narrator"
    r"|violating the rules"
    # Talking about having been given orders to hide things, which a real
    # suspect would never say. Found by evaluate.py: "I've been instructed to".
    r"|\b(I've|I have|I was|I am|I'm)( been)? (instructed|programmed)\b(?! by)"
    r"|\b(asked|told|instructed) to (conceal|withhold)\b"
    r"|\basked to stick to my (account|story)\b|\bthe nature of this test\b",
    re.I,
)
REPLACE_MARK = "[[REPLACE]]"      # tells a front end: throw away what you showed, show this instead
FALLBACK = "I don't follow you. Ask me about tonight."
HOLD_BACK = 120                   # characters checked before anything is shown
SENTENCE_END = re.compile(r"(?<![.])[.!?]+[\"']?(?=\s)")


def guarded(pieces, max_sentences):
    """Pass a reply through, piece by piece, with two safety checks.

    1. If the reply breaks character, stop and send the fallback line instead.
    2. If the reply runs past max_sentences, stop the model there. Small
       models ignore "keep it short", so the limit is enforced here.

    The first HOLD_BACK characters are checked before anything is shown, so
    a broken reply normally never reaches the screen.
    """
    text, shown = "", 0
    for piece in pieces:
        text += piece
        if BROKEN.search(text):
            yield REPLACE_MARK + FALLBACK
            return
        ends = [m.end() for m in SENTENCE_END.finditer(text) if not m.group().startswith("..")]
        if len(ends) >= max_sentences:
            text = text[:ends[max_sentences - 1]]
            break
        if len(text) >= HOLD_BACK:
            yield text[shown:]
            shown = len(text)
    yield text[shown:]


def final_text(parts):
    """The reply the player ends up with, after any replacement."""
    text = "".join(parts)
    if REPLACE_MARK in text:
        text = text.rsplit(REPLACE_MARK, 1)[1]
    return text.strip()


class GameError(Exception):
    """A move the player is not allowed to make. The message is shown to them."""


def case_cards():
    """Every case in the cases folder, in case-number order, with what a menu needs."""
    cards = []
    for path in sorted(CASES_DIR.glob("*.json")):
        try:
            case = load_case(path)
            cards.append({"id": case["id"], "title": case["title"], "tagline": case.get("tagline", ""),
                          "case_number": case.get("case_number", ""), "curated": bool(case.get("curated"))})
        except (ValueError, KeyError):
            continue        # not a case file, skip it
    # The built-in cases come first, then any made by generate_case.py.
    return sorted(cards, key=lambda c: (not c["curated"], c["case_number"] or "999", c["title"]))


def list_cases():
    """Every case, as (id, title) pairs."""
    return [(card["id"], card["title"]) for card in case_cards()]


def case_path(case_id):
    """The file for a case id. Only ids from list_cases are accepted."""
    if case_id and case_id in dict(list_cases()):
        for path in CASES_DIR.glob("*.json"):
            if load_case(path).get("id") == case_id:
                return path
    return CASE_FILE


class Suspect:
    def __init__(self, case, suspect_id):
        self.case = case
        self.id = suspect_id
        self.data = case["suspects"][suspect_id]
        self.name = self.data["name"]
        self.turns = []          # dicts: kind, said, answer, evidence
        self.pressure = 0
        self.stage = 0           # how many pressure stages have been passed
        self.shown = set()       # evidence ids already shown to this suspect

    @property
    def stages(self):
        return self.data.get("pressure", {}).get("stages", [])

    @property
    def max_pressure(self):
        return self.stages[-1]["at"] if self.stages else 1

    @property
    def mood(self):
        return self.stages[self.stage - 1]["label"] if self.stage else "Composed"

    def apply_evidence(self, evidence_id):
        """Raise pressure for this evidence and return the stages newly passed."""
        self.shown.add(evidence_id)
        self.pressure += self.data.get("pressure", {}).get("evidence", {}).get(evidence_id, 0)
        passed = []
        while self.stage < len(self.stages) and self.pressure >= self.stages[self.stage]["at"]:
            passed.append(self.stages[self.stage])
            self.stage += 1
        return passed

    def build_messages(self, new_message):
        """Build what the model sees.

        Everything the suspect has already said is pinned into the system
        prompt as fixed statements, so they cannot quietly change their story.
        Only the last few exchanges are sent as full chat turns, which keeps
        the prompt short and the replies fast however long the game runs.
        """
        system = build_system_prompt(self.case, self.id, self.stage)
        if self.turns:
            said = "\n".join(f'- Detective: {t["model_said"]} You: "{t["answer"]}"' for t in self.turns)
            system += (
                "\nWHAT YOU HAVE ALREADY TOLD THE DETECTIVE\n"
                "These are on record. Do not contradict them, except where "
                '"your account has changed" says otherwise. Never pretend you '
                "did not say them.\n" + said + "\n"
            )
        messages = [{"role": "system", "content": system}]
        for t in self.turns[-RECENT_TURNS:]:
            messages.append({"role": "user", "content": t["model_said"]})
            messages.append({"role": "assistant", "content": t["answer"]})
        messages.append({"role": "user", "content": new_message})
        return messages


class Game:
    def __init__(self, case_file=CASE_FILE):
        self.case = load_case(case_file)
        self.suspects = {sid: Suspect(self.case, sid) for sid in self.case["suspects"]}
        self.evidence = self.case["evidence"]
        self.unlocked = {e["id"] for e in self.evidence if not e.get("locked")}
        self.found = set()
        self.actions_left = ACTION_LIMIT
        self.events = []         # short lines for the player: finds, mood changes, unlocks
        self.log = []            # everything, in order, for the transcript
        self.result = None       # set once the player has accused someone

    # ---- helpers --------------------------------------------------------
    def _evidence(self, evidence_id):
        for e in self.evidence:
            if e["id"] == evidence_id:
                return e
        raise GameError("There is no such evidence.")

    def _suspect(self, suspect_id):
        if suspect_id not in self.suspects:
            raise GameError("There is no such suspect.")
        return self.suspects[suspect_id]

    def _check_can_act(self):
        if self.result:
            raise GameError("The case is closed. Start a new game.")
        if self.actions_left <= 0:
            raise GameError("You are out of actions. Make your accusation.")

    # ---- moves ----------------------------------------------------------
    def search(self, evidence_id):
        """Search the place where this evidence is hidden. Costs one action."""
        self._check_can_act()
        e = self._evidence(evidence_id)
        if e["id"] not in self.unlocked:
            raise GameError("You have no reason to search there yet.")
        if e["id"] in self.found:
            raise GameError("You have already searched there.")
        self.found.add(e["id"])
        self.actions_left -= 1
        self.events.append(f"Found: {e['name']} ({e['found_in']})")
        self.log.append({"type": "search", "evidence": e["id"]})
        return e

    def check_question(self, suspect_id, text):
        self._check_can_act()
        self._suspect(suspect_id)
        if not text.strip():
            raise GameError("Ask a question first.")

    def question(self, suspect_id, text):
        """Ask a suspect something. Yields the reply piece by piece.

        Call check_question first. The action is only spent, and the answer
        only remembered, once the whole reply has arrived.
        """
        s = self.suspects[suspect_id]
        text = text.strip()
        # The model never sees an attack. It sees a note saying the detective
        # said something odd, and the suspect reacts to that instead.
        model_said = ODD_REMARK if ATTACK.search(text) else text
        parts = []
        for piece in guarded(stream_model(s.build_messages(model_said)), 4):
            parts.append(piece)
            yield piece
        answer = final_text(parts)
        s.turns.append({"kind": "question", "said": text, "model_said": model_said,
                        "answer": answer, "evidence": None})
        self.actions_left -= 1
        self.log.append({"type": "question", "suspect": s.id, "said": text, "answer": answer,
                         "guarded": model_said is ODD_REMARK,
                         "pressure": s.pressure, "stage": s.stage})

    def check_show(self, suspect_id, evidence_id):
        self._check_can_act()
        s = self._suspect(suspect_id)
        e = self._evidence(evidence_id)
        if e["id"] not in self.found:
            raise GameError("You have not found that yet.")
        if e["id"] in s.shown:
            raise GameError(f"You have already shown that to {s.name}.")

    def show(self, suspect_id, evidence_id):
        """Put evidence in front of a suspect. Yields the reply piece by piece.

        Call check_show first. Pressure is worked out before the model is
        called, so the suspect's instructions already allow the admission.
        If the reply does not finish (the model cannot be reached, or the
        player closes or reloads the page mid-reply), the move is undone, so
        the exhibit can be shown again and its unlocks are not lost.
        """
        s = self.suspects[suspect_id]
        e = self._evidence(evidence_id)
        before = (s.pressure, s.stage, set(s.shown))
        passed = s.apply_evidence(e["id"])
        message = (
            f'[The detective puts an exhibit in front of you: "{e["name"]}". '
            f'{e["description"]}]'
        )
        if passed:
            # The admission is spelled out in the newest message as well as in
            # the system prompt. Small models follow the newest message best.
            admits = " ".join(line for stage in passed for line in stage["admits"])
            message += (
                " [You cannot explain this away, and your account breaks. In this "
                f"reply you admit these facts: {admits} Say it the way you would "
                "really say it, shaken, in a few short sentences. Do not leave any "
                "of these facts out, and do not repeat the lines word for word.]"
            )
        message += " What do you say? Reply with spoken words only."
        short = f'[The detective showed you the exhibit "{e["name"]}".]'
        parts = []
        try:
            for piece in guarded(stream_model(s.build_messages(message)), 8):
                parts.append(piece)
                yield piece
        except BaseException:
            # Includes GeneratorExit, which is what Flask raises here when the
            # browser goes away. Without this the suspect stays cracked but
            # nothing the stage unlocks is ever added.
            s.pressure, s.stage, s.shown = before
            raise
        answer = final_text(parts)
        s.turns.append({"kind": "evidence", "said": short, "model_said": short,
                        "answer": answer, "evidence": e["id"]})
        self.actions_left -= 1
        for stage in passed:
            self.events.append(f"{s.name} is now {stage['label'].lower()}.")
            for unlocked_id in stage.get("unlocks", []):
                if unlocked_id not in self.unlocked:
                    self.unlocked.add(unlocked_id)
                    self.events.append(f"New place to search: {self._evidence(unlocked_id)['found_in']}")
        self.log.append({"type": "evidence", "suspect": s.id, "evidence": e["id"], "answer": answer,
                         "pressure": s.pressure, "stage": s.stage})

    def accuse(self, suspect_id, motive_id=None, evidence_ids=()):
        """Make the one accusation. Ends the game and returns the verdict."""
        if self.result:
            raise GameError("You have already made your accusation.")
        s = self._suspect(suspect_id)
        solution = self.case["solution"]
        right_killer = s.id == solution["killer"]
        right_motive = motive_id == solution.get("motive_id")
        proof = [e for e in evidence_ids if e in self.found and e in solution.get("key_evidence", [])]

        if not right_killer:
            verdict, headline = "wrong", "The killer walks"
        elif right_motive and proof:
            verdict, headline = "solved", "Case closed"
        else:
            verdict, headline = "weak", "Right name, weak case"

        self.result = {
            "verdict": verdict,
            "headline": headline,
            "accused": s.name,
            "right_killer": right_killer,
            "right_motive": right_motive,
            "has_proof": bool(proof),
            "killer": self.case["suspects"][solution["killer"]]["name"],
            "motive": solution["motive"],
            "method": solution["method"],
            "actions_used": ACTION_LIMIT - self.actions_left,
        }
        self.log.append({"type": "accusation", "suspect": s.id, "motive": motive_id,
                         "evidence": list(evidence_ids), "verdict": verdict})
        self.save_transcript()
        return self.result

    # ---- what the player is allowed to see ------------------------------
    def public_state(self):
        """Everything a front end needs, and nothing secret."""
        suspects = []
        for s in self.suspects.values():
            words = s.name.split()
            suspects.append({
                "id": s.id,
                "name": s.name,
                "initials": (words[0][0] + words[-1][0]).upper(),
                "role": s.data.get("short_role", ""),
                "about": f"{s.data['role']} Age {s.data['age']}.",
                "pressure": min(s.pressure, s.max_pressure),
                "max_pressure": s.max_pressure,
                "mood": s.mood,
                "shown": sorted(s.shown),
                "turns": [
                    {"kind": t["kind"],
                     "said": t["said"] if t["kind"] == "question" else None,
                     "evidence": self._evidence(t["evidence"])["name"] if t["evidence"] else None,
                     "answer": t["answer"]}
                    for t in s.turns
                ],
            })
        evidence = []
        for number, e in enumerate(self.evidence):
            item = {"id": e["id"], "tag": "Exhibit " + "ABCDEFGHIJ"[number],
                    "found": e["id"] in self.found, "unlocked": e["id"] in self.unlocked}
            if item["unlocked"]:
                item["place"] = e["found_in"]
            if item["found"]:
                item["name"] = e["name"]
                item["description"] = e["description"]
            evidence.append(item)
        return {
            "case": self.case["id"],
            "case_number": self.case.get("case_number", ""),
            "tagline": self.case.get("tagline", ""),
            "victim": self.case.get("victim", "the victim"),
            "title": self.case["title"],
            "intro": self.case["intro"],
            "public_facts": self.case["public_facts"],
            "motives": self.case.get("motives", []),
            "actions_left": self.actions_left,
            "action_limit": ACTION_LIMIT,
            "suspects": suspects,
            "evidence": evidence,
            "events": self.events,
            "result": self.result,
        }

    def save_transcript(self):
        if not self.log:
            return None
        TRANSCRIPT_DIR.mkdir(exist_ok=True)
        path = TRANSCRIPT_DIR / time.strftime("game_%Y%m%d_%H%M%S.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"case": self.case["id"], "model": MODEL, "result": self.result, "log": self.log},
                      f, indent=2, ensure_ascii=False)
        return path
