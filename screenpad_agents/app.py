"""The app's loop: Herdr and firstmate called off the loop, the touch bar on it.

Worker threads do the slow calls and hand their results to the loop through
a queue (and a pipe that wakes its select):

- Herdr's: reads the agents every [herdr] poll seconds, and the screen of the
  agent whose card is open; does the jobs the loop gives it (focus a pane,
  send an answer through the guard of screen.py, send an interrupt's keys),
  each followed by a read at once;
- firstmate's: runs its reader every [firstmate] poll seconds (at least 60),
  and again on demand when the Captain's Call tile or widget is tapped; taps
  during a read add one read after it, not one each;
- firstmate's control: interrupts a task's agent through fm-control.sh, which
  takes seconds, so neither reader waits on it, opens the decisions board
  (firstmate.py) when Captain's Call is tapped, asks firstmate for one
  when its card's Request is chosen, and checks for it while the app waits
  for it (boardrequest.py);
- the Runs page's, with [runs]: reads no-mistakes (runwatch.py).

The loop keeps the connection to the touch bar through the client library's
Link (retrying every RECONNECT seconds while the daemon is not running or
refuses the app's protocol version), sends the page and tiles when what
they show changed (all of them again after a reconnect), and turns touches into work for the threads: a tap on an
agent's widget opens its card (fleet.py, card.py), whose buttons focus,
interrupt and answer; a tap on the agents tile focuses the first blocked
agent; a tap on the Captain's Call widget opens its view in place of the
grid (callpage.py), the same as the app's "calls" page: the calls waiting,
and the decisions board's button, which opens the board in the browser on
the main screen or asks firstmate to build it, saying when it is open or
that it did not come (boardrequest.py); a tap on the calls tile opens the
board straight away. Each reads firstmate again (the panel answers no
Captain's Call).
"""

import os
import queue
import select
import sys
import threading
import time

from screenpad_app import Link

from . import callpage
from . import card as cards
from .boardrequest import BoardRequest
from .common import (
    APP,
    CALLS_PAGE,
    CALLS_TILE,
    FLEET_TILE,
    PAGE,
    RECONNECT,
    RUNS_PAGE,
    RUNS_TILE,
)
from .common import why as _why
from .firstmate import FirstmateError
from .fleet import CALLS_WIDGET, Fleet
from .herdr import HerdrError
from .runwatch import RunsWatch
from .screen import guarded_send, read_screen


