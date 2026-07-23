# HOGOPLUS-FS — Mumbai Migration Runbook (Phase 1: backend → AWS Mumbai EC2)

**Goal:** run the **same** backend on your own AWS Mumbai (`ap-south-1`) EC2 so phone→server latency drops from ~300–500ms to ~20–40ms. **Neon (Singapore) stays the DB. Upstash stays Redis. R2 stays media.** The Emergent deployment keeps running unchanged → rollback is trivial.

> This is Phase 1 only. **Nothing here deploys automatically.** You execute on AWS. No app code was changed for containerization (verified — `/api/health`, `/api/dash/`, `server:app`, and the `webdash_dist` path already exist).

---

## 0. Prepare in advance (you provide)
- **Domain + DNS access** for an API subdomain, e.g. `api.hogoplus.com` (ability to add an A-record).
- **AWS account** in `ap-south-1` with an **EC2 key pair** (for SSH).
- The **current Emergent `backend/.env`** values — you'll copy them verbatim (`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, all `S3_*`, `AWS_*`, `EMERGENT_LLM_KEY`, `SMSGATEWAYHUB_*`, `OTP_MODE`, `ALLOW_NEW_REGISTRATION`, etc.). **`JWT_SECRET` must be identical** so tokens work on both backends during the transition.
- Repo access on the server (Git remote / deploy key).

## Artifacts in the repo (git pull, then use these paths)
```
Dockerfile                # repo root — multi-stage: webdash build + python runtime
docker-compose.yml        # repo root — backend service, healthcheck, log rotation, optional redis
.env.template             # repo root — EVERY env var, copy to .env and fill
.dockerignore             # repo root
setup_server.sh           # repo root — one-shot idempotent EC2 setup
latency_check.sh          # repo root — OLD vs NEW latency A/B
MUMBAI_MIGRATION.md        # this file
```
Fetch on the server: `git clone <repo> /opt/hogoplus` (or `cd /opt/hogoplus && git pull`).

---

## 1. Launch the EC2 instance
| Setting | Value |
|---|---|
| Region | **ap-south-1 (Mumbai)** |
| Type | **t3.medium** (2 vCPU / 4 GB) |
| AMI | **Ubuntu Server 24.04 LTS** |
| Storage | **30 GB gp3** |
| Key pair | your SSH key |
| Elastic IP | **Allocate + associate** (stable IP for DNS) |

**Security group (inbound):**
| Port | Source | Why |
|---|---|---|
| 22 | your IP only | SSH |
| 80 | 0.0.0.0/0 | HTTP → certbot + redirect to 443 |
| 443 | 0.0.0.0/0 | HTTPS API |

(The container listens on `127.0.0.1:8001` only — never expose 8001 publicly. `setup_server.sh` also enables UFW for 22/80/443.)

**DNS:** add an **A-record**: `api.hogoplus.com → <Elastic IP>`. Wait for it to resolve (`dig +short api.hogoplus.com`) before running certbot.

---

## 2. Deploy
SSH in, then:
```bash
sudo git clone <YOUR_REPO_URL> /opt/hogoplus       # or: cd /opt/hogoplus && sudo git pull
cd /opt/hogoplus
sudo cp .env.template .env
sudo nano .env                                     # paste Emergent values; keep DISABLE_SCHEDULER=true for now
sudo bash setup_server.sh api.hogoplus.com ops@hogoplus.com   # docker, nginx, TLS, UFW (idempotent)
sudo docker compose up -d --build                  # build image + start (or: sudo systemctl start hogoplus)
sudo docker compose logs -f backend                # watch boot
```
`setup_server.sh` installs Docker + compose, writes the nginx vhost (gzip on, `client_max_body_size 100M`), runs certbot for your domain, opens UFW 22/80/443, and installs a `hogoplus.service` systemd unit so the stack comes up on reboot.

**Verify TLS + reachability:**
```bash
curl -s https://api.hogoplus.com/api/health
# {"status":"healthy","db_seeded":true}
```

---

## 3. Smoke-test checklist (run against `https://api.hogoplus.com`)
- [ ] **Health + DB:** `GET /api/health` → `db_seeded: true` (proves Neon reachable + seeded).
- [ ] **Real-user OTP login:** send-otp + verify-otp for a real number (e.g. `+918483029039`) → returns access token.
- [ ] **Demo login:** verify-otp `+919000000500` / `123456` → token.
- [ ] **Incident submit with photo (R2 write):** upload a photo via `POST /api/files/upload`, then `POST /api/incidents` with the returned `photo_key` → 200; confirm a new object appears in the R2 bucket.
- [ ] **Dashboard load w/ password login:** open `https://api.hogoplus.com/api/dash/`, log in (CGM/MD), Incidents + Overview render.
- [ ] **ANPR on a plate photo:** submit a vehicle photo incident → after a few seconds the incident shows `plate_status` detected/not_detected (Rekognition/LLM path).
- [ ] **Scheduler startup logs:** `docker compose logs backend | grep scheduler` → **only if you flip `DISABLE_SCHEDULER=false`**; you should see `registered escalation_sweep / ai_suggestion_timeout_sweep / punchout_reminder_sweep / demo_cleanup_sweep / nightly_backup / nightly_report` and `6 jobs registered`. (Keep it `true` during dual-run — see §5.)
- [ ] **Backup-now → R2 key:** as CGM/MD, `POST /api/admin/backup-now` → returns `{"uploaded":"backups/YYYY-MM-DD/HHMM.sql.gz","method":"pg_dump"}`. `method:"pg_dump"` confirms the v18 client works; `method:"python"` means the Python fallback ran (still a valid R2 backup).

