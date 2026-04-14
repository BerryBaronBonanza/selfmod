import asyncio
import hashlib
import sys
import time

from selfmod.db import insert_frame


class FrameRecorder:
    IDLE = "idle"
    CHANGE_DETECTED = "change_detected"

    def __init__(self, conn, target="0:selfmod", tick_ms=50):
        self.conn = conn
        self.target = target
        self.tick_ms = tick_ms
        self.state = self.IDLE
        self.last_captured = ""
        self.last_stored_content = ""
        self.last_stored_hash = ""
        self.change_settle_deadline = 0.0
        self.change_entered_time = 0.0
        self.last_periodic_store = 0.0
        self.frame_count = 0

    async def capture(self):
        proc = await asyncio.create_subprocess_exec(
            "tmux", "capture-pane", "-t", self.target, "-p",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"tmux capture-pane failed: {stderr.decode().strip()}"
            )
        return stdout.decode("utf-8", errors="replace")

    def _hash(self, s):
        return hashlib.md5(s.encode()).hexdigest()

    def _normalize(self, content):
        return content.rstrip()

    def _differs_from_stored(self, content):
        return self._hash(self._normalize(content)) != self.last_stored_hash

    def _store(self, content, frame_type):
        ts = time.time()
        insert_frame(self.conn, ts, content, frame_type)
        normalized = self._normalize(content)
        self.last_stored_content = normalized
        self.last_stored_hash = self._hash(normalized)
        self.frame_count += 1
        sys.stderr.write(f"\rStored frames: {self.frame_count}")
        sys.stderr.flush()

    async def run(self):
        self.last_periodic_store = time.time()
        sys.stderr.write(f"Recording tmux pane {self.target}... (Ctrl+C to stop)\n")

        try:
            while True:
                tick_start = time.monotonic()
                now = time.time()

                content = await self.capture()
                content_changed = self._normalize(content) != self._normalize(self.last_captured)
                differs_from_stored = self._differs_from_stored(content)

                if self.state == self.IDLE:
                    if content_changed and differs_from_stored:
                        # Save the frame just before the change
                        if self.last_captured and self._differs_from_stored(self.last_captured):
                            self._store(self.last_captured, "pre_change")
                        self.state = self.CHANGE_DETECTED
                        self.change_settle_deadline = now + 0.4
                        self.change_entered_time = now

                elif self.state == self.CHANGE_DETECTED:
                    if content_changed:
                        self.change_settle_deadline = now + 0.4
                    elif now >= self.change_settle_deadline:
                        if differs_from_stored:
                            self._store(content, "post_change")
                        self.state = self.IDLE
                    # Force store after 10s of continuous change
                    if now - self.change_entered_time >= 10.0:
                        if differs_from_stored:
                            self._store(content, "post_change")
                        self.state = self.CHANGE_DETECTED
                        self.change_settle_deadline = now + 0.4
                        self.change_entered_time = now

                # Periodic: every 5s, store if different
                if now - self.last_periodic_store >= 5.0:
                    if differs_from_stored:
                        self._store(content, "periodic")
                    self.last_periodic_store = now

                self.last_captured = content

                elapsed = time.monotonic() - tick_start
                sleep_for = max(0, self.tick_ms / 1000 - elapsed)
                await asyncio.sleep(sleep_for)

        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            # Store a final frame if different
            if self.last_captured and self._differs_from_stored(self.last_captured):
                self._store(self.last_captured, "periodic")
            self.conn.commit()
            sys.stderr.write(f"\nStopped. Total stored frames: {self.frame_count}\n")
