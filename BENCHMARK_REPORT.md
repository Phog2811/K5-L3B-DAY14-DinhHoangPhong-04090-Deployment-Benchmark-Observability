# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON trong [reports/](reports/), CSV trong [benchmark-results/](benchmark-results/) và screenshot trong [screenshots/](screenshots/).

**Họ tên:** Dinh Hoang Phong
**Ngày chạy:** 2026-11-26
**Môi trường:** Laptop Windows 11 (RAM 15.3 GB) + WSL2 Ubuntu, Python 3.11.18; Docker Desktop 29.9.2 cấp 16 CPU / 7.4 GiB RAM. Agent develop chạy 1 process uvicorn; load generator chạy cùng máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Lúc bình thường p95 ≈ 220 ms (mock LLM ~120 ms + retrieval ~20 ms + overhead) → 500 ms còn gấp ~2 lần để chịu dao động tải, nhưng vẫn đủ chặt để bắt được khi > 5% request rơi vào nhóm chậm ~1.7 s. Đây cũng là ngưỡng mặc định của `load_test.py`. |
| Error rate `/ask` | < 2 % | Mock LLM có ~1% lỗi upstream (503) là "bình thường"; 2% cho error budget gấp đôi mức nền, vượt thì chắc chắn có sự cố thật. Alert đặt lỏng hơn (5% trong 1 phút) để tránh báo động vì spike ngắn. |
| Accuracy trên golden dataset | ≥ 85 % | Quality gate trong CI (`--min-accuracy 0.85`), cộng điều kiện **không regression** so với baseline. Sau khi sửa knowledge base, v2 đạt 100% nên khi phát hành mình chạy với `--min-accuracy 1.0`. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức, `MOCK_SLOW_RATE=0.03`)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.06 | 189.3 | 219.3 | 1704.0 | 1.67% | ✅ PASS |
| 10 | 35.91 | 190.6 | 219.6 | 1696.8 | 0.33% | ✅ PASS |
| 50 | 104.85 | 196.4 | 254.7 | 1715.5 | 2.00% | ✅ PASS (error rate chạm đúng ngưỡng ≤ 2.0%) |
| 100 | 55.98 | 376.5 | 3521.4 | 3771.2 | 1.67% | ❌ FAIL (p95) |

Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:** RPS tăng gần tuyến tính ở mức thấp rồi bão hoà và **giảm**. Theo định luật Little, RPS ≈ concurrency / latency:
c=1 → 1 / 0.249 s ≈ 4 req/s (đo được 4.06); c=10 → ≈ 41 (đo 35.9); c=50 → lẽ ra ≈ 187 nhưng chỉ đạt 104.9 vì p95 đã
tăng 219 → 255 ms, tức agent bắt đầu xếp hàng. Ở c=100 một process uvicorn không xử lý kịp: request phải chờ trong
hàng đợi, p50 tăng gấp đôi (376 ms), p95 lên 3.5 s và RPS **giảm** xuống 56 — thêm tải chỉ làm tăng thời gian chờ chứ
không tăng throughput. Điểm làm việc tốt nhất của 1 instance là khoảng c=50; muốn hơn thì phải scale ngang.
(Mỗi mức chỉ 300 request; ở c=100 chỉ có 3 "đợt" nên số còn dao động.)

### 2.2 Tail latency (300 request, concurrency 20)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.0 | 217.1 | 223.1 |
| 0.03 (mặc định) | 241.2 | 219.3 | 1710.6 |
| 0.1 | 376.6 | 1702.4 | 1714.8 |

Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Với 3% request chậm, **p99** nhảy từ 223 ms lên 1711 ms (×7.7) trong khi avg chỉ tăng 52 ms và p95 gần
như không đổi (vì 3% < 5%, nhóm chậm nằm ngoài p95). Lên 10% (> 5%) thì cả **p95** cũng nhảy lên 1702 ms, còn avg mới
tăng 188 ms so với ban đầu — avg vẫn trông "chấp nhận được" (377 ms) dù cứ 10 user thì 1 người chờ 1.7 s. Average trộn
nhóm chậm vào số đông nên che giấu trải nghiệm tệ; SLO phải đặt theo percentile (p95/p99) vì nó trả lời câu hỏi "x%
người dùng chờ không quá bao lâu". Lần chạy `MOCK_SLOW_RATE=0.1` vi phạm SLO p95 (`load_test.py` trả exit code 1).

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.6 | 108.8 | 113.8 |
| Tổng cost (USD) | 0.000397 | 0.000757 | 0.000792 |
| Cost / câu đúng (USD) | 0.00039675 | 0.00003607 | 0.00003443 |
| Quality gate | FAIL | PASS | PASS (`--min-accuracy 1.0`, 0 regression) |

