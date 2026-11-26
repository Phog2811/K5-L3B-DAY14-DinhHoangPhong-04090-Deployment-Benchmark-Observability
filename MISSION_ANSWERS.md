# Day 14 Lab — Mission Answers

> Môi trường chạy: Windows 11 + WSL2 Ubuntu (Python 3.11.18, `os.name = posix`), Docker Desktop 29.9.2.
> **Ghi chú cổng:** trên máy, cổng `8000` và `3000` đang bị một project khác chiếm, nên các app đọc biến `PORT`
> được chạy ở cổng khác (ghi rõ ở từng lệnh). App develop Part 1 cố định cổng 8000 trong code nên được chạy bằng
> `uvicorn app:app --port 8011` — code của app giữ nguyên.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | Hard-code secret: `OPENAI_API_KEY = "sk-hardcoded-..."`, `DATABASE_URL = "postgresql://admin:password123@..."` | 17–18 | Push lên GitHub là lộ key/mật khẩu; đổi key phải sửa code và deploy lại |
| 2 | **Log ra secret**: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log — ai đọc được log là có key (đã thấy thật trong log khi chạy, xem 1.2) |
| 3 | `print()` thay vì logging có cấu trúc, không có level | 33, 38 | Không lọc/tìm kiếm được trên log aggregator; không tắt được DEBUG ở production |
| 4 | Config cứng: `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Muốn đổi giữa dev/staging/prod phải sửa code |
| 5 | Không có `/health` (gọi thử trả **404**) | 42 | Platform không biết app chết để restart / ngừng route traffic |
| 6 | `host="localhost"` | 51 | Trong container chỉ nhận kết nối từ chính nó → không gọi được từ ngoài |
| 7 | `port=8000` cố định, không đọc `PORT` | 52 | Railway/Render cấp `PORT` động → app không nhận traffic (chính lý do mình phải chạy bằng `--port 8011`) |
| 8 | `reload=True` | 53 | Chế độ dev: tốn tài nguyên, theo dõi file, không dùng cho production |
| 9 | Không xử lý shutdown (không lifespan / SIGTERM) | — | Khi deploy lại, request đang chạy có thể bị cắt ngang |

### Exercise 1.2: Chạy bản develop

```text
$ curl -X POST "http://localhost:8011/ask?question=Hello"
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
$ curl -s http://localhost:8011/health
{"detail":"Not Found"} [HTTP 404]
--- server log (develop) ---
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
[DEBUG] Response: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.
```

Nó chạy được, nhưng không production-ready: lộ key ra log, không có health check, chỉ nghe `localhost`.

### Exercise 1.3: Chạy bản production và so sánh

```text
$ PORT=8010 python app.py
$ curl -s http://localhost:8010/health
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T09:19:38.338565+00:00"}
$ curl -s http://localhost:8010/ready
{"ready":true}
$ curl -s -X POST http://localhost:8010/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","model":"gpt-4o-mini"}
```

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hard-code trong code (`DEBUG=True`, key, DB URL) | `config.py` đọc env (`PORT`, `ENVIRONMENT`, `AGENT_API_KEY`...), có `.env.example`, `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production | Một image chạy được ở mọi môi trường; secret không nằm trong git |
| Secrets | Ghi thẳng trong code và in ra log | Từ env, không log secret (chỉ log `question_length`) | Lộ key = mất tiền / mất dữ liệu; log thường được nhiều người đọc |
| Health check | Không có (404) | `/health` (liveness) + `/ready` (readiness) | Platform tự restart khi chết, LB chỉ route vào instance đã sẵn sàng |
| Logging | `print()` | Logging có level, nội dung JSON | Dễ parse/tìm kiếm trên Loki/Datadog, lọc theo level |
| Shutdown | Đột ngột | `lifespan` dọn dẹp + handler SIGTERM, uvicorn chờ request đang chạy | Deploy/scale-down không làm hỏng request của user |
| Host / Port | `localhost:8000` cứng | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên cloud |
| Reload | `reload=True` luôn bật | Chỉ bật khi `DEBUG=true` | Không lãng phí tài nguyên ở production |
| CORS | Không có | Chỉ cho origin trong `ALLOWED_ORIGINS` | Hạn chế site lạ gọi API từ trình duyệt |

