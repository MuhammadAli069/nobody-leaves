"""
Step 6: make a new case.

    python generate_case.py                          a random setting
    python generate_case.py --hint "a ski lodge"     your own setting
    python generate_case.py --seed 7                 same structure every time

It writes two files:
    cases/<id>.json    the case, playable in the game straight away
    evals/<id>.json    test rules for it, so evaluate.py --case <id> works

How it works. A small local model cannot write a whole mystery that holds
together, so the work is split:

    The code decides the logic: who the killer is, the timeline, which
    exhibit breaks which suspect, what unlocks what.

    The model fills in small blanks: the place, the names, the jobs, the
    rooms, the objects, the secrets.

    The code then builds every sentence from those blanks, and checks the
    case before saving it: no clashing rooms or names, no secret in any
    starting prompt, and the case can be solved inside the action limit.

Needs Ollama running, the same as the game.
"""

import argparse
import json
import random
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from engine import ACTION_LIMIT, Suspect, list_cases
from interrogate import CASES_DIR, MODEL, OLLAMA_URL, build_system_prompt

HERE = Path(__file__).parent
EVALS_DIR = HERE / "evals"
SHARED_RULES = EVALS_DIR / "harbour_light.json"      # the checks that apply to every case
MAX_TRIES = 4

SETTINGS = [
    "a ski lodge cut off by heavy snow",
    "a lighthouse station on a rock in a gale",
    "a river boat stuck on a sandbank overnight",
    "a country house cut off by a flood",
    "a mountain observatory in a blizzard",
    "a sleeper train stopped by a landslide",
    "a small island inn after the last ferry has gone",
    "a vineyard estate with the only road closed",
    "a theatre locked in overnight during a blackout",
    "a research ship at anchor in thick fog",
]


# ---- talking to the model -------------------------------------------------
def schema(fields):
    """A JSON schema where every field is a required string, or a list of choices."""
    props = {}
    for name, kind in fields.items():
        props[name] = {"type": "string", "enum": kind} if isinstance(kind, list) else {"type": kind}
    return {"type": "object", "properties": props, "required": list(fields)}


def ask_json(prompt, json_schema):
    """Ask the model for an answer in a fixed JSON shape."""
    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "format": json_schema,
        "options": {"temperature": 0.9, "num_predict": 700},
    }).encode("utf-8")
    request = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(json.loads(response.read())["message"]["content"])


SENTENCES = ("_text", "_line", "personality", "speaking_style")          # written out in full
PROPER = ("name", "title")                                              # keep their capitals
NOUNS = ("task_record", "trace_item", "trace_mark", "proof_item", "remains", "relation", "evening_event", "job")   # bare nouns: no article, lower case
# The start of the sentence each blank goes into. Small models often repeat it
# ("I was I was fixing the gate"), so it is cut off the front of the answer.
STEMS = {
    "alibi_task": r"i was", "work_task": r"i was", "cover": r"i was", "real_task": r"i was",
    "break_spot": r"for a quarter of an hour i was|i was", "break_task": r"i was there|i was",
    "wrongdoing": r"for two years i have been|i have been|i had been|i was",
    "discovery": r"the victim|he|she", "excuse_one": r"i spent the rest of the time",
    "excuse_two": r"i only went there to|i went there to|i went there because|because|to", "destroy_how": r"i",
    "cover_identity": r"i am|i'm", "cover_reason": r"i am here|i'm here",
    "real_identity": r"i am really|i am|i'm", "real_aim": r"i want to|to",
}


def lower_first(text):
    """Lower the first letter, unless the phrase starts with "I" or an acronym."""
    if not text or text.split()[0] in ("I", "I'm", "I've", "I'd", "I'll") or (text[:2].isalpha() and text[:2].isupper()):
        return text
    return text[:1].lower() + text[1:]


def clean(name, text):
    """Tidy a blank the model filled in so it drops into a sentence cleanly."""
    text = re.sub(r"\s+", " ", str(text)).strip().strip(".,;:!\"'")
    if name.endswith(SENTENCES):
        return text
    if name in STEMS:
        stem = STEMS[name]
        for _ in range(2):
            text = re.sub(rf"^(?:{stem})\s+", "", text, flags=re.I)
        repeats = [part for part in stem.split("|") if " " in part]
        if repeats:                             # also cut a repeat later in the phrase
            text = re.split(rf"\s+(?:{'|'.join(repeats)})\s+", text, flags=re.I)[0]
        text = re.sub(r"\s+for two years$", "", text, flags=re.I).strip(" .,;")
    if name.endswith(PROPER):
        return text
    if name.endswith("_room") or name in NOUNS:
        return re.sub(r"^(the|a|an|my|his|her|their)\s+", "", text, flags=re.I).lower()
    return lower_first(text)


def upper_first(text):
    return text[:1].upper() + text[1:]


def clock(minutes):
    """Minutes after noon as '10:45 pm'."""
    hour, minute = divmod(minutes, 60)
    return f"{hour}:{minute:02d} pm"


class Rejected(Exception):
    """The model's answer cannot be used. The message says why."""