Nguồn: `reports/eval_v1.json`, `eval_v2.json` (baseline v1), `eval_v2_fixed.json` (baseline `eval_v2.json`).

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 — "JWT khác gì API key trong xác thực?" | `token`, `hết hạn`, `chữ ký` | Retrieval không khớp tài liệu nào nên v2 trả câu chung chung. Thêm vào `KNOWLEDGE_BASE` entry keyword `["jwt"]`: "API key là chuỗi bí mật cố định, không tự hết hạn. JWT là token có chữ ký số, chứa thông tin user và thời điểm hết hạn (exp)..." |
| scaling-03 — "Kubernetes HPA scale dựa trên những chỉ số nào?" | `cpu`, `memory`, `custom metrics` | Thêm entry keyword `["hpa", "kubernetes", "autoscal"]`: "Kubernetes HPA ... dựa trên CPU, memory hoặc custom metrics như RPS hay độ dài hàng đợi." |

Trước khi thêm, mình grep `golden_dataset.jsonl` để chắc các keyword mới (`jwt`, `kubernetes`, `hpa`, `autoscal`) chỉ
xuất hiện trong đúng 2 câu này, nên không thể "cướp" retrieval của câu khác. Kết quả eval cuối: 2 câu được cải thiện,
**0 regression**, `Quality gate (accuracy ≥ 100%, không regression): ✅ PASS`. Không sửa `golden_dataset.jsonl`.
Phần sửa được chép sang `production/utils/mock_llm.py` để stack Docker cũng dùng KB mới.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- v2 tốn **~1.9 lần token** mỗi câu (108.8 vs 56.6) và ~1.9 lần tổng cost vì prompt phải chứa thêm context lấy từ retrieval; latency p95 trong eval tăng ~24 ms (188.5 → 212.6 ms) do thêm bước retrieval.
- Đổi lại accuracy từ 4.3% lên 91.3%, nên **cost / câu đúng rẻ hơn ~11 lần** (0.000397 → 0.0000361 USD). So 2 phiên bản phải dùng cost / câu đúng: v1 "rẻ" mỗi câu nhưng gần như mọi câu trả lời đều vô dụng.
- Quality gate chiều ngược lại (eval v1 với `--baseline reports/eval_v2.json`) báo **20 câu regression**, `❌ FAIL`, exit code **1** → dùng được để chặn merge.
- p95 latency trong `eval_v2_fixed.json` là 1538.6 ms chỉ vì 2/23 request rơi vào nhóm chậm ngẫu nhiên — đúng như README cảnh báo: 23 câu quá ít để kết luận về latency, latency phải đo bằng load test.

**Job CI (Exercise 7.3):** [.github/workflows/eval.yml](.github/workflows/eval.yml) — mỗi pull request đụng tới
`develop/` sẽ cài requirements, bật agent v2 (`MOCK_ERROR_RATE=0` để kết quả ổn định), chạy
`python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85`. `run_eval.py` trả exit code 1 khi accuracy
dưới ngưỡng hoặc có regression → step fail → job fail → bật branch protection "require status check `quality-gate`" là PR không merge được.

---

## 4. Observability stack (production)

Stack chạy bằng `docker compose -p k5-day14-observability ...`. Hai điều chỉnh so với đề, ghi lại cho minh bạch:
1. **Sửa bug Dockerfile của `production/`**: container agent crash `ModuleNotFoundError: No module named 'uvicorn'` vì user
   `agent` có home là `/app` (`useradd -d /app`) nên Python tìm package `--user` ở `/app/.local`, trong khi Dockerfile copy
   vào `/home/agent/.local`. Thêm `ENV PYTHONUSERBASE=/home/agent/.local` là chạy.
2. **Grafana chạy ở cổng 3001** (file override chỉ đổi `ports`), vì cổng 3000 trên máy đang bị project khác dùng.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: [screenshots/grafana-dashboard.png](screenshots/grafana-dashboard.png) — chụp lúc chạy Locust 100 user với 3 instance
- [x] Trace chậm: [screenshots/jaeger-slow-trace.png](screenshots/jaeger-slow-trace.png)
- [x] Trace lỗi có event `exception`: [screenshots/jaeger-error-trace.png](screenshots/jaeger-error-trace.png)
- [x] Trang Alerts của Prometheus có alert firing: [screenshots/prometheus-alert-firing.png](screenshots/prometheus-alert-firing.png)