Quan sát thêm khi chạy: log JSON của `lifespan` trong bản production **không hiện ra**. Lý do: `config.py` gọi
`logging.warning(...)` trước, làm root logger tự cấu hình mặc định (level WARNING), nên `logging.basicConfig(...)` ở
`app.py` sau đó không còn tác dụng. Đây là lỗi hay gặp — Part 6 của mình tránh bằng cách gắn handler JSON riêng cho logger `agent`.

---

## Part 2: Docker

### Exercise 2.1: `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11` — bản Python đầy đủ (Debian + build tools), rất nặng.
2. **Working directory:** `/app`.
3. **Vì sao COPY `requirements.txt` trước:** Docker cache theo layer. Dependencies ít đổi, code đổi liên tục. Copy
   requirements + `pip install` trước thì khi chỉ sửa code, layer cài thư viện được dùng lại từ cache → build lại vài
   giây thay vì cài lại toàn bộ. Nếu `COPY . .` trước thì mỗi lần sửa code đều phải cài lại.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` là chương trình cố định của container; `CMD` là lệnh/tham số mặc định, bị
   ghi đè bởi tham số của `docker run <image> ...`. Khi có cả hai, `CMD` trở thành tham số cho `ENTRYPOINT`. Dùng
   dạng exec (`["python", "app.py"]`) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và run bản develop

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d -p 8012:8000 my-agent:develop        # cổng host 8012 vì 8000 đang bận
$ curl -X POST "http://localhost:8012/ask?question=What%20is%20Docker%3F"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl http://localhost:8012/health
{"status":"ok","uptime_seconds":4.1,"container":true}
```

### Exercise 2.3: Multi-stage build — kích thước đo được

- **Stage 1 (`builder`)**: `python:3.11-slim` + cài `gcc`, `libpq-dev`, rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này chỉ để build, không được ship.
- **Stage 2 (`runtime`)**: `python:3.11-slim` sạch, tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local`
  và source code, có `HEALTHCHECK`, chạy `uvicorn` 2 workers.
- **Vì sao nhỏ hơn:** base `slim` thay vì bản full; compiler, header, apt cache, pip cache nằm lại ở stage builder và bị bỏ đi.

```text
$ docker images my-agent
REPOSITORY   TAG        SIZE
my-agent     advanced   240MB
my-agent     develop    1.67GB
$ docker image inspect -f '{{index .RepoTags 0}} {{.Size}}' my-agent:develop my-agent:advanced
my-agent:develop 1667780760
my-agent:advanced 239819429
```

- Develop: **1667.8 MB**
- Production: **239.8 MB**
- Chênh lệch: (1667.8 − 239.8) / 1667.8 = **giảm 85.6 %**

### Exercise 2.4: Docker Compose stack

```text
                 :80 / :443
   client ───────────────▶ nginx (reverse proxy, security headers, rate limit 10r/s)
                              │  upstream agent:8000
                              ▼
                           agent (FastAPI, build từ 02-docker/production/Dockerfile)
                            │                     │
               redis://redis:6379/0     http://qdrant:6333
                            ▼                     ▼
                     redis:7-alpine        qdrant/qdrant:v1.9.0
                  (session, rate limit)      (vector DB cho RAG)
          ── tất cả nằm chung network bridge "internal"; chỉ nginx publish cổng ra ngoài ──
