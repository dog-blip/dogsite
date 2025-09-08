import pygame
import sys
import chess
import time
import math
import os
import socket, threading, json, queue  # networking

# ---------- resource helper (dev, PyInstaller, py2app) ----------
def resource_path(*parts):
    """Return an absolute path to bundled resources (dev, PyInstaller, py2app)."""
    if getattr(sys, "frozen", False):
        # PyInstaller one-file
        if hasattr(sys, "_MEIPASS"):
            base = sys._MEIPASS
        else:
            # PyInstaller one-dir or py2app
            base = os.path.dirname(sys.executable)
            # py2app: resources live in ../Resources next to the executable
            res = os.path.abspath(os.path.join(base, "..", "Resources"))
            if os.path.isdir(res):
                base = res
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)

# ---------- tiny TCP helper (Host/Join) ----------
class NetPlay:
    """
    Host: NetPlay('host', port=5050)       -> plays White (waits for connection)
    Join: NetPlay('join', server_ip, 5050) -> plays Black
    API: send(dict), poll() -> ('msg', d) | ('connected', info) | ('closed', None) | None
    """
    def __init__(self, mode, server_ip=None, port=5050):
        self.mode = mode
        self.port = port
        self.q = queue.Queue()
        self.alive = True
        self.sock = None
        if mode == 'host':
            self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.listener.bind(('0.0.0.0', port))
            self.listener.listen(1)
            threading.Thread(target=self._accept, daemon=True).start()
        elif mode == 'join':
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(8)
            self.sock.connect((server_ip, port))
            self.sock.settimeout(None)
            threading.Thread(target=self._recv, args=(self.sock,), daemon=True).start()
        else:
            raise ValueError("mode must be 'host' or 'join'")

    def _accept(self):
        try:
            conn, addr = self.listener.accept()
        except Exception:
            self.q.put(('closed', None))
            return
        self.sock = conn
        self.q.put(('connected', {'peer': addr}))
        threading.Thread(target=self._recv, args=(self.sock,), daemon=True).start()

    def _recv(self, s):
        buf = b''
        try:
            while self.alive:
                data = s.recv(4096)
                if not data:
                    break
                buf += data
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode('utf-8'))
                        self.q.put(('msg', msg))
                    except Exception:
                        pass
        finally:
            self.q.put(('closed', None))

    def send(self, d):
        if not self.sock:
            return
        raw = (json.dumps(d) + '\n').encode('utf-8')
        try:
            self.sock.sendall(raw)
        except Exception:
            self.q.put(('closed', None))

    def poll(self):
        try:
            return self.q.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        self.alive = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        try:
            if hasattr(self, 'listener'):
                self.listener.close()
        except Exception:
            pass

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "0.0.0.0"

# -----------------------------
# Layout constants (SIDEBAR!)
# -----------------------------
BOARD_SIZE = 640                 # 8x8 board area
SIDEBAR_WIDTH = 220              # right sidebar
WINDOW_WIDTH, WINDOW_HEIGHT = BOARD_SIZE + SIDEBAR_WIDTH, BOARD_SIZE
SQUARE_SIZE = BOARD_SIZE // 8

