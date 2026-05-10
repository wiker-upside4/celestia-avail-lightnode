# DABEAT 데이터 카탈로그

> **목적**: DABEAT가 매 분 수집해서 DB에 쌓는 데이터의 "메뉴판". 어떤 질문에 답할 수 있는지 + 어디서 어떤 컬럼을 보면 되는지 정리.
>
> **DB 접속**:
> - **Grafana** (가장 편함): `http://<dashboard-asia-ip>:3000` → 좌측 **Explore** → 데이터소스 `dabeat-pg` 선택 → SQL 직접 실행
> - **psql** (운영자만): SSH 터널 `ssh -L 5432:127.0.0.1:5432 wiker@<worker-db1-ip>` → `psql -h localhost -U dabeat_ro -d dabeat` (SELECT 전용)

---

## 0. 큰 그림

| 측면 | Celestia | Avail |
|---|---|---|
| 모니터링 노드 | `celestia-lightnode` (RPC :26658) | `avail-lightnode` (HTTP :7007) |
| 자체 prober | DABEAT01 namespace | App ID 46 (`protoBonDA`) |
| 매분 RPC 호출 수 | ~150-300 | ~50-100 |

**8개 테이블, 매분 ~50/min 행 추가, 시간당 ~3000행, 일당 ~50 MB, 연간 ~15 GB.**

모든 테이블에 `da_layer TEXT` 컬럼 (`'celestia'` 또는 `'avail'`) → **`WHERE da_layer = 'X'`로 레이어 분리**. 양쪽이 같은 테이블에 행 단위로 섞여 있음.

### 테이블 한 줄 요약

| # | 테이블 | 무엇 | 빈도 |
|---|---|---|---|
| 1 | `node_health` | 라이트노드 sync/네트워크/RPC 응답 | 1분 × 2 (양 레이어) |
| 2 | `headers` | 블록 메타 + per-block 가용성 요약 | Celestia ~10/min, Avail ~3/min |
| 3 | `block_availability_samples` | 가용성 검증 attempt 시계열 | ~10-30/min |
| 4 | `namespace_observations` | 다른 롤업/app_id 활동 | ~150/min (active 6개 기준) |
| 5 | `probes` | 자체 submit 기록 | 매 분 2 |
| 6 | `retrievals` | 자체 retrieval 결과 (Survival Curve) | 5분마다 9-30 |
| 7 | `fraud_events` | Celestia BEFP 발생 기록 (정상시 비어있음) | 0 |
| 8 | `monitored_namespaces` | 추적 대상 매핑 (설정) | 정적 |

---

## 1. `node_health` — 라이트 노드 자체 건강도

**무엇**: 라이트노드의 sync 상태, 네트워크 연결, RPC 응답성, 자원 사용량 1분 스냅샷
**빈도**: 매 분 2행 (Celestia 1 + Avail 1)
**언제 보나**: "노드 상태 점검", "RPC 느려졌나", "동기화 잘 되고 있나"

### 핵심 컬럼

| 컬럼 | 양쪽 | Celestia 전용 | Avail 전용 |
|---|---|---|---|
| `network_head` (BIGINT) | ✓ 네트워크 최신 height | | |
| `local_head` (BIGINT) | ✓ LC가 받은 최신 height | | |
| `sync_lag` (INT) | ✓ network − local | | |
| `is_syncing` (BOOL) | ✓ sync_lag > 1 | | |
| `peers_count` (INT) | | 연결 피어 수 (Avail은 NULL) | |
| `bandwidth_in_total` / `bandwidth_out_total` (BIGINT) | | 누적 바이트 | |
| `rate_in` / `rate_out` (BIGINT) | | 현재 byte/s | |
| `das_running` (BOOL) | | DAS 동작 여부 | |
| `das_concurrency` (INT) | | DAS 동시 작업 수 | |
| `das_failed_samples` (INT) | | **항상 NULL** (v0.30.2 미노출) | |
| `block_confidence` (FLOAT) | | | 최신 블록 confidence (%) |
| `rpc_latency_ms` (INT) | ✓ RPC 호출 응답 시간 | | |
| `rpc_success` (BOOL) | ✓ RPC 호출 전체 성공 여부 | | |
| `details` (JSONB) | ✓ Celestia: `{node_info, sync_state, resource_state, nat_status, pubsub_peers_count}`, Avail: `{modes, network, version, available, block_status}` | | |

### 답할 수 있는 질문

