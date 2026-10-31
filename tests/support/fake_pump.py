"""A stand-in for ``audiopump.Events`` and ``audiopump.now`` for the sequencer.

A `Sequencer` writes to its queue through two calls, ``q.at(frame, op,
target, arg)`` and ``q.cancel(token)``, and reads a clock. The queue is a C
object that exists only in a firmware carrying the pump; this is that object
in Python, with the behaviour the sequencer leans on:

* ``at()`` validates first and stores second, sorts by frame with the same
  wrapping comparison, hands back a token counting from 1, and answers **0**
  rather than raising when the queue is full;
* ``cancel()`` is True only while the event is still pending;
* :meth:`Events.apply` applies every event inside ``[now, now + block)`` in
  frame order, and counts late ones;
* ``stats()`` returns the numbers in the same order.

What a fake cannot catch: whether the real pump reaches those frames on time,
and whether applying one allocates. What this does catch is everything above
the queue: which events the sequencer writes, in what order, at which
frames, carrying which notes.

It is not installed as ``audiopump``: the sequencer takes its clock as
``now=``, and the real module stays what other tests import.
"""

PRESS = 1
RELEASE = 2
RELEASE_ALL = 3

_MASK = 0xFFFFFFFF


def before(a, b):
    """``a`` is earlier than ``b`` on the 32-bit wrapping clock."""
    return ((a - b) & _MASK) >= 0x80000000


class _Event:
    __slots__ = ("frame", "op", "target", "arg", "token")

    def __init__(self, frame, op, target, arg, token):
        self.frame = frame
        self.op = op
        self.target = target
        self.arg = arg
        self.token = token


class Events:
    """``audiopump.Events``, in Python, with a clock a test drives."""

    def __init__(self, capacity=64):
        if not 1 <= capacity <= 4096:
            raise ValueError("capacity is 1..4096")
        self.capacity = capacity
        self._events = []
        self._token = 0
        self.scheduled = 0
        self.applied_count = 0
        self.late = 0
        self.cancelled = 0
        self.dropped = 0
        self.refused = 0
        #: Every event this queue has applied, in order:
        #: ``(frame, op, target, arg)``. The C keeps no such log; a test
        #: needs one to say *when* a note sounded.
        self.log = []

    def at(self, frame, op, target, arg=None, loop=False):
        frame &= _MASK
        self._validate(op, target, arg)
        if len(self._events) >= self.capacity:
            self.dropped += 1
            return 0
        self._token += 1
        event = _Event(frame, op, target, arg, self._token)
        index = len(self._events)
        while index > 0 and before(frame, self._events[index - 1].frame):
            index -= 1
        self._events.insert(index, event)
        self.scheduled += 1
        return event.token

    def cancel(self, token):
        for index, event in enumerate(self._events):
            if event.token == token:
                del self._events[index]
                self.cancelled += 1
                return True
        return False

    def clear(self):
        was = len(self._events)
        self._events = []
        self.cancelled += was
        return was

    def pending(self):
        return len(self._events)

    def stats(self):
        return (
            self.scheduled,
            self.applied_count,
            self.late,
            self.cancelled,
            self.dropped,
            self.refused,
            len(self._events),
            self.capacity,
        )

    def apply(self, now, block_frames=256):
        """The block ``[now, now + block)``: apply what falls inside it."""
        end = (now + block_frames) & _MASK
        applied = 0
        while self._events and before(self._events[0].frame, end):
            event = self._events.pop(0)
            if before(event.frame, now):
                self.late += 1
            self.log.append((event.frame, event.op, event.target, event.arg))
            if event.op == PRESS:
                event.target.press(event.arg)
            elif event.op == RELEASE:
                event.target.release(event.arg)
            elif event.op == RELEASE_ALL:
                event.target.release_all()
            applied += 1
        self.applied_count += applied
        return applied

    def _validate(self, op, target, arg):
        if op not in (PRESS, RELEASE, RELEASE_ALL):
            raise ValueError("unknown op")
        if not hasattr(target, "press"):
            raise TypeError("press/release want a voice")
        if op != RELEASE_ALL and (isinstance(arg, bool) or not isinstance(arg, int)):
            raise TypeError("a scheduled note is a MIDI number")
        if op != RELEASE_ALL and not 0 <= arg <= 127:
            raise ValueError("a MIDI note is 0..127")


class _Clock:
    """``audiopump.now()`` -- frames pulled, which a test moves by hand."""

    def __init__(self):
        self.frame = 0

    def __call__(self):
        return self.frame & _MASK


now = _Clock()


class _Voice:
    """What a queue's press and release land on: a set of held pitches."""

    def __init__(self):
        self.pressed = set()

    def press(self, pitch):
        self.pressed.add(pitch)

    def release(self, pitch):
        self.pressed.discard(pitch)

    def release_all(self):
        self.pressed.clear()


class Kit:
    """An instrument that answers the sequencer's seam, and nothing else.

    ``schedulable`` is True, ``scheduled(q, frame, tokens)`` is a context
    manager inside which ``note_on()`` and ``note_off()`` become events on
    the queue at that frame, and ``refused`` is a number the test sets.
    ``layers`` is how many voices a note presses, as a kit presses more than
    one circuit for a hit: a heavier bar needs a deeper queue.
    """

    schedulable = True

    def __init__(self, layers=2, refused=0):
        self.voices = [_Voice() for _ in range(layers)]
        self.refused = refused
        self._armed = None
        self.live = []

    def scheduled(self, q, frame, tokens=None):
        return _Armed(self, q, frame, [] if tokens is None else tokens)

    def note_on(self, pitch, velocity=127, *rest):
        if self._armed is None:
            self.live.append(("on", pitch))
            return
        q, frame, tokens = self._armed
        for voice in self.voices:
            tokens.append(q.at(frame, PRESS, voice, pitch))

    def note_off(self, pitch, *rest):
        if self._armed is None:
            self.live.append(("off", pitch))
            return
        q, frame, tokens = self._armed
        for voice in self.voices:
            tokens.append(q.at(frame, RELEASE, voice, pitch))

    def all_notes_off(self):
        for voice in self.voices:
            voice.release_all()

    @property
    def held(self):
        return set().union(*(v.pressed for v in self.voices))

    def deinit(self):
        pass


class _Armed:
    def __init__(self, kit, q, frame, tokens):
        self._kit = kit
        self._armed = (q, frame, tokens)
        self.tokens = tokens

    def __enter__(self):
        self._kit._armed = self._armed
        return self.tokens

    def __exit__(self, *exc):
        self._kit._armed = None
        return False