```

Services được start: `redis`, `qdrant` (chờ healthy) → `agent` (`depends_on: condition: service_healthy`) → `nginx`.
Chúng gọi nhau bằng **tên service** qua DNS nội bộ của Docker network; agent không publish cổng, chỉ đi qua Nginx.

```text
$ docker compose -p k5-day14-docker up -d --build
$ docker compose -p k5-day14-docker ps
SERVICE   IMAGE                   STATUS                            PORTS
agent     k5-day14-docker-agent   Up 3 seconds (health: starting)   8000/tcp
nginx     nginx:alpine            Up 3 seconds                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 14 seconds (healthy)           6333-6334/tcp
redis     redis:7-alpine          Up 14 seconds (healthy)           6379/tcp
$ curl -i http://localhost/health
HTTP/1.1 200 OK
X-Frame-Options: DENY
{"status":"ok","uptime_seconds":2.6,"version":"2.0.0","timestamp":"2026-11-26T09:23:17.582579"}
$ curl http://localhost/ask -X POST -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Header `X-Frame-Options: DENY` chứng tỏ request đã đi qua Nginx.

---

## Part 3: Cloud Deployment

> Deploy chính agent Part 6 (`06-lab-complete/`) theo lưu ý K5. Chi tiết URL + lệnh test: [DEPLOYMENT.md](DEPLOYMENT.md).

### Nền tảng chính: Render (Exercise 3.2)

- URL: **https://day14-agent-3q3m.onrender.com**. Deploy bằng Blueprint `06-lab-complete/render.yaml` (web Docker + Key Value `day14-redis`), từ commit `31adfed`.
- 4 lệnh tự kiểm CP6, đo lúc 2026-11-26 17:31 (lệnh đầy đủ ở [DEPLOYMENT.md](DEPLOYMENT.md)):

  ```text
  health 200
  ready 200
  ask-no-key 401
  {"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","cost_usd":1.05e-05}
  ask-with-key 200
  rate-limit 11 requests (ngay sau 1 request ở trên): 200 200 200 200 200 200 200 200 200 429 429
  ```

  Rate limit 10 request/phút đã có 1 request "Hello" tính trước, nên request thứ 11 trong phút (thứ 10 của vòng lặp) bị 429. Điều này cho thấy Redis trên Render đang hoạt động: `/ready` trả 200, và bộ đếm rate limit được giữ trong Redis.
- Screenshot: [dashboard](screenshots/dashboard.png), [running](screenshots/running.png), [test](screenshots/test.png)

### Exercise 3.1: Railway (đã thử, bị chặn ở bước upload)

Đã làm đủ các bước bằng Railway CLI 5.75.0:

- `railway login`, `railway init --name day14-agent`, `railway add --database redis`, `railway add --service agent`;
- đặt `AGENT_API_KEY` (qua `--stdin`), `ENVIRONMENT`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, và `REDIS_URL=${{Redis.REDIS_URL}}`; biến này resolve thành `redis://default:***@redis.railway.internal:6379`.

Khi chạy `railway up`, Railway trả về:

```text
We limited this workspace after detecting unusual activity. Upgrade to a paid plan to lift this restriction automatically.
```

Service Redis cũng ở trạng thái `Failed` vì cùng lý do. Đây là hạn chế của tài khoản, không phải lỗi code. Rubric cho phép chọn Railway **hoặc** Render, nên tôi deploy lên Render. Phần "nền tảng còn lại" là bảng so sánh bên dưới.

### So sánh `railway.toml` và `render.yaml` (trong `06-lab-complete/`)

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Định dạng | TOML, chỉ mô tả **1 service** | YAML Blueprint, mô tả **nhiều service** trong 1 file (web + Redis) |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `rootDir: 06-lab-complete` (vì file không nằm ở gốc repo) |
| Health check | `[deploy] healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"`, `restartPolicyMaxRetries` | Render tự quản lý, không khai báo |
| Biến môi trường | **Không** khai báo trong file; đặt bằng `railway variables` / dashboard | Khai báo trong `envVars`; giá trị thường ghi thẳng, secret dùng `sync: false` (nhập trên dashboard) |
| Redis | Tạo service Redis riêng trên dashboard, copy `REDIS_URL` vào biến | Khai báo luôn `type: keyvalue`, `REDIS_URL` lấy bằng `fromService ... property: connectionString` |
| Cách deploy | `railway up` đẩy code từ máy lên (không cần GitHub) | Render đọc Blueprint từ repo GitHub, tự deploy lại mỗi lần push |

