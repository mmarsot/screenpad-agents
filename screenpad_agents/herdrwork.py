"""The Herdr thread of the app: reads, and the jobs the loop gives it.

It reads the agents every [herdr] poll seconds, and the screen of the agent
whose card is open (the loop's "watch" job names it); does the jobs the loop
gives it (focus a pane, send an answer through the guard of screen.py, send
an interrupt's keys), each followed by a read at once; and hands what it
read to the loop through post (app.py).
"""

import queue

from .common import why as _why
from .herdr import HerdrError
from .screen import guarded_send, read_screen


class HerdrWorker:
    def __init__(self, herdr, jobs, post, stopping, clock, poll):
        self.herdr, self._jobs, self._post = herdr, jobs, post
        self.stopping, self.clock, self.poll = stopping, clock, poll

    def run(self):
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
                    self._job(*job)
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
            due = self.clock() + self.poll

    def _job(self, what, *args):
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
