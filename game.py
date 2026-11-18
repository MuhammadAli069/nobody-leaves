"""
The terminal version of the game.

    python game.py

Question the suspects, search the hotel for evidence, and put that evidence
in front of a suspect to break their story. Everything you do costs one
action. You get one accusation.

Commands (type them instead of a question):
    /talk 2      switch to suspect number 2 (or /talk thomas)
    /who         list the suspects and how much pressure they are under
    /search      list the places you can search
    /search 1    search place number 1 (costs one action)
    /evidence    list the evidence you have found
    /show 2      put evidence number 2 in front of the current suspect
    /said        show everything the current suspect has told you
    /accuse 3    accuse suspect number 3 and end the game
    /help        show this list
    /quit        stop (the transcript is saved either way)
"""

import sys
import urllib.error

from engine import ACTION_LIMIT, REPLACE_MARK, Game, GameError, case_path, list_cases
from interrogate import MODEL


def pick(items, text, name_of):
    """Find an item from '2' or part of its name."""
    text = text.strip().lower()
    if text.isdigit() and 1 <= int(text) <= len(items):
        return items[int(text) - 1]
    matches = [item for item in items if text and text in name_of(item).lower()]
    return matches[0] if len(matches) == 1 else None


def meter(s):
    return "[" + "#" * min(s.pressure, s.max_pressure) + "." * (s.max_pressure - min(s.pressure, s.max_pressure)) + "] " + s.mood


def show_suspects(suspects, current):
    print()
    for number, s in enumerate(suspects, start=1):
        print(f" {'>' if s is current else ' '} {number}. {s.name:<18} {meter(s)}")
    print()


def show_places(game):
    print()
    for number, e in enumerate(game.evidence, start=1):
        if e["id"] in game.found:
            status = "searched"
        elif e["id"] in game.unlocked:
            status = "not searched"
        else:
            status = "no reason to search here yet"
        place = e["found_in"] if e["id"] in game.unlocked else "???"
        print(f"   {number}. {place:<16} ({status})")
    print()


def stream_reply(name, pieces):
    """Print a suspect's reply as it arrives. Returns False if the model failed."""
    print(f"\n{name}: ", end="", flush=True)
    try:
        for piece in pieces:
            if piece.startswith(REPLACE_MARK):      # the reply was replaced; start the line again
                piece = f"\n{name}: " + piece[len(REPLACE_MARK):]
            print(piece, end="", flush=True)
    except urllib.error.HTTPError as error:
        print(f"\nOllama returned an error ({error.code}). Is the model '{MODEL}' installed? Try: ollama pull {MODEL}\n")
        return False
    except urllib.error.URLError:
        print("\nCould not reach Ollama. Start it first (open the Ollama app or run: ollama serve).\n")
        return False
    print("\n")
    return True


def main():
    # python game.py            plays the first case
    # python game.py <case id>  plays that one (ids are listed if it is not found)
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    if wanted and wanted not in dict(list_cases()):
        print("No such case. Cases: " + ", ".join(case_id for case_id, _ in list_cases()))
        return
    game = Game(case_path(wanted))
    victim = game.case.get("victim", "the victim")
    suspects = list(game.suspects.values())
    current = suspects[0]

    print(f"\n=== {game.case['title']} ===\n")
    print(game.case["intro"])
    print(f"\nYou have {ACTION_LIMIT} actions. Questions, searches and showing evidence each cost one.")
    print("Type /help for commands.")
    show_suspects(suspects, current)
    print(f"You are questioning {current.name}.\n")

    while not game.result:
        try:
            text = input(f"[{game.actions_left} left] Detective: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        try:
            if not text.startswith("/"):
                game.check_question(current.id, text)
                stream_reply(current.name, game.question(current.id, text))
                continue

            command, _, argument = text[1:].partition(" ")
            command = command.lower()

            if command in ("quit", "exit"):
                break
            elif command == "help":
                print(__doc__)
            elif command == "who":
                show_suspects(suspects, current)
            elif command == "talk":
                chosen = pick(suspects, argument, lambda s: s.name)
                if chosen:
                    current = chosen
                    print(f"\nYou are now questioning {current.name}. {meter(current)}\n")
                else:
                    print("\nUse a number or a name, for example: /talk 2\n")
            elif command == "said":
                if not current.turns:
                    print(f"\n{current.name} has not told you anything yet.\n")
                else:
                    print()
                    for t in current.turns:
                        you = t["said"] if t["kind"] == "question" else "(showed evidence)"
                        print(f"  You: {you}\n  {current.name}: {t['answer']}\n")
            elif command == "evidence":
                have = [e for e in game.evidence if e["id"] in game.found]
                if not have:
                    print("\nYou have not found any evidence yet. Try /search.\n")
                else:
                    print()
                    for number, e in enumerate(have, start=1):
                        print(f"   {number}. {e['name']}: {e['description']}")
                    print()
            elif command == "search":
                if not argument.strip():
                    show_places(game)
                    continue
                place = pick(game.evidence, argument, lambda e: e["found_in"])
                if not place:
                    print("\nType /search to see the places, then for example: /search 1\n")
                    continue
                e = game.search(place["id"])
                print(f"\nYou search: {e['found_in']}. You find: {e['name']}\n  {e['description']}\n")
            elif command == "show":
                have = [e for e in game.evidence if e["id"] in game.found]
                item = pick(have, argument, lambda e: e["name"])
                if not item:
                    print("\nShow which evidence? Type /evidence to see the numbers, then for example: /show 1\n")
                    continue
                game.check_show(current.id, item["id"])
                seen = len(game.events)
                print(f"\nYou show {current.name}: {item['name']}")
                if stream_reply(current.name, game.show(current.id, item["id"])):
                    print(f"  Pressure on {current.name}: {meter(current)}")
                    for line in game.events[seen:]:
                        print(f"  {line}")
                    print()
            elif command == "accuse":
                chosen = pick(suspects, argument, lambda s: s.name)
                if not chosen:
                    print("\nUse a number or a name, for example: /accuse 2\n")
                    continue
                sure = input(f"Accuse {chosen.name}? You only get one. (yes/no): ").strip().lower()
                if sure not in ("y", "yes"):
                    print()
                    continue
                # The terminal version only asks for the name, so judge it on that.
                result = game.accuse(chosen.id)
                if result["right_killer"]:
                    print(f"\nCorrect. {result['killer']} killed {victim}.")
                else:
                    print(f"\nWrong. It was {result['killer']}. {chosen.name} is innocent.")
                print(f"\nMotive: {result['motive']}\nHow: {result['method']}\n")
            else:
                print("\nUnknown command. Type /help.\n")
        except GameError as error:
            print(f"\n{error}\n")

    if not game.result:
        path = game.save_transcript()
        if path:
            print(f"Transcript saved to {path}")
    else:
        print("Transcript saved in the transcripts folder.")


if __name__ == "__main__":
    main()
