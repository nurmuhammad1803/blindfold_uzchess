import json
import os
import time
import uuid
from contextlib import contextmanager
from streamlit_autorefresh import st_autorefresh
import streamlit as st
import chess

# =============================
# Config / Paths
# =============================
ROOMS_PATH = "rooms.json"  # shared state on disk
AUTOREFRESH_MS = 1500      # how often the UI polls for updates

# =============================
# Small disk-backed “DB”
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

# =============================
# Minimal “lock” (single-proc friendly)
# Streamlit runs your script in a single Python process, so this is fine.
# =============================
@contextmanager
def room_io():
    data = _load_rooms()
    yield data
    _save_rooms(data)

# =============================
# Helpers
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
        "offers": {"draw": None}, # user_id who offered draw
    }

def assign_slot(room: dict, user_id: str, prefer: str | None):
    # Try to honor preference first
    if prefer == "white" and room["players"]["white"] in (None, user_id):
        room["players"]["white"] = user_id
        return "white"
    if prefer == "black" and room["players"]["black"] in (None, user_id):
        room["players"]["black"] = user_id
        return "black"
    # Otherwise auto-assign
    if room["players"]["white"] in (None, user_id):
        room["players"]["white"] = user_id
        return "white"
    if room["players"]["black"] in (None, user_id):
        room["players"]["black"] = user_id
        return "black"
    return None  # spectator

def color_to_move(fen: str) -> str:
    return "white" if fen.split()[1] == "w" else "black"

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
    # Normalize common variants of castling
    s = s.replace("0-0-0", "O-O-O").replace("0-0", "O-O")
    s = s.replace("o-o-o", "O-O-O").replace("o-o", "O-O")
    return s

# Optional OpenAI cleanup (only if user pastes key in sidebar)
def gpt_clean(raw: str, fen: str, api_key: str | None) -> str | None:
    if not api_key:
        return None
    # Using the modern OpenAI client
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        prompt = f"""You are a chess move normalizer.
Given a rough spoken/text input and the current board (FEN), output exactly ONE legal move in SAN.
- Use SAN like: e4, Nf3, Bxe5, O-O, O-O-O, exd8=Q+, Qh7#
- If input is already valid SAN, return it as-is.
- If unclear, return the single most likely legal SAN.
Only output the SAN, with nothing else.

FEN: {fen}
Input: "{raw}"
"""
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=prompt,
            max_output_tokens=12,
        )
        txt = resp.output_text.strip()
        # extra cleanup just in case
        return sanitize_user_san(txt)
    except Exception as e:
        st.sidebar.warning(f"OpenAI error (cleaning disabled): {e}")
        return None

# =============================
# UI
# =============================
st.set_page_config(page_title="Blindfold Chess (Multiplayer)", page_icon="♟")
st.title("♟ Blindfold Chess — Multiplayer (beta)")

# Stable per-browser ID
if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())

with st.sidebar:
    st.markdown("### Session")
    st.write(f"Your ID: `{st.session_state.user_id[:8]}`")
    st.divider()

    st.markdown("### Create / Join Room")
    default_code = (st.session_state.get("last_room_code") or "").upper()
    colA, colB = st.columns([2,1])
    with colA:
        room_code = st.text_input("Room code", value=default_code, placeholder="e.g., ABC123").upper().strip()
    with colB:
        side_pref = st.selectbox("Side", ["auto", "white", "black"], index=0)

    col1, col2 = st.columns(2)
    create_clicked = col1.button("Create room")
    join_clicked   = col2.button("Join room")

    st.divider()
    st.markdown("### Optional: OpenAI move cleaner")
    api_key = st.text_input("OpenAI API Key (optional)", type="password", placeholder="sk-...")

    st.divider()
    st.caption("Invite your friend with the same room code. This is blindfold: no board, only moves.")

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
            st.error("Room not found. Create it or check the code.")
        else:
            assigned = assign_slot(data[room_code], st.session_state.user_id,
                                   None if side_pref == "auto" else side_pref)
            st.session_state.last_room_code = room_code
            st.success(f"Joined room {room_code}. You are **{assigned or 'spectator'}**.")

