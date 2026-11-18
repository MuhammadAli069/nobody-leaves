"""
The web version of the game.

    pip install flask
    python server.py

Then open http://127.0.0.1:5000 in your browser.

This file is only the bridge between the browser and engine.py. All the
rules live in engine.py.
"""

import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from engine import Game, GameError, case_cards, case_path
from interrogate import MODEL, OLLAMA_URL

WEB_DIR = Path(__file__).parent / "web"
ERROR_MARK = "[[ERROR]]"

app = Flask(__name__, static_folder=None)
GAMES = {}   # game id -> Game. Kept in memory, so restarting the server clears them.


def get_game():
    data = request.get_json(silent=True) or {}
    game = GAMES.get(data.get("game") or request.args.get("game"))
    if not game:
        raise GameError("That game no longer exists. Start a new one.")
    return game, data


@app.errorhandler(GameError)
def game_error(error):
    return jsonify({"error": str(error)}), 400


def stream(pieces):
    """Send a suspect's reply to the browser as it is generated."""
    def generate():
        try:
            for piece in pieces:
                yield piece
        except urllib.error.HTTPError as error:
            yield f"{ERROR_MARK}Ollama returned an error ({error.code}). Is the model '{MODEL}' installed? Try: ollama pull {MODEL}"
        except (urllib.error.URLError, OSError):
            yield f"{ERROR_MARK}Could not reach Ollama. Start it, then try again."
    return Response(generate(), mimetype="text/plain; charset=utf-8",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- pages --------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:name>")
def static_file(name):
    return send_from_directory(WEB_DIR, name)


# ---- api ----------------------------------------------------------------
@app.get("/api/health")
def health():
    """Tell the browser whether Ollama is running and the model is there."""
    try:
        tags_url = OLLAMA_URL.replace("/api/chat", "/api/tags")
        with urllib.request.urlopen(tags_url, timeout=3) as response:
            names = [m.get("name", "") for m in json.loads(response.read()).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return jsonify({"ollama": False, "model": False, "model_name": MODEL})
    has_model = any(n == MODEL or n.split(":")[0] == MODEL.split(":")[0] for n in names)
    return jsonify({"ollama": True, "model": has_model, "model_name": MODEL})


@app.get("/api/cases")
def cases():
    return jsonify(case_cards())


@app.post("/api/new")
def new_game():
    data = request.get_json(silent=True) or {}
    game_id = uuid.uuid4().hex
    GAMES[game_id] = Game(case_path(data.get("case", "")))
    return jsonify({"game": game_id, "state": GAMES[game_id].public_state()})


@app.get("/api/state")
def state():
    game, _ = get_game()
    return jsonify(game.public_state())


@app.post("/api/search")
def search():
    game, data = get_game()
    game.search(data.get("evidence", ""))
    return jsonify(game.public_state())


@app.post("/api/ask")
def ask():
    game, data = get_game()
    game.check_question(data.get("suspect", ""), data.get("text", ""))
    return stream(game.question(data["suspect"], data["text"]))


@app.post("/api/show")
def show():
    game, data = get_game()
    game.check_show(data.get("suspect", ""), data.get("evidence", ""))
    return stream(game.show(data["suspect"], data["evidence"]))


@app.post("/api/accuse")
def accuse():
    game, data = get_game()
    game.accuse(data.get("suspect", ""), data.get("motive"), data.get("evidence") or [])
    return jsonify(game.public_state())


if __name__ == "__main__":
    print("\nThe game is running. Open http://127.0.0.1:5000 in your browser.\n")
    app.run(host="127.0.0.1", port=5000, threaded=True)
