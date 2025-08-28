import chess
import chess.engine

# CONFIG
STOCKFISH_PATH = "C:/Users/Nurmuhammad/Downloads/stockfish/stockfish-windows-x86-64-avx2.exe"
STOCKFISH_LEVEL = 1
THINK_TIME = 0.0001

# SETUP
board = chess.Board()
engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
engine.configure({"Skill Level": STOCKFISH_LEVEL})

def print_board():
    print("\n" + board.unicode() + "\n")

while not board.is_game_over():
    print_board()

    # Player move
    move_input = input("Your move (e.g., e4, Nf3, Bxf5): ")
    try:
        move = board.parse_san(move_input)
        if move in board.legal_moves:
            board.push(move)
        else:
            print("Illegal move! Try again.")
            continue
    except Exception:
        print("Invalid move format! Try again.")
        continue

    # Check if game over after player move
    if board.is_game_over():
        break

    # Stockfish move
    result = engine.play(board, chess.engine.Limit(time=THINK_TIME))
    if result.move is not None:  # check to avoid NoneType
        stockfish_move_san = board.san(result.move)
        board.push(result.move)
        print(f"Stockfish plays: {stockfish_move_san}")

print_board()
print("Game over! Result:", board.result())

engine.quit()
