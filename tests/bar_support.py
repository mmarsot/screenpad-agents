"""A stand-in for the touch bar daemon's side of the app socket, for the
agent app's tests: it checks every message the app sends against the app
protocol, version 2, as screenpad-linux's docs/app-api.md gives it, and lets
a test touch the app's tiles and widgets and answer its questions.

The daemon lives in screenpad-linux, so this is its shape only: the same
messages, limits and replies, written out here (not taken from the client
library, so the app is checked against the protocol rather than against its
own library). It draws nothing, arms nothing and grows no card.

  Apps        the apps on the socket: hello and welcome, tiles, pages,
              questions, and touches sent to them (press, event)
  AppServer   the listening socket that hands Apps each line
  FakeClient  an app as Apps sees it, without a socket
  pump        one turn of the server
"""

import json
import os
import re
import select
import socket

PROTOCOL = 2
MIN_PROTOCOL = 1
MAX_LINE = 16384
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
TONES = ("neutral", "accept", "reject", "warning")
TOUCHES = ("tap", "long", "none")
MAX_TILES = 8
MAX_PAGES = 4
MAX_COLUMNS = 6
MAX_ROWS = 4
MAX_WIDGETS = 24
MAX_LINES = 16
MAX_LINE_CHARS = 120
MAX_OPTIONS = 3
MAX_ASK_TIMEOUT = 3600
PAGE_FIELDS = {"page", "title", "text", "icon", "badge", "tone", "columns", "rows", "widgets"}
WIDGET_FIELDS = {"id", "col", "row", "cols", "rows", "label", "text", "lines", "icon", "badge", "tone", "touch"}


class ProtocolError(Exception):
    """A message refused; fields go into the error sent back."""

    def __init__(self, message, **fields):
        super().__init__(message)
        self.fields = fields


def known_fields(msg, allowed):
    unknown = set(msg) - allowed - {"op"}
    if unknown:
        raise ProtocolError("unknown field(s): %s" % ", ".join(sorted(unknown)))


