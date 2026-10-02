"""Read subprocess pipes on Windows and Unix without blocking cancellation."""
import queue
import threading


class EventLines:
    def __init__(self, stream):
        self.queue = queue.Queue()
        def read():
            try:
                for line in stream:
                    self.queue.put(line)
            finally:
                self.queue.put(None)
        self.thread = threading.Thread(target=read, daemon=True)
        self.thread.start()

    def next(self, timeout=.2):
        try:
            return True, self.queue.get(timeout=timeout)
        except queue.Empty:
            return False, None
