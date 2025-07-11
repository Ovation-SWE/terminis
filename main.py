#!/usr/bin/env python3

import curses
import random
import time
from copy import deepcopy
from dataclasses import dataclass

# Game constants
BOARD_WIDTH = 10
BOARD_HEIGHT = 20
HIDDEN_ROWS = 4  # extra rows at top for spawning
FPS = 30

# Tetromino definitions (using 4x4 matrices). Each piece is a list of rotation states.
# We'll store rotations as lists of (x, y) coordinates relative to a 4x4 grid origin (0,0) top-left.
# The shapes use the Super Rotation System-like layouts for convenience.

TETROMINOES = {
    "I": [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)],
    ],
    "J": [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    "L": [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
    "O": [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    "S": [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "T": [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    "Z": [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
}

COLORS = {
    "I": 6,
    "J": 4,
    "L": 3,
    "O": 2,
    "S": 5,
    "T": 1,
    "Z": 7,
}


@dataclass
class Piece:
    kind: str
    rotation: int
    x: int
    y: int

    def blocks(self):
        state = TETROMINOES[self.kind][self.rotation % 4]
        return [(self.x + bx, self.y + by) for (bx, by) in state]

    def rotated(self, delta):
        return Piece(self.kind, (self.rotation + delta) % 4, self.x, self.y)


class Board:
    def __init__(self, width=BOARD_WIDTH, height=BOARD_HEIGHT, hidden=HIDDEN_ROWS):
        self.width = width
        self.height = height
        self.hidden = hidden
        self.grid = [[None for _ in range(width)] for _ in range(height + hidden)]

    def inside(self, x, y):
        return 0 <= x < self.width and 0 <= y < (self.height + self.hidden)

    def empty(self, x, y):
        if not self.inside(x, y):
            return False
        return self.grid[y][x] is None

    def valid(self, piece: Piece):
        for x, y in piece.blocks():
            if not self.inside(x, y) or not self.empty(x, y):
                return False
        return True

    def place(self, piece: Piece):
        for x, y in piece.blocks():
            if self.inside(x, y):
                self.grid[y][x] = piece.kind

    def clear_lines(self):
        lines_cleared = 0
        new_grid = []
        for row in self.grid:
            if all(cell is not None for cell in row):
                lines_cleared += 1
            else:
                new_grid.append(row)
        for _ in range(lines_cleared):
            new_grid.insert(0, [None] * self.width)
        self.grid = new_grid
        return lines_cleared

    def game_over(self):
        # game over if any block in the hidden rows (y < hidden) is filled
        for y in range(self.hidden):
            if any(self.grid[y][x] is not None for x in range(self.width)):
                return True
        return False


class TetrisGame:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.board = Board()
        self.score = 0
        self.level = 0
        self.lines = 0
        self.bag = []
        self.next_piece = None
        self.current = None
        self.lock_delay = 0.5
        self.drop_interval = self.level_to_interval(self.level)
        self.last_drop_time = time.time()
        self.gameover = False
        self.paused = False
        self.init_curses()
        self.spawn_next()

    def init_curses(self):
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        curses.start_color()
        curses.use_default_colors()
        # init color pairs 1..7
        for i in range(1, 8):
            curses.init_pair(i, i, -1)

    def level_to_interval(self, level):
        # simplified gravity table; decreases interval as level rises
        base = 1.0
        interval = max(0.05, base * (0.85**level))
        return interval

    def refill_bag(self):
        pieces = list(TETROMINOES.keys())
        random.shuffle(pieces)
        self.bag.extend(pieces)

    def next_from_bag(self):
        if not self.bag:
            self.refill_bag()
        return self.bag.pop(0)

    def spawn_next(self):
        if self.next_piece is None:
            self.next_piece = self.next_from_bag()
        kind = self.next_piece
        self.next_piece = self.next_from_bag()
        # spawn position: x roughly centered, y = 0 (account for block offsets)
        piece = Piece(kind, 0, x=(self.board.width // 2) - 2, y=0)
        self.current = piece
        # if spawn invalid -> immediate game over
        if not self.board.valid(self.current):
            self.gameover = True

    def rotate_current(self, delta):
        if self.current is None:
            return
        new_piece = self.current.rotated(delta)
        # simple wall-kick: try offsets
        for dx in (0, -1, 1, -2, 2):
            candidate = Piece(
                new_piece.kind, new_piece.rotation, new_piece.x + dx, new_piece.y
            )
            if self.board.valid(candidate):
                self.current = candidate
                return

    def move_current(self, dx, dy):
        if self.current is None:
            return False
        moved = Piece(
            self.current.kind,
            self.current.rotation,
            self.current.x + dx,
            self.current.y + dy,
        )
        if self.board.valid(moved):
            self.current = moved
            return True
        return False

    def hard_drop(self):
        if self.current is None:
            return
        while self.move_current(0, 1):
            pass
        self.lock_piece()

    def soft_drop(self):
        moved = self.move_current(0, 1)
        if moved:
            self.score += 1  # small score for soft drop
        return moved

    def lock_piece(self):
        self.board.place(self.current)
        cleared = self.board.clear_lines()
        if cleared:
            # scoring: standard-ish
            if cleared == 1:
                self.score += 40 * (self.level + 1)
            elif cleared == 2:
                self.score += 100 * (self.level + 1)
            elif cleared == 3:
                self.score += 300 * (self.level + 1)
            elif cleared >= 4:
                self.score += 1200 * (self.level + 1)
            self.lines += cleared
            # level up every 10 lines
            new_level = self.lines // 10
            if new_level != self.level:
                self.level = new_level
                self.drop_interval = self.level_to_interval(self.level)
        # spawn next piece
        self.spawn_next()

    def tick(self):
        now = time.time()
        if self.paused or self.gameover:
            self.last_drop_time = now
            return
        if now - self.last_drop_time >= self.drop_interval:
            moved = self.move_current(0, 1)
            if not moved:
                # start lock delay
                # simple handling: lock immediately
                self.lock_piece()
            self.last_drop_time = now

    def handle_input(self):
        try:
            key = self.stdscr.getch()
        except Exception:
            key = -1
        if key == -1:
            return
        if key in (curses.KEY_LEFT, ord("a")):
            self.move_current(-1, 0)
        elif key in (curses.KEY_RIGHT, ord("d")):
            self.move_current(1, 0)
        elif key in (curses.KEY_DOWN,):  # soft drop
            self.soft_drop()
        elif key in (ord("z"), ord("Z")):
            self.rotate_current(-1)
        elif key in (ord("x"), ord("X")):
            self.rotate_current(1)
        elif key == ord(" "):
            self.hard_drop()
        elif key in (ord("p"), ord("P")):
            self.paused = not self.paused
        elif key in (ord("q"), ord("Q")):
            self.gameover = True

    def draw(self):
        self.stdscr.erase()
        # calculate offsets
        sh, sw = self.stdscr.getmaxyx()
        board_w = self.board.width * 2 + 2
        board_h = self.board.height + 2
        offset_x = max(2, (sw - board_w - 20) // 2)
        offset_y = max(1, (sh - board_h) // 2)

        # draw border
        for y in range(self.board.height + 2):
            self.stdscr.addstr(offset_y + y, offset_x, "|")
            self.stdscr.addstr(offset_y + y, offset_x + board_w - 1, "|")
        self.stdscr.addstr(
            offset_y + self.board.height + 1, offset_x, "+" + "-" * (board_w - 2) + "+"
        )

        # draw grid
        for y in range(self.board.hidden, self.board.height + self.board.hidden):
            for x in range(self.board.width):
                cell = self.board.grid[y][x]
                draw_y = offset_y + 1 + (y - self.board.hidden)
                draw_x = offset_x + 1 + x * 2
                if cell is None:
                    self.stdscr.addstr(draw_y, draw_x, "  ")
                else:
                    color = COLORS.get(cell, 1)
                    try:
                        self.stdscr.addstr(
                            draw_y, draw_x, "[]", curses.color_pair(color)
                        )
                    except curses.error:
                        # fallback if terminal doesn't support colors
                        self.stdscr.addstr(draw_y, draw_x, "[]")

        # draw current piece
        if self.current:
            for x, y in self.current.blocks():
                if y >= self.board.hidden:
                    draw_y = offset_y + 1 + (y - self.board.hidden)
                    draw_x = offset_x + 1 + x * 2
                    color = COLORS.get(self.current.kind, 1)
                    try:
                        self.stdscr.addstr(
                            draw_y,
                            draw_x,
                            "[]",
                            curses.color_pair(color) | curses.A_BOLD,
                        )
                    except curses.error:
                        self.stdscr.addstr(draw_y, draw_x, "[]")

        # draw next piece preview
        self.stdscr.addstr(offset_y, offset_x + board_w + 2, f"Score: {self.score}")
        self.stdscr.addstr(offset_y + 1, offset_x + board_w + 2, f"Level: {self.level}")
        self.stdscr.addstr(offset_y + 2, offset_x + board_w + 2, f"Lines: {self.lines}")
        self.stdscr.addstr(offset_y + 4, offset_x + board_w + 2, "Next:")
        if self.next_piece:
            shape = TETROMINOES[self.next_piece][0]
            for bx, by in shape:
                # normalize preview coords to 0..3 and draw
                py = offset_y + 6 + by
                px = offset_x + board_w + 2 + bx * 2
                try:
                    self.stdscr.addstr(
                        py, px, "[]", curses.color_pair(COLORS.get(self.next_piece, 1))
                    )
                except curses.error:
                    self.stdscr.addstr(py, px, "[]")

        # instructions
        self.stdscr.addstr(
            offset_y + board_h + 1,
            offset_x,
            "Controls: Arrows / A D, Z/X rotate, Space hard drop, P pause, Q quit",
        )

        if self.paused:
            self.stdscr.addstr(
                offset_y + board_h // 2, offset_x + board_w // 2 - 5, "[ PAUSED ]"
            )
        if self.gameover:
            self.stdscr.addstr(
                offset_y + board_h // 2, offset_x + board_w // 2 - 6, "== GAME OVER =="
            )
            self.stdscr.addstr(
                offset_y + board_h // 2 + 1,
                offset_x + board_w // 2 - 10,
                "Press Q to quit or Ctrl+C to exit.",
            )

        self.stdscr.refresh()

    def run(self):
        last_time = time.time()
        while not self.gameover:
            now = time.time()
            dt = now - last_time
            # limit frame rate
            if dt < 1.0 / FPS:
                time.sleep(max(0, 1.0 / FPS - dt))
            last_time = time.time()

            self.handle_input()
            self.tick()
            self.draw()

        self.draw()
        while True:
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q")):
                break
            time.sleep(0.05)


def main(stdscr):
    game = TetrisGame(stdscr)
    game.run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("\nBye!")