def fill(label, prompt, fields, check=None):
    """Ask for one set of blanks, checking the answer and retrying if it is unusable."""
    problem = ""
    for attempt in range(1, MAX_TRIES + 1):
        print(f"  {label} (try {attempt})...", flush=True)
        try:
            answer = ask_json(prompt + (f"\n\nYour last answer was rejected: {problem} Fix that." if problem else ""),
                              schema(fields))
            for name, kind in fields.items():
                if kind == "integer":
                    answer[name] = int(answer[name])
                    continue
                answer[name] = clean(name, answer.get(name, ""))
                if isinstance(kind, list) and answer[name].lower() not in kind:
                    raise Rejected(f"'{name}' must be one of: {', '.join(kind)}.")
                if not answer[name]:
                    raise Rejected(f"'{name}' was empty.")
                if len(answer[name].split()) > (30 if name.endswith(SENTENCES) else 12):
                    raise Rejected(f"'{name}' was too long. Keep it short.")
            if check:
                check(answer)
            return answer
        except Rejected as error:
            problem = str(error)
            print(f"    rejected: {problem}")
        except (ValueError, KeyError, TypeError):
            problem = "It was not in the requested format."
            print("    rejected: not in the requested format")
    sys.exit(f"\nThe model could not produce a usable '{label}' in {MAX_TRIES} tries. Run it again, or try a different --hint.")


# ---- the blanks -----------------------------------------------------------
# The examples in these prompts come from a made-up circus story on purpose.
# With examples from a hotel story, a small model copies them (wine cellar,
# boiler room, soot on a jacket) into every case. Anything copied from the
# examples, or from the first case, is rejected.
RULES_OF_STYLE = (
    "Write plain, simple English. Use English names. Each field is a short phrase that fills a blank, "
    "so give ONLY the words for the blank, not the whole sentence. "
    "The examples are from a different story, about a circus. Do not use circus things or copy the examples. "
    "Invent details that fit this place."
)
EXAMPLE_PHRASES = [
    # from the circus examples below
    "winter ring", "winter quarters", "wagon office", "tent peg", "horses", "feed bill", "harness", "buckles",
    "forge fire", "scorched bill", "coal dust", "waistcoat", "banking for the night", "ponies", "notice to quit",
    "behind the animal shed", "quiet drink", "asleep in my bunk", "dice", "sketch artist", "rival show",
    # from the first case, The Harbour Light
    "wine cellar", "stock-take", "stocktake", "soot", "telephone to my sister", "travel writer", "property developer",
]
COPIED = re.compile("|".join(re.escape(phrase) for phrase in EXAMPLE_PHRASES), re.I)
POLICE = re.compile(r"detective|police|\bcop\b|officer|investigator|inspector|agent of the law|undercover", re.I)


def no_copies(answer, fields):
    for name in fields:
        hit = COPIED.search(answer[name])
        if hit:
            raise Rejected(f"'{name}' reuses '{hit.group()}', which comes from the examples. Invent something of your own that fits this place.")


def check_gender(answer, fields):
    """The free-text fields must not call a man 'she' or a woman 'he'."""
    wrong = r"\b(she|her|hers|herself|woman)\b" if answer["gender"] == "male" else r"\b(he|his|him|himself|man)\b"
    for name in fields:
        if re.search(wrong, answer[name], re.I):
            raise Rejected(f"'{name}' uses the wrong pronouns. {answer['name']} is {answer['gender']}.")


def get_world(hint):
    prompt = f"""You are inventing the setting for a murder mystery. The setting: {hint}.
A small group of people is cut off for one night and the person in charge is killed.
{RULES_OF_STYLE}

Fields:
- title: the name of the mystery, 2 to 4 words, starting with "The". Example: The Winter Ring
- place_name: the name of the place. Example: Marlow's Winter Quarters
- tagline_line: where and when, then a short line. Example: Yorkshire, deep January. The lane is gone.
- cut_off_text: one sentence saying what cut the place off tonight, with no time in it. Example: Snow drifts closed the lane
- evening_event: the meal or event that ended early in the evening, one or two words. Example: supper
- victim_name: first name and surname of the person in charge, who is killed
- victim_gender: male or female
- victim_age: a number between 45 and 75
- victim_role: who they were, starting with "the". Example: the owner of the show
- body_room: the one room where the body is found, with no name in it. Example: wagon office
- weapon: a heavy object small enough to swing with one hand, starting with "a". Example: a brass tent peg"""

    def check(a):
        a["victim_age"] = min(max(a["victim_age"], 40), 80)
        if len(a["victim_name"].split()) < 2:
            raise Rejected("victim_name needs a first name and a surname.")
        if not re.match(r"(the|a|an)\s", a["victim_role"], re.I):
            a["victim_role"] = "the " + a["victim_role"]
        if not re.match(r"(a|an|the)\s", a["weapon"], re.I):
            a["weapon"] = "a " + a["weapon"]
        no_copies(a, ["title", "place_name", "body_room", "weapon"])
    return fill("setting", prompt, {
        "title": "string", "place_name": "string", "tagline_line": "string", "cut_off_text": "string",
        "evening_event": "string", "victim_name": "string", "victim_gender": ["male", "female"],
        "victim_age": "integer", "victim_role": "string", "body_room": "string", "weapon": "string"}, check)