```sql
-- 지난 1시간 평균 sync_lag
SELECT da_layer, AVG(sync_lag), MAX(sync_lag)
FROM node_health WHERE ts > NOW() - INTERVAL '1 hour' GROUP BY 1;

-- Celestia 피어 변동
SELECT date_trunc('minute', ts), peers_count
FROM node_health WHERE da_layer='celestia' AND ts > NOW() - INTERVAL '6 hours'
ORDER BY 1;

-- RPC latency p95
SELECT da_layer, percentile_cont(0.95) WITHIN GROUP (ORDER BY rpc_latency_ms)
FROM node_health WHERE ts > NOW() - INTERVAL '24 hours' GROUP BY 1;

-- Avail 최신 confidence
SELECT ts, block_confidence
FROM node_health WHERE da_layer='avail' AND block_confidence IS NOT NULL
ORDER BY ts DESC LIMIT 10;
```

---

## 2. `headers` — 블록 단위 메타데이터 + 가용성 요약

**무엇**: 라이트노드가 본 모든 블록의 헤더 정보 + per-block 가용성 검증 결과
**빈도**: Celestia ~10행/min (블록 ~6초), Avail ~3행/min (블록 ~20초). 합 ~13/min, 18,720/day
**언제 보나**: "블록 X에 있는 데이터", "특정 시간대 처리량", "가용성 검증 실패한 블록 찾기"

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `da_layer`, `height`, `block_hash`, `parent_hash` | 식별 + 체이닝 |
| `block_time` (TIMESTAMPTZ) | 블록 생성 시각 |
| `data_root` | 데이터 공약 머클 root |
| `proposer_address` | Celestia: 채워짐 / Avail: NULL (LC 미노출) |
| `square_size` (INT) | Celestia EDS 사이드 길이 (32, 64, 128 등) |
| `rows`, `cols` (INT) | Avail matrix 크기 |
| `data_size_bytes` (BIGINT) | Celestia: square² × 512 / Avail: rows × cols × 32 |
| `details` (JSONB) | 추가 메타 (chain_id, app_lookup, KZG commitments 등) |
| **per-block 가용성 (양 레이어 공통):** | |
| `availability_first_check_at` (TIMESTAMPTZ) | 첫 체크 시각 |
| `availability_settled_at` (TIMESTAMPTZ) | settle된 시각 (NULL = 진행 중) |
| `availability_attempts` (INT) | 누적 체크 수 |
| `availability_max_confidence` (FLOAT) | Avail만 — 최고 도달 confidence |
| `availability_last_status` (TEXT) | Avail만 — `verifying-data` / `incomplete` |
| **Celestia 전용 가용성:** | |
| `shares_available` (BOOL) | `share.SharesAvailable` 결과 |
| `shares_check_latency_ms` (INT) | 체크 RPC latency |
| `shares_check_error` (TEXT) | 실패 시 에러 분류 |

### 답할 수 있는 질문

```sql
-- 시간대별 처리량 (KB/s)
SELECT time_bucket('5 min', ts) AS bucket, da_layer,
       SUM(data_size_bytes)/1024/300 AS kbs
FROM headers WHERE ts > NOW() - INTERVAL '6 hours' GROUP BY 1, 2 ORDER BY 1;

-- Avail incomplete 블록 비율 (DA 신뢰성 신호)
SELECT 100.0 * COUNT(*) FILTER (WHERE availability_last_status='incomplete') / COUNT(*) AS pct_incomplete
FROM headers WHERE da_layer='avail' AND availability_settled_at IS NOT NULL;

-- Celestia square_size 분포
SELECT square_size, COUNT(*)
FROM headers WHERE da_layer='celestia' AND ts > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY 1;

-- 특정 블록 정보 lookup
SELECT * FROM headers WHERE da_layer='celestia' AND height = 10984650;
```

---

## 3. `block_availability_samples` — 가용성 검증 시도별 시계열

**무엇**: 한 블록을 여러 번 가용성 체크한 매 attempt 기록
**빈도**: Celestia ~6/min (블록당 1회 single-shot), Avail ~3-9/min (블록당 1~3회 settle까지)
**언제 보나**: Avail confidence가 시간에 따라 어떻게 변했나, retrieval latency 분석

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `da_layer`, `height`, `attempt` (INT) | 동일 블록 N번째 시도 |
| `status` (TEXT) | Avail만 (`verifying-data`/`incomplete`) |
| `confidence` (FLOAT) | Avail만 (0~100) |
| `available` (BOOL) | Celestia만 |
| `latency_ms` (INT) | 양쪽 |

### 답할 수 있는 질문

