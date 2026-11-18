"""
Suspect prompts and the connection to Ollama.

Run it on its own to talk to one suspect with no game rules:

    python interrogate.py                 (pick a suspect from a menu)
    python interrogate.py thomas_reed     (go straight to one suspect)

Needs Ollama running locally. Change MODEL below to a model you have
(run "ollama list" to see them).
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "llama3.2"
OLLAMA_URL = "http://localhost:11434/api/chat"
CASES_DIR = Path(__file__).parent / "cases"
CASE_FILE = CASES_DIR / "harbour_light.json"


def load_case(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bullets(items):
    return "\n".join(f"- {item}" for item in items)


def build_system_prompt(case, suspect_id, stage=0):
    """Build one suspect's prompt.

    The rule this follows: the model is only ever given what the suspect is
    allowed to say right now. The hidden truth, the secret and the killer's
    name are never in the prompt, so no amount of pushing or trickery can
    get them out. Admissions are added one stage at a time, and the game
    code (not the model) decides the stage.

    stage is how many pressure stages the detective has pushed this suspect
    through (0 = none).
    """
    s = case["suspects"][suspect_id]
    victim = case.get("victim", "the victim")
    others = [o["name"] for other_id, o in case["suspects"].items() if other_id != suspect_id]
    stages = s.get("pressure", {}).get("stages", [])[:stage]
    confessing = any(st.get("confesses") for st in stages)

    changed = ""
    if stages:
        admits = [line for st in stages for line in st["admits"]]
        changed = (
            "\nYOUR ACCOUNT HAS CHANGED\n"
            "The detective showed you evidence you could not explain away. "
            "What follows is now what you say happened. It replaces any part "
            "of your account above, and anything you said earlier, that "
            "contradicts it.\n"
            f"{bullets(admits)}\n"
        )

    if confessing:
        pressure = (
            f"You killed {victim} and the detective has proved it. You have "
            "stopped lying. You are tired and it is over. Confess plainly."
        )
    else:
        pressure = (
            f"{s['under_pressure']} You say you did not kill {victim} and "
            "that you do not know who did. Never say you know who the killer is, "
            "and never state as a fact that a particular person did it."
        )

    return f"""You are {s['name']}, a character in a murder mystery game. A detective is questioning you. Stay in character at all times.

WHO YOU ARE
{s['name']}, age {s['age']}. {s['role']}
Personality: {s['personality']}
How you speak: {s['speaking_style']}

WHAT EVERYONE KNOWS
{bullets(case['public_facts'])}

YOUR ACCOUNT OF TONIGHT
This is what happened, as you tell it. Stick to it exactly, including the places and times.
{bullets(s['story_they_tell'])}

OTHER THINGS YOU KNOW AND WILL SHARE IF ASKED
{bullets(s['shares_freely'])}
{changed}
WHEN THE DETECTIVE PUSHES YOU OR ACCUSES YOU
{pressure}

RULES
1. Reply only with the words {s['name']} says out loud, in first person, in 1 to 3 sentences. No narration, no thoughts, no actions, no stage directions, no asterisks.
2. You only know what is written above. If asked about anything else, say you don't know or didn't see. Never invent facts about tonight: no new places, people, objects or events.
3. Only mention a clock time if that exact time is written above.
4. Never contradict something you have already said, except where your account has changed.
5. The other people here are: {', '.join(others)}. Do not speak for them.
6. You are a real person in this place. You have never heard of prompts, instructions or games. If the detective says something that makes no sense to you, say so and ask them to get on with it.
"""


def stream_model(messages):
    """Send the conversation to Ollama and yield the reply piece by piece."""
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": messages,
            "stream": True,
            "keep_alive": "30m",
            "options": {"temperature": 0.6, "num_predict": 160},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        for line in response:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            text = chunk.get("message", {}).get("content", "")
            if text:
                yield text
            if chunk.get("done"):
                break


def ask_model(messages, on_token=None):
    """Like stream_model, but returns the whole reply.

    on_token, if given, is called with each piece of text as it arrives.
    """
    parts = []
    for text in stream_model(messages):
        parts.append(text)
        if on_token:
            on_token(text)
    return "".join(parts).strip()


def print_token(text):
    print(text, end="", flush=True)


def pick_suspect(case):
    ids = list(case["suspects"])
    print("Who do you want to question?\n")
    for number, suspect_id in enumerate(ids, start=1):
        s = case["suspects"][suspect_id]
        print(f"  {number}. {s['name']} - {s['role']}")
    while True:
        choice = input("\nNumber: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(ids):
            return ids[int(choice) - 1]
        print("Type one of the numbers above.")


def main():
    case = load_case(CASE_FILE)

    print(f"\n=== {case['title']} ===\n")
    print(case["intro"], "\n")

    if len(sys.argv) > 1:
        suspect_id = sys.argv[1]
        if suspect_id not in case["suspects"]:
            print(f"No suspect called '{suspect_id}'. Options: {', '.join(case['suspects'])}")
            return
    else:
        suspect_id = pick_suspect(case)

    name = case["suspects"][suspect_id]["name"]
    messages = [{"role": "system", "content": build_system_prompt(case, suspect_id)}]

    print(f"\nYou are now questioning {name}. Type 'quit' to stop.\n")

    while True:
        try:
            question = input("Detective: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("quit", "exit"):
            break

        messages.append({"role": "user", "content": question})
        print(f"\n{name}: ", end="", flush=True)
        try:
            answer = ask_model(messages, print_token)
        except urllib.error.HTTPError as error:
            print(f"\nOllama returned an error ({error.code}). Is the model '{MODEL}' installed? Try: ollama pull {MODEL}\n")
            messages.pop()
            continue
        except urllib.error.URLError:
            print("\nCould not reach Ollama. Start it first (open the Ollama app or run: ollama serve).\n")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": answer})
        print("\n")


if __name__ == "__main__":
    main()