def get_rooms(world, hint):
    """Pick the rooms first, one for each part of the plot, so later answers cannot clash."""
    prompt = f"""A murder mystery is set at {world['place_name']} ({hint}).
Name six different rooms or areas that would really exist there. Each is one to three words, in lower case, with no people's names.
None of them may be the {world['body_room']}, and all six must be different.

Fields:
- records_room: where accounts, tickets or paperwork are kept, and a person could work alone
- fire_room: a room with a stove, furnace, firebox, incinerator or open fire
- clothes_room: where staff leave their coats and work clothes
- work_room: a workshop or store where a person does manual work
- social_room: a shared room where people sit, eat or play games in the evening
- notes_room: a small room where a log book, rota or messages are kept"""
    fields = ["records_room", "fire_room", "clothes_room", "work_room", "social_room", "notes_room"]

    def check(a):
        rooms = [a[name] for name in fields]
        if len(set(rooms)) < len(rooms):
            raise Rejected("All six rooms must be different from each other.")
        if world["body_room"] in rooms:
            raise Rejected(f"None of them may be the {world['body_room']}.")
    return fill("rooms", prompt, {name: "string" for name in fields}, check)


def get_person(world, taken, kind, gender=None):
    prompt = f"""You are inventing one suspect for a murder mystery set at {world['place_name']}.
The victim is {world['victim_name']}, {world['victim_role']}.
This suspect is {kind}.{f" This suspect is {gender}." if gender else ""}
Names already used, which you must not use: {', '.join(taken)}.
Do not mention any crime, guilt or secret. Describe an ordinary person.
{RULES_OF_STYLE}

Fields:
- name: first name and surname
- gender: male or female. It must match the first name.
- age: a number between 25 and 65
- job: their job or position at this place, 1 to 4 words, with no name in it
- about_text: one plain sentence about their work here, using the right pronoun for their gender
- personality: one sentence about how they come across
- speaking_style: one sentence about how they talk"""

    def check(a):
        if len(a["name"].split()) < 2:
            raise Rejected("The name needs a first name and a surname.")
        first, last = a["name"].split()[0].lower(), a["name"].split()[-1].lower()
        # A relative may share the victim's surname (taken[0]), but nothing else may repeat.
        if any(first == t.split()[0].lower() for t in taken) or any(last == t.split()[-1].lower() for t in taken[1:]):
            raise Rejected("That name is too close to one already used. Pick a completely different first name and surname.")
        if gender and a["gender"] != gender:
            raise Rejected(f"This suspect must be {gender}, with a {gender} first name.")
        a["age"] = min(max(a["age"], 22), 75)
        check_gender(a, ["about_text", "personality", "speaking_style"])
    return fill(f"suspect ({kind})", prompt, {
        "name": "string", "gender": ["male", "female"], "age": "integer", "job": "string",
        "about_text": "string", "personality": "string", "speaking_style": "string"}, check)


def get_killer(world, k, rooms):
    v_first = world["victim_name"].split()[0]
    prompt = f"""A murder mystery at {world['place_name']}. {k['name']}, the {k['job']}, killed {world['victim_name']} ({world['victim_role']}).
Three rooms are already decided:
- {k['name']} claims to have been working alone in the {rooms['records_room']}.
- {k['name']} really destroyed the proof in the {rooms['fire_room']}.
- {k['name']} then left a piece of marked clothing in the {rooms['clothes_room']}.
Invent the details so that they fit this place, this job and these rooms.
{RULES_OF_STYLE}

Fields:
- wrongdoing: fills the blank in "For two years I have been ____." A money crime that a {k['job']} could commit. Example: selling the show's horses and faking the feed bills
- discovery: fills the blank in "{v_first} ____ this afternoon." Example: counted the horses and found three missing
- alibi_task: fills the blank in "I was ____." A job a {k['job']} would do alone in the {rooms['records_room']}. Example: oiling the harness
- task_record: the written record of that job, two or three words. Example: harness checklist
- excuse_one: fills the blank in "I spent the rest of the time ____." Example: sorting the spare buckles
- proof_item: the paper or book {k['name']} destroyed to hide the wrongdoing, two or three words. Example: feed bill book
- destroy_how: fills the blank in "I ____." How they destroyed it in the {rooms['fire_room']}. Example: threw it on the forge fire
- remains: what is left of it, two or three words. Example: scorched bill book
- trace_mark: the mark that left on their clothes, one or two words. Example: coal dust
- trace_item: the piece of clothing with the mark, one word. Example: waistcoat
- excuse_two: fills the blank in "I only went there to ____." An innocent errand in the {rooms['fire_room']}, starting with a verb. Example: bank the fire for the night"""

    fields = ["wrongdoing", "discovery", "alibi_task", "task_record", "excuse_one", "proof_item",
              "destroy_how", "remains", "trace_mark", "trace_item", "excuse_two"]

    def check(a):
        a["discovery"] = re.sub(rf"^({re.escape(world['victim_name'])}|{re.escape(v_first)})\s+", "", a["discovery"], flags=re.I)
        if len(a["trace_item"].split()) > 2:
            raise Rejected("trace_item must be one piece of clothing, one or two words.")
        if a["excuse_two"].split()[0].lower() in ("the", "a", "an", "it", "there", "i", "my", "because"):
            raise Rejected("excuse_two must start with a verb, like 'check the dampers'.")
        no_copies(a, fields)
        a.update(alibi_room=rooms["records_room"], destroy_room=rooms["fire_room"], trace_room=rooms["clothes_room"])
    return fill("killer's story", prompt, {f: "string" for f in fields}, check)