```sql
-- 특정 블록의 confidence 변화 추이 (Avail)
SELECT attempt, status, confidence, latency_ms
FROM block_availability_samples
WHERE da_layer='avail' AND height = 2901817 ORDER BY attempt;

-- 시간대별 incomplete 발생률
SELECT date_trunc('hour', ts) AS hr,
       100.0 * COUNT(*) FILTER (WHERE status='incomplete') / COUNT(*) AS pct_incomplete
FROM block_availability_samples WHERE da_layer='avail'
GROUP BY 1 ORDER BY 1;
```

---

## 4. `namespace_observations` — 다른 롤업 활동 시계열

**무엇**: 모니터링 대상 namespace/app_id의 블록별 활동 (메타데이터 기반)
**빈도**:
- Celestia: 활성 namespace × 50 blocks/run = ~150/min (Eclipse/Lightlink/Movement)
- Avail: 3 app_ids × ~3 blocks/min = ~9/min
**언제 보나**: "Manta는 시간당 얼마나 데이터 올리나", "롤업 활동 변동", "DA 사용 시장"

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `da_layer`, `namespace_or_appid`, `height` | 식별 |
| `blob_count` (INT) | 해당 블록의 이 namespace에 속한 blob 수 |
| `total_bytes` (BIGINT) | 페이로드 합계 |
| `commitments` (TEXT[]) | Celestia만 — KZG/blob commitment 목록 |
| `fetch_latency_ms` (INT) | RPC fetch 시간 |
| `fetch_success` (BOOL) | retrieval 성공 여부 |
| `error_type` (TEXT) | 실패 시 분류 |

### 답할 수 있는 질문

```sql
-- 24h 롤업별 데이터 사용량 (rollup_name과 함께)
SELECT mn.rollup_name,
       SUM(no.blob_count) AS blobs,
       pg_size_pretty(SUM(no.total_bytes)) AS bytes
FROM namespace_observations no
JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
WHERE no.ts > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY blobs DESC;

-- 롤업별 fetch 성공률
SELECT mn.rollup_name,
       100.0 * COUNT(*) FILTER (WHERE no.fetch_success) / COUNT(*) AS pct_ok
FROM namespace_observations no
JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
GROUP BY 1;

-- 특정 롤업이 갑자기 멈췄는지 (1시간 무활동 감지)
SELECT mn.rollup_name, MAX(no.ts) AS last_seen
FROM monitored_namespaces mn
LEFT JOIN namespace_observations no USING (da_layer, namespace_or_appid)
WHERE mn.active = TRUE GROUP BY 1 ORDER BY 2 NULLS FIRST;
```

---

## 5. `probes` — 자체 submit 기록

**무엇**: DABEAT 워커가 직접 보낸 페이로드 기록 (Avail App ID 46 + Celestia DABEAT01 namespace)
**빈도**: 매 분 2행 (양 레이어)
**언제 보나**: "submit 성공률", "회당 비용 (Celestia)", "submit latency"

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `probe_id` (BIGSERIAL) | 자동 증가 ID. retrievals와 JOIN 키 |
| `da_layer`, `ts` | 시각 |
| `namespace_or_appid` | Avail: `'46'` / Celestia: 29-byte hex |
| `submit_height` (BIGINT) | inclusion block |
| `submit_tx_hash` | Avail만 채워짐 |
| `submit_latency_ms` (INT) | submit 호출 latency |
| `submit_success` (BOOL) | |
| `payload_size_bytes`, `payload_hash` | retrieval 검증용 |
| `error_type` (TEXT) | 실패 분류 |
| `details` (JSONB) | Celestia: `fee_paid_utia`, `gas_price`, `balance_before/after` / Avail: `block_hash`, `index` |

### 답할 수 있는 질문

```sql
-- 시간당 submit 성공률
SELECT date_trunc('hour', ts) AS hr, da_layer,
       COUNT(*) AS attempts,
       ROUND(100.0 * COUNT(*) FILTER (WHERE submit_success) / COUNT(*), 2) AS pct_ok,
       AVG(submit_latency_ms)::int AS avg_ms
FROM probes WHERE ts > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Celestia 회당 fee 추적
SELECT date_trunc('hour', ts) AS hr,
       AVG((details->>'fee_paid_utia')::int) AS avg_fee_utia,
       MAX((details->>'fee_paid_utia')::int) AS max_fee
FROM probes WHERE da_layer='celestia' AND submit_success
  AND details->>'fee_paid_utia' IS NOT NULL
  AND ts > NOW() - INTERVAL '7 days' GROUP BY 1 ORDER BY 1;

-- 최근 실패 분석
SELECT da_layer, error_type, COUNT(*)
FROM probes WHERE NOT submit_success AND ts > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2;
```

---

