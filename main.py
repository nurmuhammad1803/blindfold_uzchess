import os
import json
import time
import uuid
from contextlib import contextmanager

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import chess

# =============================
# Config / Paths
# =============================
ROOMS_PATH = "rooms.json"  # file-based rooms DB
AUTOREFRESH_MS = 1500      # how often the UI polls for updates (ms)

# 🔑 Your GPT API key (HARD-CODED, not safe if shared)
GPT_API_KEY = "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"

# =============================
# Persistent rooms file helpers
# =============================
def _ensure_rooms_file():
    if not os.path.exists(ROOMS_PATH):
        with open(ROOMS_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)

def _load_rooms():
    _ensure_rooms_file()
    with open(ROOMS_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def _save_rooms(data: dict):
    tmp = ROOMS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, ROOMS_PATH)

def now_ts():
    return int(time.time())

@contextmanager
def room_io():
    data = _load_rooms()
    yield data
    _save_rooms(data)

# =============================
# Room / chess helpers
# =============================
def new_room(code: str):
    return {
        "code": code,
        "fen": chess.STARTING_FEN,
        "history": [],            # SAN strings
        "created": now_ts(),
        "turn": "w",              # "w" or "b"
        "status": "ongoing",      # "ongoing" | "ended"
        "winner": None,           # "white" | "black" | "draw" | None
        "players": {"white": None, "black": None},
        "last_update": now_ts(),
    }

def assign_slot(room: dict, user_id: str, prefer: str | None):
    if prefer == "white" and room["players"]["white"] in (None, user_id):
        room["players"]["white"] = user_id
        return "white"
    if prefer == "black" and room["players"]["black"] in (None, user_id):
        room["players"]["black"] = user_id
        return "black"
    if room["players"]["white"] in (None, user_id):
        room["players"]["white"] = user_id
        return "white"
    if room["players"]["black"] in (None, user_id):
        room["players"]["black"] = user_id
        return "black"
    return None  # spectator

def pretty_result(board: chess.Board) -> str:
    if board.is_checkmate():
        return "1-0 (White mates)" if board.turn == chess.BLACK else "0-1 (Black mates)"
    if board.is_stalemate():
        return "½-½ (Stalemate)"
    if board.is_insufficient_material():
        return "½-½ (Insufficient material)"
    if board.can_claim_threefold_repetition():
        return "½-½ (Threefold repetition)"
    if board.can_claim_fifty_moves():
        return "½-½ (Fifty-move rule)"
    return "*"

def sanitize_user_san(s: str) -> str:
    s = s.strip()
    s = s.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    s = s.replace("o-o-o", "O-O-O").replace("o-o", "O-O")
    return s

# =============================
# GPT move cleaner (always on)
# =============================
def clean_with_gpt(raw_text: str, fen: str) -> tuple[str | None, str | None]:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=GPT_API_KEY)
    except Exception as e:
        return None, f"OpenAI client missing: {e}"

    try:
        prompt = (
            "You are a chess move normalizer. Convert the following spoken or typed text "
            "into exactly one legal move in SAN (Standard Algebraic Notation) relative to the "
            "given board FEN. If the input already is valid SAN, return it as-is. Output ONLY the SAN move.\n\n"
            f"Board FEN: {fen}\n"
            f"User input: \"{raw_text}\"\n\n"
            "Examples:\n"
            "- 'knight f three' -> 'Nf3'\n"
            "- 'rook takes e5' -> 'Rxe5'\n"
            "- 'pawn to e4' -> 'e4'\n"
            "- 'castle kingside' -> 'O-O'\n\n"
            "Return only the SAN string (no more than 5-6 letters without spaces between), nothing else."
        )
        resp = client.responses.create(
            model="gpt-5-mini",
            input=prompt,
            max_output_tokens=12,
        )
        out = (resp.output_text or "").strip()
        return sanitize_user_san(out), out
    except Exception as e:
        return None, f"OpenAI request failed: {e}"

# =============================
# Streamlit UI
# =============================
st.set_page_config(page_title="Blindfold Chess (Multiplayer)", page_icon="♟", layout="wide")
st.title("♟ Blindfold Chess — Multiplayer (SAN + GPT cleaner)")

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())

with st.sidebar:
    st.markdown("### Session")
    st.write(f"Your ID: `{st.session_state.user_id[:8]}`")
    st.divider()

    st.markdown("### Create / Join Room")
    default_code = (st.session_state.get("last_room_code") or "").upper()
    colA, colB = st.columns([2, 1])
    with colA:
        room_code = st.text_input("Room code", value=default_code, placeholder="e.g., ABC123").upper().strip()
    with colB:
        side_pref = st.selectbox("Side", ["auto", "white", "black"], index=0)

    col1, col2 = st.columns(2)
    create_clicked = col1.button("Create room")
    join_clicked = col2.button("Join room")

    st.caption("This is blindfold: no board, only SAN move log. Use SAN or free text → GPT.")

