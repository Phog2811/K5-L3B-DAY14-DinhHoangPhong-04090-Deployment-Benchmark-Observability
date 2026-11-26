# Deployment Information

> Agent Part 6 (`06-lab-complete/`) deploy lên cloud theo lưu ý K5 (README mục 8).

## Public URL

`<ĐIỀN_URL_SAU_KHI_DEPLOY>`

## Platform

Railway — build bằng `06-lab-complete/Dockerfile` theo [06-lab-complete/railway.toml](06-lab-complete/railway.toml)
(`builder = "DOCKERFILE"`, `healthcheckPath = "/health"`), kèm một service Redis của Railway.

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã đặt trên Railway (không ghi key vào repo):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả:

```text
<DÁN_KẾT_QUẢ_4_LỆNH>
```

## Environment Variables Set (trên Railway dashboard, không có trong code)

| Biến | Giá trị |
|---|---|
| `AGENT_API_KEY` | chuỗi ngẫu nhiên (secret, chỉ đặt trên Railway) |
| `REDIS_URL` | tham chiếu `${{Redis.REDIS_URL}}` tới service Redis của Railway |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | Railway tự cấp; `CMD` trong Dockerfile nghe theo `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