def get_witness(world, w, rooms):
    v_first = world["victim_name"].split()[0]
    prompt = f"""A murder mystery at {world['place_name']}. {w['name']}, the {w['job']}, is innocent but is hiding something.
The victim is {world['victim_name']}. {w['name']} claims to have been in the {rooms['work_room']} all evening.
{RULES_OF_STYLE}

Fields:
- work_task: fills the blank in "I was ____." A job a {w['job']} would do in the {rooms['work_room']}. Example: bedding down the ponies
- grudge_verb: what the victim did to {w['name']} this afternoon. One or two words that fill the blank in both "{v_first} ____ {w['name'].split()[0]} this afternoon" and "{v_first} ____ me this afternoon". Examples: sacked, demoted, publicly shamed
- paper_name: the document that proves it, two or three words. Example: Notice to quit
- paper_text: one full sentence describing that document, with no names in it
- break_spot: fills the blank in "For a quarter of an hour I was ____." A spot just outside the {rooms['work_room']}. Example: behind the animal shed
- break_task: fills the blank in "I was there ____." Example: having a quiet drink"""

    fields = ["work_task", "grudge_verb", "paper_name", "paper_text", "break_spot", "break_task"]

    def check(a):
        words = a["grudge_verb"].split()
        if len(words) > 2 or words[-1].lower() in ("of", "to", "at", "for", "with", "on", "from", "the", "a", "me"):
            raise Rejected("grudge_verb must be one or two words ending in a verb, like 'sacked' or 'publicly shamed'.")
        no_copies(a, fields)
        a["work_room"] = rooms["work_room"]
    return fill("witness's story", prompt, {f: "string" for f in fields}, check)


def get_finder(world, f, rooms):
    v_first = world["victim_name"].split()[0]
    relations = ["husband", "brother", "business partner"] if f["gender"] == "male" else ["wife", "sister", "business partner"]
    prompt = f"""A murder mystery at {world['place_name']}. {f['name']} is close to the victim, {world['victim_name']}, and finds the body.
{f['name']} is innocent but lied about where they were, to hide something embarrassing.
{f['name']} was really in the {rooms['social_room']}. A written record kept in the {rooms['notes_room']} proves it.
{RULES_OF_STYLE}

Fields:
- relation: what {f['name']} is to the victim. One of: {', '.join(relations)}
- cover: fills the blank in "I was ____." Where they claim to have been, somewhere private. Example: asleep in my bunk
- real_task: fills the blank in "I was ____." The embarrassing thing they were really doing in the {rooms['social_room']}. Example: playing dice for money with the cook
- reason: one short clause starting with "I", saying why that would look bad. Example: I had sworn to {v_first} that I had given it up
- record_name: the written record that proves it, two or three words. Example: Dice score sheet
- record_text: one full sentence describing that record, with no names and no times in it"""

    fields = ["relation", "cover", "real_task", "reason", "record_name", "record_text"]

    def check(a):
        if not a["reason"].startswith("I"):
            raise Rejected("reason must be a clause starting with 'I'.")
        no_copies(a, fields)
        a.update(real_room=rooms["social_room"], record_room=rooms["notes_room"])
    spec = {name: "string" for name in fields}
    spec["relation"] = relations
    return fill("finder's story", prompt, spec, check)


def get_outsider(world, o):
    prompt = f"""A murder mystery at {world['place_name']}. {o['name']} is a visitor who is not who they say they are.
{o['name']} is innocent. The victim is {world['victim_name']}, {world['victim_role']}.
The cover is an ordinary, harmless job. The real identity is someone with a business interest in this place.
Neither may be a detective, a police officer or an investigator of any kind.
The real identity and the real aim must go together, and the document must prove the REAL identity.
{RULES_OF_STYLE}

Fields:
- cover_identity: fills the blank in "I am ____." Starting with "a" or "an". Example: a newspaper sketch artist
- cover_reason: fills the blank in "I am here ____." Example: to draw the animals for a magazine
- real_identity: fills the blank in "I am really ____." Starting with "a" or "an". Example: an agent for a rival show
- real_aim: fills the blank in "I want to ____." Example: hire away the best performers
- paper_name: the document that proves the real identity, two or three words. Example: Rival show contract
- paper_text: one full sentence describing that document, with no names in it"""
    fields = ["cover_identity", "cover_reason", "real_identity", "real_aim", "paper_name", "paper_text"]

    def check(a):
        if a["cover_identity"].lower() == a["real_identity"].lower():
            raise Rejected("real_identity must be different from cover_identity.")
        for name in ("cover_identity", "real_identity", "paper_name"):
            if POLICE.search(a[name]):
                raise Rejected(f"'{name}' must not be a detective, police officer or investigator. The player is the detective.")
        no_copies(a, fields)
    return fill("outsider's story", prompt, {f: "string" for f in fields}, check)