## 6. `retrievals` — 자체 retrieval 결과 (Survival Curve)

**무엇**: 우리가 보낸 데이터를 N분 후 다시 가져올 수 있나 검증. 9개 age bucket으로.
**빈도**: 5분 cron, bucket별 candidate 수만큼 (~9-30/run)
**언제 보나**: "DA 레이어가 시간 지나도 데이터 유지하나", "retrieval latency 분포"

### 9개 age bucket

`5m`, `15m`, `1h`, `6h`, `1d`, `3d`, `7d`, `14d`, `30d` (각 ±90s tolerance)

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `probe_id` (FK → probes) | 어떤 submit 검증 |
| `da_layer`, `ln_instance` | |
| `bucket_label` (TEXT) | `'5m'`, `'15m'`, ..., `'30d'` |
| `attempt` (INT) | 보통 1 |
| `fetch_latency_ms` (INT) | retrieval 시간 (Avail ~10ms, Celestia ~250ms) |
| `fetch_success` (BOOL) | hash 일치 여부 |
| `bytes_received` (BIGINT) | 받은 페이로드 사이즈 |
| `error_type` (TEXT) | `hash_mismatch` / `blob_not_found` / `timeout` 등 |

### 답할 수 있는 질문 — **DABEAT 핵심 지표**

```sql
-- ⭐ Survival Curve: bucket별 retrieval 성공률
SELECT
  da_layer, bucket_label,
  COUNT(*) AS samples,
  ROUND(100.0 * COUNT(*) FILTER (WHERE fetch_success) / COUNT(*), 2) AS pct_ok,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY fetch_latency_ms)::int AS p95_ms
FROM retrievals
GROUP BY 1, 2
ORDER BY 1, CASE bucket_label
  WHEN '5m' THEN 1 WHEN '15m' THEN 2 WHEN '1h' THEN 3 WHEN '6h' THEN 4
  WHEN '1d' THEN 5 WHEN '3d' THEN 6 WHEN '7d' THEN 7 WHEN '14d' THEN 8 WHEN '30d' THEN 9 END;

-- 양 레이어 비교: 1h bucket retrieval 성공률
SELECT da_layer, COUNT(*), AVG(fetch_latency_ms)::int
FROM retrievals WHERE bucket_label='1h' GROUP BY 1;

-- 실패 종류별 분포
SELECT da_layer, bucket_label, error_type, COUNT(*)
FROM retrievals WHERE NOT fetch_success
GROUP BY 1, 2, 3 ORDER BY 1, 2;
```

---

## 7. `fraud_events` — Celestia fraud proof 발생 기록

**무엇**: BEFP (Bad Encoding Fraud Proof) 등 발생 시 알림. **정상 시 비어있음**.
**빈도**: 0 (행이 추가되면 ⚠️ 메인넷 사고)
**언제 보나**: 알람용. 행이 있으면 그 자체가 사건

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `ts` | 감지 시각 |
| `da_layer`, `ln_instance` | |
| `proof_type` (TEXT) | 현재 `'bad-encoding'` (BEFP) 한 가지 |
| `block_height` (BIGINT) | proof 대상 블록 |
| `raw_proof` (JSONB) | 원본 proof 객체 |
| `details` (JSONB) | 메타 (감지 latency 등) |

```sql
-- 1시간 내 fraud 발생 여부
SELECT COUNT(*) FROM fraud_events WHERE ts > NOW() - INTERVAL '1 hour';

-- (행이 발견되면 자동 alert으로 연결 권장)
```

---

## 8. `monitored_namespaces` — 추적 대상 매핑 (설정 테이블)

**무엇**: 어떤 namespace/app_id를 모니터링할지 결정하는 화이트리스트
**빈도**: 정적, 수동 INSERT/UPDATE
**언제 보나**: 새 롤업 추가, rollup_name JOIN용

### 핵심 컬럼

| 컬럼 | 의미 |
|---|---|
| `da_layer`, `namespace_or_appid` (PK) | 식별 |
| `rollup_name` | 표시명 (Eclipse, Manta Pacific, ...) |
| `source` | `celenium`, `manual` 등 |
| `active` (BOOL) | 워커가 fetch할지 여부 |

### 현재 등록 상태

| da_layer | namespace_or_appid | rollup_name | active |
|---|---|---|---|
| celestia | `0000...0065636c69707365` | Eclipse | ✅ |
| celestia | `0000...6c696768746c696e6b` | Lightlink | ✅ |
| celestia | `0000...6d6f76656d656e7430` | Movement | ✅ |
| celestia | PLACEHOLDER_manta_pacific | Manta Pacific | ❌ |
| celestia | PLACEHOLDER_aevo | Aevo | ❌ |
| avail | `1` | unknown | ✅ |
| avail | `7` | unknown | ✅ |
| avail | `11` | unknown | ✅ |

