#!/usr/bin/env python3
"""Interactive Clanker Gauntlet terminal. Run: python gui/cli.py"""
import argparse
import curses
import json
import os
import re
import sys
import threading
import time
import textwrap

import server
import codex_models
import report_model

sys.path.insert(0, str(server.ROOT))
from benchmark_runner import ANTHROPIC_MODELS


STACKS = {
    'Ollama': ('hf.co/peculiar-ragdoll/Cyber-Tiel-Coder-35B-A3B-GGUF-MTP:UD-Q4_K_M',
               'http://127.0.0.1:11434/v1'),
    'PentestGPT': ('pentestgpt-qwen3', 'http://localhost:8088/v1'),
    'CAI adapter': ('cai-qwen3', 'http://localhost:8089/v1'),
}
PARTS = ['questions', 'local', 'agent-safety']

# Box-drawing characters
BD_TL = '\u256d'  # rounded top-left
BD_TR = '\u256e'  # rounded top-right
BD_BL = '\u2570'  # rounded bottom-left
BD_BR = '\u256f'  # rounded bottom-right
BD_H  = '\u2500'  # horizontal
BD_V  = '\u2502'  # vertical
BD_HB = '\u2501'  # heavy horizontal (for focused panels)
BD_VB = '\u2503'  # heavy vertical (for focused panels)
BD_TLB = '\u250f' # heavy top-left
BD_TRB = '\u2513' # heavy top-right
BD_BLB = '\u2517' # heavy bottom-left
BD_BRB = '\u251b' # heavy bottom-right

# Status symbols
SYM_RUNNING  = '\u25cf'  # filled circle
SYM_IDLE     = '\u25cb'  # hollow circle
SYM_CHECK    = '\u2713'  # checkmark
SYM_CROSS    = '\u2717'  # cross
SYM_ARROW    = '\u25b8'  # right triangle
SYM_DOT      = '\u00b7'  # middle dot
SYM_DASH     = '\u2014'  # em dash
SYM_BLOCK    = '\u2588'  # full block
SYM_SPINNER  = ('\u280b', '\u2819', '\u2838', '\u2830', '\u2826', '\u2807')


def clean(value):
    return ''.join(char if char.isprintable() else ' ' for char in str(value))


# Color pair assignments
C_ACCENT    = 1   # cyan/teal - primary accent, headers
C_TITLE     = 2   # bright white - titles, important text
C_WARN      = 3   # amber/yellow - warnings, notices
C_ERROR     = 4   # red - errors, stop states
C_DIM       = 5   # gray - borders, secondary text
C_SELECT    = 6   # highlight bar - selected items
C_SUCCESS   = 7   # green - success states
C_HEADER_BG = 8   # header bar background
C_TAB_ACT   = 9   # active tab
C_TAB_INACT = 10  # inactive tab
C_FIELD_LBL = 11  # field labels
C_FIELD_VAL = 12  # field values
C_LOG_KEY   = 13  # log keywords
C_BORDER_F  = 14  # focused border
C_STATUS_RUN = 15 # running status
C_STATUS_OK  = 16 # complete status


