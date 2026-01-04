from __future__ import annotations
import time
from collections import defaultdict, deque

class SlidingRateLimiter:
    def __init__(self, limit:int, window_sec:int):
        self.limit=limit
        self.window=window_sec
        self.buckets=defaultdict(deque)

    def allow(self, key:str) -> bool:
        now=time.time()
        q=self.buckets[key]
        while q and now-q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True