Tóm lại: Railway tách cấu hình build/deploy (file) khỏi biến môi trường (dashboard/CLI); Render coi `render.yaml` là
"infrastructure as code" cho cả hạ tầng, kể cả Redis và cách nối các service với nhau.

### Exercise 3.3: Cloud Run CI/CD (`03-cloud-deployment/production-cloud-run/`)

`cloudbuild.yaml` là pipeline 4 bước chạy tuần tự trên Cloud Build (mỗi bước `waitFor` bước trước):
1. **test** — trong `python:3.11-slim`, cài requirements + pytest và chạy `pytest tests/`; test fail là dừng pipeline.
2. **build** — `docker build` gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache.
3. **push** — đẩy cả 2 tag lên Container Registry.
4. **deploy** — `gcloud run deploy` image đúng `$COMMIT_SHA` (truy vết được commit nào đang chạy) lên `asia-southeast1`, min 1 / max 10 instance, 512Mi/1 CPU, timeout 60s, secret `OPENAI_API_KEY` lấy từ Secret Manager.

`service.yaml` mô tả cùng service theo kiểu khai báo (Knative): autoscale 1–10 instance, `containerConcurrency: 80`,
secret qua `secretKeyRef`, `livenessProbe` gọi `/health` và `startupProbe` gọi `/ready`.

---

## Part 4: API Security

### Exercise 4.1: API key (`04-api-gateway/develop`, chạy `AGENT_API_KEY=secret-key-123 PORT=8013 python app.py`)

- Key được kiểm tra trong dependency `verify_api_key()` (dùng `APIKeyHeader(name="X-API-Key")`), gắn vào `/ask` bằng `Depends(verify_api_key)`.
- Thiếu key → **401**; sai key → **403**.
- Rotate key: key đọc từ env `AGENT_API_KEY` → đặt giá trị mới trên platform rồi restart/redeploy, không sửa code.
  Muốn rotate không downtime thì cho phép tạm thời 2 key (cũ + mới) rồi bỏ key cũ.

```text
$ curl -i -X POST http://localhost:8013/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'   # không có key
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i ... -H "X-API-Key: wrong-key"   # sai key
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i ... -H "X-API-Key: secret-key-123"   # đúng key
HTTP/1.1 200 OK
{"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`, `PORT=8014`, tài khoản `student` / `demo123`)

Flow: `POST /auth/token` kiểm tra username/password → `create_token()` ký JWT (HS256) chứa `sub`, `role`, `exp` (60 phút)
→ client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm chữ ký + hạn, trả `{username, role}`. Server
không cần tra DB mỗi request.