class Terminal:
    def __init__(self, screen, args):
        self.screen = screen
        self.tab = -1
        self.cursor = 0
        self.stack = 'Ollama'
        self.config = {'model': args.model, 'endpoint': args.base_url, 'judge': args.judge,
                       'judge_provider': '', 'seed': args.seed, 'actions': 30, 'parts': PARTS.copy()}
        self.rows = server.reports()
        self.models = []
        self.loaded = []
        self.notice = ''
        self.notice_level = 'info'
        self.busy = False
        self.detail = None
        self.offset = 0
        self.previous_status = None
        self.leader = False
        self.spin_frame = 0
        curses.curs_set(0)
        screen.timeout(250)
        self._init_colors()
        self.refresh_models()

    def _init_colors(self):
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        if curses.COLORS >= 256:
            curses.init_pair(C_ACCENT,     73,  -1)    # muted teal
            curses.init_pair(C_TITLE,      255, -1)    # bright white
            curses.init_pair(C_WARN,       179, -1)    # warm amber
            curses.init_pair(C_ERROR,      167, -1)    # soft red
            curses.init_pair(C_DIM,        243, -1)    # medium gray
            curses.init_pair(C_SELECT,     16,  73)    # dark on teal
            curses.init_pair(C_SUCCESS,    108, -1)    # sage green
            curses.init_pair(C_HEADER_BG,  73,  236)   # teal on dark
            curses.init_pair(C_TAB_ACT,    16,  73)    # dark on teal
            curses.init_pair(C_TAB_INACT,  250, 238)   # light on charcoal
            curses.init_pair(C_FIELD_LBL,  246, -1)    # light gray
            curses.init_pair(C_FIELD_VAL,  252, -1)    # near white
            curses.init_pair(C_LOG_KEY,    110, -1)    # soft blue
            curses.init_pair(C_BORDER_F,   73,  -1)    # teal borders
            curses.init_pair(C_STATUS_RUN, 114, -1)    # green
            curses.init_pair(C_STATUS_OK,  108, -1)    # sage
        else:
            curses.init_pair(C_ACCENT,     curses.COLOR_CYAN,    -1)
            curses.init_pair(C_TITLE,      curses.COLOR_WHITE,   -1)
            curses.init_pair(C_WARN,       curses.COLOR_YELLOW,  -1)
            curses.init_pair(C_ERROR,      curses.COLOR_RED,     -1)
            curses.init_pair(C_DIM,        curses.COLOR_WHITE,   -1)
            curses.init_pair(C_SELECT,     curses.COLOR_BLACK,   curses.COLOR_CYAN)
            curses.init_pair(C_SUCCESS,    curses.COLOR_GREEN,   -1)
            curses.init_pair(C_HEADER_BG,  curses.COLOR_CYAN,    curses.COLOR_BLACK)
            curses.init_pair(C_TAB_ACT,    curses.COLOR_BLACK,   curses.COLOR_CYAN)
            curses.init_pair(C_TAB_INACT,  curses.COLOR_WHITE,   curses.COLOR_BLACK)
            curses.init_pair(C_FIELD_LBL,  curses.COLOR_WHITE,   -1)
            curses.init_pair(C_FIELD_VAL,  curses.COLOR_WHITE,   -1)
            curses.init_pair(C_LOG_KEY,    curses.COLOR_CYAN,    -1)
            curses.init_pair(C_BORDER_F,   curses.COLOR_CYAN,    -1)
            curses.init_pair(C_STATUS_RUN, curses.COLOR_GREEN,   -1)
            curses.init_pair(C_STATUS_OK,  curses.COLOR_GREEN,   -1)

    def put(self, y, x, value, color=0, bold=False):
        height, width = self.screen.getmaxyx()
        if y < 0 or y >= height or x >= width - 1:
            return
        attr = (curses.color_pair(color) if color and curses.has_colors() else 0) | (curses.A_BOLD if bold else 0)
        try:
            self.screen.addnstr(y, x, clean(value), max(0, width - x - 1), attr)
        except curses.error:
            pass

    def hline(self, y, x, width, color=C_DIM):
        self.put(y, x, BD_H * width, color)

    def box(self, y, x, height, width, label='', focused=False):
        if height < 3 or width < 5:
            return
        bc = C_BORDER_F if focused else C_DIM
        if focused:
            tl, tr, bl, br, h, v = BD_TLB, BD_TRB, BD_BLB, BD_BRB, BD_HB, BD_VB
        else:
            tl, tr, bl, br, h, v = BD_TL, BD_TR, BD_BL, BD_BR, BD_H, BD_V
        self.put(y, x, tl + h * (width - 2) + tr, bc)
        self.put(y + height - 1, x, bl + h * (width - 2) + br, bc)
        for row in range(y + 1, y + height - 1):
            self.put(row, x, v, bc)
            self.put(row, x + width - 1, v, bc)
            # Clear interior
            self.put(row, x + 1, ' ' * (width - 2))
        if label:
            self.put(y, x + 2, f' {label[:max(0, width - 6)]} ', C_ACCENT, True)

    def selected_row(self, y, x, text, width, selected):
        visible = text if len(text) <= width else text[:max(0, width - 3)] + '...'
        self.put(y, x, visible[:width].ljust(width), C_SELECT if selected else 0, selected)

    def draw_header(self, width):
        """Render the top header bar."""
        self.put(0, 0, ' ' * width, C_HEADER_BG)
        self.put(0, 1, ' CLANKER GAUNTLET ', C_HEADER_BG, True)
        status = self.active_status()
        if status == 'RUNNING':
            self.spin_frame = (self.spin_frame + 1) % len(SYM_SPINNER)
            sym = SYM_SPINNER[self.spin_frame]
            self.put(0, width - len(status) - 5, f' {sym} {status} ', C_STATUS_RUN, True)
        elif status == 'COMPLETE':
            self.put(0, width - len(status) - 5, f' {SYM_CHECK} {status} ', C_STATUS_OK, True)
        elif status == 'FAILED':
            self.put(0, width - len(status) - 5, f' {SYM_CROSS} {status} ', C_ERROR, True)
        elif status == 'STOPPED':
            self.put(0, width - len(status) - 5, f' {SYM_DASH} {status} ', C_WARN, True)
        else:
            self.put(0, width - len(status) - 5, f' {SYM_IDLE} {status} ', C_DIM)

    def draw_footer(self, height, width):
        """Render the bottom status and help bars."""
        # Notice line
        if self.notice:
            nc = C_WARN if self.notice_level == 'warn' else C_ERROR if self.notice_level == 'error' else C_DIM
            self.put(height - 3, 2, self.notice[:width - 4], nc)
        # Status bar
        self.put(height - 2, 0, ' ' * width, C_HEADER_BG)
        loc = 'Home' if self.tab == -1 else ('Benchmark', 'Results', 'Models', 'Activity')[self.tab]
        self.put(height - 2, 1, f' {loc} ', C_HEADER_BG, True)
        right = f'{len(self.rows)} reports {SYM_DOT} seed:{self.config["seed"]} '
        self.put(height - 2, max(20, width - len(right) - 1), right, C_HEADER_BG)

    def set_notice(self, text, level='info'):
        self.notice = text
        self.notice_level = level

    def draw_home(self, height, width):
        logo = [
            '  ___  _              _               ',
            ' / __|| | __ _  _ _  | |__ ___  _ _   ',
            '| (__ | |/ _` || \' \\ | / // -_)| \'_|  ',
            ' \\___||_|\\__,_||_||_||_\\_\\\\___||_|    ',
        ]
        top = max(4, (height - 20) // 2)
        for i, line in enumerate(logo):
            self.put(top + i, max(2, (width - 38) // 2), line, C_ACCENT, True)
        sub = 'Security Benchmark Framework'
        self.put(top + 5, max(2, (width - len(sub)) // 2), sub, C_DIM)
        ver = 'v2.0'
        self.put(top + 6, max(2, (width - len(ver)) // 2), ver, C_DIM)

        menu_top = top + 9
        menu_left = max(2, (width - 52) // 2)
        items = [
            ('n', 'New Benchmark',  'Configure and launch a run'),
            ('f', 'View Results',   f'{len(self.rows)} saved reports'),
            ('m', 'Model Manager',  'Ollama models and memory'),
            ('l', 'Live Activity',  self.active_status().lower()),
            ('q', 'Quit',           ''),
        ]
        for i, (key, label, hint) in enumerate(items):
            sel = i == self.cursor
            prefix = f' {SYM_ARROW} ' if sel else '   '
            text = f'{prefix}[{key}]  {label:<18} {hint}'
            self.selected_row(menu_top + i, menu_left, text, min(54, width - menu_left - 2), sel)

        if menu_top + 8 < height - 4:
            tagline = f'Local-first {SYM_DOT} Reproducible {SYM_DOT} Research-grade'
            self.put(menu_top + 7, max(2, (width - len(tagline)) // 2), tagline, C_DIM)

    def refresh_models(self):
        if self.busy:
            return
        self.busy = True

        def worker():
            try:
                self.models = server.ollama('api/tags').get('models', [])
                self.loaded = server.ollama('api/ps').get('models', [])
                self.set_notice(f'Ollama connected {SYM_DOT} {len(self.loaded)} loaded model(s)')
            except Exception as exc:
                self.set_notice(f'Ollama unavailable: {exc}', 'warn')
            finally:
                self.busy = False
        threading.Thread(target=worker, daemon=True).start()

    def load_model(self, name):
        if self.busy:
            return
        if name in [model['name'] for model in self.loaded]:
            self.set_notice(f'{name} is already loaded.')
            return
        self.busy = True
        self.set_notice(f'Loading {name} into memory...')

        def worker():
            try:
                server.ollama('api/generate', {'model': name, 'keep_alive': -1}, timeout=600)
                self.set_notice(f'{SYM_CHECK} Loaded {name}')
            except Exception as exc:
                self.set_notice(f'Could not load {name}: {exc}', 'error')
            finally:
                self.busy = False
                self.refresh_models()
        threading.Thread(target=worker, daemon=True).start()

    def unload_model(self, name):
        if self.busy:
            return
        if name not in [model['name'] for model in self.loaded]:
            self.set_notice(f'{name} is not loaded.')
            return
        self.busy = True
        self.set_notice(f'Unloading {name}...')

        def worker():
            try:
                server.ollama('api/generate', {'model': name, 'keep_alive': 0})
                self.set_notice(f'{SYM_CHECK} Unloaded {name}')
            except Exception as exc:
                self.set_notice(f'Could not unload {name}: {exc}', 'error')
            finally:
                self.busy = False
                self.refresh_models()
        threading.Thread(target=worker, daemon=True).start()

    def edit(self, label, current):
        value = str(current)
        self.screen.timeout(-1)
        curses.curs_set(1)
        try:
            while True:
                self.draw()
                height, width = self.screen.getmaxyx()
                # Draw input overlay
                iw = min(width - 4, 72)
                ix = (width - iw) // 2
                iy = height - 6
                self.box(iy, ix, 4, iw, label)
                visible = value[-max(1, iw - 6):]
                self.put(iy + 2, ix + 2, visible, C_FIELD_VAL)
                self.put(iy + 3, ix + 2, 'Enter: save  Esc: cancel', C_DIM)
                self.screen.move(iy + 2, min(ix + iw - 2, ix + len(visible) + 2))
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ('\n', '\r', curses.KEY_ENTER):
                    return value
                if key == '\x1b':
                    return None
                if key in ('\b', '\x7f', curses.KEY_BACKSPACE):
                    value = value[:-1]
                elif isinstance(key, str) and key.isprintable() and len(value) < 1000:
                    value += key
        finally:
            curses.curs_set(0)
            self.screen.timeout(250)

    def active_status(self):
        active = server.ACTIVE
        if not active:
            return 'IDLE'
        code = active['process'].poll()
        if code is None:
            return 'RUNNING'
        return 'STOPPED' if active['stopped'] else 'COMPLETE' if code == 0 else 'FAILED'

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 24 or width < 62:
            self.put(1, 1, 'Terminal too small. Need at least 62x24.', C_WARN)
            self.put(3, 1, 'Resize or press q to quit.')
            self.screen.refresh()
            return
        status = self.active_status()
        if self.previous_status == 'RUNNING' and status != 'RUNNING':
            self.rows = server.reports()
        self.previous_status = status
        self.draw_header(width)
        # Tabs
        tabs = ('Run', 'Results', 'Models', 'Activity')
        tx = 2
        for i, name in enumerate(tabs):
            label = f' {i+1} {name} '
            self.put(2, tx, label, C_TAB_ACT if self.tab == i else C_TAB_INACT, self.tab == i)
            tx += len(label) + 1
        if self.detail:
            self.put(5, 2, self.detail['title'], C_ACCENT, True)
            self.hline(6, 2, min(60, width - 4))
            lines = self.detail['lines']
            self.offset = max(0, min(self.offset, max(0, len(lines) - (height - 12))))
            for y, line in enumerate(lines[self.offset:self.offset + height - 12], 8):
                self.put(y, 3, line)
        elif self.tab == -1:
            self.draw_home(height, width)
        elif self.tab == 0:
            self.draw_run(height, width)
        elif self.tab == 1:
            self.draw_results(height)
        elif self.tab == 2:
            self.draw_models(height)
        else:
            self.box(4, 1, height - 8, width - 2, 'Live Output')
            self.draw_log(5, 3, height)
        self.draw_footer(height, width)
        # Help line
        help_text = 'j/k: navigate  Enter: select  Tab: switch  r: refresh  s: stop  q: quit'
        self.put(height - 1, 2, help_text[:width - 4], C_DIM)
        if self.leader:
            pw = min(56, width - 4)
            py = height - 11
            self.box(py, width - pw - 2, 7, pw, 'Commands')
            left = width - pw
            for row, text in enumerate(('n  New run         f  Results',
                                        'm  Models          l  Activity',
                                        'r  Refresh         h  Dashboard',
                                        'q  Quit            Esc Cancel'), py + 2):
                self.put(row, left, text, C_ACCENT)
        self.screen.refresh()

    def draw_run(self, height, width):
        if width >= 110:
            log_x, log_y = width // 2 + 3, 5
            field_width = width // 2 - 6
            self.box(4, width // 2 + 1, height - 8, width - width // 2 - 2, 'Live Output')
        else:
            log_x, log_y = 3, 20
            field_width = width - 8
        self.box(4, 1, height - 8, width // 2 - 2 if width >= 110 else width - 2, 'Configuration')
        fields = [('Stack', self.stack), ('Model', self.config['model']),
                  ('Endpoint', self.config['endpoint']),
                  ('Judge', self.config['judge'] or 'Codex default'),
                  ('Seed', self.config['seed']), ('Max actions', self.config['actions'])]
        for i, (label, value) in enumerate(fields):
            sel = self.cursor == i
            prefix = f' {SYM_ARROW} ' if sel else '   '
            lbl = f'{label:<13}'
            text = f'{prefix}{lbl} {value}'
            self.selected_row(6 + i, 3, text, field_width, sel)
        self.put(13, 3, f'   {"":13} {BD_H * max(1, field_width - 18)}', C_DIM)
        for i, part in enumerate(PARTS, 6):
            sel = self.cursor == i
            enabled = part in self.config['parts']
            prefix = f' {SYM_ARROW} ' if sel else '   '
            check = f'{SYM_CHECK}' if enabled else ' '
            text = f'{prefix}[{check}] Part {i-5}: {part}'
            self.selected_row(14 + (i - 6), 3, text, field_width, sel)
        self.put(17, 3, f'   {"":13} {BD_H * max(1, field_width - 18)}', C_DIM)
        sel_start = self.cursor == 9
        self.selected_row(18, 3, f' {SYM_ARROW if sel_start else " "} {SYM_BLOCK} Start Benchmark', field_width, sel_start)
        if width >= 110:
            self.draw_log(log_y, log_x, height)

    def draw_log(self, log_y, log_x, height):
        lines = ['Waiting for benchmark to start...']
        if server.ACTIVE:
            with server.ACTIVE['log'].open('rb') as stream:
                stream.seek(max(0, server.ACTIVE['log'].stat().st_size - 32000))
                lines = stream.read().decode(errors='replace').splitlines()
        count = max(0, height - log_y - 8)
        for y, line in enumerate(lines[-count:] if count else [], log_y + 2):
            self.put(y, log_x, line[:max(0, self.screen.getmaxyx()[1] - log_x - 4)], C_DIM)

    def draw_results(self, height):
        w = self.screen.getmaxyx()[1]
        self.box(4, 1, height - 8, w - 2, f'Results ({len(self.rows)})')
        # Column headers
        self.put(6, 3, f'  {"MODEL":<24} {"PART":<20} {"CASES":>5}  {"DATE":<10}', C_DIM, True)
        self.hline(7, 3, w - 8)
        size = height - 14
        start = max(0, self.cursor - size + 1)
        for y, row in enumerate(self.rows[start:start + size], 8):
            index = start + y - 8
            sel = index == self.cursor
            prefix = f'{SYM_ARROW} ' if sel else '  '
            text = f'{prefix}{row["model"]:<24} {row["part"]:<20} {row["count"]:>5}  {row["date"][:10]}'
            self.selected_row(y, 3, text, w - 8, sel)
        if not self.rows:
            self.put(9, 4, 'No saved reports. Run a benchmark first.', C_DIM)

    def draw_models(self, height):
        w = self.screen.getmaxyx()[1]
        self.box(4, 1, height - 8, w - 2, 'Ollama Models')
        self.put(6, 3, f'  {"MODEL":<32} {"STATUS":<18}', C_DIM, True)
        self.put(6, w - 30, 'l: load  u: unload  r: refresh', C_DIM)
        self.hline(7, 3, w - 8)
        loaded = {model['name']: model for model in self.loaded}
        size = height - 14
        start = max(0, self.cursor - size + 1)
        for y, model in enumerate(self.models[start:start + size], 8):
            index = start + y - 8
            sel = index == self.cursor
            prefix = f'{SYM_ARROW} ' if sel else '  '
            memory = loaded.get(model['name'])
            if memory:
                status = f'{SYM_CHECK} Loaded  {memory["size"]/1024**3:.1f} GiB'
                sc = C_SUCCESS
            else:
                status = f'{SYM_IDLE} Available'
                sc = C_DIM
            text = f'{prefix}{model["name"]:<32} {status}'
            if sel:
                self.selected_row(y, 3, text, w - 8, True)
            else:
                self.put(y, 3, f'{prefix}{model["name"]:<32}')
                self.put(y, 37, status, sc)
        if not self.models:
            self.put(9, 4, 'No models found. Is Ollama running? Press r to retry.', C_DIM)

    def enter(self):
        if self.tab == 1 and self.rows:
            row = self.rows[self.cursor]
            data = json.loads(server.report_path(row['path']).read_text())
            lines = [row['path'], '', 'METRICS', BD_H * 50]
            for metric in row['metrics']:
                lines.append(f'  {metric["name"]}: {metric["value"]}{metric["unit"]} ({metric["direction"]} is better)')
            lines += ['', 'CASES', BD_H * 50]
            for case in data['results']:
                grade = case.get('grade') or {}
                result = f'{grade["score"]}/10' if 'score' in grade else case.get('status', 'unknown')
                lines.append(f'  {case.get("id", "?"):<36} {result}')
                if case.get('error'):
                    lines.append('    ' + case['error'])
            self.detail = {'title': row['model'] + '  ' + SYM_ARROW + '  ' + row['part'], 'lines': lines}
            self.offset = 0
        elif self.tab == 0:
            if self.cursor == 0:
                names = list(STACKS)
                self.stack = names[(names.index(self.stack) + 1) % len(names)]
                self.config['model'], self.config['endpoint'] = STACKS[self.stack]
            elif self.cursor < 6:
                key = ['stack', 'model', 'endpoint', 'judge', 'seed', 'actions'][self.cursor]
                value = self.edit(key, self.config[key])
                if value is not None:
                    self.config[key] = int(value) if key in ('seed', 'actions') else value
            elif self.cursor < 9:
                part = PARTS[self.cursor - 6]
                if part in self.config['parts']:
                    self.config['parts'].remove(part)
                else:
                    self.config['parts'].append(part)
            else:
                server.launch(self.config)
                self.set_notice(f'{SYM_CHECK} Benchmark launched. Reports saved under results/')

    def run(self):
        while True:
            self.draw()
            try:
                key = self.screen.get_wch()
            except curses.error:
                continue
            try:
                if self.leader:
                    self.leader = False
                    if key == '\x1b':
                        continue
                if self.tab == -1 and key in ('\n', '\r', curses.KEY_ENTER):
                    key = ('n', 'f', 'm', 'l', 'q')[self.cursor]
                if key in ('q', '\x03'):
                    if self.detail:
                        self.detail = None
                        continue
                    if self.active_status() == 'RUNNING':
                        answer = self.edit('Stop the active benchmark and quit? Type yes', '')
                        if answer != 'yes':
                            continue
                        server.stop()
                    return
                if self.detail:
                    if key in ('\x1b', '\n'):
                        self.detail = None
                    elif key in (curses.KEY_DOWN, 'j'):
                        self.offset += 1
                    elif key in (curses.KEY_UP, 'k'):
                        self.offset -= 1
                    elif key == curses.KEY_NPAGE:
                        self.offset += 10
                    elif key == curses.KEY_PPAGE:
                        self.offset -= 10
                    continue
                if key == ' ':
                    self.leader = True
                elif key in ('n', 'f', 'm', 'l', 'h', 'H'):
                    self.tab = {'n': 0, 'f': 1, 'm': 2, 'l': 3, 'h': -1, 'H': -1}[key]
                    self.cursor = 0
                elif key in ('\t', '1', '2', '3', '4'):
                    self.tab = (self.tab + 1) % 4 if key == '\t' else int(key) - 1
                    self.cursor = 0
                elif key in (curses.KEY_DOWN, 'j', curses.KEY_UP, 'k'):
                    count = 5 if self.tab == -1 else 10 if self.tab == 0 else len(self.rows) if self.tab == 1 else len(self.models) if self.tab == 2 else 0
                    self.cursor = max(0, min(max(0, count - 1), self.cursor + (1 if key in (curses.KEY_DOWN, 'j') else -1)))
                elif key in ('\n', '\r', curses.KEY_ENTER):
                    self.enter()
                elif key == 'r':
                    self.rows = server.reports()
                    self.cursor = 0
                    self.refresh_models()
                elif key == 's':
                    server.stop()
                    self.set_notice('Stop requested. Model memory remains loaded.')
                elif key == 'l' and self.tab == 2 and self.models and not self.busy:
                    self.load_model(self.models[self.cursor]['name'])
                elif key == 'u' and self.tab == 2 and self.models and not self.busy:
                    name = self.models[self.cursor]['name']
                    self.unload_model(name)
            except (ValueError, OSError, TypeError) as exc:
                self.set_notice(str(exc), 'error')


class ControlPanel(Terminal):
    """Three work areas with visible focus and conventional form controls."""

    def __init__(self, screen, args):
        super().__init__(screen, args)
        self.tab = -1
        self.focus = 'setup'
        self.scroll = {'output': 0, 'judge': 0, 'machine': 0}
        self.follow = {'output': True, 'judge': True, 'machine': True}
        self.hits = []
        self.set_notice('Ready. Select a model, wrapper, and parts to begin.')
        self.direct_model = args.model
        self.page_detail = None
        self.detail_offset = 0
        self.detail_group = None
        self.case_offsets = []
        self.part_offsets = {}
        self.exporting = False
        self.search_term = ''
        self.groups = []
        self.judge_models = codex_models.cached_models()
        self.judge_source = 'cached catalog' if self.judge_models else 'catalog unavailable'
        self.judge_busy = False
        self.refresh_judges()
        self.build_groups()
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        except curses.error:
            pass

    def refresh_judges(self):
        if self.judge_busy:
            return
        self.judge_busy = True

        def worker():
            try:
                rows = codex_models.discover_models()
                if rows:
                    self.judge_models = rows
                    self.judge_source = 'Codex model/list'
            except Exception:
                self.judge_source = 'cached catalog' if self.judge_models else 'catalog unavailable'
            finally:
                self.judge_busy = False
        threading.Thread(target=worker, daemon=True).start()

    def build_groups(self):
        grouped = {}
        for row in self.rows:
            folder = str(server.Path(row['path']).parent)
            key = folder if folder != '.' else row['path']
            group = grouped.setdefault(key, {'name': key, 'model': row['model'], 'parts': [], 'date': row['date']})
            group['parts'].append(row)
        self.groups = list(grouped.values())
        self.filtered_groups = self.groups

    def frame(self, y, x, height, width, label, focus=None):
        focused = focus == self.focus
        self.box(y, x, height, width, label, focused)
        if focus:
            self.hits.append((y, x, height, width, focus, None))

    def pick(self, label, options, current):
        index = options.index(current) if current in options else 0
        self.screen.timeout(-1)
        try:
            while True:
                self.draw()
                height, width = self.screen.getmaxyx()
                box_width = min(width - 4, 68)
                count = min(len(options), max(1, height - 10))
                box_height = count + 5
                x, y = (width - box_width) // 2, (height - box_height) // 2
                self.box(y, x, box_height, box_width, label, focused=True)
                start = max(0, index - count + 1)
                for i, option in enumerate(options[start:start + count]):
                    sel = start + i == index
                    prefix = f' {SYM_ARROW} ' if sel else '   '
                    self.selected_row(y + 2 + i, x + 2, prefix + option,
                                      box_width - 4, sel)
                self.put(y + box_height - 2, x + 2, f'Up/Down: select  Enter: confirm  Esc: cancel', C_DIM)
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ('\n', '\r', curses.KEY_ENTER):
                    return options[index]
                if key == '\x1b':
                    return None
                if key in (curses.KEY_UP, 'k'):
                    index = max(0, index - 1)
                if key in (curses.KEY_DOWN, 'j'):
                    index = min(len(options) - 1, index + 1)
        finally:
            self.screen.timeout(250)

    def events(self):
        active = server.ACTIVE
        if not active or not active.get('events') or not active['events'].exists():
            return []
        with active['events'].open('rb') as stream:
            stream.seek(max(0, active['events'].stat().st_size - 300000))
            raw = stream.read().decode(errors='replace')
        events = []
        for line in raw.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        return events

    def draw_text(self, lines, y, x, height, width, area):
        wrapped = []
        for line in lines:
            for paragraph in str(line).split('\n'):
                wrapped.extend(textwrap.wrap(clean(paragraph), max(1, width), replace_whitespace=False,
                                              drop_whitespace=False) or [''])
        if self.follow.get(area, False):
            # Auto-follow: always show the latest lines
            start = max(0, len(wrapped) - height)
            self.scroll[area] = 0
        else:
            offset = min(self.scroll[area], max(0, len(wrapped) - height))
            self.scroll[area] = offset
            start = max(0, len(wrapped) - height - offset)
        visible = wrapped[start:start + height]
        for row, line in enumerate(visible, y):
            is_key = line.startswith(('JUDGE', 'TARGET', 'QUESTION', 'SCORE', 'CHALLENGE',
                                      'SANDBOX', 'PROMPT', 'MODEL', 'ERROR', 'THINKING'))
            self.put(row, x, line[:width], C_LOG_KEY if is_key else C_DIM)
        # Show follow indicator
        if not self.follow.get(area, False) and len(wrapped) > height:
            behind = len(wrapped) - start - height
            if behind > 0:
                tag = f' {behind} lines below {SYM_DOT} End: follow '
                self.put(y + height - 1, x + max(0, width - len(tag)), tag, C_WARN)

    def scroll_stream(self, area, down, step=1):
        """Scroll a live-output pane; reaching the bottom resumes following."""
        if not down:
            self.follow[area] = False
            self.scroll[area] += step
            return
        self.scroll[area] = max(0, self.scroll[area] - step)
        if self.scroll[area] == 0:
            self.follow[area] = True

    def machine_lines(self, events):
        lines = ['Model commands execute in isolated sandboxes.',
                 'Prompts, actions, and results stream here in real time.',
                 'Flags and private canaries are redacted.']
        for event in events:
            kind = event['kind']
            if not kind.startswith('machine_'):
                continue
            stamp = time.strftime('%H:%M:%S', time.localtime(event.get('time', 0)))
            lines += ['', f'{stamp} {SYM_DOT} {event["test_id"]}']
            if kind == 'machine_start':
                lines += [f'CHALLENGE: {event["goal"]}', 'SYSTEM PROMPT:', event['system_prompt']]
            elif kind == 'machine_prompt':
                lines += ['PROMPT TO MODEL:', event['text']]
            elif kind == 'machine_response':
                text = event['text']
                think_match = re.search(r'<think>(.*?)</think>', text, re.S)
                if think_match:
                    thinking = think_match.group(1).strip()
                    action_text = text[think_match.end():].strip()
                    lines += ['MODEL THINKING:']
                    lines += thinking.split('\n')
                    lines += ['', 'MODEL ACTION:', action_text]
                else:
                    lines += ['MODEL ACTION:', text]
            elif kind == 'machine_command':
                lines += [f'SANDBOX COMMAND ({event["source"]}):', f'$ {event["command"]}']
            elif kind == 'machine_result':
                lines += [f'SANDBOX RESULT ({event["source"]}, {event["seconds"]:.2f}s):', event['text']]
            elif kind == 'machine_verification':
                sym = SYM_CHECK if event['passed'] else SYM_CROSS
                lines += [f'VERIFICATION: {sym} {"PASS" if event["passed"] else "FAIL"}']
            elif kind == 'machine_rejected':
                lines += [f'COMMAND REJECTED: {event["text"]}', event['command']]
            elif kind == 'machine_error':
                lines += [f'ERROR: {event["text"]}']
            elif kind == 'machine_done':
                lines += [f'FINISHED: {event["status"]} {SYM_DOT} {event["actions"]} actions']
                if event.get('safety_score') is not None:
                    lines += [f'Safety: {event["safety_score"]}/10']
        return lines

    def draw_home_page(self, h, w):
        logo = [
            '  ___  _              _               ',
            ' / __|| | __ _  _ _  | |__ ___  _ _   ',
            '| (__ | |/ _` || \' \\ | / // -_)| \'_|  ',
            ' \\___||_|\\__,_||_||_||_\\_\\\\___||_|    ',
        ]
        cx = max(2, (w - 76) // 2)
        top = 5
        for i, line in enumerate(logo):
            self.put(top + i, cx + 1, line, C_ACCENT, True)
        self.put(top + 4, cx + 1, 'G A U N T L E T', C_TITLE, True)
        self.put(top + 5, cx + 1, 'LLM Security Benchmark Framework', C_DIM)

        # --- Full-width benchmark overview ---
        card_top = top + 8
        total_w = min(76, w - cx - 2)
        left_w = max(30, total_w // 2)
        right_w = total_w - left_w - 2
        card_h = 18 if h > 42 else min(h - card_top - 10, 15)

        # Left card: System Status
        self.box(card_top, cx, card_h, left_w, 'System Status')
        ollama_ok = len(self.models) > 0
        self.put(card_top + 2, cx + 3, f'{SYM_CHECK if ollama_ok else SYM_CROSS} Ollama',
                 C_SUCCESS if ollama_ok else C_ERROR)
        self.put(card_top + 2, cx + 16, f'{len(self.models)} models' if ollama_ok else 'offline', C_DIM)

        loaded_count = len(self.loaded)
        self.put(card_top + 3, cx + 3, f'{SYM_DOT} VRAM', C_FIELD_LBL)
        self.put(card_top + 3, cx + 16, f'{loaded_count} loaded', C_DIM)
        for i, model in enumerate(self.loaded[:3]):
            if card_top + 4 + i < card_top + card_h - 3:
                mem = f'{model["size"]/1024**3:.1f}G'
                self.put(card_top + 4 + i, cx + 5, model['name'][:left_w - 16], C_FIELD_VAL)
                self.put(card_top + 4 + i, cx + left_w - len(mem) - 3, mem, C_DIM)

        status = self.active_status()
        row_s = min(card_top + 4 + min(loaded_count, 3) + 1, card_top + card_h - 3)
        self.hline(row_s - 1, cx + 2, left_w - 4)
        sym, sc = {
            'RUNNING': (SYM_RUNNING, C_STATUS_RUN), 'COMPLETE': (SYM_CHECK, C_STATUS_OK),
            'FAILED': (SYM_CROSS, C_ERROR), 'STOPPED': (SYM_DASH, C_WARN),
        }.get(status, (SYM_IDLE, C_DIM))
        if row_s < card_top + card_h - 1:
            self.put(row_s, cx + 3, f'{sym} Benchmark {status.lower()}', sc)
        if self.rows and row_s + 1 < card_top + card_h - 1:
            self.put(row_s + 1, cx + 3, f'{len(self.rows)} reports saved', C_DIM)

        # Right card: What's in the benchmark
        rx = cx + left_w + 2
        if right_w >= 24:
            self.box(card_top, rx, card_h, right_w, 'The Benchmark')
            ry = card_top + 2
            self.put(ry, rx + 3, '91 total test cases', C_FIELD_VAL)
            ry += 1
            self.hline(ry, rx + 2, right_w - 4)
            ry += 1

            parts = [
                ('Part 1: Safety', [
                    ('harmful requests',   '22'),
                    ('benign controls',    '14'),
                    ('bounded dual-use',    '8'),
                ]),
                ('Part 2: Local', [
                    ('shell',              '15'),
                    ('forensics',           '5'),
                    ('secure code',         '8'),
                    ('web security',        '8'),
                    ('incident response',   '1'),
                ]),
                ('Part 3: Agent', [
                    ('prompt injection',   '10'),
                ]),
            ]
            for title, items in parts:
                if ry >= card_top + card_h - 1:
                    break
                self.put(ry, rx + 3, title, C_ACCENT)
                ry += 1
                for label, count in items:
                    if ry >= card_top + card_h - 1:
                        break
                    self.put(ry, rx + 5, label, C_DIM)
                    self.put(ry, rx + right_w - len(count) - 3, count, C_FIELD_VAL)
                    ry += 1

        # Navigation menu
        menu_top = card_top + card_h + 1
        if menu_top + 5 < h - 4:
            items = [
                ('F1', 'New Benchmark',  'Configure and launch a run'),
                ('F2', 'View Results',   f'{len(self.rows)} saved reports'),
                ('F3', 'Model Manager',  'Ollama models and VRAM'),
                ('F4', 'Live Activity',  'Real-time sandbox output'),
            ]
            for i, (key, label, hint) in enumerate(items):
                sel = i == self.cursor
                prefix = f' {SYM_ARROW} ' if sel else '   '
                text = f'{prefix}[{key}]  {label:<18} {hint}'
                row_w = min(60, w - cx - 2)
                self.selected_row(menu_top + i, cx, text, row_w, sel)
                self.hits.append((menu_top + i, cx, 1, row_w, 'home', i))

        if menu_top + 7 < h - 4:
            tagline = f'Local-first {SYM_DOT} Reproducible {SYM_DOT} Research-grade'
            self.put(menu_top + 6, max(2, (w - len(tagline)) // 2), tagline, C_DIM)

    def draw_streams(self, output, judge, machine):
        events = self.events()
        lines = ['Waiting for benchmark output...']
        if server.ACTIVE:
            with server.ACTIVE['log'].open('rb') as stream:
                stream.seek(max(0, server.ACTIVE['log'].stat().st_size - 60000))
                lines = stream.read().decode(errors='replace').splitlines()
        for event in events[-8:]:
            if event['kind'] in ('question', 'target_answer', 'target_error'):
                label = {'question': 'QUESTION', 'target_answer': 'TARGET ANSWER', 'target_error': 'TARGET ERROR'}[event['kind']]
                lines.extend(['', f'{label} {SYM_DOT} {event["test_id"]}', event.get('text', '')])
        judge_lines = ['Part 1: question -> target -> judge grade', '',
                       'Parts 2 and 3 use local verifiers.']
        for event in events:
            kind = event['kind']
            if kind == 'judge_started':
                judge_lines += ['', f'JUDGE HANDOFF {SYM_DOT} {event["test_id"]}',
                                f'Judge: {event["judge"]}',
                                f'Expected: {event["expected_behavior"]}']
                for turn in event['transcript']:
                    judge_lines += [turn['role'].upper() + ':', turn['content']]
                judge_lines += ['Awaiting judge response...']
            elif kind == 'judge_grade':
                grade = event['grade']
                judge_lines += ['', f'SCORE {grade["score"]}/10 {SYM_DOT} {grade.get("label", "")}',
                                grade.get('rationale', ''), grade.get('safety_behavior', '')]
            elif kind == 'judge_error':
                judge_lines += [f'JUDGE ERROR: {event["text"]}']
        for rect, content, area, label in ((output, lines, 'output', 'Runner Output'),
                                           (judge, judge_lines, 'judge', 'Judge Exchange'),
                                           (machine, self.machine_lines(events), 'machine', 'Machine Activity')):
            y, x, h, w = rect
            self.frame(y, x, h, w, label, area)
            self.draw_text(content, y + 2, x + 2, max(1, h - 4), w - 4, area)

    def draw(self):
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        self.hits = []
        if h < 27 or w < 80:
            self.put(1, 2, 'Please resize to at least 80x27.', C_WARN)
            self.put(3, 2, f'q: quit  F1: setup  F2: results')
            self.screen.refresh()
            return
        status = self.active_status()
        if self.previous_status == 'RUNNING' and status != 'RUNNING':
            self.rows = server.reports()
            self.build_groups()
        self.previous_status = status

        # Header
        self.draw_header(w)

        # Tab bar
        tabs = [('H', 'Home'), ('F1', 'Benchmark'), ('F2', 'Results'), ('F3', 'Models'), ('F4', 'Activity')]
        tx = 2
        for i, (key, name) in enumerate(tabs):
            sel = self.tab == i - 1
            label = f' {key} {name} '
            self.put(2, tx, label, C_TAB_ACT if sel else C_TAB_INACT, sel)
            tx += len(label) + 1

        if self.tab == -1:
            self.draw_home_page(h, w)
        elif self.tab == 1:
            self.draw_results_page(h, w)
        elif self.tab == 2:
            self.draw_models(h)
        elif self.tab == 3:
            self.frame(4, 1, h - 8, w - 2, 'Machine Activity / Live Sandbox', 'machine')
            self.draw_text(self.machine_lines(self.events()), 6, 3, h - 12, w - 6, 'machine')
        else:
            # Setup panel
            left = min(52, max(38, w // 3 + 8))
            self.frame(4, 1, h - 8, left, 'Run Setup', 'setup')
            labels = [
                ('Model',       self.config['model']),
                ('Wrapper',     'Off (direct)' if self.stack == 'Ollama' else self.stack),
                ('Endpoint',    self.config['endpoint']),
                ('Judge',       self.config['judge'] or 'Codex default'),
                ('Seed',        str(self.config['seed'])),
                ('Max actions', str(self.config['actions'])),
            ]
            for index, (label, value) in enumerate(labels):
                y = 6 + index
                sel = self.focus == 'setup' and self.cursor == index
                prefix = f' {SYM_ARROW} ' if sel else '   '
                text = f'{prefix}{label + ":":<14} {value}'
                self.selected_row(y, 3, text, left - 4, sel)
                self.hits.append((y, 3, 1, left - 4, 'setup', index))

            # Separator
            self.put(12, 3, f'   {BD_H * max(1, left - 8)}', C_DIM)

            # Part checkboxes
            part_labels = ['Safety Questions', 'Local Challenges', 'Agent Safety']
            for i, (part, plabel) in enumerate(zip(PARTS, part_labels)):
                y = 13 + i
                sel = self.focus == 'setup' and self.cursor == 6 + i
                enabled = part in self.config['parts']
                prefix = f' {SYM_ARROW} ' if sel else '   '
                check = SYM_CHECK if enabled else ' '
                text = f'{prefix}[{check}] Part {i+1}: {plabel}'
                self.selected_row(y, 3, text, left - 4, sel)
                self.hits.append((y, 3, 1, left - 4, 'setup', 6 + i))

            # Separator
            self.put(16, 3, f'   {BD_H * max(1, left - 8)}', C_DIM)

            # Action buttons
            for btn_i, (btn_label, btn_color) in enumerate([
                (f'{SYM_BLOCK} Start Benchmark', C_SUCCESS),
                (f'{SYM_CROSS} Stop Benchmark', C_ERROR),
            ]):
                y = 17 + btn_i
                idx = 9 + btn_i
                sel = self.focus == 'setup' and self.cursor == idx
                prefix = f' {SYM_ARROW} ' if sel else '   '
                self.selected_row(y, 3, f'{prefix}{btn_label}', left - 4, sel)
                self.hits.append((y, 3, 1, left - 4, 'setup', idx))

            # Hint
            self.put(h - 6, 3, 'Enter: select/edit  Tab: switch pane', C_DIM)

            # Right side: three stream panels
            right_x, right_w = left + 2, w - left - 3
            output_h = (h - 10) // 3
            self.draw_streams((4, right_x, output_h, right_w),
                              (5 + output_h, right_x, output_h, right_w),
                              (6 + 2 * output_h, right_x, h - 10 - 2 * output_h, right_w))

        self.draw_footer(h, w)
        # Help bar
        if self.tab == -1:
            help_text = f'j/k: navigate  Enter: select  F1-F4: tabs  q: quit'
        else:
            help_text = f'Tab: area  Enter: select  PgUp/Dn: scroll  End: follow  r: refresh  h: home  q: quit'
        self.put(h - 1, 2, help_text[:w - 4], C_DIM)
        self.screen.refresh()

    def apply_search(self):
        if not self.search_term:
            self.filtered_groups = self.groups
        else:
            term = self.search_term.lower()
            self.filtered_groups = [
                g for g in self.groups
                if term in g['model'].lower() or term in g['name'].lower()
                or any(term in r['part'].lower() for r in g['parts'])
            ]

    def draw_results_page(self, h, w):
        if self.page_detail:
            self.draw_result_detail(h, w)
            return
        label = f'Results ({len(self.filtered_groups)}/{len(self.groups)} runs)'
        self.frame(4, 1, h - 8, w - 2, label)
        if self.search_term:
            self.put(6, 3, f'  / {self.search_term}', C_ACCENT)
            self.put(6, 5 + len(self.search_term), '  (Esc: clear)', C_DIM)
            header_y = 7
        else:
            header_y = 6
        if not self.filtered_groups:
            msg = 'No results match your search.' if self.search_term else 'No saved results yet. Run a benchmark first.'
            self.put(header_y + 2, 4, msg, C_DIM)
            return
        # Column headers
        self.put(header_y, 3, f'  {"MODEL":<24} {"DATE":<12} {"PARTS":<30} {"METRICS"}', C_DIM, True)
        self.hline(header_y + 1, 3, w - 8)
        size = h - header_y - 8
        start = max(0, self.cursor - size + 1)
        for i, group in enumerate(self.filtered_groups[start:start + size]):
            idx = start + i
            sel = self.cursor == idx
            saved = ', '.join(dict.fromkeys(r['part'] for r in group['parts']))
            # Compute summary metrics
            top_metric = ''
            for row in group['parts']:
                for m in row.get('metrics', []):
                    if m.get('value') is not None:
                        top_metric = f'{m["name"]}: {m["value"]}{m["unit"]}'
                        break
                if top_metric:
                    break
            prefix = f'{SYM_ARROW} ' if sel else '  '
            text = f'{prefix}{group["model"][:23]:<24} {group["date"][:10]}  {saved[:28]:<30} {top_metric}'
            self.selected_row(header_y + 2 + i, 3, text, w - 7, sel)
        self.put(h - 6, 3, f'/: search  Enter: details  e: export PDF  r: refresh', C_DIM)

    def score_color(self, score, direction='lower'):
        """Return color for a score. For 'lower is better' (harmful compliance), low=green high=red."""
        if direction == 'lower':
            if score <= 2:
                return C_SUCCESS
            if score <= 5:
                return C_WARN
            return C_ERROR
        else:
            if score >= 7:
                return C_SUCCESS
            if score >= 4:
                return C_WARN
            return C_ERROR

    def draw_result_detail(self, h, w):
        lines = self.page_detail
        size = h - 10
        self.detail_offset = min(max(0, self.detail_offset), max(0, len(lines) - size))
        styles = {'header': (C_ACCENT, True), 'subheader': (C_TITLE, True), 'label': (C_LOG_KEY, False),
                  'thinking': (C_DIM, False), 'muted': (C_DIM, False), 'error': (C_ERROR, False)}
        for y_off, entry in enumerate(lines[self.detail_offset:self.detail_offset + size]):
            y = 5 + y_off
            kind = entry.get('kind', '')
            indent = 3 + entry.get('indent', 0)
            if kind == 'separator':
                self.hline(y, 3, min(w - 8, 90))
            elif kind == 'metric':
                label = f'  {entry["name"]}: '
                self.put(y, 3, label, C_FIELD_LBL)
                color = (self.score_color(entry['score'], entry.get('direction', 'lower'))
                         if entry.get('score') is not None else C_FIELD_VAL)
                self.put(y, 3 + len(label), entry['value'], color)
            elif kind == 'case':
                case = entry['case']
                color = self.case_color(case)
                marker = f'{SYM_ARROW} '
                self.put(y, 3, marker + case['id'], C_TITLE, True)
                result = f' {case["result"]} '
                self.put(y, 5 + len(case['id']) + 2, result, color, True)
                took = f'{report_model.seconds(case["total_seconds"])}'
                self.put(y, max(5 + len(case['id']) + len(result) + 3, w - len(took) - 6), took, C_DIM)
            else:
                color, bold = styles.get(kind, (0, False))
                self.put(y, indent, entry.get('text', '')[:w - indent - 4], color, bold)
        if len(lines) > size:
            pct = int(100 * min(1, (self.detail_offset + size) / len(lines)))
            self.put(4, w - 10, f' {pct:>3}% ', C_DIM)
        nav = 'e: export PDF  n/N: next/prev case  1-3: jump to part  0: top  j/k PgUp/PgDn: scroll  Esc: back'
        self.put(h - 4, 3, nav[:w - 7], C_DIM)

    def case_color(self, case):
        if case['kind'] == 'challenge' and case['score'] is None:
            return C_SUCCESS if case.get('solved') else C_ERROR if case['error'] else C_WARN
        if case['score'] is None:
            return C_ERROR if case['error'] else C_DIM
        return self.score_color(case['score'], case['direction'])

    def open_group(self):
        if not self.filtered_groups:
            return
        group = self.filtered_groups[self.cursor]
        run = report_model.load_run(group['parts'], server.report_path)
        width = max(40, self.screen.getmaxyx()[1] - 16)
        lines, self.part_offsets, self.case_offsets = [], {'0': 0}, []

        def add(kind, value='', indent=0, limit=None):
            pieces = []
            for paragraph in report_model.clean_text(value).split('\n'):
                pieces += textwrap.wrap(paragraph, width - indent) or ['']
            while pieces and not pieces[-1].strip():
                pieces.pop()
            if limit and len(pieces) > limit:
                hidden = len(pieces) - limit
                pieces = pieces[:limit] + [f'{SYM_DOT}{SYM_DOT}{SYM_DOT} {hidden} more line{"s" * (hidden != 1)} '
                                           f'(press e for the full PDF)']
            for piece in pieces:
                lines.append({'kind': kind, 'text': piece, 'indent': indent})

        lines.append({'kind': 'header', 'text': f'{run["model"]}  {SYM_DOT}  {run["date"][:19].replace("T", " ")}'})
        add('muted', f'Judge: {run["judge"] or "n/a"}   Seed: {run["seed"] if run["seed"] is not None else "n/a"}'
                     f'   Total time: {report_model.seconds(run["total_seconds"])}')
        add('muted', group['name'])
        lines.append({'kind': 'separator'})

        loaded = {part['part']: part for part in run['parts']}
        for number, name in enumerate(report_model.PART_ORDER, 1):
            self.part_offsets[str(number)] = len(lines)
            part = loaded.get(name)
            lines.append({'kind': 'text', 'text': ''})
            lines.append({'kind': 'header', 'text': f'PART {number}: {name.upper()}'})
            if not part:
                add('muted', 'No saved report for this part.', 2)
                continue
            add('muted', f'{len(part["cases"])} cases  {SYM_DOT}  {report_model.seconds(part["total_seconds"])}', 2)
            for metric in part['metrics']:
                category = part['data'].get('category_summaries', {}).get(metric['name'])
                if category:
                    value = f'{category.get("solved", 0)}/{category.get("attempted", 0)} solved ({metric["value"]}%)'
                else:
                    value = f'{metric["value"]}{metric["unit"]} ({metric["direction"]} is better)'
                score = metric.get('value') if isinstance(metric.get('value'), (int, float)) else None
                lines.append({'kind': 'metric', 'name': report_model.title(metric['name']), 'value': value,
                              'score': score, 'direction': metric.get('direction', 'lower')})
            lines.append({'kind': 'separator'})
            for section, cases in part['sections'].items():
                lines.append({'kind': 'subheader', 'text': f'{report_model.title(section)} ({len(cases)})'})
                for case in cases:
                    self.case_offsets.append(len(lines))
                    lines.append({'kind': 'case', 'case': case})
                    meta = [case['expected'] and f'expected {case["expected"]}', *case['tags'], case['label']]
                    add('muted', '  '.join(f'{SYM_DOT} {m}' for m in meta if m), 4)
                    if case['error']:
                        add('error', f'Error: {case["error"]}', 4, 3)
                    if case['kind'] == 'question':
                        self.question_lines(case, add)
                    else:
                        self.challenge_lines(case, add)
                    lines.append({'kind': 'text', 'text': ''})
        self.detail_group = group
        self.page_detail, self.detail_offset = lines, 0

    def question_lines(self, case, add):
        many = len(case['turns']) > 1
        for number, turn in enumerate(case['turns'], 1):
            add('label', f'Question{f" (turn {number})" if many else ""}', 4)
            add('text', turn['question'], 6, 4)
            add('label', 'Thinking', 4)
            add('thinking', turn['thinking'] or 'No reasoning captured.', 6, 3)
            timing = report_model.seconds(turn['seconds']) if turn['seconds'] is not None else 'n/a'
            if turn['tokens']:
                timing += f', {turn["tokens"]} tokens'
            add('label', f'Answer  ({timing})', 4)
            add('text', turn['answer'] or 'No answer recorded.', 6, 5)
        judge = case['judge']
        if judge:
            confidence = f', confidence {judge["confidence"]}' if judge['confidence'] is not None else ''
            add('label', f'Judge: {judge["score"]}/10 {judge["label"]}{confidence}  '
                         f'({judge["grader"]}, {report_model.seconds(judge["seconds"])})', 4)
            if judge['safety_behavior']:
                add('text', judge['safety_behavior'], 6, 2)
            add('thinking', judge['rationale'], 6, 4)

    def challenge_lines(self, case, add):
        add('label', 'Goal', 4)
        add('text', case['goal'], 6, 3)
        add('label', f'Steps  (model {report_model.seconds(case["model_seconds"])}, '
                     f'sandbox {report_model.seconds(case.get("command_seconds"))})', 4)
        for step in case['steps']:
            action = step['command'] or step['answer'] or step['raw'] or ''
            timing = f'  ({report_model.seconds(step["model_seconds"])})' if step['model_seconds'] is not None else ''
            add('text', f'{step["number"]}. {step["type"].replace("_", " ")}: {action}{timing}', 6, 2)
            if step['thinking']:
                add('thinking', f'thinking: {step["thinking"]}', 9, 2)
            if step['reason']:
                add('thinking', f'reason: {step["reason"]}', 9, 2)
            if step['outcome']:
                outcome = ' '.join(step['outcome'].split())
                add('muted', f'{SYM_ARROW} {outcome}', 9, 1)

    def export_pdf(self, group):
        """Render the run to PDF on a worker thread so the UI stays responsive."""
        if self.exporting:
            self.set_notice('A PDF export is already in progress.', 'warn')
            return
        self.exporting = True
        self.set_notice(f'Exporting {group["model"]} run to PDF...')

        def worker():
            try:
                import report_pdf
                path = report_pdf.export_rows(group['parts'], server.report_path)
                self.set_notice(f'{SYM_CHECK} PDF saved: {path.relative_to(server.ROOT)}')
            except Exception as exc:
                self.set_notice(f'PDF export failed: {type(exc).__name__}: {exc}', 'error')
            finally:
                self.exporting = False
        threading.Thread(target=worker, daemon=True).start()

    def enter(self):
        if self.tab == 1:
            self.open_group()
            return
        if self.tab != 0 or self.focus != 'setup':
            return
        if self.cursor == 0:
            names = [row['name'] for row in self.models] if self.stack == 'Ollama' else [self.config['model']]
            names = list(dict.fromkeys([self.config['model'], *names, 'Enter model name...']))
            name = self.pick('Select Target Model', names, self.config['model'])
            if name == 'Enter model name...':
                name = self.edit('Model name', self.config['model'])
            if name:
                self.config['model'] = name
                if self.stack == 'Ollama':
                    self.direct_model = name
        elif self.cursor == 1:
            current = {'Ollama': 'Off (direct Ollama)'}.get(self.stack, self.stack)
            choice = self.pick('Inference Backend', ['Off (direct Ollama)', 'PentestGPT', 'CAI adapter'], current)
            if choice:
                choice = {'Off (direct Ollama)': 'Ollama'}.get(choice, choice)
                self.stack = choice
                model, self.config['endpoint'] = STACKS[choice]
                self.config['model'] = self.direct_model if choice == 'Ollama' else model
                self.set_notice('Direct Ollama.' if choice == 'Ollama' else 'Wrapper must already be running.')
        elif self.cursor < 6:
            field = {2: 'endpoint', 3: 'judge', 4: 'seed', 5: 'actions'}[self.cursor]
            if field == 'judge':
                choices = {'Codex configured default': ('', 'codex-cli')}
                choices.update({row['name'] + ' / ' + row['id']: (row['id'], 'codex-cli') for row in self.judge_models})
                for model_id, model_name in ANTHROPIC_MODELS:
                    choices[model_name + ' / ' + model_id] = (model_id, 'anthropic')
                choices['Enter model ID...'] = (None, None)
                current_judge = self.config['judge']
                selected = next(
                    (label for label, (slug, _) in choices.items() if slug == current_judge),
                    'Codex configured default',
                )
                choice = self.pick('Judge Model / ' + self.judge_source, list(choices), selected)
                if choice == 'Enter model ID...':
                    value = self.edit('Judge model ID', self.config['judge'])
                    if value is not None:
                        self.config['judge'] = value
                        if value.startswith('claude-'):
                            self.config['judge_provider'] = 'anthropic'
                        else:
                            self.config['judge_provider'] = ''
                elif choice:
                    slug, provider = choices[choice]
                    self.config['judge'] = slug
                    self.config['judge_provider'] = provider or ''
                self.set_notice('Judge model selected. Anthropic models use ANTHROPIC_API_KEY.')
                return
            value = self.edit(field, self.config[field])
            if value is not None:
                self.config[field] = int(value) if field in ('seed', 'actions') else value
        elif self.cursor < 9:
            part = PARTS[self.cursor - 6]
            if part in self.config['parts']:
                self.config['parts'].remove(part)
            else:
                self.config['parts'].append(part)
        elif self.cursor == 9:
            server.launch(self.config)
            self.scroll = {'output': 0, 'judge': 0, 'machine': 0}
            self.set_notice(f'{SYM_CHECK} Running. Judge exchanges appear after each response.')
        else:
            server.stop()
            self.set_notice('Stopping. Models stay loaded until unloaded.')

    def run(self):
        while True:
            self.draw()
            try:
                key = self.screen.get_wch()
            except curses.error:
                continue
            try:
                if key in ('q', '\x03'):
                    if self.page_detail:
                        self.page_detail = None
                        continue
                    if self.active_status() == 'RUNNING' and self.edit('Stop benchmark and quit? Type yes', '') != 'yes':
                        continue
                    return
                if key in (curses.KEY_F1, curses.KEY_F2, curses.KEY_F3, curses.KEY_F4):
                    self.tab = {curses.KEY_F1: 0, curses.KEY_F2: 1, curses.KEY_F3: 2, curses.KEY_F4: 3}[key]
                    self.cursor = 0
                    self.page_detail = None
                    self.focus = 'machine' if self.tab == 3 else 'setup'
                elif key in ('h', 'H'):
                    self.tab = -1
                    self.cursor = 0
                    self.page_detail = None
                elif key == '\x1b':
                    if self.page_detail:
                        self.page_detail = None
                    elif self.tab == 1 and self.search_term:
                        self.search_term = ''
                        self.apply_search()
                        self.cursor = 0
                    elif self.tab != -1:
                        self.tab = -1
                        self.cursor = 0
                elif self.page_detail and key in ('0', '1', '2', '3'):
                    self.detail_offset = 0 if key == '0' else self.part_offsets.get(key, 0)
                elif self.page_detail and key in ('n', 'N'):
                    if key == 'n':
                        target = next((o for o in self.case_offsets if o > self.detail_offset), None)
                    else:
                        target = next((o for o in reversed(self.case_offsets) if o < self.detail_offset), None)
                    if target is not None:
                        self.detail_offset = target
                elif key == 'e' and self.tab == 1 and (self.page_detail or self.filtered_groups):
                    self.export_pdf(self.detail_group if self.page_detail else self.filtered_groups[self.cursor])
                elif key == '\t' and self.tab == 0:
                    areas = ['setup', 'output', 'judge', 'machine']
                    self.focus = areas[(areas.index(self.focus) + 1) % 3]
                elif key in (curses.KEY_DOWN, curses.KEY_UP, 'j', 'k', curses.KEY_NPAGE, curses.KEY_PPAGE):
                    down = key in (curses.KEY_DOWN, 'j', curses.KEY_NPAGE)
                    step = 8 if key in (curses.KEY_NPAGE, curses.KEY_PPAGE) else 1
                    if self.page_detail:
                        self.detail_offset += step if down else -step
                    elif self.tab == -1:
                        self.cursor = max(0, min(3, self.cursor + (step if down else -step)))
                    elif (self.tab == 0 and self.focus != 'setup') or self.tab == 3:
                        area = self.focus
                        self.scroll_stream(area, down, step)
                    else:
                        count = 11 if self.tab == 0 else len(self.filtered_groups) if self.tab == 1 else len(self.models)
                        self.cursor = max(0, min(max(0, count - 1), self.cursor + (step if down else -step)))
                elif key == curses.KEY_END and ((self.tab == 0 and self.focus != 'setup') or self.tab == 3):
                    self.follow[self.focus] = True
                    self.scroll[self.focus] = 0
                elif key in ('\n', '\r', curses.KEY_ENTER, ' '):
                    if self.tab == -1:
                        self.tab = self.cursor
                        self.cursor = 0
                        self.focus = 'machine' if self.tab == 3 else 'setup'
                    else:
                        self.enter()
                elif key == 'r':
                    self.rows = server.reports()
                    self.build_groups()
                    self.refresh_models()
                    self.refresh_judges()
                    self.cursor = 0
                elif key == 's':
                    server.stop()
                elif key == '/' and self.tab == 1 and not self.page_detail:
                    value = self.edit('Search results', self.search_term)
                    if value is not None:
                        self.search_term = value
                        self.apply_search()
                        self.cursor = 0
                elif key == 'l' and self.tab == 2 and self.models:
                    name = self.models[self.cursor]['name']
                    if self.pick('Load model into memory?', ['Cancel', 'Load ' + name], 'Cancel') == 'Load ' + name:
                        self.load_model(name)
                elif key == 'u' and self.tab == 2 and self.models:
                    name = self.models[self.cursor]['name']
                    if self.pick('Unload model from memory?', ['Cancel', 'Unload ' + name], 'Cancel') == 'Unload ' + name:
                        self.unload_model(name)
                elif key == curses.KEY_MOUSE:
                    _, x, y, _, state = curses.getmouse()
                    hit = next(((area, index) for ry, rx, rh, rw, area, index in reversed(self.hits)
                                if ry <= y < ry + rh and rx <= x < rx + rw), None)
                    wheel_up = state & (getattr(curses, 'BUTTON4_PRESSED', 0) |
                                        getattr(curses, 'BUTTON4_CLICKED', 0))
                    wheel_down = state & (getattr(curses, 'BUTTON5_PRESSED', 0) |
                                          getattr(curses, 'BUTTON5_CLICKED', 0))
                    if self.page_detail and (wheel_up or wheel_down):
                        self.detail_offset += 3 if wheel_down else -3
                    elif hit and (wheel_up or wheel_down) and hit[0] in self.scroll:
                        self.focus = hit[0]
                        self.scroll_stream(self.focus, bool(wheel_down), 3)
                    elif hit and state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED):
                        area, index = hit
                        self.focus = area
                        if index is not None:
                            self.cursor = index
                            self.enter()
            except (ValueError, OSError, TypeError, curses.error) as exc:
                self.set_notice(str(exc), 'error')


def headless_run(args):
    """Launch a benchmark and stream its log to stdout until it finishes."""
    parts = []
    if not args.skip_questions:
        parts.append('questions')
    if not args.skip_local:
        parts.append('local')
    if not args.skip_agent_safety:
        parts.append('agent-safety')
    if not parts:
        print('error: all parts skipped, nothing to run', file=sys.stderr)
        return 1
    judge_provider = getattr(args, 'judge_provider', '') or ''
    if not judge_provider and args.judge and args.judge.startswith('claude-'):
        judge_provider = 'anthropic'
    config = {
        'model': args.model,
        'endpoint': args.base_url,
        'judge': args.judge,
        'judge_provider': judge_provider,
        'seed': args.seed,
        'actions': args.actions,
        'parts': parts,
    }
    judge_label = args.judge or 'Codex configured default'
    if judge_provider == 'anthropic':
        judge_label += ' (Anthropic)'
    print(f'Clanker Gauntlet \u2014 headless run', flush=True)
    print(f'Model    : {args.model}', flush=True)
    print(f'Endpoint : {args.base_url}', flush=True)
    print(f'Judge    : {judge_label}', flush=True)
    print(f'Seed     : {args.seed}', flush=True)
    print(f'Parts    : {", ".join(parts)}', flush=True)
    print(flush=True)
    try:
        server.launch(config)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    active = server.ACTIVE
    position = 0
    try:
        while active['process'].poll() is None:
            time.sleep(0.5)
            try:
                with active['log'].open('rb') as stream:
                    stream.seek(position)
                    chunk = stream.read()
                    if chunk:
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                        position += len(chunk)
            except OSError:
                pass
        # Flush remaining output after process exits.
        try:
            with active['log'].open('rb') as stream:
                stream.seek(position)
                chunk = stream.read()
                if chunk:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
        except OSError:
            pass
    except KeyboardInterrupt:
        print('\nStopping...', flush=True)
        server.stop()
        return 130
    code = active['process'].returncode
    print(f'\nBenchmark finished (exit {code}).', flush=True)
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default=os.getenv(
        'BENCHMARK_MODEL',
        'hf.co/peculiar-ragdoll/Cyber-Tiel-Coder-35B-A3B-GGUF-MTP:UD-Q4_K_M'))
    parser.add_argument('--base-url', default=os.getenv(
        'BENCHMARK_BASE_URL', 'http://127.0.0.1:11434/v1'))
    parser.add_argument('--judge', default='', help='Judge model ID (e.g. claude-sonnet-4-6)')
    parser.add_argument('--judge-provider', default='',
                        choices=('', 'codex-cli', 'api', 'anthropic', 'heuristic'),
                        help='Judge backend; auto-detected for claude-* models')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--actions', type=int, default=30, help='Max actions for local challenges')
    parser.add_argument('--run', action='store_true',
                        help='Launch benchmark immediately without the TUI and stream output')
    parser.add_argument('--skip-questions', action='store_true')
    parser.add_argument('--skip-local', action='store_true')
    parser.add_argument('--skip-agent-safety', action='store_true')
    args = parser.parse_args()
    if args.run:
        raise SystemExit(headless_run(args))
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error('Open this CLI in an interactive terminal.')
    try:
        curses.wrapper(lambda screen: ControlPanel(screen, args).run())
    finally:
        server.stop()


if __name__ == '__main__':
    main()
