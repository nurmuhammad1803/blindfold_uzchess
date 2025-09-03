import os
import queue
import sounddevice as sd
import vosk
import json
import time
import openai
import chess
import chess.engine

# ==== CONFIG ====
OPENAI_API_KEY = "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"
openai.api_key = OPENAI_API_KEY
STOCKFISH_PATH = r"C:/Users/Nurmuhammad/Downloads/stockfish/stockfish-windows-x86-64-avx2.exe"
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"

# ==== SPEECH RECOGNITION ====
def recognize_speech():
    q = queue.Queue()
    model = vosk.Model(VOSK_MODEL_PATH)
    recognizer = vosk.KaldiRecognizer(model, 16000)

    def callback(indata, frames, time, status):
        if recognizer.AcceptWaveform(bytes(indata)):  # <-- FIXED HERE
            result = json.loads(recognizer.Result())
            if "text" in result:
                q.put(result["text"])

    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype="int16",
                           channels=1, callback=callback):
        print("🎤 Speak your move...")
        while True:
            try:
                return q.get()
            except queue.Empty:
                pass

# ==== GPT CLEANER ====
from openai import OpenAI
client = OpenAI(api_key='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')

def clean_command(raw_text):
    prompt = f"""
You are a chess move cleaner. 
Convert the spoken move into a valid SAN chess move.
Examples:
- "knight f three" -> Nf3
- "pawn e four" -> e4
- "bishop c four" -> Bc4
- "castle kingside" -> O-O
- "castle queenside" -> O-O-O
Output ONLY the cleaned chess move, nothing else.

Spoken: "{raw_text}"
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You output only valid SAN chess moves."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ GPT error: {e}")
        return None

# ==== BOARD PRINT ====
def print_board(board):
    piece_symbols = {
        chess.PAWN:   "♙", chess.KNIGHT: "♘", chess.BISHOP: "♗",
        chess.ROOK:   "♖", chess.QUEEN:  "♕", chess.KING:   "♔",
    }
    piece_symbols_black = {
        chess.PAWN:   "♟", chess.KNIGHT: "♞", chess.BISHOP: "♝",
        chess.ROOK:   "♜", chess.QUEEN:  "♛", chess.KING:   "♚",
    }

    print("\n   a b c d e f g h")
    print("  -----------------")
    for rank in range(8, 0, -1):
        row = []
        for file in range(1, 9):
            square = chess.square(file-1, rank-1)
            piece = board.piece_at(square)
            if piece:
                if piece.color == chess.WHITE:
                    row.append(piece_symbols[piece.piece_type])
                else:
                    row.append(piece_symbols_black[piece.piece_type])
            else:
                row.append(".")
        print(f"{rank} | {' '.join(row)} | {rank}")
    print("  -----------------")
    print("   a b c d e f g h")

# ==== MAIN ====
def main():
    board = chess.Board()
    engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

    while not board.is_game_over():
        print_board(board)

        # === USER MOVE ===
        raw_text = recognize_speech()
        print(f"👂 You said: {raw_text}")
        move_san = clean_command(raw_text)
        if not move_san:
            print("❌ Could not understand move, try again.")
            continue

        try:
            move = board.parse_san(move_san)
            board.push(move)
            print(f"✅ Your move: {move_san}")
        except:
            print(f"❌ Illegal move: {move_san}")
            continue

        # === STOCKFISH MOVE ===
        result = engine.play(board, chess.engine.Limit(time=1.0))
        if result.move:
            move_san_sf = board.san(result.move)  # must do before push
            board.push(result.move)
            print(f"\n♟️ Stockfish plays: {move_san_sf}")

    print("Game Over:", board.result())
    engine.quit()

if __name__ == "__main__":
    main()