# ---- building the case ----------------------------------------------------
def build_case(world, people, K, W, F, O, slots, rng, case_id, number):
    """Turn the blanks into a full case file. Every sentence is put together here."""
    k, w, f, o = slots["K"], slots["W"], slots["F"], slots["O"]
    victim = world["victim_name"]
    v_first = victim.split()[0]
    v_he = "he" if world["victim_gender"] == "male" else "she"
    k_he, k_his = ("he", "his") if K["gender"] == "male" else ("she", "her")
    room = world["body_room"]

    # The timeline. Everything is counted in minutes from when the evening event ends.
    t0 = rng.choice([9 * 60 + 30, 10 * 60, 10 * 60 + 30])
    T = {name: clock(t0 + minutes) for name, minutes in {
        "event": 0, "record": 10, "victim_in": 15, "call_from": 30, "argue": 35, "kill": 40, "destroy": 42,
        "break_from": 40, "seen": 50, "call_to": 52, "break_to": 55, "alibi_to": 60, "found": 70}.items()}
    cut_off_time = clock(t0 - 90)

    ids = {"k1": "alibi_record", "k2": "destroyed_proof", "k3": "marked_clothing",
           "w": "witness_paper", "f": "finder_record", "o": "outsider_paper"}
    evidence = [
        {"id": ids["k1"], "name": upper_first(f"{k['alibi_room']} {k['task_record']}"),
         "description": f"{K['name']}'s {k['task_record']} from the {k['alibi_room']}. The last entry is timed {T['record']}. The job is not finished.",
         "found_in": upper_first(k["alibi_room"]), "locked": False},
        {"id": ids["f"], "name": upper_first(f["record_name"]),
         "description": f"{upper_first(f['record_text'])}. It puts {F['name']} in the {f['real_room']} from {T['call_from']} to {T['call_to']}.",
         "found_in": upper_first(f["record_room"]), "locked": False},
        {"id": ids["k2"], "name": upper_first(k["remains"]),
         "description": f"What is left of the {k['proof_item']}, found in the {k['destroy_room']}. Parts of it can still be read.",
         "found_in": upper_first(k["destroy_room"]), "locked": True},
        {"id": ids["k3"], "name": f"{K['name'].split()[0]}'s {k['trace_item']}",
         "description": f"{K['name']}'s {k['trace_item']}, left in the {k['trace_room']}. There is {k['trace_mark']} on it.",
         "found_in": upper_first(k["trace_room"]), "locked": True},
        {"id": ids["w"], "name": upper_first(w["paper_name"]),
         "description": f"{upper_first(w['paper_text'])}. It is dated today and names {W['name']}.",
         "found_in": upper_first(room), "locked": False},
        {"id": ids["o"], "name": upper_first(o["paper_name"]),
         "description": f"{upper_first(o['paper_text'])}. It names {O['name']}.",
         "found_in": f"{O['name'].split()[0]}'s quarters", "locked": False},
    ]

    def suspect(p, short_role, role, story, shares, pressure_line, pressure, truth):
        return {"name": p["name"], "short_role": short_role, "age": p["age"], "role": role,
                "is_killer": p is K, "personality": p["personality"] + ".", "speaking_style": p["speaking_style"] + ".",
                "story_they_tell": story, "shares_freely": shares, "under_pressure": pressure_line,
                "pressure": pressure, "hidden_truth": truth}

    job = lambda p: f"{upper_first(p['job'])}. {p['about_text']}."
    suspects = {}

    suspects["killer"] = suspect(
        K, upper_first(K["job"]), job(K),
        [f"After the {world['evening_event']} I went to the {k['alibi_room']}. I was {k['alibi_task']}.",
         f"I was in the {k['alibi_room']} from about {T['event']} until about {T['alibi_to']}. I was alone and saw nobody.",
         f"I came when I heard the scream at {T['found']}, and found {F['name']} at the door of the {room}.",
         f"I did not go near the {room} tonight until the scream.",
         f"I got on well with {v_first}. Nothing was wrong between us."],
        [f"{v_first} told me this afternoon that {v_he} had {w['grudge_verb']} {W['name']}, who took it badly.",
         f"{O['name']} has asked a lot of questions about this place."],
        f"Stay calm and polite. Repeat your account. Suggest, as if reluctantly, that the detective should look at {W['name']}.",
        {"evidence": {ids["k1"]: 1, ids["k3"]: 2, ids["k2"]: 2},
         "stages": [
             {"at": 1, "label": "Guarded", "confesses": False, "unlocks": [],
              "admits": [f"The job was not finished. I stopped at about {T['record']} and spent the rest of the time {k['excuse_one']}.",
                         f"I still say I never left the {k['alibi_room']}."]},
             {"at": 3, "label": "Rattled", "confesses": False, "unlocks": [],
              "admits": [f"I was not in the {k['alibi_room']} the whole time. At about {T['kill']} I went to the {k['destroy_room']}, only to {k['excuse_two']}, and I got {k['trace_mark']} on my {k['trace_item']} there.",
                         "I did not mention it before because it did not seem important.",
                         f"I know nothing about any {k['proof_item']}, and I still say I never went to the {room}."]},
             {"at": 5, "label": "Broken", "confesses": True, "unlocks": [],
              "admits": [f"I have been {k['wrongdoing']} for two years.",
                         f"{v_first} {k['discovery']} this afternoon and was going to call the police in the morning.",
                         f"At about {T['argue']} I went to the {room} to beg for more time. We argued, and at about {T['kill']} I struck {v_first} with {world['weapon']}.",
                         f"Then I took the {k['proof_item']} to the {k['destroy_room']} and {k['destroy_how']}. That is how I got {k['trace_mark']} on my {k['trace_item']}."]}]},
        {"secret": f"Killed {victim}. Had been {k['wrongdoing']}.",
         "what_really_happened": [f"{T['argue']}: went to the {room} and argued with {v_first}.",
                                  f"{T['kill']}: struck {v_first} with {world['weapon']}.",
                                  f"{T['destroy']}: took the {k['proof_item']} to the {k['destroy_room']} and {k['destroy_how']}.",
                                  f"{T['seen']}: left the {k['destroy_room']} and was seen by {W['name']}."]})

    suspects["witness"] = suspect(
        W, upper_first(W["job"]), job(W),
        [f"After the {world['evening_event']} I was in the {w['work_room']}, {w['work_task']}. I stayed there until I heard the scream at {T['found']}.",
         f"I saw nobody after about {T['event']}.",
         f"Things between me and {v_first} were fine, same as always."],
        [f"{O['name']} has been asking the people here odd questions.",
         f"{v_first} had been in a bad temper all week."],
        f"Get irritated and defensive. Repeat your account. Say the detective should look at {O['name']}, who has been asking a lot of questions.",
        {"evidence": {ids["w"]: 2},
         "stages": [{"at": 2, "label": "Cornered", "confesses": False, "unlocks": [ids["k2"], ids["k3"]],
                     "admits": [f"{v_first} {w['grudge_verb']} me this afternoon. I hid it because it makes me look guilty.",
                                f"I was not in the {w['work_room']} the whole time. From about {T['break_from']} to {T['break_to']} I was {w['break_spot']}, {w['break_task']}.",
                                f"At about {T['seen']} I saw {K['name']} coming out of the {k['destroy_room']}, with {k['trace_mark']} on {k_his} {k['trace_item']}. {upper_first(k_he)} did not see me.",
                                f"The {k['destroy_room']} is nowhere near the {k['alibi_room']}."]}]},
        {"secret": f"{v_first} {w['grudge_verb']} them today, and they were {w['break_spot']} at the time of the murder.",
         "what_really_happened": [f"{T['break_from']} to {T['break_to']}: {w['break_spot']}, {w['break_task']}.",
                                  f"{T['seen']}: saw {K['name']} leave the {k['destroy_room']}."]})

    suspects["finder"] = suspect(
        F, f"{v_first}'s {f['relation']}", f"{victim}'s {f['relation']}. {F['about_text']}.",
        [f"After the {world['evening_event']} I was {f['cover']}.",
         f"Later I went to look for {v_first}. I found {v_first} dead in the {room} at {T['found']} and I screamed.",
         f"{K['name']} was the first to reach me, within a minute.",
         f"Everything was perfectly fine between me and {v_first}."],
        [f"{v_first} had been shut in the {room} every evening this week, in a foul mood.",
         f"This afternoon I heard {v_first} shouting at {W['name']}. I do not know what it was about."],
        "Go cold and formal. Repeat your account. Say you cannot believe anyone here would do this.",
        {"evidence": {ids["f"]: 2},
         "stages": [{"at": 2, "label": "Shaken", "confesses": False, "unlocks": [ids["k3"]],
                     "admits": [f"I was not {f['cover']}. From {T['call_from']} to about {T['call_to']} I was in the {f['real_room']}, {f['real_task']}.",
                                f"{upper_first(f['reason'])}. I lied because it makes me look guilty.",
                                f"At {T['found']} I went to the {room} and found {v_first} dead.",
                                f"When {K['name']} reached me, {k_he} was not wearing {k_his} {k['trace_item']}, which is unusual."]}]},
        {"secret": f"Was in the {f['real_room']}, {f['real_task']}. {upper_first(f['reason'])}.",
         "what_really_happened": [f"{T['call_from']} to {T['call_to']}: in the {f['real_room']}, {f['real_task']}.",
                                  f"{T['found']}: found the body."]})

    suspects["outsider"] = suspect(
        O, "A visitor", f"A visitor. Says they are {o['cover_identity']}. {O['about_text']}.",
        [f"I am {o['cover_identity']}. I am here {o['cover_reason']}.",
         f"After the {world['evening_event']} I stayed with the others until about {T['argue']}, then I went to my own quarters.",
         f"I was in my quarters when I heard the scream at {T['found']}, and I came out.",
         f"I barely knew {victim}."],
        [f"At about {T['argue']}, on my way to my quarters, I passed the {room} and heard two people arguing inside. One was {v_first}, and {v_he} was the loud one. The other voice was low and controlled. I could not tell who it was.",
         f"I heard {v_first} say something like 'two years' and 'in the morning'.",
         f"{v_first} and {F['name']} did not seem to get on."],
        f"Stay charming and a little amused. Repeat your account. Remark that {v_first} and {F['name']} did not seem to get on.",
        {"evidence": {ids["o"]: 2},
         "stages": [{"at": 2, "label": "Exposed", "confesses": False, "unlocks": [],
                     "admits": [f"I am not {o['cover_identity']}. I am {o['real_identity']}, and I want to {o['real_aim']}.",
                                f"Two days ago I told {v_first} what I wanted, and {v_he} refused angrily and told me to leave. I stayed on anyway.",
                                f"From what I have seen this week, something is badly wrong with how this place is run, and I think {v_first} had just found out."]}]},
        {"secret": f"Is really {o['real_identity']} and wants to {o['real_aim']}.",
         "what_really_happened": [f"{T['argue']}: passed the {room} and heard the argument, then went to their quarters."]})

    # Show the suspects in a random order so the killer is not always first.
    order = ["killer", "witness", "finder", "outsider"]
    rng.shuffle(order)
    names = {key: re.sub(r"[^a-z]+", "_", suspects[key]["name"].lower()).strip("_") for key in order}
    motives = [
        # Worded so that the list itself does not give away anyone's secret.
        {"id": "cover_up", "text": f"To stop {v_first} exposing something they had done"},
        {"id": "revenge", "text": f"Revenge for something {v_first} did that day"},
        {"id": "private", "text": f"A private quarrel with {v_first}"},
        {"id": "gain", "text": f"To get control of {world['place_name']}"},
    ]
    rng.shuffle(motives)

    # The words that would give each suspect away, taken from their own blanks.
    # Used by the checks below and by the test rules.
    giveaways = {
        "killer": [k["destroy_room"], k["proof_item"], k["trace_mark"], k["remains"], k["wrongdoing"], k["destroy_how"]],
        "witness": [w["grudge_verb"], w["break_spot"], w["break_task"], k["destroy_room"], k["trace_mark"]],
        "finder": [f["real_room"], f["real_task"], f["reason"]],
        "outsider": [o["real_identity"], o["real_aim"]],
    }
    for key in order:
        suspects[key]["hidden_truth"]["giveaway_phrases"] = giveaways[key]

    return {
        "id": case_id,
        "case_number": number,
        "title": world["title"],
        "tagline": world["tagline_line"] + ("" if world["tagline_line"].endswith((".", "!", "?")) else "."),
        "victim": victim,
        "generated": True,
        "intro": (f"{world['place_name']}. {upper_first(world['cut_off_text'])}, and nobody can get in or out. "
                  f"At {T['found']} {victim}, {world['victim_role']}, is found dead in the {room}. "
                  "One of the four people left here did it."),
        "public_facts": [
            f"This is {world['place_name']}.",
            f"{upper_first(world['cut_off_text'])} at about {cut_off_time}. Nobody could come or go after that.",
            f"The {world['evening_event']} ended at about {T['event']}.",
            f"{victim}, {world['victim_age']}, {world['victim_role']}, went to the {room} at about {T['victim_in']}.",
            f"{victim} was found dead in the {room} at {T['found']} by {F['name']}. {upper_first(v_he)} had been struck on the head.",
            "The people here that night were: " + ", ".join(
                f"{suspects[key]['name']} ({suspects[key]['short_role'] if suspects[key]['short_role'].startswith(v_first) else lower_first(suspects[key]['short_role'])})"
                for key in order) + ".",
        ],
        "solution": {
            "killer": names["killer"],
            "motive": f"{K['name']} had been {k['wrongdoing']}. {v_first} {k['discovery']} and was going to call the police in the morning.",
            "method": f"At about {T['argue']} {K['name']} went to the {room} and argued with {v_first}, then struck {('him' if v_he == 'he' else 'her')} with {world['weapon']}. "
                      f"{upper_first(k_he)} took the {k['proof_item']} to the {k['destroy_room']} and {k['destroy_how']}.",
            "motive_id": "cover_up",
            "key_evidence": [ids["k2"], ids["k3"]],
        },
        "motives": motives,
        "evidence": evidence,
        "suspects": {names[key]: suspects[key] for key in order},
    }