**Trả lời Exercise 7.4** (đọc trên ảnh dashboard):
1. Latency p95 = **292 ms**; trên panel "Latency /ask", đường avg (~240 ms, khớp `Average` 236.6 ms của Locust) nằm sát p50/p95 còn p99 ở **~1.8 s**. Khoảng cách avg ↔ p99 rất lớn = tail latency: đa số request nhanh nhưng ~3% bị chậm bất thường; nhìn avg sẽ không thấy nhóm này.
2. Panel "Requests/s theo instance": khi có 3 instance, Nginx chia đều (các đường gần chồng lên nhau, round-robin). Lúc chạy scale_1 chỉ có một đường duy nhất gánh ~60 req/s.
3. Panel "Tokens/s" vẽ dạng **stack** (`stacking: normal` trong JSON dashboard) nên đỉnh đường vàng là input + output. Hỏi thẳng Prometheus `sum by (type) (rate(llm_tokens_total[1m]))` lúc chạy 15 user: **input 714.9 tokens/s, output 375.3 tokens/s (gấp 1.9 lần)**; ở mức từng request: input 83 / output 44 token (trace 4.3). Input lớn hơn vì agent v2 nhét **context từ retrieval vào prompt** → prompt (input) dài hơn câu trả lời (output). Cũng vì vậy v2 tốn gần gấp đôi token so với v1.
4. `curl -i http://localhost:8080/metrics` → **HTTP 404**. Nginx chặn `/metrics` từ bên ngoài: endpoint này lộ thông tin nội bộ (route, số request, chi phí, version) và chỉ dành cho Prometheus scrape thẳng từng container trong mạng `obs_net`, không đi qua Nginx.

Thêm: Error rate 1.02% (mức nền ~1% của mock), Instances up = 3, panel "Phiên bản đang chạy" = `mock-llm-small` / `v2` / 3 instance.
`promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

### 4.2 Thí nghiệm "phá hệ thống"

Điều kiện chạy: 3 agent sau Nginx, Locust headless 15 user chạy nền liên tục. Chọn 15 thay vì 30 user vì riêng tải 100 user đã đủ làm `LLMCostBurnRateHigh` firing ($6.35/h, mục 5), nên cần nền chi phí dưới ngưỡng $2/h thì thí nghiệm C mới có ý nghĩa; nền đo lúc 16:46:53 là $1.86/h. Mỗi thay đổi áp bằng biến môi trường và `docker compose up -d --no-deps --scale agent=3 agent`, tương đương sửa `.env`. Thời điểm chuyển trạng thái lấy từ script poll `GET /api/v1/alerts` mỗi 5 s.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` (đổi 16:47:09, cùng lúc với B) | `AgentHighErrorRate` | pending 16:47:42 → firing 16:48:42, **≈ 93 s** (rule `for: 1m`) | Error rate (Golden Signals), LLM calls theo kết quả |
| B | `MOCK_SLOW_RATE=0.3` (đổi 16:47:09, cùng lúc với A) | `AgentHighLatencyP95` | pending 16:47:42 → firing 16:49:42, **≈ 153 s** (rule `for: 2m`) | Latency /ask — p50 / p95 / p99 |
| C | `LLM_MODEL=mock-llm-large`, A/B trả về mặc định (đổi 16:52:38) | `LLMCostBurnRateHigh` | pending 16:53:23 → firing 16:55:23, **≈ 165 s**; lúc đó burn rate = **$9.09/h** (≈ 4.9× nền $1.86/h, cửa sổ `rate[5m]` vẫn còn lẫn dữ liệu model nhỏ) | Cost burn rate (USD/giờ), LLM cost (1h) |
| D | `docker pause k5-day14-observability-agent-2` (16:51:46) | `AgentInstanceDown` | pending 16:51:57 → firing 16:52:27, **≈ 41 s** (rule `for: 30s`); unpause ngay sau đó | Instances up |
| E | `AGENT_VERSION=v1`, các biến khác mặc định (đổi 16:55:33) | **Không có** | Theo dõi 420 s cộng thêm đến 17:03: không alert nào firing; lúc 17:02:36 `/api/v1/alerts` = `[]` | Phiên bản đang chạy (3/3 instance `v1`), Retrieval hit ratio (agent v2) |

Số đo trong lúc E chạy (PromQL, cửa sổ 5m, lúc 17:03:05):

