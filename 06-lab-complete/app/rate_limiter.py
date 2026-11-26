"""
Rate limiting (tiêu chí 7) — sliding window 60 giây bằng Redis sorted set.

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request / 60 giây
  • Vượt giới hạn → HTTP 429 + header Retry-After
  • State nằm trong Redis → mọi worker/instance dùng chung, còn nguyên sau khi restart agent
"""
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    now = time.time()
    zkey = f"ratelimit:{key}"
    member = f"{now}:{uuid.uuid4().hex}"
    # ZADD trước rồi ZCARD trong cùng 1 transaction → đếm đúng kể cả khi nhiều worker gọi cùng lúc
    pipe = r.pipeline()
    pipe.zremrangebyscore(zkey, 0, now - WINDOW_SECONDS)
    pipe.zadd(zkey, {member: now})
    pipe.zcard(zkey)
    pipe.expire(zkey, WINDOW_SECONDS)
    count = pipe.execute()[2]

    if count > settings.rate_limit_per_minute:
        r.zrem(zkey, member)  # request bị chặn không chiếm chỗ trong cửa sổ
        oldest = r.zrange(zkey, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        raise HTTPException(status_code=429, detail="Rate limit exceeded",
                            headers={"Retry-After": str(max(retry_after, 1))})