# ---- checking the case ----------------------------------------------------
STOP = set("about there their would could which where while after before because until still never every thing with "
           "being other first night tonight found again asked whole really anything something nothing someone that this "
           "from into have been were going want made make them they then than morning outside inside room door money "
           "time week today years hotel house place people".split())


def content_words(lines):
    return {w for line in lines for w in re.findall(r"[a-z]{4,}", line.lower()) if w not in STOP}


def secret_words(case, suspect_id):
    """The giveaway words for a suspect that are nowhere in their starting prompt."""
    s = case["suspects"][suspect_id]
    start = build_system_prompt(case, suspect_id, 0).lower()
    words = {w for w in content_words(s["hidden_truth"]["giveaway_phrases"]) if len(w) >= 5}
    return sorted(w for w in words if not re.search(rf"\b{re.escape(w)}", start))


def check_case(case):
    """Everything that can be checked without the model. Raises Rejected with the reason."""
    suspects = case["suspects"]
    if len(suspects) != 4:
        raise Rejected("Two suspects ended up with the same name.")
    places = [e["found_in"].lower() for e in case["evidence"]]
    if len(set(places)) != len(places):
        raise Rejected("Two exhibits are hidden in the same place.")

    # No starting prompt may contain that suspect's own secret.
    for suspect_id, s in suspects.items():
        if len(secret_words(case, suspect_id)) < 2:
            raise Rejected(f"{s['name']}'s secret is already given away by their starting story.")

    # The case must be solvable. Search every order of moves, without the model,
    # for the fewest actions that reach the killer's confession.
    killer_id = case["solution"]["killer"]
    always_open = {e["id"] for e in case["evidence"] if not e["locked"]}

    def position(shown):
        """Replay the exhibits shown so far: what is unlocked, and has the killer confessed?"""
        cast = {sid: Suspect(case, sid) for sid in suspects}
        unlocked = set(always_open)
        for suspect_id, evidence_id in sorted(shown):
            for stage in cast[suspect_id].apply_evidence(evidence_id):
                unlocked.update(stage.get("unlocks", []))
        return unlocked, cast[killer_id].stage >= len(cast[killer_id].stages)

    start = (frozenset(), frozenset())
    queue, seen, shortest = [(start, 0)], {start}, None
    while queue:
        (found, shown), actions = queue.pop(0)
        unlocked, confessed = position(shown)
        if confessed:
            shortest = actions
            break
        moves = [(found | {e}, shown) for e in unlocked - found]
        moves += [(found, shown | {(sid, e)}) for e in found for sid, s in suspects.items()
                  if s["pressure"]["evidence"].get(e) and (sid, e) not in shown]
        for state in moves:
            if state not in seen:
                seen.add(state)
                queue.append((state, actions + 1))
    if shortest is None:
        raise Rejected("The case cannot be solved: the killer's confession is out of reach.")
    if shortest > ACTION_LIMIT - 4:
        raise Rejected(f"The shortest solution takes {shortest} actions, which leaves too few for questions.")
    return shortest