# Colors
LIGHT_BROWN = (240, 217, 181)
DARK_BROWN = (181, 136, 99)
HIGHLIGHT = (255, 255, 0, 100)
GREEN = (0, 255, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
BG_COLOR = (245, 222, 179)       # splash screen background
SIDEBAR_BG = (235, 228, 210)     # sidebar background
DIVIDER = (160, 140, 120)

# Buttons
EXIT_BG = (200, 50, 50)
EXIT_BG_HOVER = (220, 70, 70)
NEW_BG = (60, 120, 200)
NEW_BG_HOVER = (80, 140, 220)
HINT_BG = (40, 160, 90)
HINT_BG_HOVER = (60, 180, 110)
HINT_BG_ON = (30, 130, 75)

pygame.init()
SCREEN = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
pygame.display.set_caption("Chess with Pygame")
FONT = pygame.font.SysFont("DejaVu Sans", 32)
SMALL_FONT = pygame.font.SysFont("Arial", 24)
BUTTON_FONT = pygame.font.SysFont("Arial", 25)
CLOCK_FONT = pygame.font.SysFont("Consolas", 36, bold=True)
LABEL_FONT = pygame.font.SysFont("Arial", 18, bold=True)

# icon (optional)
try:
    icon32 = pygame.image.load(resource_path('assets', 'icon32.png')).convert_alpha()
    pygame.display.set_icon(icon32)
    pygame.display.set_caption("Chess")
except Exception:
    pass

# Button rects (right sidebar, bottom)
# Place New + Hint side-by-side, then Exit below
# Button rects (right sidebar, stacked)
BTN_PAD = 16
BTN_W, BTN_H = SIDEBAR_WIDTH - 2*BTN_PAD, 40

EXIT_BTN_RECT = pygame.Rect(BOARD_SIZE + BTN_PAD,
                            WINDOW_HEIGHT - BTN_PAD - BTN_H,
                            BTN_W, BTN_H)
HINT_BTN_RECT = pygame.Rect(BOARD_SIZE + BTN_PAD,
                            EXIT_BTN_RECT.y - 8 - BTN_H,  # 8px gap
                            BTN_W, BTN_H)
NEW_BTN_RECT  = pygame.Rect(BOARD_SIZE + BTN_PAD,
                            HINT_BTN_RECT.y - 8 - BTN_H,
                            BTN_W, BTN_H)


# ---------- orientation helpers ----------
def board_to_screen_rc(square: int, white_bottom: bool):
    """Map chess square -> screen row/col depending on orientation."""
    rank = square // 8
    file = square % 8
    if white_bottom:
        dr = 7 - rank
        dc = file
    else:
        dr = rank
        dc = 7 - file
    return dr, dc

def mouse_to_square(mx: int, my: int, white_bottom: bool):
    """Map mouse x,y -> chess square with orientation."""
    col = mx // SQUARE_SIZE
    row = my // SQUARE_SIZE
    if white_bottom:
        file = col
        rank = 7 - row
    else:
        file = 7 - col
        rank = row
    if 0 <= file < 8 and 0 <= rank < 8:
        return chess.square(file, rank)
    return None

# ---------- Piece images (pre-scale once for sharpness) ----------
def load_piece_images(square_size: int):
    """Load original PNGs and also a pre-scaled copy for the board."""
    orig = {}
    scaled = {}
    for p in ['r', 'n', 'b', 'q', 'k', 'p']:
        b_raw = pygame.image.load(resource_path('assets', f'b{p}.png')).convert_alpha()
        w_raw = pygame.image.load(resource_path('assets', f'w{p}.png')).convert_alpha()
        orig[p] = b_raw
        orig[p.upper()] = w_raw
        scaled[p] = pygame.transform.smoothscale(b_raw, (square_size, square_size)).convert_alpha()
        scaled[p.upper()] = pygame.transform.smoothscale(w_raw, (square_size, square_size)).convert_alpha()
    return orig, scaled

PIECE_ORIG, PIECE_IMAGES = load_piece_images(SQUARE_SIZE)

# sounds
try:
    capture_sound = pygame.mixer.Sound(resource_path('assets', 'capture.wav'))
    move_sound    = pygame.mixer.Sound(resource_path('assets', 'move.wav'))
    check_sound   = pygame.mixer.Sound(resource_path('assets', 'check.wav'))
except Exception:
    # fallback no-op if audio missing
    capture_sound = move_sound = check_sound = type('S', (), {'play': lambda *_: None})()

def draw_text(surface, text, pos, font, color):
    surface.blit(font.render(text, True, color), pos)

def draw_board(board, white_bottom=True, selected_square=None, valid_moves=None,
               hide_squares=None, show_hints=False):
    if valid_moves is None:
        valid_moves = []
    if hide_squares is None:
        hide_squares = set()

    # draw squares
    for r in range(8):
        for c in range(8):
            color = LIGHT_BROWN if (r + c) % 2 == 0 else DARK_BROWN
            pygame.draw.rect(
                SCREEN, color,
                (c * SQUARE_SIZE, r * SQUARE_SIZE, SQUARE_SIZE, SQUARE_SIZE)
            )

    # highlight selected square
    if selected_square is not None:
        r, c = board_to_screen_rc(selected_square, white_bottom)
        s = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)
        s.fill(HIGHLIGHT)
        SCREEN.blit(s, (c * SQUARE_SIZE, r * SQUARE_SIZE))

    # draw pieces
    for square in chess.SQUARES:
        if square in hide_squares:
            continue
        piece = board.piece_at(square)
        if piece:
            r, c = board_to_screen_rc(square, white_bottom)
            img = PIECE_IMAGES[piece.symbol()]
            SCREEN.blit(img, (c * SQUARE_SIZE, r * SQUARE_SIZE))

    # draw move hints on top (if enabled and something is selected)
    if show_hints and selected_square is not None and valid_moves:
        for to_sq in valid_moves:
            r, c = board_to_screen_rc(to_sq, white_bottom)
            cx = c * SQUARE_SIZE + SQUARE_SIZE // 2
            cy = r * SQUARE_SIZE + SQUARE_SIZE // 2
            overlay = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)

            if board.piece_at(to_sq) is None:
                # empty square: small dot
                pygame.draw.circle(overlay, (0, 0, 0, 120),
                                   (SQUARE_SIZE // 2, SQUARE_SIZE // 2),
                                   max(6, SQUARE_SIZE // 10))
            else:
                # capture: ring
                pygame.draw.circle(overlay, (0, 0, 0, 150),
                                   (SQUARE_SIZE // 2, SQUARE_SIZE // 2),
                                   SQUARE_SIZE // 2 - max(4, SQUARE_SIZE // 12),
                                   width=max(4, SQUARE_SIZE // 16))
            SCREEN.blit(overlay, (c * SQUARE_SIZE, r * SQUARE_SIZE))

def draw_sidebar(white_time, black_time, white_to_move, game_over, hint_on=False):
    sidebar_x = BOARD_SIZE
    SCREEN.fill(SIDEBAR_BG, (sidebar_x, 0, SIDEBAR_WIDTH, WINDOW_HEIGHT))
    pygame.draw.line(SCREEN, DIVIDER, (sidebar_x, 0), (sidebar_x, WINDOW_HEIGHT), 2)

    pad = 16
    x = sidebar_x + pad
    y = pad

    draw_text(SCREEN, "Timers", (x, y), SMALL_FONT, BLACK)
    y += 10
    pygame.draw.line(SCREEN, DIVIDER, (x, y + 28), (sidebar_x + SIDEBAR_WIDTH - pad, y + 28), 1)
    y += 40

    def fmt(t):
        t = max(0, int(t))
        return f"{t//60:02d}:{t%60:02d}"

    label_h = LABEL_FONT.get_height()
    clock_h = CLOCK_FONT.get_height()
    clear_w = SIDEBAR_WIDTH - 2*pad
    pad_above = 2
    pad_below = 2

    # --- WHITE ---
    draw_text(SCREEN, "WHITE", (x, y), LABEL_FONT, (80, 80, 80))
    y += label_h + 6
    time_box = pygame.Rect(x, y - pad_above, clear_w, clock_h + pad_above + pad_below)
    SCREEN.fill(SIDEBAR_BG, time_box)
    draw_text(SCREEN, fmt(white_time), (x, y), CLOCK_FONT,
              BLACK if white_to_move else (90, 90, 90))
    y += clock_h + 12

    # --- BLACK ---
    draw_text(SCREEN, "BLACK", (x, y), LABEL_FONT, (80, 80, 80))
    y += label_h + 6
    time_box = pygame.Rect(x, y - pad_above, clear_w, clock_h + pad_above + pad_below)
    SCREEN.fill(SIDEBAR_BG, time_box)
    draw_text(SCREEN, fmt(black_time), (x, y), CLOCK_FONT,
              BLACK if not white_to_move else (90, 90, 90))
    y += clock_h + 12

    pygame.draw.line(SCREEN, DIVIDER, (x, y), (sidebar_x + SIDEBAR_WIDTH - pad, y), 1)
    y += 14
    status = "Game Over" if game_over else ("Turn: WHITE" if white_to_move else "Turn: BLACK")
    draw_text(SCREEN, status, (x, y), SMALL_FONT, (200, 0, 0) if game_over else (0, 90, 0))

    # --- Buttons: New + Hint side-by-side, Exit below ---
    mx, my = pygame.mouse.get_pos()

    # New Game
    is_hover_new = NEW_BTN_RECT.collidepoint((mx, my))
    pygame.draw.rect(SCREEN, NEW_BG_HOVER if is_hover_new else NEW_BG, NEW_BTN_RECT, border_radius=6)
    new_text = SMALL_FONT.render("New Game", True, WHITE)
    SCREEN.blit(new_text, (NEW_BTN_RECT.x + (NEW_BTN_RECT.w - new_text.get_width()) // 2,
                           NEW_BTN_RECT.y + (NEW_BTN_RECT.h - new_text.get_height()) // 2))

    # Hint (toggle)
    is_hover_hint = HINT_BTN_RECT.collidepoint((mx, my))
    hint_color = HINT_BG_ON if hint_on else (HINT_BG_HOVER if is_hover_hint else HINT_BG)
    pygame.draw.rect(SCREEN, hint_color, HINT_BTN_RECT, border_radius=6)
    hint_text = SMALL_FONT.render("Hint", True, WHITE)
    SCREEN.blit(hint_text, (HINT_BTN_RECT.x + (HINT_BTN_RECT.w - hint_text.get_width()) // 2,
                            HINT_BTN_RECT.y + (HINT_BTN_RECT.h - hint_text.get_height()) // 2))

    # Exit
    is_hover_exit = EXIT_BTN_RECT.collidepoint((mx, my))
    pygame.draw.rect(SCREEN, EXIT_BG_HOVER if is_hover_exit else EXIT_BG, EXIT_BTN_RECT, border_radius=6)
    exit_text = SMALL_FONT.render("Exit", True, WHITE)
    SCREEN.blit(exit_text, (EXIT_BTN_RECT.x + (EXIT_BTN_RECT.w - exit_text.get_width()) // 2,
                            EXIT_BTN_RECT.y + (EXIT_BTN_RECT.h - exit_text.get_height()) // 2))

# ---------- Animation helpers ----------
def draw_last_move(last_move, white_bottom, alpha=120):
    if not last_move or alpha <= 0:
        return
    s, e = last_move
    overlay = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)
    overlay.fill((255, 235, 80, max(0, min(255, int(alpha)))))  # warm yellow
    for sq in (s, e):
        r, c = board_to_screen_rc(sq, white_bottom)
        SCREEN.blit(overlay, (c * SQUARE_SIZE, r * SQUARE_SIZE))

def draw_check_pulse(board, white_bottom, t):
    if not board.is_check():
        return
    king_sq = board.king(board.turn)
    if king_sq is None:
        return
    r, c = board_to_screen_rc(king_sq, white_bottom)
    phase = (math.sin(t * 6.0) + 1) * 0.5  # 0..1
    radius = int((SQUARE_SIZE * 0.35) + phase * (SQUARE_SIZE * 0.1))
    alpha = int(120 + phase * 80)  # 120..200
    surf = pygame.Surface((SQUARE_SIZE, SQUARE_SIZE), pygame.SRCALPHA)
    center = (SQUARE_SIZE // 2, SQUARE_SIZE // 2)
    color = (220, 40, 40, alpha)
    pygame.draw.circle(surf, color, center, radius, width=4)
    SCREEN.blit(surf, (c * SQUARE_SIZE, r * SQUARE_SIZE))

def animate_move(board, start, end, white_time, black_time, white_to_move, game_over,
                 white_bottom=True, hint_on=False):
    sr, sc = board_to_screen_rc(start, white_bottom)
    er, ec = board_to_screen_rc(end, white_bottom)

    # use pre-scaled board sprite; integer pixel coords to keep it sharp
    piece_img = PIECE_IMAGES[board.piece_at(start).symbol()]

    frames = 25
    for frame in range(frames):
        draw_board(board, white_bottom=white_bottom, hide_squares={start, end}, show_hints=False)
        t = frame / (frames - 1)
        r = sr + (er - sr) * t
        c = sc + (ec - sc) * t
        SCREEN.blit(piece_img, (int(c * SQUARE_SIZE), int(r * SQUARE_SIZE)))
        draw_sidebar(white_time, black_time, white_to_move, game_over, hint_on=hint_on)
        pygame.display.flip()
        pygame.time.delay(18)

# ---------- Promotion ----------
def promotion_dialog(color):
    options = ['q', 'r', 'b', 'n']          # returns these lowercase letters
    gap = 16
    icon = max(52, int(SQUARE_SIZE * 0.90)) # a bit smaller

    # Snapshot current frame
    backdrop = SCREEN.copy()

    # Piece images for the promoting side — scale from ORIGINALs for max quality
    img_keys = [o.upper() if color == chess.WHITE else o for o in options]
    imgs = [pygame.transform.smoothscale(PIECE_ORIG[k], (icon, icon)).convert_alpha() for k in img_keys]

    # Center over board
    total_w = icon * 4 + gap * 3
    start_x = (BOARD_SIZE - total_w) // 2
    y = (BOARD_SIZE - icon) // 2
    rects = [pygame.Rect(start_x + i * (icon + gap), y, icon, icon) for i in range(4)]

    # Capsule
    pad_x, pad_y = 14, 10
    capsule = pygame.Rect(rects[0].x - pad_x, y - pad_y, total_w + 2 * pad_x, icon + 2 * pad_y)

    selected = 0
    running = True
    while running:
        SCREEN.blit(backdrop, (0, 0))

        # shadow
        shadow = pygame.Surface((capsule.w, capsule.h), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 55), shadow.get_rect(), border_radius=14)
        SCREEN.blit(shadow, (capsule.x + 2, capsule.y + 3))

        # capsule
        cap = pygame.Surface((capsule.w, capsule.h), pygame.SRCALPHA)
        pygame.draw.rect(cap, (245, 245, 245, 215), cap.get_rect(), border_radius=12)
        pygame.draw.rect(cap, (0, 0, 0, 45), cap.get_rect(), width=2, border_radius=12)
        SCREEN.blit(cap, capsule.topleft)

        for i, (img, r) in enumerate(zip(imgs, rects)):
            if i == selected:
                pygame.draw.rect(SCREEN, GREEN, r.inflate(10, 10), width=3, border_radius=8)
            SCREEN.blit(img, r.topleft)

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RIGHT:
                    selected = (selected + 1) % 4
                elif event.key == pygame.K_LEFT:
                    selected = (selected - 1) % 4
                elif event.key in (pygame.K_RETURN, pygame.K_ESCAPE):
                    return options[selected]

            if event.type == pygame.MOUSEMOTION:
                for i, r in enumerate(rects):
                    if r.collidepoint(event.pos):
                        selected = i

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, r in enumerate(rects):
                    if r.collidepoint(event.pos):
                        return options[i]

# ---- Multiplayer splash (choose Solo/Host/Join) ----
def splash_screen():
    # timer inputs
    WHITE_INPUT_RECT = pygame.Rect(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 3, 100, 40)
    BLACK_INPUT_RECT = pygame.Rect(WINDOW_WIDTH // 2, WINDOW_HEIGHT // 3 + 80, 100, 40)

    # net mode UI
    mode_y = WINDOW_HEIGHT // 3 + 130
    SOLO_BTN  = pygame.Rect(WINDOW_WIDTH // 2 - 180, mode_y, 80, 36)
    HOST_BTN  = pygame.Rect(WINDOW_WIDTH // 2 - 80,  mode_y, 80, 36)
    JOIN_BTN  = pygame.Rect(WINDOW_WIDTH // 2 + 20,  mode_y, 80, 36)
    IP_RECT   = pygame.Rect(WINDOW_WIDTH // 2 - 140, mode_y + 50, 220, 36)
    PORT_RECT = pygame.Rect(WINDOW_WIDTH // 2 + 90,  mode_y + 50, 70, 36)

    white_input_text = "10"
    black_input_text = "10"
    ip_text = ""
    port_text = "5050"
    net_mode = "solo"   # 'solo' | 'host' | 'join'

    input_active = None  # 'white', 'black', 'ip', 'port', or None
    start_btn = pygame.Rect(WINDOW_WIDTH // 2 - 50, mode_y + 110, 140, 50)

    running = True
    while running:
        SCREEN.fill(BG_COLOR)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                if WHITE_INPUT_RECT.collidepoint(event.pos):
                    input_active = 'white'
                elif BLACK_INPUT_RECT.collidepoint(event.pos):
                    input_active = 'black'
                elif SOLO_BTN.collidepoint(event.pos):
                    net_mode = 'solo'; input_active = None
                elif HOST_BTN.collidepoint(event.pos):
                    net_mode = 'host'; input_active = 'port'
                elif JOIN_BTN.collidepoint(event.pos):
                    net_mode = 'join'; input_active = 'ip'
                elif (net_mode in ('host','join')) and IP_RECT.collidepoint(event.pos):
                    input_active = 'ip'
                elif (net_mode in ('host','join')) and PORT_RECT.collidepoint(event.pos):
                    input_active = 'port'
                elif start_btn.collidepoint(event.pos):
                    # Require IP for Join
                    if net_mode != 'join' or ip_text.strip():
                        running = False
                else:
                    input_active = None

            if event.type == pygame.KEYDOWN and input_active:
                if event.key == pygame.K_BACKSPACE:
                    if input_active == 'white':
                        white_input_text = white_input_text[:-1]
                    elif input_active == 'black':
                        black_input_text = black_input_text[:-1]
                    elif input_active == 'ip':
                        ip_text = ip_text[:-1]
                    else:
                        port_text = port_text[:-1]
                elif input_active in ('white','black','port'):
                    if event.unicode.isdigit():
                        if input_active == 'white': white_input_text += event.unicode
                        elif input_active == 'black': black_input_text += event.unicode
                        else: port_text += event.unicode
                elif input_active == 'ip':
                    if event.unicode.isdigit() or event.unicode == '.':
                        ip_text += event.unicode
                if event.key == pygame.K_RETURN:
                    if net_mode != 'join' or ip_text.strip():
                        running = False

        # Labels
        label_padding = 10
        white_label_surface = FONT.render("White", True, BLACK)
        SCREEN.blit(white_label_surface, (WHITE_INPUT_RECT.x - white_label_surface.get_width() - label_padding,
                                          WHITE_INPUT_RECT.y + 5))
        black_label_surface = FONT.render("Black", True, BLACK)
        SCREEN.blit(black_label_surface, (BLACK_INPUT_RECT.x - black_label_surface.get_width() - label_padding,
                                          BLACK_INPUT_RECT.y + 5))

        # Input boxes
        pygame.draw.rect(SCREEN, WHITE, WHITE_INPUT_RECT, 2)
        pygame.draw.rect(SCREEN, WHITE, BLACK_INPUT_RECT, 2)
        SCREEN.blit(FONT.render(white_input_text, True, GREEN), (WHITE_INPUT_RECT.x + 5, WHITE_INPUT_RECT.y + 5))
        SCREEN.blit(FONT.render(black_input_text, True, GREEN), (BLACK_INPUT_RECT.x + 5, BLACK_INPUT_RECT.y + 5))

        # Net mode buttons
        def draw_mode(btn, text, selected):
            pygame.draw.rect(SCREEN, (90, 160, 90) if selected else (60, 60, 60), btn, border_radius=6, width=2)
            SCREEN.blit(SMALL_FONT.render(text, True, BLACK), (btn.x + 10, btn.y + 6))
        draw_text(SCREEN, "Mode:", (SOLO_BTN.x - 90, SOLO_BTN.y + 4), SMALL_FONT, BLACK)
        draw_mode(SOLO_BTN, "Solo",  net_mode == 'solo')
        draw_mode(HOST_BTN, "Host",  net_mode == 'host')
        draw_mode(JOIN_BTN, "Join",  net_mode == 'join')

        # IP/Port fields
        if net_mode in ('host','join'):
            if net_mode == 'join':
                pygame.draw.rect(SCREEN, WHITE, IP_RECT, 2)
                hint = ip_text or "host-ip"
                SCREEN.blit(SMALL_FONT.render(hint, True, GREEN if ip_text else (120,120,120)),
                            (IP_RECT.x + 6, IP_RECT.y + 6))
            pygame.draw.rect(SCREEN, WHITE, PORT_RECT, 2)
            SCREEN.blit(SMALL_FONT.render(port_text, True, GREEN), (PORT_RECT.x + 6, PORT_RECT.y + 6))

        # Start button (disabled if Join without IP)
        can_start = (net_mode != 'join') or bool(ip_text.strip())
        pygame.draw.rect(SCREEN, (0,0,0) if can_start else (120,120,120), start_btn, border_radius=6)
        SCREEN.blit(BUTTON_FONT.render("Start Game", True, WHITE), (start_btn.x + 8, start_btn.y + 10))

        pygame.display.flip()

    w_time = int(white_input_text) if white_input_text.isdigit() else 10
    b_time = int(black_input_text) if black_input_text.isdigit() else 10

    net_cfg = {'mode': net_mode}
    if net_mode in ('host','join'):
        try:
            net_cfg['port'] = int(port_text) if port_text.isdigit() else 5050
        except Exception:
            net_cfg['port'] = 5050
        if net_mode == 'join':
            net_cfg['ip'] = ip_text.strip()
    return w_time * 60, b_time * 60, net_cfg

# ---------- Color selection screen ----------
def color_select_screen(net, local_default_white=True):
    WHITE_BTN = pygame.Rect(WINDOW_WIDTH//2 - 190, WINDOW_HEIGHT//2 - 24, 170, 48)
    BLACK_BTN = pygame.Rect(WINDOW_WIDTH//2 + 20,  WINDOW_HEIGHT//2 - 24, 170, 48)
    CANCEL_BTN = pygame.Rect(WINDOW_WIDTH//2 - 60, WINDOW_HEIGHT//2 + 50, 120, 42)

    local_choice = None
    remote_choice = None
    sent = False

    clock = pygame.time.Clock()
    while True:
        clock.tick(60)
        SCREEN.fill(BG_COLOR)
        title = "Choose your side"
        tw, th = FONT.size(title)
        SCREEN.blit(FONT.render(title, True, BLACK), (WINDOW_WIDTH//2 - tw//2, WINDOW_HEIGHT//2 - th - 60))

        # Buttons
        mx, my = pygame.mouse.get_pos()
        for rect, label in [(WHITE_BTN, "Play White"), (BLACK_BTN, "Play Black")]:
            hover = rect.collidepoint((mx, my))
            pygame.draw.rect(SCREEN, (80,140,220) if hover else (60,120,200), rect, border_radius=8)
            txt = SMALL_FONT.render(label, True, WHITE)
            SCREEN.blit(txt, (rect.x + (rect.w - txt.get_width())//2,
                              rect.y + (rect.h - txt.get_height())//2))

        pygame.draw.rect(SCREEN, (120,60,60), CANCEL_BTN, border_radius=8)
        SCREEN.blit(SMALL_FONT.render("Cancel", True, WHITE),
                    (CANCEL_BTN.x + 24, CANCEL_BTN.y + 10))

        # Status line
        status = []
        if local_choice:
            status.append(f"You: {local_choice}")
        if remote_choice:
            status.append(f"Peer: {remote_choice}")
        if status:
            s = " | ".join(status)
            stw, sth = SMALL_FONT.size(s)
            SCREEN.blit(SMALL_FONT.render(s, True, BLACK),
                        (WINDOW_WIDTH//2 - stw//2, WINDOW_HEIGHT//2 - sth - 100))

        pygame.display.flip()

        # ---- safe poll ----
        while True:
            evt = net.poll() if net else None
            if not evt:
                break
            kind, payload = evt
            if kind == 'msg' and payload.get('type') == 'choose':
                remote_choice = payload.get('color')
                if local_choice and remote_choice == local_choice:
                    local_choice = 'black' if local_choice == 'white' else 'white'
            elif kind == 'closed':
                dim = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
                dim.fill((0, 0, 0, 130))
                SCREEN.blit(dim, (0, 0))
                msg = "Player 2 has left"
                tw2, th2 = FONT.size(msg)
                SCREEN.blit(FONT.render(msg, True, WHITE),
                            (WINDOW_WIDTH//2 - tw2//2, WINDOW_HEIGHT//2 - th2//2))
                pygame.display.flip()
                pygame.time.delay(1400)
                if net: net.close()
                return None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if net: net.close()
                pygame.quit()
                sys.exit()

            if event.type == pygame.MOUSEBUTTONDOWN:
                if WHITE_BTN.collidepoint(event.pos):
                    desired = 'white'
                elif BLACK_BTN.collidepoint(event.pos):
                    desired = 'black'
                elif CANCEL_BTN.collidepoint(event.pos):
                    if net: net.close()
                    return None
                else:
                    desired = None

                if desired:
                    if remote_choice == desired:
                        local_choice = 'black' if desired == 'white' else 'white'
                    else:
                        local_choice = desired
                    if net and not sent:
                        try:
                            net.send({"type": "choose", "color": local_choice})
                            sent = True
                        except Exception:
                            pass

        if local_choice and remote_choice:
            if local_choice == remote_choice:
                local_choice = 'black' if local_choice == 'white' else 'white'
            return local_choice

# ---------- Main game (with disconnect handling + hints) ----------
def main_game(w_time_sec, b_time_sec, net_cfg):
    # Networking
    net = None
    local_color = None
    white_bottom = True  # orientation; updated after color selection

    # Host waiting then color select
    if net_cfg.get('mode') == 'host':
        try:
            net = NetPlay('host', port=net_cfg.get('port', 5050))

            # Waiting UI
            CANCEL_BTN = pygame.Rect(WINDOW_WIDTH//2 - 60, WINDOW_HEIGHT//2 + 40, 120, 44)
            clock = pygame.time.Clock()
            ip = get_local_ip()
            connected = False
            while not connected:
                clock.tick(60)
                SCREEN.fill(BG_COLOR)
                msg1 = "Waiting for Player 2…"
                msg2 = f"Your IP: {ip}   Port: {net_cfg.get('port', 5050)}"
                tw1, th1 = FONT.size(msg1)
                tw2, th2 = SMALL_FONT.size(msg2)
                SCREEN.blit(FONT.render(msg1, True, BLACK), (WINDOW_WIDTH//2 - tw1//2, WINDOW_HEIGHT//2 - 30))
                SCREEN.blit(SMALL_FONT.render(msg2, True, BLACK), (WINDOW_WIDTH//2 - tw2//2, WINDOW_HEIGHT//2 + 5))

                pygame.draw.rect(SCREEN, (120, 60, 60), CANCEL_BTN, border_radius=6)
                SCREEN.blit(SMALL_FONT.render("Cancel", True, WHITE),
                            (CANCEL_BTN.x + 22, CANCEL_BTN.y + 10))
                pygame.display.flip()

                evt = net.poll() if net else None
                if evt and evt[0] == 'connected':
                    connected = True

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        if net: net.close()
                        pygame.quit()
                        sys.exit()
                    if event.type == pygame.MOUSEBUTTONDOWN and CANCEL_BTN.collidepoint(event.pos):
                        if net: net.close()
                        return "exit"
        except Exception as e:
            print("Host error:", e)
            if net: net.close()
            return "exit"

        choice = color_select_screen(net)
        if not choice:
            return "exit"
        local_color = chess.WHITE if choice == 'white' else chess.BLACK
        white_bottom = (local_color == chess.WHITE)

    elif net_cfg.get('mode') == 'join':
        try:
            net = NetPlay('join', server_ip=net_cfg.get('ip') or '127.0.0.1', port=net_cfg.get('port', 5050))
        except Exception as e:
            print("Join error:", e)
            return "exit"

        choice = color_select_screen(net)
        if not choice:
            return "exit"
        local_color = chess.WHITE if choice == 'white' else chess.BLACK
        white_bottom = (local_color == chess.WHITE)

    else:
        net = None
        local_color = None  # solo
        white_bottom = True

    # --- Game state ---
    board = chess.Board()
    selected_square = None
    valid_moves = []
    clock = pygame.time.Clock()
    game_over = False

    white_time = w_time_sec
    black_time = b_time_sec
    last_tick = time.time()
    white_to_move = True

    # Overlays
    last_move = None
    last_move_alpha = 0

    # peer disconnect UI
    peer_left = False
    peer_msg = ""
    LEAVE_BTN = pygame.Rect(WINDOW_WIDTH//2 - 140, WINDOW_HEIGHT//2 + 22, 280, 52)

    # Hints toggle
    hint_enabled = False

    def shutdown(ret):
        if net: net.close()
        return ret

    while True:
        clock.tick(60)
        now = time.time()
        dt = now - last_tick
        last_tick = now

        # --- Network receive (SAFE POLL) ---
        if net and not peer_left:
            while True:
                evt = net.poll() if net else None
                if not evt:
                    break
                kind, payload = evt
                if kind == 'msg' and payload.get('type') == 'move':
                    u = payload['uci']
                    m = chess.Move.from_uci(u)
                    if m in board.legal_moves:
                        will_cap = board.is_capture(m)
                        animate_move(board, m.from_square, m.to_square,
                                     white_time, black_time, white_to_move, game_over,
                                     white_bottom=white_bottom, hint_on=hint_enabled)
                        board.push(m)
                        if will_cap: capture_sound.play()
                        else: move_sound.play()
                        if board.is_check() and not board.is_checkmate():
                            check_sound.play()
                        last_move = (m.from_square, m.to_square)
                        last_move_alpha = 170
                        white_time = float(payload.get('wtime', white_time))
                        black_time = float(payload.get('btime', black_time))
                        white_to_move = (board.turn == chess.WHITE)
                        if board.is_checkmate() or board.is_stalemate():
                            game_over = True

                elif kind == 'closed':
                    other_num = 2 if (local_color == chess.WHITE) else 1 if (local_color == chess.BLACK) else 2
                    peer_msg = f"Player {other_num} has left"
                    peer_left = True
                    try:
                        if net:
                            net.close()
                    except Exception:
                        pass
                    net = None

        # --- Clocks ---
        if not game_over and not peer_left:
            if white_to_move:
                white_time -= dt
                if white_time <= 0:
                    print("Black wins on time!")
                    game_over = True
            else:
                black_time -= dt
                if black_time <= 0:
                    print("White wins on time!")
                    game_over = True

        # --- Events ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if net: net.close()
                pygame.quit()
                sys.exit()

            if peer_left:
                if event.type == pygame.MOUSEBUTTONDOWN:
                    pos = pygame.mouse.get_pos()
                    if LEAVE_BTN.collidepoint(pos) or EXIT_BTN_RECT.collidepoint(pos):
                        return "exit"
                continue

            if event.type == pygame.MOUSEBUTTONDOWN:
                pos = pygame.mouse.get_pos()

                # Sidebar buttons
                if NEW_BTN_RECT.collidepoint(pos):
                    return shutdown("new")
                if HINT_BTN_RECT.collidepoint(pos):
                    hint_enabled = not hint_enabled
                    continue
                if EXIT_BTN_RECT.collidepoint(pos):
                    return shutdown("exit")

                # Ignore clicks in sidebar
                if pos[0] >= BOARD_SIZE:
                    continue
                if game_over:
                    continue

                # Online: only your turn
                if local_color is not None:
                    if (board.turn == chess.WHITE and local_color != chess.WHITE) or \
                       (board.turn == chess.BLACK and local_color != chess.BLACK):
                        continue

                sq = mouse_to_square(pos[0], pos[1], white_bottom)
                if sq is None:
                    continue

                if selected_square is None:
                    piece = board.piece_at(sq)
                    if piece and piece.color == board.turn:
                        selected_square = sq
                        valid_moves = [m.to_square for m in board.legal_moves if m.from_square == sq]
                else:
                    if sq in valid_moves:
                        move = chess.Move(selected_square, sq)

                        # Promotion
                        if board.piece_at(selected_square).piece_type == chess.PAWN and (sq // 8 == 0 or sq // 8 == 7):
                            promotion = promotion_dialog(board.turn)
                            move = chess.Move(selected_square, sq, promotion=chess.PIECE_SYMBOLS.index(promotion))

                        if move in board.legal_moves:
                            will_capture = board.is_capture(move)
                            animate_move(board, selected_square, sq,
                                         white_time, black_time, white_to_move, game_over,
                                         white_bottom=white_bottom, hint_on=hint_enabled)
                            board.push(move)

                            if net and not peer_left:
                                try:
                                    net.send({"type": "move", "uci": move.uci(),
                                              "wtime": max(0, white_time), "btime": max(0, black_time)})
                                except Exception:
                                    pass

                            if will_capture: capture_sound.play()
                            else: move_sound.play()
                            if board.is_check() and not board.is_checkmate():
                                check_sound.play()

                            last_move = (selected_square, sq)
                            last_move_alpha = 170

                            white_to_move = not white_to_move
                            selected_square = None
                            valid_moves = []

                            if board.is_checkmate():
                                print("Checkmate!")
                                game_over = True
                            elif board.is_stalemate():
                                print("Stalemate!")
                                game_over = True
                    else:
                        selected_square = None
                        valid_moves = []

        # ---- DRAW FRAME ----
        draw_board(board, white_bottom=white_bottom,
                   selected_square=selected_square, valid_moves=valid_moves,
                   show_hints=hint_enabled)

        if last_move_alpha > 0:
            draw_last_move(last_move, white_bottom, last_move_alpha)
            last_move_alpha = max(0, last_move_alpha - 120 * dt)
        draw_check_pulse(board, white_bottom, now)

        draw_sidebar(white_time, black_time, white_to_move, game_over, hint_on=hint_enabled)

        if peer_left:
            dim = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 130))
            SCREEN.blit(dim, (0, 0))

            tw, th = FONT.size(peer_msg)
            SCREEN.blit(FONT.render(peer_msg, True, WHITE),
                        (WINDOW_WIDTH//2 - tw//2, WINDOW_HEIGHT//2 - th//2 - 28))

            mx, my = pygame.mouse.get_pos()
            hover = LEAVE_BTN.collidepoint((mx, my))
            pygame.draw.rect(SCREEN, EXIT_BG_HOVER if hover else EXIT_BG, LEAVE_BTN, border_radius=10)
            btn_txt = SMALL_FONT.render("Exit to Menu", True, WHITE)
            SCREEN.blit(btn_txt, (LEAVE_BTN.x + (LEAVE_BTN.w - btn_txt.get_width())//2,
                                  LEAVE_BTN.y + (LEAVE_BTN.h - btn_txt.get_height())//2))

        if game_over and not peer_left:
            msg = "Game Over"
            tw, th = FONT.size(msg)
            draw_text(SCREEN, msg, (BOARD_SIZE//2 - tw//2, BOARD_SIZE//2 - th//2), FONT, (200, 0, 0))

        pygame.display.flip()

if __name__ == "__main__":
    # Splash -> (game -> new game -> ...) -> splash
    while True:
        w_time_sec, b_time_sec, net_cfg = splash_screen()

        while True:
            result = main_game(w_time_sec, b_time_sec, net_cfg)
            if result == "new":
                continue
            break