- error rate /ask là 0.75%;
- p95 /ask là 0.199 s;
- cost là $0.59/h;
- `count(agent_info{version="v1"}) = 3`.

Tức là mọi Golden Signal đều xanh, trong khi eval cho thấy v1 chỉ đúng **4.3%** (1/23, mục 3).

Ghi chú:

- A và B áp cùng lúc nên hai alert chạy song song. Chênh lệch thời gian firing (93 s và 153 s) đúng bằng chênh lệch `for:` giữa hai rule.
- Thời gian thực tế = `for:` + thời gian để `rate[1m]` (hoặc `rate[5m]`) vượt ngưỡng + chu kỳ evaluate/scrape. Vì vậy alert luôn đến muộn hơn giá trị `for:`.
- Trong lúc E, `AgentHighLatencyP95` có một lần pending lúc 17:00:01. Đó là một đợt slow request ngẫu nhiên trong cửa sổ 1m với `MOCK_SLOW_RATE=0.03`. Điều kiện không giữ đủ 2 phút nên alert không firing; đây chính là tác dụng của `for:` trong việc chống báo động giả.
- Ở D, panel Error rate của agent vẫn xanh. Metric `http_requests_total` do chính agent tự đếm: instance bị pause không đếm được request của nó, còn hai instance còn lại vẫn trả 200. Lỗi 504 chỉ phát sinh ở Nginx (upstream timeout), nên chỉ Locust và log Nginx nhìn thấy. Tôi không tách riêng số lượng 504 trong lần chạy này.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Lỗi chất lượng không làm hỏng hạ tầng, nên phải đo chính chất lượng:

1. **Chặn trước khi deploy:** quality gate trong CI ([.github/workflows/eval.yml](.github/workflows/eval.yml)) chạy `run_eval.py --min-accuracy 0.85` và so với baseline. Đã đo: v1 so với baseline v2 cho 20 regression, exit code 1, nên PR bị chặn.
2. **Phát hiện sau khi deploy:** một job synthetic định kỳ (vài phút một lần) gửi các câu trong golden set vào production, xuất `agent_eval_accuracy` thành metric Prometheus và đặt alert, ví dụ `< 0.85 for 10m`.
3. **Metric proxy rẻ:** v2 luôn retrieve nên retrieval hit ratio rơi về 0 là dấu hiệu bất thường. Có thể alert theo phiên bản đang chạy hoặc tokens/request lệch so với baseline.
4. **Tín hiệu từ người dùng:** tỉ lệ thumbs-down, câu hỏi lặp lại, hoặc chấm điểm mẫu bằng LLM-as-judge trên traffic thật.

### 4.3 Debug bằng trace

Trace chậm nhất (Jaeger → `observable-agent` → `POST /ask`, Min Duration 1s, sort theo Duration giảm dần):