if create_clicked and room_code:
    with room_io() as data:
        if room_code in data:
            st.error("Room already exists. Choose another code or join it.")
        else:
            data[room_code] = new_room(room_code)
            assigned = assign_slot(data[room_code], st.session_state.user_id,
                                   None if side_pref == "auto" else side_pref)
            st.session_state.last_room_code = room_code
            st.success(f"Room {room_code} created. You are **{assigned or 'spectator'}**.")

if join_clicked and room_code:
    with room_io() as data:
        if room_code not in data:
            st.error("Room not found. Create it first or check code.")
        else:
            assigned = assign_slot(data[room_code], st.session_state.user_id,
                                   None if side_pref == "auto" else side_pref)
            st.session_state.last_room_code = room_code
            st.success(f"Joined room {room_code}. You are **{assigned or 'spectator'}**.")

st_autorefresh(interval=AUTOREFRESH_MS, limit=None, key="refresh")

if not room_code:
    st.info("Enter a room code in the sidebar and Create or Join a room.")
    st.stop()

rooms = _load_rooms()
if room_code not in rooms:
    st.warning("Room not found. Create it in the sidebar.")
    st.stop()

room = rooms[room_code]
board = chess.Board(room["fen"])

role = "spectator"
if room["players"]["white"] == st.session_state.user_id:
    role = "white"
elif room["players"]["black"] == st.session_state.user_id:
    role = "black"

st.subheader(f"Room **{room_code}** — You are **{role}**")
colX, colY, colZ = st.columns([1, 1, 1])
with colX:
    st.write(f"White: `{(room['players']['white'] or '—')[:8]}`")
with colY:
    st.write(f"Black: `{(room['players']['black'] or '—')[:8]}`")
with colZ:
    st.write(f"Status: **{room['status']}**")

st.markdown(f"**Turn:** {'White' if board.turn == chess.WHITE else 'Black'}")

st.markdown("### Move log")
if room["history"]:
    halfmoves = []
    for idx, san in enumerate(room["history"], start=1):
        prefix = f"{(idx+1)//2}." if idx % 2 == 1 else ""
        halfmoves.append(f"{prefix} {san}".strip())
    st.code(" ".join(halfmoves), language=None)
else:
    st.info("No moves yet.")

if room["status"] == "ongoing" and role in ("white", "black"):
    am_to_move = (role == "white" and board.turn == chess.WHITE) or (role == "black" and board.turn == chess.BLACK)
else:
    am_to_move = False

if am_to_move:
    st.markdown("### Your move (SAN or free text → GPT)")

    if "move_input" not in st.session_state:
        st.session_state.move_input = ""

    st.session_state.move_input = st.text_input(
        "Move:",
        value=st.session_state.move_input,
        placeholder="e.g. e4  OR  'knight to f three'",
        key="move_input_box"
    )

    col1, col2, col3 = st.columns([1, 1, 1])
    clean_btn = col1.button("🧹 Clean with GPT")
    submit_btn = col3.button("Submit move")

    if "gpt_debug" not in st.session_state:
        st.session_state.gpt_debug = ""

    if clean_btn:
        raw = st.session_state.move_input.strip()
        if not raw:
            st.warning("Type something first.")
        else:
            san, debug = clean_with_gpt(raw, board.fen())
            st.session_state.gpt_debug = debug or "<no debug>"
            if san:
                st.session_state.move_input = san
                st.success(f"GPT suggests SAN: **{san}**")
            else:
                st.error(f"GPT failed. Debug: {debug}")

    if st.session_state.gpt_debug:
        st.caption(f"GPT debug: {st.session_state.gpt_debug}")

    if submit_btn:
        candidate = st.session_state.move_input.strip()
        candidate = sanitize_user_san(candidate)
        try:
            move_obj = board.parse_san(candidate)
            with room_io() as data:
                r = data[room_code]
                b2 = chess.Board(r["fen"])
                b2.push(move_obj)
                r["fen"] = b2.fen()
                r["history"].append(candidate)
                r["turn"] = "w" if b2.turn == chess.WHITE else "b"
                r["last_update"] = now_ts()
                if b2.is_game_over():
                    r["status"] = "ended"
                    res = pretty_result(b2)
                    if "1-0" in res:
                        r["winner"] = "white"
                    elif "0-1" in res:
                        r["winner"] = "black"
                    else:
                        r["winner"] = "draw"
            st.success(f"Played: **{candidate}**")
            st.session_state.move_input = ""
            st.rerun()
        except Exception as e:
            st.error(f"Illegal move `{candidate}` — {e}")

    colR1, colR2 = st.columns([1,1])
    if colR1.button("Resign"):
        with room_io() as data:
            r = data[room_code]
            r["status"] = "ended"
            r["winner"] = "black" if role == "white" else "white"
            r["last_update"] = now_ts()
        st.warning("You resigned.")
        st.rerun()
    if colR2.button("Refresh"):
        st.rerun()
else:
    st.info("Waiting for opponent...")

if room["status"] == "ended":
    if room["winner"] == "white":
        st.success("Game over — White wins")
    elif room["winner"] == "black":
        st.success("Game over — Black wins")
    else:
        st.success("Game over — Draw")

st.caption("Tip: share the room code. Both players join same room and play with SAN or GPT-cleaned input.")