# Auto-refresh to pull other player's moves
st_autorefresh(interval=AUTOREFRESH_MS, limit=None, key="refresh")


# =============================
# In-room UI
# =============================
if not room_code:
    st.info("Enter a room code to create or join a game.")
    st.stop()

rooms = _load_rooms()
if room_code not in rooms:
    st.warning("Room not found (maybe not created yet).")
    st.stop()

room = rooms[room_code]
board = chess.Board(room["fen"])

# Who am I?
role = "spectator"
if room["players"]["white"] == st.session_state.user_id:
    role = "white"
elif room["players"]["black"] == st.session_state.user_id:
    role = "black"

st.subheader(f"Room **{room_code}** — You are **{role}**")
colX, colY, colZ = st.columns([1,1,1])
with colX:
    st.write(f"White: `{(room['players']['white'] or '—')[:8]}`")
with colY:
    st.write(f"Black: `{(room['players']['black'] or '—')[:8]}`")
with colZ:
    st.write(f"Status: **{room['status']}**")

st.markdown(f"**Turn:** {'White' if board.turn == chess.WHITE else 'Black'}")

# Move input (only if it's my turn and game is ongoing)
if room["status"] == "ongoing" and role in ("white", "black"):
    am_to_move = (role == "white" and board.turn == chess.WHITE) or (role == "black" and board.turn == chess.BLACK)
else:
    am_to_move = False

# History
st.markdown("### Move log")
if room["history"]:
    halfmoves = []
    for idx, san in enumerate(room["history"], start=1):
        prefix = f"{(idx+1)//2}." if idx % 2 == 1 else ""
        halfmoves.append(f"{prefix} {san}".strip())
    st.code(" ".join(halfmoves), language=None)
else:
    st.info("No moves yet.")

# Input section
if am_to_move:
    st.markdown("### Your move")
    raw = st.text_input(
        "Type your move (SAN). Example: e4, Nf3, Bxe5, O-O, O-O-O, exd8=Q+",
        key="move_input",
        placeholder="e4"
    )

    colA, colB, colC = st.columns([1,1,1])
    use_clean = colA.checkbox("Use OpenAI cleaner (if key set)", value=bool(api_key))
    submit = colB.button("Submit move")
    resign = colC.button("Resign")

    if submit:
        # Try GPT cleaner first (optional), then fallback to raw
        candidate = None
        if use_clean and api_key and raw.strip():
            gpt = gpt_clean(raw, board.fen(), api_key)
            if gpt:
                candidate = gpt
        if not candidate:
            candidate = sanitize_user_san(raw)

        try:
            move_obj = board.parse_san(candidate)  # validate on a copy
            # Apply to real room
            with room_io() as data:
                room2 = data[room_code]
                b2 = chess.Board(room2["fen"])
                b2.push(move_obj)
                room2["fen"] = b2.fen()
                room2["history"].append(candidate)
                room2["turn"] = "w" if b2.turn == chess.WHITE else "b"
                room2["last_update"] = now_ts()

                if b2.is_game_over():
                    room2["status"] = "ended"
                    res = pretty_result(b2)
                    if "1-0" in res:
                        room2["winner"] = "white"
                    elif "0-1" in res:
                        room2["winner"] = "black"
                    else:
                        room2["winner"] = "draw"
            st.success(f"Played: **{candidate}**")
            st.experimental_rerun()
        except Exception as e:
            st.error(f"Illegal/invalid move: `{candidate}`  \nDetails: {e}")

    if resign:
        with room_io() as data:
            room2 = data[room_code]
            if role == "white":
                room2["status"] = "ended"
                room2["winner"] = "black"
            else:
                room2["status"] = "ended"
                room2["winner"] = "white"
            room2["last_update"] = now_ts()
        st.warning("You resigned.")
        st.experimental_rerun()
else:
    st.info("Waiting for opponent… (auto-updates)")

# Ended game banner
if room["status"] == "ended":
    if room["winner"] == "white":
        st.success("Game over: **White wins**")
    elif room["winner"] == "black":
        st.success("Game over: **Black wins**")
    else:
        st.success("Game over: **Draw**")

st.caption("Tip: share the room code with your friend. Both of you open this page, join the same room, and play with SAN moves. No board, just pure blindfold 😎")