- `trace_id`: `6bdf4d79289f40c91768f57c2d078662`
- Tổng thời gian: **1792.8 ms** (Jaeger hiển thị 1.8 s; số chính xác lấy từ log `http_request.ms`)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (**1696.3 ms, ≈ 94.6%**); `agent.retrieve_context` chỉ 79.8 ms. Model `mock-llm-small`, input 83 / output 44 token → chậm nằm ở upstream LLM, không phải code của agent.
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep 6bdf4d79289f40c91768f57c2d078662`):

```json
{"ts": "2026-11-26T09:33:25.850675+00:00", "level": "INFO", "service": "observable-agent", "instance": "4f394e24395b", "event": "llm_call", "trace_id": "6bdf4d79289f40c91768f57c2d078662", "span_id": "0b71027b8459a448", "request_id": "ae593e01bfcc", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 83, "output_tokens": 44, "cost_usd": 3.9e-05, "llm_ms": 1696.3}
{"ts": "2026-11-26T09:33:25.850969+00:00", "level": "INFO", "service": "observable-agent", "instance": "4f394e24395b", "event": "http_request", "trace_id": "6bdf4d79289f40c91768f57c2d078662", "span_id": "0b71027b8459a448", "request_id": "ae593e01bfcc", "method": "POST", "route": "/ask", "status": 200, "ms": 1792.8}
```

Trace lỗi (tag `error=true`): `trace_id` `7b110ec6d328e04ff76771edda66def4`, 862 ms, `POST /ask` trả **503**. Span
`chat mock-llm-small` (836 ms) có `error.type = upstream_unavailable` và event `exception`:
`Upstream LLM error: 503 Service Unavailable (mock)`. Log tương ứng:

```json
{"ts": "2026-11-26T09:34:12.067636+00:00", "level": "INFO", "service": "observable-agent", "instance": "4f394e24395b", "event": "llm_error", "trace_id": "7b110ec6d328e04ff76771edda66def4", "span_id": "540e3912f7f73e12", "request_id": "db3c27420bb8", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T09:34:12.067834+00:00", "level": "INFO", "service": "observable-agent", "instance": "4f394e24395b", "event": "http_request", "trace_id": "7b110ec6d328e04ff76771edda66def4", "span_id": "540e3912f7f73e12", "request_id": "db3c27420bb8", "method": "POST", "route": "/ask", "status": 503, "ms": 861.7}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 59.44 | 190 | 260 | 1700 | 88 / 7115 (1.24%) |
| 3 | 59.82 | 190 | 230 | 1700 | 69 / 7083 (0.97%) |

Nguồn: dòng `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`. Failures đều là `503` từ mock LLM (lỗi ngẫu nhiên ~1%).

**Giải thích kết quả:** Scale 1 → 3 instance **không tăng RPS** (59.4 → 59.8) và p95 chỉ giảm nhẹ 260 → 230 ms; p50 và
p99 giữ nguyên. Lý do:
- **Throughput bị giới hạn bởi phía tạo tải, không phải bởi agent.** Mỗi user Locust có thời gian nghỉ giữa các request, nên 100 user chỉ sinh ra ~60 req/s. Ở mức này 1 instance chưa bão hoà (in-flight ~10–20, p95 vẫn dưới SLO 500 ms), nên thêm instance không có thêm việc để làm. Muốn thấy lợi ích của scale phải đẩy tải tới mức làm 1 instance bão hoà (như c=100 ở mục 2.1).
- **Nút thắt latency nằm ở LLM.** Panel "LLM latency p95" ~198 ms gần bằng toàn bộ p50 190 ms của request, còn p99 1.7 s là do request chậm của mock LLM (`MOCK_SLOW_RATE`). Scale ngang không làm LLM trả lời nhanh hơn, nên p50/p99 không đổi; p95 giảm nhẹ chỉ vì mỗi instance ít hàng đợi hơn.

**Lưu ý về cách chạy:** lệnh mẫu `docker compose run --rm locust ...` sẽ khởi động lại service phụ thuộc theo
`deploy.replicas: 2` trong compose → lần chạy đầu "1 instance" thực ra có **2 instance** (container `agent-2` được tạo lúc
16:33:11), lần "3 instance" bị xoá mất `agent-3`. Mình phát hiện qua panel "Requests/s theo instance" và `docker ps`,
nên chạy lại cả hai lần với `--no-deps`; sau mỗi lần chạy đã kiểm tra số container agent (1 và 3) trước khi lấy CSV.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối.** 3% request chậm làm p99 tăng 7.7 lần mà avg chỉ tăng 52 ms; 10% chậm thì p95 vọt lên 1.7 s trong khi avg vẫn "ổn". SLO và alert phải đặt theo percentile.
  2. **Metric hạ tầng không đo được chất lượng.** Đổi sang v1 accuracy rơi từ 100% xuống 4.3% nhưng dashboard vẫn xanh; chỉ eval trên golden dataset (gắn vào CI bằng exit code) mới bắt được. Và so 2 phiên bản phải dùng cost / câu đúng chứ không phải cost / câu.
  3. **Ba trụ cột phải nối được với nhau và phải tự kiểm chứng số liệu.** Dashboard báo p99 cao → Jaeger chỉ ra span `chat mock-llm-small` chiếm 94.6% → `trace_id` grep ra đúng dòng log JSON. Cũng chính nhờ nhìn dashboard mà mình phát hiện lần benchmark "1 instance" đầu tiên thực ra chạy 2 instance.
- Nếu đưa agent này lên production thật, sẽ thêm:
  - Synthetic check từ bên ngoài + metric/alert ở tầng Nginx (tỉ lệ 502/504, upstream response time) — vì lỗi ở LB không hiện trên metric của agent.
  - Alert "LLM error rate" tách riêng khỏi HTTP error rate và theo từng model/provider, kèm alert khi `retrieval hit ratio` giảm (dấu hiệu sớm của lỗi chất lượng như thí nghiệm E).
  - Eval định kỳ trên mẫu traffic thật (LLM-as-judge) và alert khi điểm chất lượng giảm; budget alert theo ngày/tháng song song với burn rate; alert saturation (in-flight / hàng đợi) để biết khi nào cần scale.