```text
$ curl -i -X POST http://localhost:8014/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN_DA_CHE>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN_DA_CHE>"}

$ curl -i -X POST http://localhost:8014/ask -d '{"question":"Explain JWT"}'   # không có token
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8014/ask -H "Authorization: Bearer $TOKEN" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- Thuật toán: **sliding window log** — mỗi user một `deque` timestamp; bỏ timestamp cũ hơn 60s, đếm phần còn lại.
- Giới hạn: user thường **10 req/phút** (`rate_limiter_user`), admin **100 req/phút** (`rate_limiter_admin`).
- "Bypass" cho admin: `app.py` chọn limiter theo `role` trong JWT — `teacher` có role `admin` nên dùng limiter 100/phút.
- Hạn chế: state nằm trong RAM của process → nhiều instance thì mỗi instance đếm riêng (Part 6 mình chuyển sang Redis).

Vòng lặp 20 request bằng cùng token (đã dùng 1 request ở bước 4.2):

```text
request 1: HTTP 200
...
request 9: HTTP 200
request 10: HTTP 429 retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
request 11 → 20: HTTP 429 retry-after: 59   (cùng nội dung)
```

→ 10 request thành công trong 60s (1 ở 4.2 + 9 ở đây), request thứ 11 bị **429** kèm header `Retry-After`.

### Exercise 4.4: Cost guard

`04-api-gateway/production/cost_guard.py`: trước khi gọi LLM, `check_budget(user)` trả **402** nếu chi phí hôm nay của
user ≥ $1, hoặc **503** nếu tổng toàn hệ thống ≥ $10/ngày; sau khi gọi, `record_usage()` cộng token × đơn giá. Điểm yếu: state trong RAM.

Cách mình làm ở Part 6 (`06-lab-complete/app/cost_guard.py`):
- Chi phí mỗi request = `input_tokens/1000 × $0.00015 + output_tokens/1000 × $0.0006` (giá gpt-4o-mini).
- Cộng dồn vào Redis bằng `INCRBYFLOAT cost:<YYYY-MM-DD>` (nguyên tử → nhiều worker/instance cùng cộng không mất số), `EXPIRE` 2 ngày để key tự dọn → tự "reset" mỗi ngày theo UTC.
- `check_budget()` chạy **trước** khi gọi LLM: tổng ≥ `DAILY_BUDGET_USD` → `HTTPException(402)`.
- Budget đọc từ env nên đổi không cần sửa code.
- Khác với solution mẫu ($10/tháng/user): mình dùng ngân sách theo **ngày** cho toàn agent (contract cho phép `DAILY_BUDGET_USD` hoặc `MONTHLY_BUDGET_USD`). Muốn theo user/tháng thì đổi key thành `cost:<user>:<YYYY-MM>` và `EXPIRE` 32 ngày.
- Rate limit bảo vệ **tốc độ** (chống spam/DoS trong ngắn hạn), cost guard bảo vệ **tiền** (nhiều request hợp lệ, chậm nhưng đều cũng có thể đốt hết budget) — cần cả hai.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health & readiness (`05-scaling-reliability/develop`, `PORT=8015`)

```text
$ curl -i http://localhost:8015/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.7,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T09:24:42.860245+00:00","checks":{"memory":{"status":"ok","used_percent":39.9}}}
$ curl -i http://localhost:8015/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

- **Liveness (`/health`)**: "process còn sống không?" — fail thì platform **restart** container. Không được phụ thuộc
  Redis/DB, nếu không Redis chết một chút là mọi instance bị restart liên hoàn.
- **Readiness (`/ready`)**: "nhận traffic được chưa?" — fail (503) thì LB **ngừng route** vào instance đó nhưng không
  restart. Kiểm tra dependency (Redis) ở đây. Part 6: Redis chết → `/ready` 503, `/health` vẫn 200.

### Exercise 5.2: Graceful shutdown

```text
$ curl -X POST "http://localhost:8015/ask?question=Long%20task" &  ;  kill -TERM $PID
Kết quả request đang chạy: {"answer":"Đây là câu trả lời từ AI agent (mock). ..."} [HTTP 200]
Process thoát với exit code: 0
--- server log ---
INFO:     Shutting down
INFO:     127.0.0.1:41436 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
... INFO 🔄 Graceful shutdown initiated...
... INFO ✅ Shutdown complete
INFO:     Finished server process [3762]
```

SIGTERM đến **trước** khi request xong (log `Shutting down` đứng trước dòng `POST /ask 200`), nhưng request vẫn trả
200 rồi process mới thoát với exit code 0. Uvicorn ngừng nhận kết nối mới, chờ request đang chạy (tối đa
`timeout_graceful_shutdown=30`), chạy phần shutdown của `lifespan` rồi thoát.

### Exercise 5.3: Stateless design

Bản production lưu conversation history trong Redis (`save_session` / `load_session` / `append_to_history`, key theo
`session_id`, có TTL) thay vì dict trong RAM. Lý do: khi scale ra N instance sau load balancer, request kế tiếp của
cùng user có thể rơi vào instance khác; nếu state ở RAM thì instance đó không thấy history, và restart là mất hết.
Đưa state ra Redis → mọi instance giống hệt nhau, thêm/bớt/restart instance thoải mái.