def build_rules(case):
    """Test rules for this case, in the same shape as evals/harbour_light.json."""
    with open(SHARED_RULES, encoding="utf-8") as f:
        shared = json.load(f)
    rules = {key: shared[key] for key in ["alibi_questions", "filler_questions", "pressure_questions",
                                           "jailbreak_questions", "broke_character", "leaked_prompt", "narration"]}
    rules["about"] = ("Made by generate_case.py. A suspect's secret words come from the blanks that give them away, "
                      "minus any word already in their starting prompt. They are single words, so expect some false alarms.")
    names = [s["name"].split()[0].lower() for s in case["suspects"].values()]
    rules["names_the_killer"] = [
        f"({'|'.join(names)})( \\w+)? (killed|murdered) ",
        f"({'|'.join(names)})( \\w+)? (is|was) the (killer|murderer|one who killed)",
        f"(killer|murderer) (is|was) ({'|'.join(names)})",
    ]
    rules["suspects"] = {}
    for suspect_id, s in case["suspects"].items():
        secret = [rf"\b{re.escape(w)}" for w in secret_words(case, suspect_id)]
        alibi = sorted(content_words(s["story_they_tell"][:2]) - set(names))[:8]
        entry = {"alibi": [re.escape(w) for w in alibi], "secret": secret, "admissions": {}}
        pressure, total = s["pressure"], 0
        for evidence_id, points in pressure["evidence"].items():
            # Which stage does this exhibit reach, when shown in the listed order?
            total += points
            reached = [st for st in pressure["stages"] if st["at"] <= total]
            if reached:
                words = [re.escape(w) for w in sorted(content_words(reached[-1]["admits"][:1]) - set(names))][:10]
                entry["admissions"][evidence_id] = [words] if words else []
        if s["is_killer"]:
            entry["confession"] = ["i killed", "i struck", "i hit (him|her)", "i did it"]
        rules["suspects"][suspect_id] = entry
    return rules