```sql
-- 활성 모니터링 대상 보기
SELECT da_layer, rollup_name, namespace_or_appid, active
FROM monitored_namespaces ORDER BY da_layer, rollup_name;
```

---

## 자주 쓸 만한 cross-table 쿼리

### 1. 양 레이어 retrieval 신뢰성 비교 (DABEAT 핵심 그림)

```sql
SELECT
  r.da_layer, r.bucket_label,
  COUNT(*) AS samples,
  ROUND(100.0 * COUNT(*) FILTER (WHERE r.fetch_success) / COUNT(*), 2) AS pct_ok
FROM retrievals r
WHERE r.ts > NOW() - INTERVAL '7 days'
GROUP BY 1, 2 ORDER BY 1, 2;
```

### 2. Celestia 한 블록의 모든 정보

```sql
SELECT
  h.height, h.block_time, h.square_size, h.data_size_bytes,
  h.shares_available,
  (SELECT COUNT(*) FROM namespace_observations no
   WHERE no.da_layer='celestia' AND no.height=h.height) AS namespaces_observed
FROM headers h
WHERE h.da_layer='celestia' AND h.height = 10984650;
```

### 3. Avail App Mode 운영 health (24h)

```sql
SELECT
  COUNT(*) AS submits,
  COUNT(*) FILTER (WHERE submit_success) AS ok,
  ROUND(100.0 * COUNT(*) FILTER (WHERE submit_success) / COUNT(*), 2) AS pct_ok,
  AVG(submit_latency_ms)::int AS avg_ms
FROM probes WHERE da_layer='avail' AND ts > NOW() - INTERVAL '24 hours';
```

### 4. 워커 freshness — 데이터 흐름 막혔는지 점검

```sql
SELECT 'node_health' AS tbl, MAX(ts), AGE(NOW(), MAX(ts)) AS lag FROM node_health
UNION ALL SELECT 'headers', MAX(ts), AGE(NOW(), MAX(ts)) FROM headers
UNION ALL SELECT 'block_avail_samples', MAX(ts), AGE(NOW(), MAX(ts)) FROM block_availability_samples
UNION ALL SELECT 'namespace_obs', MAX(ts), AGE(NOW(), MAX(ts)) FROM namespace_observations
UNION ALL SELECT 'probes', MAX(ts), AGE(NOW(), MAX(ts)) FROM probes
UNION ALL SELECT 'retrievals', MAX(ts), AGE(NOW(), MAX(ts)) FROM retrievals
ORDER BY tbl;
-- 모든 lag가 5분 이내면 정상
```

---

## 활용 가이드 — 질문 → 어디 보나

| "...을 알고 싶다" | 어디 봐야 |
|---|---|
| 노드 살아있나 / sync 잘 되나 | `node_health` |
| 특정 블록의 데이터 메타 | `headers` (height로 lookup) |
| 한 시간 동안 처리량 | `headers` SUM(data_size_bytes) |
| Avail confidence 신뢰성 | `headers.availability_*` 또는 `block_availability_samples` |
| Celestia per-block 가용성 | `headers.shares_available` |
| 다른 롤업이 얼마나 사용 | `namespace_observations` JOIN `monitored_namespaces` |
| 우리 자체 데이터 retrieval 보장 | `retrievals` (특히 bucket별) |
| 비용 추이 (Celestia) | `probes.details->>'fee_paid_utia'` |
| 메인넷에 문제 생겼나 | `fraud_events` (행 있으면 사건) |
| 워커가 멈췄나 | 모든 테이블의 MAX(ts) lag 확인 |

---

## 운영 데이터 (참고)

- 모든 테이블에 인덱스: `(da_layer, ts DESC)`. 대부분 쿼리에 `WHERE da_layer='X' AND ts > ...` 패턴이 효율적
- TimescaleDB hypertable: `node_health`, `headers`, `block_availability_samples`, `namespace_observations`, `retrievals`, `fraud_events`
- 일반 테이블: `probes`, `monitored_namespaces`
- `retention policy` / `compression policy` 미적용 — 필요 시 운영자에게 문의
- 백업: 매일 03:00 UTC, 7일치 보관 (`/home/wiker/dabeat/backups/`)

---

*문서 위치: 레포 `docs/DATA-CATALOG.md`. 데이터 모델 변경 시 이 문서도 함께 업데이트 권장.*