### Exercise 5.4: Load balancing (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`)

```text
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 5 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-2   Up 6 seconds (healthy)    8000/tcp
k5-day14-scaling-agent-3   Up 6 seconds (healthy)    8000/tcp
k5-day14-scaling-nginx-1   Up 5 seconds              0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 16 seconds (healthy)   6379/tcp

Request 1 -> served_by instance-215c4a
Request 2 -> served_by instance-ec19a4
Request 3 -> served_by instance-5f3867
Request 4 -> served_by instance-215c4a
...
Request 10 -> served_by instance-215c4a

$ docker compose -p k5-day14-scaling logs agent | grep '"POST /chat' (đếm theo instance)
      3 agent-1
      4 agent-2
      3 agent-3
```

Nginx chia **round-robin** đều cho 3 instance (4/3/3 cho 10 request).

### Exercise 5.5: `python test_stateless.py`

```text
Session ID: 778bb5be-5ef3-48ed-9f37-05381c8ced5e
Request 1: [instance-ec19a4]   Q: What is Docker?
Request 2: [instance-5f3867]   Q: Why do we need containers?
Request 3: [instance-215c4a]   Q: What is Kubernetes?
Request 4: [instance-ec19a4]   Q: How does load balancing work?
Request 5: [instance-5f3867]   Q: What is Redis used for?
------------------------------------------------------------
Total requests: 5
Instances used: {'instance-5f3867', 'instance-ec19a4', 'instance-215c4a'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

5 câu trong cùng session đi qua cả 3 instance, nhưng history đọc lại vẫn đủ 10 message (5 user + 5 assistant) vì
mọi instance đọc/ghi cùng một Redis. Script không tắt instance nào — nếu state nằm trong RAM, history sẽ chỉ có
phần của instance đang trả lời.

---

## Part 6: Final Project — `python check_production_ready.py` (bản đầy đủ, có Docker)

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Một số con số từ cùng lần chạy: image **273 MB**; `docker stop` xong trong **0.5 s**, exit code 0; rate limit trả
429 sau đúng 5 request (`RATE_LIMIT_PER_MINUTE=5`) và vẫn 429 sau khi restart agent (state ở Redis).

Thiết kế chính:
- `app/config.py` — mọi cấu hình từ env, `AGENT_API_KEY` mặc định rỗng → không có key là mọi `/ask` bị 401 (không có secret trong code).
- `app/auth.py` — `APIKeyHeader("X-API-Key")`, so sánh bằng `secrets.compare_digest` (chống timing attack), thiếu/sai → 401.
- `app/rate_limiter.py` — sliding window bằng Redis sorted set: `ZREMRANGEBYSCORE → ZADD → ZCARD → EXPIRE` trong một transaction (đếm đúng khi nhiều worker gọi cùng lúc); vượt → 429 + `Retry-After`; request bị chặn được xoá khỏi cửa sổ.
- `app/cost_guard.py` — `INCRBYFLOAT` theo ngày trong Redis, ≥ budget → 402.
- `app/redis_client.py` — `redis.from_url` không kết nối lúc import (app khởi động được khi chưa có Redis), timeout 1–2s để `/ready` trả 503 nhanh.
- `app/main.py` — log JSON (formatter riêng, mỗi request một dòng có `path/status/ms`), `/health`, `/ready`, lỗi Redis → 503 gọn (không lộ stack trace), `lifespan` cho shutdown; SIGTERM để uvicorn tự xử lý (không tự đăng ký handler đè lên).
- `Dockerfile` — 2 stage, venv copy sang runtime `python:3.11-slim`, user `app` (uid 1000), `HEALTHCHECK` bằng Python, `CMD ["sh","-c","exec uvicorn ... --port ${PORT:-8000}"]` → uvicorn là PID 1.

---

## AI log

Theo [RULES.md](RULES.md) mục 1. Công cụ: **Claude Code (Claude Opus)** chạy trong VS Code.

| # | Hỏi AI gì | AI làm/đưa ra gì | Mình tự kiểm tra thế nào |
|---|---|---|---|
| 1 | Đọc đề (README, RULES, RUBRIC, CHECKPOINTS) và lên kế hoạch | Tóm tắt yêu cầu, thứ tự làm, chỉ ra cần WSL2 vì Windows Python không gửi được SIGTERM | Đối chiếu với README mục "Lưu ý khi làm bài" |
| 2 | Cài WSL Ubuntu bị lỗi `Wsl/Service/E_UNEXPECTED` | Chẩn đoán WSL 2.1.5 quá cũ so với Windows → `wsl --update` lên 3.0.5, cài lại Ubuntu; Ubuntu kèm Python 3.14 không có wheel cho `pydantic==2.9.0` → dùng `uv` tạo venv Python 3.11 | `python -c "import os; print(os.name)"` in `posix` |
| 3 | Viết code Part 6 theo các TODO | AI viết `app/*.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` sau khi đọc `check_production_ready.py` | Chạy `check_production_ready.py --static-only` → `--skip-docker` → bản đầy đủ: **PASS 12/12**; tự đọc lại từng file để giải thích được |
| 4 | Chạy các ví dụ Part 1, 2, 4, 5 và gom output | AI chạy lệnh trong WSL/Docker, lưu output thật, đổi cổng vì 8000 bị project khác chiếm | Output dán ở trên là output gốc của lệnh (token JWT đã che) |
| 5 | Viết câu trả lời Part 1–5 | AI soạn nháp giải thích dựa trên code và output | Đối chiếu từng câu với code/dòng tương ứng |
| 6 | Part 7 develop: load test, tail latency, eval v1/v2, sửa lỗi eval | AI chạy `load_test.py`/`run_eval.py`. Tìm 2 câu v2 trả sai (JWT, HPA) và thêm 2 mục vào knowledge base của `mock_llm.py`. Thêm histogram `agent_question_length_chars`. Viết workflow quality gate `.github/workflows/eval.yml` | v2 sau khi sửa đạt 23/23, 0 regression; v1 so với baseline v2 cho exit 1 (gate chặn được). Số liệu trong report khớp với `reports/*.json` |
| 7 | Part 7 production: dựng stack, scale, trace, alert | AI phát hiện image production crash `No module named uvicorn` và sửa bằng `ENV PYTHONUSERBASE` trong Dockerfile. Phát hiện `docker compose run locust` tự reset số agent về 2, làm sai lần đo scale đầu, nên chạy lại với `--no-deps`. Chụp Grafana/Jaeger/Prometheus bằng Playwright. Chạy thí nghiệm A–E bằng script poll `/api/v1/alerts` | Kiểm số container trước/sau mỗi lần scale (`docker ps`). Đọc lại từng screenshot. Thời gian firing lấy từ log script, không ước lượng. `promtool test rules` SUCCESS |
| 9 | Part 3: deploy | Sau khi tôi tự `railway login`, AI chạy Railway CLI để tạo project, Redis, biến môi trường; key sinh bằng `secrets.token_urlsafe(32)`, đặt qua `--stdin`, không ghi vào repo. `railway up` bị tài khoản chặn nên AI đề xuất chuyển sang Render Blueprint; tôi tự tạo Blueprint trên dashboard | AI chạy 4 lệnh CP6 trên URL Render: 200/200/401/200, thêm rate limit 429. Phát hiện `day14-agent.onrender.com` (không có hậu tố) là service của người khác, vì key trả 401, nên lấy đúng URL `-3q3m` từ dashboard |
| 8 | Viết BENCHMARK_REPORT.md | AI soạn nháp phân tích từ JSON/CSV/log đã đo. Đọc sai panel Tokens/s (panel dạng stacked) nên phải sửa lại bằng truy vấn PromQL | Đối chiếu từng số với file nguồn trong `reports/`, `benchmark-results/` và log thí nghiệm |