---

## 4. Mobile cutover (requires a new APK — v1.0.9)
The app reads the backend base URL from its env at build time. Change **both** to the new HTTPS domain (no trailing slash, no `/api`):
```
EXPO_PUBLIC_BACKEND_URL=https://api.hogoplus.com
EXPO_PUBLIC_API_URL=https://api.hogoplus.com
```
Then build a **new APK (v1.0.9)** via the Emergent **Publish → build** flow and distribute it. There is **no OTA/env hot-swap** for a native app — the URL is baked into the binary, so a cutover = a new build. Until users install v1.0.9 they keep hitting the Emergent backend (which is fine — same DB).

> Do this build **after** the smoke tests pass on Mumbai.

---

## 5. Dual-backend safety (both live on the SAME Neon + Upstash)
During the transition, the Emergent backend and the Mumbai backend both point at the **same Neon DB and Upstash Redis**. This is safe; here's what's enforced and what you must do:

**5a. Scheduled jobs run ONCE globally — verified.** Every scheduled job (`escalation_sweep`, `ai_suggestion_timeout_sweep`, `punchout_reminder_sweep`, `demo_cleanup_sweep`, `nightly_backup`, `nightly_report`) first takes a **Redis NX lock** `jobs:lock:<name>` on the shared Upstash before running (`app/scheduler.py::_run` → `acquire_job_lock`). `SET NX` is atomic, so across **all workers and all hosts** exactly one acquires it and runs; the rest log `skipped — already executed by another container`. Each lock TTL is shorter than its interval (e.g. escalation 25min < 30min, backup 210min < 240min), so the lock always clears before the next fire → no missed runs, no double runs. **This covers cross-host duplication — no change needed.**

**Belt-and-suspenders (do this):** keep **`DISABLE_SCHEDULER=true`** in the Mumbai `.env` while the Emergent backend is still serving traffic, so the new/unverified box doesn't run backups/reports/sweeps at all yet (the lock already prevents doubles; this removes even the race and keeps ops on the known-good host). **After** DNS/APK cutover and once you're happy, set `DISABLE_SCHEDULER=false` (or remove it) and `docker compose up -d` so Mumbai owns the jobs — then retire Emergent.

**5b. What else could double-execute — and why it won't:**
- **Push / SMS from sweeps:** triggered inside the locked jobs → single run (covered by 5a).
- **Push / SMS from user actions** (approvals, submits): run only on the backend that served that request → never duplicated (a request hits one backend).
- **Overview cache warmer** (`_overview_warmer`, every 15s per process): writes only a cache value → idempotent, harmless if it runs on both.
- **Redis write-probe at boot:** harmless.
- No Celery beat/worker runs in production (jobs are in-process), so there's no separate scheduler to double-fire.

**5c. Sessions are stateless — logins work on either backend.** Auth is **JWT** (HMAC-signed, no server-side session store). OTP codes, OTP rate-limits, fail-counters and lockouts all live in the **shared Upstash Redis** (`otp:code:*`, `otp:fail:*`, `otp:lock:*`), so an OTP requested via one backend verifies on the other. The only in-process state is **perf caches** (S3 presign cache, dashboard overview cache) — independent per host, no correctness impact. **Nothing in local memory breaks with two backends.** (Requirement: `JWT_SECRET` identical on both — see §0.)

---

## 6. Rollback (always trivial)
Because the Emergent backend never stopped and shares the same Neon DB:
1. **Fastest (no infra change):** users on the **old APK** already hit Emergent — nothing to do for them. Just **don't distribute v1.0.9** / ask testers to keep the old build.
2. **If v1.0.9 is already out and Mumbai misbehaves:** re-point the **DNS A-record** `api.hogoplus.com` away, or ship a hotfix build pointing back to the Emergent URL. Since the URL is baked into the APK, the DNS re-point is the instant lever if you fronted Mumbai with your own domain.
3. **Stop Mumbai:** `sudo docker compose down` on the EC2 box. Emergent continues serving.

**Data risk during rollback: effectively none.** Both backends write to the **same** Neon DB and R2, so no data diverges or is stranded — switching which backend serves traffic doesn't move or lose data. The only thing to remember: if you had flipped `DISABLE_SCHEDULER=false` on Mumbai, ensure **exactly one** backend has the scheduler enabled after rollback (turn Mumbai's back to `true` or keep Emergent as the job owner) so scheduled jobs keep running on the surviving host.

---

## 7. Latency proof (measured before/after)
From your laptop or phone hotspot on an Indian network:
```bash
bash latency_check.sh \
  https://hogo-backend-phase1.preview.emergentagent.com \
  https://api.hogoplus.com \
  +919000000500 123456 15
```
Prints a median-ms table for `/api/health` and `/api/auth/me` on OLD vs NEW. Expect NEW (Mumbai) ~20–40ms vs OLD ~300–500ms.

---

## Notes / gotchas
- **pg_dump version:** Neon is PostgreSQL **18**, so the image ships `postgresql-client-18` (pg_dump must be ≥ server major). If it's ever unavailable, `backup-now` transparently falls back to a pure-Python SQL dump (still uploaded to R2).
- **First AI call is slow:** the fastembed ONNX model (~100–400MB) downloads lazily on the first RAG/embedding call; it's cached to the `fastembed_cache` Docker volume so restarts stay fast.
- **Workers:** 2 uvicorn workers sized for t3.medium. Each starts an APScheduler, but the Redis NX lock keeps execution single (§5a).
- **Do NOT** put `TESTING` in the server `.env`.
- **Do NOT** expose port 8001 in the security group — nginx (443) is the only public edge.