class App:
    def __init__(self, config, herdr, firstmate, socket_path, log=None, clock=time.monotonic, nomistakes=None):
        self.config, self.herdr, self.firstmate = config, herdr, firstmate
        self.socket_path, self.clock = socket_path, clock
        self.log = log or (lambda line: print("screenpad-agents: " + line, file=sys.stderr, flush=True))
        self.fleet = Fleet(config.session, firstmate is not None)
        self.runs = None
        if config.runs is not None and nomistakes is not None:
            self.runs = RunsWatch(config.runs, nomistakes, config.home, self._post, clock)
        self.stopping = threading.Event()
        self._results: queue.Queue = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()
        self._control: queue.Queue = queue.Queue()
        self._read_firstmate = threading.Event()
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        tiles = self.fleet.tiles() + ([RUNS_TILE] if self.runs else [])
        self.link = Link(socket_path, APP, tiles, retry=RECONNECT, log=self.log, clock=clock)
        self._threads = []
        self._told = set()
        self._dirty = False
        self.board = BoardRequest(firstmate, self._control, self._post, self.log, self.refresh_calls, clock)
        self.fleet.board = self.board.board

    # --- the worker threads ------------------------------------------------

    def start(self):
        workers = [("herdr", self._herdr_worker)]
        if self.firstmate is not None:
            workers += [("firstmate", self._firstmate_worker), ("control", self._control_worker)]
        if self.runs is not None:
            workers.append(("runs", self.runs.worker))
        self._threads = [threading.Thread(target=run, name=name, daemon=True) for name, run in workers]
        for t in self._threads:
            t.start()

    def _post(self, *item):
        self._results.put(item)
        self._wake()

    def _wake(self):
        try:
            os.write(self._wake_w, b"x")
        except OSError:
            pass

    def _herdr_worker(self):
        due, watching = 0.0, None
        while not self.stopping.is_set():
            try:
                job = self._jobs.get(timeout=max(0.0, due - self.clock()))
            except queue.Empty:
                job = None
            if self.stopping.is_set():
                return
            if job is not None and job[0] == "watch":
                watching = job[1]
            elif job is not None:
                try:
                    self._herdr_job(*job)
                except Exception as e:
                    self._post("log", _why(e, HerdrError))
            try:
                self._post("agents", self.herdr.agents(), None)
            except Exception as e:
                self._post("agents", None, _why(e, HerdrError))
            if watching is not None:
                try:
                    self._post("screen", read_screen(self.herdr, watching))
                except Exception as e:
                    self._post("log", _why(e, HerdrError))
            due = self.clock() + self.config.herdr_poll

    def _herdr_job(self, what, *args):
        if what == "focus":
            self.herdr.focus(args[0])
        elif what == "answer":
            drawn, answer, keys = args
            try:
                why, fresh = guarded_send(self.herdr, drawn, keys)
            except Exception as e:
                why, fresh = "sending failed: %s" % _why(e, HerdrError), None
            self._post("answered", drawn.pane, answer, why, fresh)
        elif what == "keys":
            pane, kind, keys = args
            try:
                agent = self.herdr.agent(pane)
                if agent.kind != kind:
                    raise HerdrError("another agent is in pane %s now" % pane)
                self.herdr.send_keys(pane, keys)
            except Exception as e:
                self._post("interrupted", pane, None, _why(e, HerdrError))
            else:
                self._post("interrupted", pane, "sent %s" % " ".join(keys), None)

    def _firstmate_worker(self):
        while not self.stopping.is_set():
            self._read_firstmate.clear()
            try:
                self._post("bearings", self.firstmate.read(), None)
            except Exception as e:
                self._post("bearings", None, _why(e, FirstmateError))
            self._read_firstmate.wait(self.config.firstmate_poll)

    def _control_worker(self):
        while not self.stopping.is_set():
            try:
                job = self._control.get(timeout=self.board.timeout())
            except queue.Empty:
                job = ("check",)  # the board's next check is due
            if job is None or self.stopping.is_set():
                return
            if self.board.work(job):
                continue
            _, pane, task_id = job
            try:
                self._post("interrupted", pane, self.firstmate.interrupt(task_id), None)
            except Exception as e:
                self._post("interrupted", pane, None, _why(e, FirstmateError))

    # --- the loop ------------------------------------------------------------

    def run(self):
        self.start()
        try:
            while not self.stopping.is_set():
                self.step(1.0)
        finally:
            self.close()

    def stop(self):
        self.stopping.set()
        self._wake()

    def step(self, timeout):
        """One turn of the loop: connect if due, wait up to timeout, then
        handle what the threads and the touch bar sent."""
        if self.link.connect():
            self._dirty = True  # a new connection has shown nothing yet
        fd = self.link.fileno()
        ready, _, _ = select.select([self._wake_r] + ([fd] if fd is not None else []), [], [], timeout)
        changed = self._drain()
        if self.board.tick():
            changed = True
        if fd is not None and fd in ready:
            for msg in self.link.receive():
                self.handle(msg)
        if self.runs is not None:
            self.runs.showing(self.link.connected)
        if (changed or self._dirty) and self.link.connected:
            self._dirty = False
            runs = self.runs.board.messages(self.fleet) if self.runs is not None else []
            self.link.show(self.fleet.messages() + runs)

    def _drain(self):
        try:
            while os.read(self._wake_r, 4096):
                pass
        except BlockingIOError:
            pass
        changed = False
        while True:
            try:
                what, *rest = self._results.get_nowait()
            except queue.Empty:
                return changed
            changed = self._result(what, *rest) or changed

    def _result(self, what, *rest):
        """Take one result of a thread in; True if what the bar shows changed."""
        if what == "agents":
            value, error = rest
            had_card = self.fleet.card is not None
            self.fleet.set_agents(value, error)
            if had_card and self.fleet.card is None:
                self._jobs.put(("watch", None))
            self._tell("herdr", error)
            if self.runs is not None:
                self.runs.update(self.fleet)
        elif what == "bearings":
            value, error = rest
            self.fleet.set_bearings(value, error)
            self._tell("firstmate", error)
            if self.runs is not None:
                self.runs.update(self.fleet)
        elif what in ("runs", "run"):
            if what == "runs":
                self._tell("no-mistakes", rest[1])
            return self.runs is not None and self.runs.result(what, *rest)
        elif what == "screen":
            self.fleet.set_screen(rest[0])
        elif what == "answered":
            self._answered(*rest)
        elif what == "interrupted":
            pane, done, error = rest
            self.log("interrupt %s: %s" % (pane, done or error))
            card = self.fleet.card
            if card is not None and card.pane == pane:
                card.interrupting = False
                card.note = "interrupt: %s" % (done or "failed: %s" % error)
        elif what in ("board", "look", "requested", "watched"):
            return self.board.result(what, *rest)
        elif what == "log":
            self.log(rest[0])
            return False
        return True

    def request_board(self):
        """Request board chosen: ask firstmate for the board."""
        if self.firstmate is not None and self.board.request():
            self._dirty = True

    def _answered(self, pane, answer, why, fresh):
        card = self.fleet.card
        if why is None:
            self.log("answered %s in pane %s" % (answer, pane))
            if card is not None and card.pane == pane:
                self.fleet.close_card()
                self._jobs.put(("watch", None))
            return
        self.log("nothing sent to pane %s: %s" % (pane, why))
        if card is not None and card.pane == pane:
            card.pending = False
            card.note = "nothing sent: %s" % why
            if fresh is not None:
                self.fleet.set_screen(fresh)

    def _tell(self, source, error):
        """Log a source's error once, and once again when it recovers."""
        if error and source not in self._told:
            self._told.add(source)
            self.log(error)
        elif not error and source in self._told:
            self._told.discard(source)
            self.log("%s answers again" % source)

    # --- touches -------------------------------------------------------------

    def handle(self, msg):
        op = msg.get("op")
        if op == "welcome":
            for tile in msg.get("unplaced") or []:
                if tile == CALLS_TILE:  # page = "calls" is what the bar needs for Captain's Call
                    continue
                self.log('tile "%s" has no spot; give it one with tile = "%s" in touchbar.toml' % (tile, tile))
            for tile in msg.get("taken") or []:
                self.log('another app already provides the tile "%s"' % tile)
        elif op == "error":
            self.log("the touch bar refused %s: %s" % (msg.get("request"), msg.get("message")))
        elif op == "event" and msg.get("page") == CALLS_PAGE and self.firstmate is not None:
            if msg.get("type") == "tap" and self.board.choose(msg.get("widget")):
                self._dirty = True
        elif op == "event" and msg.get("page") == PAGE and msg.get("type") in ("tap", "long"):
            self._touch(msg.get("widget"), msg["type"])
        elif op == "event" and msg.get("page") == RUNS_PAGE and self.runs is not None:
            changed, pane = self.runs.touch(msg.get("widget"), msg.get("type"), self.fleet)
            self._dirty = self._dirty or changed
            self._focus_pane(pane)
        elif op == "event" and msg.get("type") == "up" and msg.get("inside") is True:
            if msg.get("tile") == FLEET_TILE:
                self._focus_pane(self.fleet.first_blocked())
            elif msg.get("tile") == CALLS_TILE:
                self.captains_call()
            elif msg.get("tile") == RUNS_TILE and self.runs is not None:
                self._focus_pane(self.runs.board.first_attention_pane(self.fleet))

    def _touch(self, widget, touch):
        card = self.fleet.shown_card()
        if self.fleet.calls_open:
            if touch != "tap":
                return
            if widget == callpage.BACK:
                self.fleet.close_calls()
                self._dirty = True
            elif self.board.choose(widget):
                self._dirty = True
        elif card is not None:
            self._card_touch(card, widget, touch)
        elif touch != "tap":
            return
        elif widget == CALLS_WIDGET:
            self.open_calls()
        else:
            pane = self.fleet.pane_of(widget)
            if pane is not None and self.fleet.open_card(pane) is not None:
                self._jobs.put(("watch", pane))
                self._dirty = True

    def _card_touch(self, card, widget, touch):
        agent = self.fleet.agent_of(card.pane)
        chosen = card.answer_for(agent, widget, touch)
        if chosen is not None:
            answer, keys = chosen
            card.pending, card.note = True, None
            self._jobs.put(("answer", card.screen, answer, keys))
            self._dirty = True
        elif touch != "tap":
            return
        elif widget == cards.BACK:
            self.fleet.close_card()
            self._jobs.put(("watch", None))
            self._dirty = True
        elif widget == cards.FOCUS:
            self._focus_pane(card.pane)
        elif widget == cards.INTERRUPT:
            self._interrupt(card, agent)

    def _interrupt(self, card, agent):
        route, value = self.fleet.interrupt_route(agent)
        if route is None or card.interrupting:
            return
        card.interrupting, card.note = True, "interrupting…"
        self._dirty = True
        if route == "firstmate":
            self._control.put(("interrupt", card.pane, value))
        else:
            self._jobs.put(("keys", card.pane, agent.kind, value))

    def _focus_pane(self, pane):
        if pane is not None:
            self._jobs.put(("focus", pane))

    def refresh_calls(self):
        if self.firstmate is not None:
            self._read_firstmate.set()

    def captains_call(self):
        """A tap on the calls tile: read firstmate again, and open its
        decisions board."""
        if self.firstmate is not None:
            self.board.tap()

    def open_calls(self):
        """A tap on the Captain's Call widget: its view in place of the
        grid, firstmate read again and the board looked for."""
        if self.firstmate is not None:
            self.fleet.open_calls()
            self._jobs.put(("watch", None))
            self.board.look()
            self._dirty = True

    def close(self):
        self.stopping.set()
        self._read_firstmate.set()
        self._jobs.put(None)
        self._control.put(None)
        if self.runs is not None:
            self.runs.stop()
        self.link.close()
        for t in self._threads:
            t.join(timeout=2.0)
        # A thread still running could write to a reused descriptor number,
        # so the pipe is closed only once they all ended.
        if self._wake_r >= 0 and not any(t.is_alive() for t in self._threads):
            for fd in (self._wake_r, self._wake_w):
                os.close(fd)
            self._wake_r = self._wake_w = -1