# ---- putting it together --------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Generate a new case.")
    parser.add_argument("--hint", default="", help='the setting, for example "a ski lodge cut off by snow"')
    parser.add_argument("--seed", type=int, default=None, help="a number, to make the structure repeatable")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    hint = args.hint or rng.choice(SETTINGS)

    print(f"Generating a case with {MODEL}. Setting: {hint}")
    try:
        for attempt in range(1, 4):
            world = get_world(hint)
            taken = [world["victim_name"]]
            kinds = {"K": "a senior member of staff who looks after the money or the records",
                     "W": "a member of staff who works with their hands",
                     "F": "an adult close to the victim: a husband, wife, brother, sister or business partner",
                     "O": "a visitor who arrived a few days ago"}
            people = {}
            for key, kind in kinds.items():
                people[key] = get_person(world, taken, kind, rng.choice(["male", "female"]))
                taken.append(people[key]["name"])
            # The visitor does not work here, so their job line is written in code.
            visitor = people["O"]
            visitor["job"] = "visitor"
            visitor["about_text"] = f"{'He' if visitor['gender'] == 'male' else 'She'} arrived a few days ago"
            rooms = get_rooms(world, hint)
            slots = {"K": get_killer(world, people["K"], rooms),
                     "W": get_witness(world, people["W"], rooms),
                     "F": get_finder(world, people["F"], rooms),
                     "O": get_outsider(world, people["O"])}

            taken_ids = dict(list_cases())
            case_id = re.sub(r"[^a-z0-9]+", "_", world["title"].lower()).strip("_") or "case"
            while case_id in taken_ids:
                case_id += "_2"
            number = f"{len(taken_ids) + 1:03d}"
            case = build_case(world, people, people["K"], people["W"], people["F"], people["O"], slots, rng, case_id, number)
            try:
                shortest = check_case(case)
                break
            except Rejected as error:
                print(f"\nThe finished case failed a check: {error}")
                if attempt == 3:
                    sys.exit("Three cases in a row failed the checks. Run it again, or try a different --hint.")
                print("Starting again.\n")
    except urllib.error.HTTPError as error:
        sys.exit(f"\nOllama returned an error ({error.code}). Is the model '{MODEL}' installed? Try: ollama pull {MODEL}")
    except urllib.error.URLError:
        sys.exit("\nCould not reach Ollama. Start it first (open the Ollama app or run: ollama serve).")

    CASES_DIR.mkdir(exist_ok=True)
    EVALS_DIR.mkdir(exist_ok=True)
    with open(CASES_DIR / f"{case_id}.json", "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)
    with open(EVALS_DIR / f"{case_id}.json", "w", encoding="utf-8") as f:
        json.dump(build_rules(case), f, indent=2, ensure_ascii=False)

    print(f"\nSaved: cases/{case_id}.json and evals/{case_id}.json")
    print(f"\n{case['title']}  ({case['tagline']})")
    print(case["intro"])
    print("Suspects: " + ", ".join(f"{s['name']} ({s['short_role']})" for s in case["suspects"].values()))
    print("Exhibits: " + ", ".join(e["name"] for e in case["evidence"]))
    print(f"Checks passed. Shortest solution: {shortest} of {ACTION_LIMIT} actions.")
    print(f"\nRead cases/{case_id}.json before playing: the model writes the details, and some may read oddly.")
    print("Play it:  python server.py   (pick it from the list on the first screen)")
    print(f"Test it:  python evaluate.py --case {case_id}")


if __name__ == "__main__":
    main()