def text_field(value, what, limit, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or not value.isprintable():
        raise ProtocolError("%s must be printable text of 1 to %d characters" % (what, limit))
    return value.strip()


def int_field(value, what, low, high, default=None):
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ProtocolError("%s must be a whole number from %d to %d" % (what, low, high))
    return value


def look_fields(msg, limits):
    """The tone, icon and text fields (limits: name -> length) of a message."""
    tone = msg.get("tone", "neutral")
    if tone not in TONES:
        raise ProtocolError("tone must be one of %s" % ", ".join(TONES))
    look = {"tone": tone}
    icon = msg.get("icon")
    if icon is not None:
        if not isinstance(icon, str) or not (
            re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", icon) or (icon.startswith("/") and icon.isprintable())
        ):
            raise ProtocolError("icon must be an icon name or an absolute image path")
        look["icon"] = icon
    for key, limit in limits.items():
        value = text_field(msg.get(key), key, limit, required=False)
        if value:
            look[key] = value
    return look


class Widget:
    """One widget of a page: its cells, what it shows and what a touch does."""

    def __init__(self, id, col, row, cols, rows, look, touch):
        self.id, self.col, self.row, self.cols, self.rows = id, col, row, cols, rows
        self.look, self.touch = look, touch


class Page:
    """An app's page for the apps page."""

    def __init__(self, client, name, look, columns, rows, widgets):
        self.client, self.name, self.look = client, name, look
        self.columns, self.rows, self.widgets = columns, rows, widgets


def parse_widget(msg, columns, rows):
    if not isinstance(msg, dict):
        raise ProtocolError("each widget is an object with an id")
    known_fields(msg, WIDGET_FIELDS)
    wid = msg.get("id")
    if not isinstance(wid, str) or not ID.fullmatch(wid):
        raise ProtocolError("widget id must be a name (letters, digits, . _ -, at most 32)")
    col = int_field(msg.get("col"), "col", 0, columns - 1)
    row = int_field(msg.get("row"), "row", 0, rows - 1)
    cols = int_field(msg.get("cols"), "cols", 1, columns - col, default=1)
    nrows = int_field(msg.get("rows"), "rows", 1, rows - row, default=1)
    look = look_fields(msg, {"label": 32, "text": 200, "badge": 4})
    lines = msg.get("lines")
    if lines is not None:
        if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
            raise ProtocolError("lines must be a list of 1 to %d lines" % MAX_LINES)
        for line in lines:
            if not isinstance(line, str) or len(line) > MAX_LINE_CHARS or not line.isprintable():
                raise ProtocolError("each line must be printable text of at most %d characters" % MAX_LINE_CHARS)
        look["lines"] = [line.rstrip() for line in lines]
    if len(look) == 1:
        raise ProtocolError("widget %s shows nothing: give it a label, text, lines or an icon" % wid)
    touch = msg.get("touch", "tap")
    if touch not in TOUCHES:
        raise ProtocolError("touch must be one of %s" % ", ".join(TOUCHES))
    return Widget(wid, col, row, cols, nrows, look, touch)


def parse_page(client, msg):
    known_fields(msg, PAGE_FIELDS)
    name = msg.get("page")
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ProtocolError("page must be a name (lower case, at most 32)")
    look = look_fields(msg, {"title": 32, "text": 48, "badge": 4})
    columns = int_field(msg.get("columns"), "columns", 1, MAX_COLUMNS, default=4)
    rows = int_field(msg.get("rows"), "rows", 1, MAX_ROWS, default=2)
    widgets = msg.get("widgets", [])
    if not isinstance(widgets, list) or len(widgets) > MAX_WIDGETS:
        raise ProtocolError("widgets must be a list of at most %d widgets" % MAX_WIDGETS)
    clean: list[Widget] = []
    taken: set[tuple[int, int]] = set()
    for w in widgets:
        widget = parse_widget(w, columns, rows)
        if widget.id in [c.id for c in clean]:
            raise ProtocolError("widget id %s appears twice" % widget.id)
        cells = {
            (c, r)
            for c in range(widget.col, widget.col + widget.cols)
            for r in range(widget.row, widget.row + widget.rows)
        }
        if cells & taken:
            raise ProtocolError("widget %s overlaps another" % widget.id)
        taken |= cells
        clean.append(widget)
    return Page(client, name, look, columns, rows, clean)


class Ask:
    """A question an app asked."""

    def __init__(self, client, id, title, text, options):
        self.client, self.id, self.title, self.text, self.options = client, id, title, text, options


def parse_ask(client, msg):
    known_fields(msg, {"id", "title", "text", "options", "timeout"})
    ask_id = msg.get("id")
    if not isinstance(ask_id, str) or not ID.fullmatch(ask_id):
        raise ProtocolError("id must be a name (letters, digits, . _ -, at most 32)")
    title = text_field(msg.get("title"), "title", 80)
    text = text_field(msg.get("text"), "text", 200, required=False)
    options = msg.get("options")
    if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
        raise ProtocolError("options must be a list of 1 to %d answers" % MAX_OPTIONS)
    clean: list[dict] = []
    for o in options:
        if not isinstance(o, dict):
            raise ProtocolError("each option is an object with id and label")
        known_fields(o, {"id", "label", "tone"})
        if not isinstance(o.get("id"), str) or not ID.fullmatch(o["id"]) or o["id"] in [c["id"] for c in clean]:
            raise ProtocolError("option ids must be distinct names")
        tone = o.get("tone", "neutral")
        if tone not in TONES:
            raise ProtocolError("tone must be one of %s" % ", ".join(TONES))
        clean.append({"id": o["id"], "label": text_field(o.get("label"), "option label", 24), "tone": tone})
    timeout = msg.get("timeout", 60)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= MAX_ASK_TIMEOUT:
        raise ProtocolError("timeout must be 1 to %d seconds" % MAX_ASK_TIMEOUT)
    return Ask(client, ask_id, title, text, clean)


class Asks:
    """The questions waiting, first one shown. While the bar cannot show
    questions (available False, as at first), one is answered "unavailable"
    at once."""

    def __init__(self):
        self.queue: list[Ask] = []
        self.available = False

    def find(self, client, ask_id):
        return next((a for a in self.queue if a.client is client and a.id == ask_id), None)

    def add(self, ask):
        if self.find(ask.client, ask.id):
            raise ProtocolError("question %s is already waiting" % ask.id)
        if not self.available:
            self._reply(ask, None, "unavailable")
        else:
            self.queue.append(ask)

    def choose(self, ask, k):
        self._finish(ask, ask.options[k]["id"], "chosen")

    def cancel(self, client, ask_id):
        ask = self.find(client, ask_id)
        if ask is None:
            return False
        self._finish(ask, None, "cancelled")
        return True

    def drop(self, client):
        for a in [a for a in self.queue if a.client is client]:
            self.queue.remove(a)

    def set_available(self, ok):
        self.available = ok
        if not ok:
            for a in list(self.queue):
                self._finish(a, None, "unavailable")

    def _finish(self, ask, option, reason):
        self.queue.remove(ask)
        self._reply(ask, option, reason)

    @staticmethod
    def _reply(ask, option, reason):
        ask.client.send({"op": "answer", "id": ask.id, "option": option, "reason": reason})


class Apps:
    """The apps on the socket: who provides which tile and page, and their
    questions. A tile or page belongs to the first app that provides it."""

    def __init__(self):
        self.clients: list = []
        self.owner: dict = {}  # tile name -> client
        self.look: dict = {}  # tile name -> what it shows
        self.placed: set = set()  # tile names the config gives a spot
        self.pages: dict = {}  # page name -> Page
        self.asks = Asks()

    def connect(self, client):
        client.name, client.protocol = None, None
        self.clients.append(client)
        return True

    def disconnect(self, client):
        if client not in self.clients:
            return
        self.clients.remove(client)
        self.asks.drop(client)
        for name in [n for n, c in self.owner.items() if c is client]:
            del self.owner[name]
            self.look.pop(name, None)
        for name in [n for n, p in self.pages.items() if p.client is client]:
            del self.pages[name]

    def set_placed(self, names):
        self.placed = set(names)

    def provided(self):
        """What each provided tile shows."""
        return {name: self.look.get(name, {}) for name in self.owner}

    def event(self, name, kind, inside=None):
        """A touch on a tile: "down", then "up" with inside."""
        client = self.owner.get(name)
        if client is None:
            return
        msg = {"op": "event", "tile": name, "type": kind}
        if inside is not None:
            msg["inside"] = inside
        client.send(msg)

    def press(self, client, page, widget, kind):
        """A touch on a widget of client's page: "down", then "tap", "long" or "cancel"."""
        if client in self.clients:
            client.send({"op": "event", "page": page, "widget": widget, "type": kind})

    def handle(self, client, msg):
        """One message from an app; errors go back to it."""
        op = msg.get("op") if isinstance(msg, dict) else None
        try:
            if op == "ping":
                client.send({"op": "pong"})
            elif op == "hello":
                self._hello(client, msg)
            elif client.name is None:
                raise ProtocolError("say hello first")
            elif op == "set":
                self._set(client, msg)
            elif op == "ask":
                self.asks.add(parse_ask(client, msg))
            elif op == "page":
                self._page(client, msg)
            elif op == "unpage":
                known_fields(msg, {"page"})
                page = self.pages.get(msg.get("page"))
                if page is None or page.client is not client:
                    raise ProtocolError("page %r is not yours" % msg.get("page"))
                del self.pages[page.name]
            elif op == "cancel":
                known_fields(msg, {"id"})
                if not self.asks.cancel(client, msg.get("id")):
                    raise ProtocolError("no waiting question %r" % msg.get("id"))
            else:
                raise ProtocolError("unknown op %r" % op)
        except ProtocolError as e:
            reply = {"op": "error", "request": op if isinstance(op, str) else None, "message": str(e), **e.fields}
            if isinstance(msg, dict) and isinstance(msg.get("id"), str):
                reply["id"] = msg["id"]
            client.send(reply)

    def _hello(self, client, msg):
        known_fields(msg, {"app", "tiles", "protocol"})
        if client.name is not None:
            raise ProtocolError("hello was already said")
        protocol = msg.get("protocol", 1)
        if isinstance(protocol, bool) or not isinstance(protocol, int) or protocol < 1:
            raise ProtocolError("protocol must be a version number (1 or more)")
        if not MIN_PROTOCOL <= protocol <= PROTOCOL:
            raise ProtocolError(
                "app protocol %d is not supported" % protocol,
                code="unsupported-protocol",
                protocol=protocol,
                supported={"min": MIN_PROTOCOL, "max": PROTOCOL},
            )
        name = msg.get("app")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ProtocolError("app must be a name (lower case, at most 32)")
        tiles = msg.get("tiles", [])
        if (
            not isinstance(tiles, list)
            or len(tiles) > MAX_TILES
            or not all(isinstance(t, str) and NAME.fullmatch(t) for t in tiles)
        ):
            raise ProtocolError("tiles must be a list of at most %d tile names" % MAX_TILES)
        client.name, client.protocol = name, protocol
        mine, taken = [], []
        for tile in dict.fromkeys(tiles):
            if tile in self.owner:
                taken.append(tile)
            else:
                self.owner[tile], self.look[tile] = client, {}
                mine.append(tile)
        welcome = {"op": "welcome", "app": name, "taken": taken, "protocol": protocol}
        welcome["placed"] = [t for t in mine if t in self.placed]
        welcome["unplaced"] = [t for t in mine if t not in self.placed]
        client.send(welcome)

    def _set(self, client, msg):
        known_fields(msg, {"tile", "icon", "label", "text", "badge", "tone"})
        tile = msg.get("tile")
        if self.owner.get(tile) is not client:
            raise ProtocolError("tile %r is not yours; provide it in hello" % tile)
        self.look[tile] = look_fields(msg, {"label": 32, "text": 48, "badge": 4})

    def _page(self, client, msg):
        page = parse_page(client, msg)
        old = self.pages.get(page.name)
        if old is not None and old.client is not client:
            raise ProtocolError("page %r is another app's" % page.name)
        if old is None and sum(p.client is client for p in self.pages.values()) >= MAX_PAGES:
            raise ProtocolError("at most %d pages per app" % MAX_PAGES)
        self.pages[page.name] = page


class FakeClient:
    """An app as Apps sees it, without a socket."""

    def __init__(self):
        self.sent: list = []
        self.name = None
        self.protocol = None

    def send(self, msg):
        self.sent.append(msg)


class AppClient:
    """One connection to the socket."""

    def __init__(self, sock):
        self.sock = sock
        self.rbuf = b""
        self.wbuf = b""
        self.name = None
        self.protocol = None

    def send(self, msg):
        self.wbuf += (json.dumps(msg, separators=(",", ":")) + "\n").encode()


class AppServer:
    """The listening socket at path and its connections, driven by pump."""

    def __init__(self, path, apps):
        self.path, self.apps = path, apps
        self.clients: dict = {}  # fd -> AppClient
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_NONBLOCK | socket.SOCK_CLOEXEC)
        self.sock.bind(path)
        self.sock.listen(8)

    def rfds(self):
        return [self.sock.fileno()] + list(self.clients)

    def wfds(self):
        return [fd for fd, c in self.clients.items() if c.wbuf]

    def readable(self, fd):
        if fd == self.sock.fileno():
            try:
                conn, _ = self.sock.accept()
            except BlockingIOError:
                return
            conn.setblocking(False)
            new = AppClient(conn)
            self.apps.connect(new)
            self.clients[conn.fileno()] = new
            return
        client = self.clients.get(fd)
        if client is None:
            return
        try:
            data = client.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self.drop(client)
            return
        client.rbuf += data
        while b"\n" in client.rbuf:
            line, client.rbuf = client.rbuf.split(b"\n", 1)
            if len(line) > MAX_LINE:
                raise AssertionError("the app sent a line of %d bytes, past the limit" % len(line))
            if line.strip():
                self.apps.handle(client, json.loads(line))

    def flush(self):
        for client in list(self.clients.values()):
            if client.wbuf:
                try:
                    n = client.sock.send(client.wbuf)
                except BlockingIOError:
                    continue
                except OSError:
                    self.drop(client)
                    continue
                client.wbuf = client.wbuf[n:]

    def drop(self, client):
        self.clients.pop(client.sock.fileno(), None)
        self.apps.disconnect(client)
        client.sock.close()

    def close(self):
        for client in list(self.clients.values()):
            self.drop(client)
        self.sock.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def pump(server, rounds=1):
    """Read, handle and answer what is ready on the server."""
    for _ in range(rounds):
        ready, _, _ = select.select(server.rfds(), server.wfds(), [], 0.01)
        for fd in ready:
            server.readable(fd)
        server.flush()
