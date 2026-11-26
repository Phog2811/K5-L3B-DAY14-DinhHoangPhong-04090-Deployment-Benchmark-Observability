# Deployment Information

> Agent Part 6 (`06-lab-complete/`) deploy lên cloud theo lưu ý K5 (README mục 8).

## Public URL

**https://day14-agent-3q3m.onrender.com**

## Platform

**Render**, deploy bằng Blueprint [06-lab-complete/render.yaml](06-lab-complete/render.yaml), gồm:

- web service `day14-agent`: `runtime: docker`, `rootDir: 06-lab-complete`, `healthCheckPath: /health`, plan free;
- Key Value `day14-redis`: `REDIS_URL` được nối vào web service bằng `fromService ... property: connectionString`.

Render đọc Blueprint từ repo GitHub (branch `main`) và tự deploy lại mỗi lần push.

Railway ([06-lab-complete/railway.toml](06-lab-complete/railway.toml)) đã được thử trước. `railway up` bị tài khoản chặn ("We limited this workspace after detecting unusual activity…"), chi tiết ở `MISSION_ANSWERS.md` mục Part 3.

Gói free của Render tắt instance khi không có traffic. Request đầu tiên sau đó có thể mất khoảng 50 giây để khởi động lại.

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã nhập trên Render. Không ghi key vào repo.

```bash
BASE=https://day14-agent-3q3m.onrender.com
curl -sS -o /dev/null -w 'health %{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w 'ready %{http_code}\n' "$BASE/ready"       # 200
curl -sS -o /dev/null -w 'ask-no-key %{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -w '\nask-with-key %{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả, chạy lúc 2026-11-26 17:31:19:

```text
health 200
ready 200
ask-no-key 401
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","cost_usd":1.05e-05}
ask-with-key 200
```

Thêm phần rate limit: gửi 11 request liên tiếp ngay sau đó, giới hạn là 10/phút và request "Hello" ở trên cũng được tính:

```text
200 200 200 200 200 200 200 200 200 429 429
```

## Environment Variables Set

Các biến này đặt trên Render, không có trong code.

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | chuỗi ngẫu nhiên 43 ký tự (`sync: false` trong `render.yaml`, nhập trên dashboard lúc tạo Blueprint) |
| `REDIS_URL` | tham chiếu tự động tới Key Value `day14-redis` (`fromService` / `connectionString`) |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | Render tự cấp; `CMD` trong Dockerfile nghe theo `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
