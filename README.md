# DABEAT — 운영 문서

DA(Data Availability) 레이어의 retrieval 가능성과 건강도를 측정하는 모니터링 시스템.
Celestia, Avail 두 레이어를 모니터링 (EigenDA는 추후 추가). 토큰 충전 후 self-probe submit/retrieve도 추가 예정.

마지막 업데이트: 2026-05-20
- **네트워크 전체 per-block blob aggregate 수집** — 신규 테이블 `celestia_block_blobs` / `avail_block_blobs`, 기존 `celestia/header.py` + `avail/header.py` 에 통합 (새 cron 라인 없음)
- Celestia: `share.GetEDS` + ODS share 파싱 (신규 `workers/celestia/share_parser.py`) — Celenium per-block 수치와 1:1 매칭 검증 완료
- Avail: 기존 LC `/v2/blocks/{N}/header` 응답의 `extension.app_lookup` 사용 — 추가 RPC 호출 0건
- `dabeat_ro` SELECT 권한 두 신규 테이블에도 부여 (메인 DB 측에서 같은 유저로 긁어가기 가능)
- 이전 (2026-05-07): Grafana 인스턴스 asia-northeast3로 이전, Celestia fraud 모니터링, Avail App Mode + Self-Probe (9 age bucket), Celestia Self-Probe (DABEAT01 namespace, 320 utia/회), Celestia 추가 health 메트릭, monitored_namespaces 3개 활성화, Grafana Dashboard 6 신설
- **워커 13개, 테이블 10개, Grafana 대시보드 6개 (59 패널)**

---

## 목차

1. [전체 아키텍처](#1-전체-아키텍처)
2. [GCP 인스턴스](#2-gcp-인스턴스)
3. [네트워크 / 방화벽](#3-네트워크--방화벽)
4. [라이트 노드 — 수집 대상](#4-라이트-노드--수집-대상)
5. [워커 스택](#5-워커-스택)
6. [DB 스키마](#6-db-스키마)
7. [Grafana 대시보드](#7-grafana-대시보드)
8. [운영 (cron / 백업 / logrotate)](#8-운영-cron--백업--logrotate)
9. [현재 한계 / 채워야 할 것](#9-현재-한계--채워야-할-것)
10. [접속 / 자격증명](#10-접속--자격증명)
11. [작업 이력 요약](#11-작업-이력-요약)

---

## 1. 전체 아키텍처

```
                    ┌─────────────────────┐
                    │  Team Browsers      │
                    │  (외부)             │
                    └──────────┬──────────┘
                               │ HTTP :3000
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ GCP Project: <gcp-project-id>                             │
│ Region: asia-northeast3-c  (모든 운영 인스턴스 동일 zone)           │
│                                                                    │
│  ┌──────────────────────┐    ┌──────────────────────────────────┐  │
│  │ dashboard-asia       │    │ worker-db1 (<worker-db1-internal-ip>)          │  │
│  │ (<dashboard-asia-internal-ip>)         │    │ ─ PostgreSQL 14 + TimescaleDB    │  │
│  │                      │    │ ─ Python venv + 8 cron 워커      │  │
│  │ Grafana 13.0.1       ├───5432──►│ ─ 백업, logrotate           │  │
│  │ ~1ms intra-zone      │    │                                  │  │
│  │ 외부 <dashboard-asia-ip>    │    └─────┬───────────────┬────────────┘  │
│  └──────────────────────┘          │ RPC           │ HTTP          │
│                                    │ :26658        │ :7007         │
│                                    ▼               ▼               │
│                               ┌──────────┐    ┌──────────┐         │
│                               │ celestia-│    │ avail-   │         │
│                               │ lightnode│    │ lightnode│         │
│                               │ internal │    │ internal │         │
│                               │ Celestia │    │ Avail LC │         │
│                               │ light    │    │ light    │         │
│                               │ v0.30.2  │    │ v1.13.3  │         │
│                               └──────────┘    └──────────┘         │
└────────────────────────────────────────────────────────────────────┘
```

데이터 흐름:
- **수집**: cron 워커 → 라이트 노드 RPC → DB INSERT (매 분)
- **시각화**: Grafana → cross-region SELECT → 대시보드 렌더
- **접속**: 팀은 외부 IP `<old-dashboard-ip>:3000` (HTTP)

---

## 2. GCP 인스턴스

| 인스턴스 | 역할 | Zone | 사양 | 내부 IP | 외부 IP | OS |
|---|---|---|---|---|---|---|
| `celestia-lightnode` | Celestia mainnet light node | asia-northeast3-c | e2-small (추정) | <celestia-internal-ip> | <celestia-lightnode-ip> | Ubuntu 22.04 |
| `avail-lightnode` | Avail mainnet light client | asia-northeast3-c | e2-small | <avail-internal-ip> | <avail-lightnode-ip> | Ubuntu 22.04 |
| `worker-db1` | PostgreSQL/TimescaleDB + 워커 | asia-northeast3-c | e2-small (2 vCPU, 1.9 GiB) | <worker-db1-internal-ip> | <worker-db1-ip> | Ubuntu 24.04 |
| `dashboard-asia` | Grafana | asia-northeast3-c | e2-small (2 vCPU, 1.9 GiB) | <dashboard-asia-internal-ip> | <dashboard-asia-ip> | Ubuntu 24.04 |

> 모든 인스턴스가 동일 zone(`asia-northeast3-c`) 내 동일 /24 서브넷(10.178.0.0/24)에 위치 → intra-zone 통신 ~1ms.
> *(이전 `dashboard` 인스턴스 (us-central1-c, <old-dashboard-ip>)는 cross-region 지연 해소 위해 폐기됨.)*

**모든 인스턴스 사용자**: `wiker`
**SSH 키 (운영 PC)**: `~/.ssh/google_compute_engine` (gcloud 자동 생성)

---

## 3. 네트워크 / 방화벽

### 인스턴스 태그

| 인스턴스 | 태그 |
|---|---|
| celestia-lightnode | `celestia-node` |
| avail-lightnode | `avail-node` |
| worker-db1 | `dabeat-worker` |
| dashboard-asia | `dabeat-grafana` |

### 방화벽 규칙

| 규칙 | source | target | 포트 | 목적 |
|---|---|---|---|---|
| `allow-worker-to-celestia` | `dabeat-worker` | `celestia-node` | tcp:26658 | 워커 → Celestia RPC |
| `allow-worker-to-avail` | `dabeat-worker` | `avail-node` | tcp:7007 | 워커 → Avail HTTP API |
| `allow-grafana-to-dabeat-db` | `dabeat-grafana` | `dabeat-worker` | tcp:5432 | Grafana → Postgres |
| `allow-grafana-public` | `0.0.0.0/0` | `dabeat-grafana` | tcp:3000 | 팀 → Grafana UI |

### PostgreSQL 바인딩 / 인증

- `postgresql.conf`: `listen_addresses = 'localhost,<worker-db1-internal-ip>'`
- `pg_hba.conf`:
  - 로컬: `local all all peer`
  - 워커: `host dabeat dabeat 127.0.0.1/32 scram-sha-256` (기본)
  - Grafana: `host dabeat dabeat_ro 10.178.0.0/24 scram-sha-256` (intra-zone)

---

## 4. 라이트 노드 — 수집 대상

### 4.1 Celestia (`celestia-lightnode`)

- **버전**: celestia-node v0.30.2
- **systemd 서비스**: `celestia-light` (auto-start)
- **명령**:
  ```
  /usr/local/bin/celestia light start \
    --core.ip rpc.celestia.pops.one --core.port 9090 \
    --p2p.network celestia \
    --rpc.addr 0.0.0.0 --rpc.port 26658
  ```
- **JWT 토큰**: `/home/wiker/celestia-token.txt` (모드 600)
  - 워커 측 사본: `/home/wiker/.dabeat/celestia-token.txt`

#### 호출 RPC 메소드

| 메소드 | 용도 | 응답 핵심 필드 |
|---|---|---|
| `header.NetworkHead` | 네트워크 최신 head | `header.height` (string) |
| `header.LocalHead` | 로컬 sync 위치 | 동일 |
| `header.GetByHeight(h)` | 특정 높이 헤더 | `header.{height,time,proposer_address,...}`, `commit.block_id.hash`, `dah.{row_roots[],column_roots[]}` |
| `header.SyncState` | sync 진행 정보 | `from_height/to_height/from_hash/to_hash` |
| `das.SamplingStats` | DAS 진행 상태 | `head_of_sampled_chain`, `concurrency`, `is_running`, `catch_up_done` |
| `p2p.Peers` | 연결 피어 | 배열 길이 = peer 수 |
| `p2p.BandwidthStats` | 누적/현재 대역 | `TotalIn/Out`, `RateIn/Out` |
| `share.SharesAvailable(h)` | 블록 데이터 가용성 검증 | `null` 성공 / error 시 unavailable |
| `fraud.Get(type)` | fraud proof 조회 | 정상시 `error: "datastore: key not found"`, 발견시 `result: [proof]` |
| `node.Info` | 노드 메타 | `type`, `api_version` |
| `blob.GetAll(h, [ns])` | 특정 namespace blob 조회 | `[{namespace, data, share_version, commitment, index}, ...]` |
| `blob.Submit([blob], opts)` | 자체 blob 제출 (gas_price 0.002) | `result: <height>` |
| `state.Balance` | 라이트노드 keyring 잔액 | `{denom: utia, amount: <int>}` |
| `state.AccountAddress` | 노드 keyring 주소 | celestia1... |

**미노출 / 미지원**:
- `das.SamplingStats.failed_samples` — 필드 자체 없음 (v0.30.2 한계)
- `fraud.Subscribe` — HTTP-RPC 모드 미지원 (WebSocket 전용). 우리는 `fraud.Get` polling으로 대체
- `fraud.GetAll` / `fraud.List` — 메소드 없음. type별 개별 호출 필요. 현재 정식 type은 `bad-encoding` (BEFP) 한 가지

### 4.2 Avail (`avail-lightnode`)

- **버전**: avail-light v1.13.3
- **systemd 서비스**: `avail-light` (auto-start)
- **모드**: **app + light** (App ID 46 = `protoBonDA`, owner `5HBJN...`)
- **config**: `/home/wiker/.avail/mainnet/config/config.yml`
  - `confidence=99.9` (10 cell 샘플링, 99.90% 도달)
  - `app_id=46`
  - `http_server_host="0.0.0.0"`, `http_server_port=7007`
- **identity**: `/home/wiker/.avail/mainnet/identity.toml` (mode 600, double-quoted `avail_secret_uri = "<mnemonic>"`)
  - ⚠️ `~/.avail/identity/identity.toml` (다른 경로) 는 LC가 무시함. mainnet/ 폴더 안의 파일만 실제로 사용

#### 호출 HTTP 엔드포인트

| 엔드포인트 | 용도 | 응답 |
|---|---|---|
| `GET /v2/status` | 노드 상태 + sync | `modes`, `network`, `genesis_hash`, `blocks.{latest, available.{first,last}}` |
| `GET /v2/version` | 빌드 버전 | `version`, `network_version` |
| `GET /v2/blocks/{n}` | 블록 status + confidence | `status` (`verifying-data`/`incomplete`/`finalized` 등), `confidence` (0~100) |
| `GET /v2/blocks/{n}/header` | 블록 헤더 (full) | `hash`, `parent_hash`, `number`, `state_root`, `extrinsics_root`, `extension.{rows, cols, data_root, commitments[], app_lookup.{size, index[].appId}}`, `digest`, `received_at` |
| `GET /v2/blocks/{n}/data` | App ID 46 페이로드 fetch | `block_number`, `data_transactions[].{data, extrinsic}` (자체 app만) |
| `POST /v2/submit` | App Mode submit | `block_number`, `block_hash`, `hash`, `index` |

**App Mode 핵심:** LC가 `/v2/submit`으로 자체 페이로드 보낼 때 **App ID 46 owner 키로 sign**. 이 데이터만 LC가 sync해서 저장. `/v2/blocks/{n}/data?app_id=X`의 `app_id` query는 우리 데이터만 필터링하는 식으로 동작 — 다른 app_id의 실 페이로드는 못 가져옴.

**미노출 (light 빌드 제약, 토큰/모드 무관)**: `/v2/peers/list` 404, `/metrics` 404, `/v2/balance` 404, `/v2/identity` 404
→ peer count / bandwidth / 잔액 / sender 정보 직접 못 가져옴. 빌드 옵션 변경 또는 외부 explorer (`avail.subscan.io`) 활용 필요.

---

## 5. 워커 스택

### 5.1 위치

```
/home/wiker/.dabeat/         (mode 700, 비밀)
├── .env                     (mode 600)
├── celestia-token.txt       (mode 600)
└── venv/                    (Python 3.12, requests / psycopg2-binary / python-dotenv)

/home/wiker/dabeat/          (mode 755, 코드)
├── workers/
│   ├── common/              (config.py, db.py, rpc.py)
│   ├── celestia/            (health, header, namespace_mon, shares_check, fraud_monitor, submit, retrieve, share_parser)
│   └── avail/               (health, header, app_id_mon, availability_check, submit, retrieve, watchdog)
├── schema/                  (001~009 마이그레이션)
│   ├── 001_init.sql              (초기 테이블 6개 + hypertable)
│   ├── 002_seed.sql              (monitored_namespaces 시드)
│   ├── 003_shares_available.sql  (headers에 shares_* 컬럼)
│   ├── 004_availability.sql      (headers에 availability_* 컬럼 + block_availability_samples)
│   ├── 005_fraud_events.sql      (fraud_events hypertable)
│   ├── 006_avail_probes.sql      (probes.payload_hash, retrievals.bucket_label)
│   ├── 007_da_metadata.sql       (da_layer_metadata: claim vs measured 정책 비교용)
│   ├── 008_service_events.sql    (service_events hypertable: LC 재시작 등 운영 timeline)
│   └── 009_block_blobs.sql       (celestia_block_blobs / avail_block_blobs: 네트워크 전체 per-block blob 집계)
├── scripts/                 (install_cron.sh, backup.sh, logrotate.dabeat, backfill.py)
├── dashboards/              (Grafana JSON 백업)
├── logs/                    (cron 로그)
└── backups/                 (pg_dump 7일치)
```

로컬 마스터 사본: `/Users/wiker/breakingVali/dabeat-deploy/`

### 5.2 .env 환경변수

```
CELESTIA_RPC=http://<celestia-internal-ip>:26658
CELESTIA_TOKEN_FILE=/home/wiker/.dabeat/celestia-token.txt
CELESTIA_LN_INSTANCE=celestia-A1
AVAIL_LC=http://<avail-internal-ip>:7007
AVAIL_LN_INSTANCE=avail-A1
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=dabeat
DB_USER=dabeat
DB_PASSWORD=<28자 랜덤>
```

### 5.3 워커 13개 (대부분 매분 cron, retrieve만 5분)

| 워커 | RPC 호출 | INSERT/UPDATE 대상 | 동작 요약 |
|---|---|---|---|
| `celestia/health.py` | `header.NetworkHead`, `header.LocalHead`, `das.SamplingStats`, `p2p.Peers`, `p2p.BandwidthStats`, `node.Info`, `header.SyncState` | `node_health` (1행/min) | sync_lag, das, peers, bw, latency 모두 |
| `celestia/header.py` | `header.LocalHead`, `header.GetByHeight(h)`, `share.GetEDS(h)` | `headers` + `celestia_block_blobs` (≤200 blocks/run) | MAX(height)~LocalHead catch-up. 블록당 EDS 파싱(`share_parser.count_blobs`)으로 네트워크 전체 user blob 집계 upsert. EDS fetch 실패 시 block_blobs만 skip하고 headers 삽입은 계속 |
| `celestia/namespace_mon.py` | `blob.GetAll(h, [ns])` | `namespace_observations` (≤50 blocks/ns/run) | active=TRUE만 처리 (현재 placeholder는 skip) |
| `celestia/shares_check.py` | `share.SharesAvailable(h)` | `headers.shares_*` UPDATE + `block_availability_samples` INSERT | 헤더 들어오는 대로 단발 가용성 검증 |
| `celestia/fraud_monitor.py` | `fraud.Get('bad-encoding')` | `fraud_events` INSERT (발견 시만) | BEFP polling. 정상=0건, 발견 시 alert 가치 |
| `avail/health.py` | `GET /v2/status`, `/v2/blocks/{last}`, `/v2/version` | `node_health` (1행/min) | block_confidence, status, sync_lag |
| `avail/header.py` | `GET /v2/blocks/{n}/header` | `headers` + `avail_block_blobs` (≤100 blocks/run) | 사용 가능 범위 내에서 catch-up. 같은 응답의 `extension.app_lookup`에서 네트워크 전체 blob_count/total_bytes/app_id_count 집계 upsert — 추가 RPC 호출 0건 |
| `avail/app_id_mon.py` | `GET /v2/blocks/{n}/header` | `namespace_observations` | header.app_lookup으로 app_id별 blob_count/bytes 추출 |
| `avail/availability_check.py` | `GET /v2/blocks/{h}` | `headers.availability_*` UPDATE + `block_availability_samples` INSERT | settle까지 ≤3회 재호출, status+confidence 시계열 |
| `avail/submit.py` | `POST /v2/submit` | `probes` INSERT (1행/min) | App ID 46으로 자체 페이로드 submit. payload_hash로 retrieval 매칭 가능 |
| `avail/retrieve.py` | `GET /v2/blocks/{h}/data` | `retrievals` INSERT | 5분 cron, log-spaced age bucket(5m/15m/1h/6h/1d/3d/7d/14d/30d), ±90s tolerance, hash 일치 검증 |
| `celestia/submit.py` | `blob.Submit`, `state.Balance` | `probes` INSERT (1행/min) | DABEAT namespace `0000...4441424541543031` (29 bytes), gas_price 0.002, 회당 320 utia 측정 |
| `celestia/retrieve.py` | `blob.GetAll(h, [ns_b64])` | `retrievals` INSERT | 5분 cron, Avail와 동일 9-bucket 패턴, payload_hash 매칭 |

### 5.4 한 분당 평균 적재량

| 테이블 | rows/min |
|---|---|
| `node_health` | 2 |
| `headers` | ~13 (Celestia ~10 + Avail ~3) |
| `block_availability_samples` | ~10-30 (백로그 정리 시 burst, steady state ~10) |
| `namespace_observations` | ~9 (Avail 3 app_id × 3 blocks/min) |
| `probes` (양 레이어 self) | 2 (Avail 1 + Celestia 1) |
| `retrievals` (양 레이어 self) | 3.6/min 평균 (5분 cron × 9 bucket × 양 레이어) |
| `fraud_events` | 0 (정상 시 비어있음) |

**디스크 소비**: ~1.5-2 MB/hr (steady state) → 40-50 MB/day → ~15 GB/year

**Celestia 비용**: 회당 320 utia (0.000320 TIA) — 8주 1분 cron 운영 시 ~25.8 TIA. 보유 30.2 TIA → 4.4 TIA buffer.

---

## 6. DB 스키마

### 6.1 분리 방식

**모든 테이블은 long-format**. `da_layer TEXT` 컬럼 값 (`'celestia'` 또는 `'avail'`)으로 분리. 같은 테이블에 양 레이어 데이터가 행 단위로 섞임. 레이어 전용 컬럼은 해당 레이어가 아닐 때 NULL.

### 6.2 테이블 10개

| 테이블 | 종류 | 설명 |
|---|---|---|
| `node_health` | hypertable (ts) | 라이트 노드 헬스 시계열 |
| `headers` | hypertable (ts) | 블록 헤더 + per-block 가용성 요약 |
| `namespace_observations` | hypertable (ts) | namespace/app_id별 활동 시계열 (모니터링 대상만) |
| `block_availability_samples` | hypertable (ts) | 가용성 체크 매 attempt 시계열 |
| `fraud_events` | hypertable (ts) | fraud proof 발생 기록 (정상시 비어있음) |
| `service_events` | hypertable (ts) | LC 재시작 등 운영 이벤트 timeline (watchdog 등이 INSERT) |
| `monitored_namespaces` | regular | 모니터링 대상 매핑 (rollup_name) |
| `da_layer_metadata` | regular | DA 레이어별 정책/메타 (claim vs measured 비교용) |
| `probes` | regular | self-probe submit 기록 (양 레이어 운영 중) |
| `retrievals` | hypertable (ts) | self-probe retrieval 결과 (9 bucket × 양 레이어) |
| `celestia_block_blobs` | regular | **네트워크 전체** Celestia 블록당 blob 집계 (height PK) |
| `avail_block_blobs` | regular | **네트워크 전체** Avail 블록당 blob 집계 (height PK) |

### 6.3 `node_health` (hypertable)

| 컬럼 | 타입 | 양쪽 채움? | 설명 |
|---|---|---|---|
| `ts` | TIMESTAMPTZ | ✓ | 측정 시각 |
| `da_layer` | TEXT | ✓ | `'celestia'` / `'avail'` |
| `ln_instance` | TEXT | ✓ | `celestia-A1` / `avail-A1` |
| `network_head` | BIGINT | ✓ | 네트워크 최신 height |
| `local_head` | BIGINT | ✓ | LC sync 도달 height |
| `sampled_head` | BIGINT | Celestia만 | DAS sampled head |
| `sync_lag` | INT | ✓ | network - local |
| `is_syncing` | BOOLEAN | ✓ | sync_lag > 1 |
| `das_running` | BOOLEAN | Celestia만 | DAS 동작 여부 |
| `das_concurrency` | INT | Celestia만 | 동시 sampling 수 |
| `das_failed_samples` | INT | **항상 NULL** | API 미노출 |
| `block_confidence` | DOUBLE PRECISION | Avail만 | 최신 블록 confidence (%) |
| `peers_count` | INT | Celestia만 | Avail은 LC API 미노출 |
| `bandwidth_in_total` / `bandwidth_out_total` | BIGINT | Celestia만 | 누적 bytes |
| `rate_in` / `rate_out` | BIGINT | Celestia만 | bytes/sec |
| `rpc_latency_ms` | INT | ✓ | 워커가 측정한 대표 latency |
| `rpc_success` | BOOLEAN | ✓ | 호출 성공 여부 |
| `details` | JSONB | ✓ | Celestia: `{node_info, sync_state, catch_up_done, head_of_catchup}`<br>Avail: `{modes, network, version, available, block_status}` |

**인덱스**: `(da_layer, ts DESC)`

### 6.4 `headers` (hypertable)

| 컬럼 | 타입 | 채움 정책 | 설명 |
|---|---|---|---|
| `ts` | TIMESTAMPTZ | ✓ | 워커 INSERT 시각 |
| `da_layer` | TEXT | ✓ | |
| `height` | BIGINT | ✓ | |
| `block_hash` | TEXT | ✓ | Celestia: `commit.block_id.hash` (대문자 hex)<br>Avail: `header.hash` (`0x...`) |
| `block_time` | TIMESTAMPTZ | ✓ | Celestia: `header.time`<br>Avail: `header.received_at` (LC 수신 시각) |
| `parent_hash` | TEXT | ✓ | Celestia: `header.last_block_id.hash`<br>Avail: `header.parent_hash` |
| `data_root` | TEXT | ✓ | Celestia: `header.data_hash`<br>Avail: `extension.data_root` |
| `proposer_address` | TEXT | Celestia만 | Avail은 LC API 미노출 (BABE digest 디코딩 필요) |
| `square_size` | INT | Celestia만 | EDS 사이드 길이 (`len(row_roots)`) |
| `rows` / `cols` | INT | Avail만 | matrix 크기 |
| `data_size_bytes` | BIGINT | ✓ | Celestia: `square_size² × 512` (EDS bytes)<br>Avail: `rows × cols × 32` |
| `details` | JSONB | ✓ | Celestia: `{chain_id, app_version, ods_bytes, row_roots_count, column_roots_count}`<br>Avail: `{extrinsics_root, state_root, app_lookup, app_data_bytes, kzg_commitments}` |
| `shares_available` | BOOLEAN | Celestia만 | `share.SharesAvailable` 결과 |
| `shares_check_latency_ms` | INT | Celestia만 | |
| `shares_check_error` | TEXT | Celestia만 | 실패 시 분류 |
| `shares_checked_at` | TIMESTAMPTZ | Celestia만 | |
| `availability_first_check_at` | TIMESTAMPTZ | ✓ | 첫 가용성 체크 시각 |
| `availability_settled_at` | TIMESTAMPTZ | ✓ | settle된 시각 (NULL=아직 진행) |
| `availability_attempts` | INT | ✓ | 누적 체크 수 (Celestia=1, Avail=1~3) |
| `availability_max_confidence` | DOUBLE PRECISION | Avail만 | 최고 도달 confidence |
| `availability_last_confidence` | DOUBLE PRECISION | Avail만 | 마지막 관측값 |
| `availability_last_status` | TEXT | Avail만 | `verifying-data` / `incomplete` 등 |

**제약**: `UNIQUE (da_layer, height, ts)` (hypertable 제약상 ts 포함)
**인덱스**: `(da_layer, height DESC)`

### 6.5 `namespace_observations` (hypertable)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `ts` | TIMESTAMPTZ | |
| `da_layer` | TEXT | |
| `ln_instance` | TEXT | |
| `namespace_or_appid` | TEXT | Celestia: namespace hex / Avail: app_id 정수 string |
| `height` | BIGINT | 관측 블록 |
| `blob_count` | INT | 해당 namespace/app_id에 속한 blob 수 |
| `total_bytes` | BIGINT | 페이로드 합계 (Avail은 cell 단위 추정) |
| `commitments` | TEXT[] | Celestia만, blob commitment 목록 (Avail은 NULL — block 단위 KZG라 namespace 단위 commitment 없음) |
| `fetch_latency_ms` | INT | RPC/HTTP 호출 latency |
| `fetch_success` | BOOLEAN | |
| `error_type` | TEXT | timeout / rpc_error / not_found 등 |
| `details` | JSONB | Avail: `{source: "header.app_lookup"}` (light 모드라 메타데이터만) |

**제약**: `UNIQUE (da_layer, namespace_or_appid, height, ts)`
**인덱스**: `(da_layer, namespace_or_appid, ts DESC)`, `(da_layer, height)`

### 6.6 `block_availability_samples` (hypertable)

매 가용성 체크 attempt마다 1행. Celestia는 single-shot이라 1행/블록, Avail는 settle까지 1~3행/블록.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `ts` | TIMESTAMPTZ | 체크 시각 |
| `da_layer` | TEXT | |
| `height` | BIGINT | |
| `attempt` | INT | 1, 2, 3 ... |
| `status` | TEXT | Avail만, `verifying-data` 등 |
| `confidence` | DOUBLE PRECISION | Avail만, 0~100 |
| `available` | BOOLEAN | Celestia만 |
| `latency_ms` | INT | RPC/HTTP latency |
| `error_type` | TEXT | 실패 시 |
| `details` | JSONB | |

**인덱스**: `(da_layer, height, ts DESC)`, `(da_layer, ts DESC)`

### 6.7 `monitored_namespaces` (regular)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `da_layer` | TEXT | PRIMARY KEY 일부 |
| `namespace_or_appid` | TEXT | PRIMARY KEY 일부 |
| `rollup_name` | TEXT | 표시명 |
| `source` | TEXT | `'l2beat'`, `'celenium'`, `'avail-explorer'`, `'manual'` |
| `added_at` | TIMESTAMPTZ | DEFAULT NOW() |
| `active` | BOOLEAN | DEFAULT TRUE — 워커가 active=TRUE만 fetch |

**현재 시드 데이터:**
| da_layer | namespace_or_appid | rollup_name | active |
|---|---|---|---|
| celestia | `0000...0065636c69707365` | Eclipse | **TRUE** ✅ |
| celestia | `0000...6c696768746c696e6b` | Lightlink | **TRUE** ✅ |
| celestia | `0000...6d6f76656d656e7430` | Movement | **TRUE** ✅ |
| celestia | PLACEHOLDER_manta_pacific | Manta Pacific | FALSE (hex 미확인) |
| celestia | PLACEHOLDER_aevo | Aevo | FALSE (hex 미확인) |
| avail | 1 | unknown | TRUE |
| avail | 7 | unknown | TRUE |
| avail | 11 | unknown | TRUE |

→ Celestia 5건은 실제 namespace hex(29-byte)로 교체 후 `active=TRUE`로 바꿔야 데이터 수집 시작.

### 6.8 `probes` (regular, **Avail 운영 중**)

자체 probe submit 기록. Avail App ID 46용으로 활성, Celestia는 토큰 충전 후 추가 예정.

| 컬럼 | 타입 |
|---|---|
| `probe_id` | BIGSERIAL PRIMARY KEY |
| `ts` | TIMESTAMPTZ DEFAULT NOW() |
| `da_layer` | TEXT (`'avail'`) |
| `ln_instance` | TEXT (`'avail-A1'`) |
| `namespace_or_appid` | TEXT (Avail은 `'46'`) |
| `payload_size_bytes` | INT |
| `payload_hash` | TEXT (sha256 hex) — retrieval 매칭용 |
| `submit_height` | BIGINT |
| `submit_tx_hash` | TEXT |
| `submit_latency_ms` | INT |
| `submit_success` | BOOLEAN |
| `error_type` | TEXT |
| `details` | JSONB (block_hash, index 등) |

### 6.9 `fraud_events` (hypertable, **정상 시 비어있음**)

Celestia (또는 추후 Avail의 동등 시스템)에서 fraud proof가 발견될 때만 행이 추가됨. 매분 워커가 polling — `fraud.Get('bad-encoding')` 응답이 "key not found" 에러면 무시(정상), 실제 proof가 반환되면 INSERT.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `ts` | TIMESTAMPTZ | 감지 시각 |
| `da_layer` | TEXT | `'celestia'` |
| `ln_instance` | TEXT | |
| `proof_type` | TEXT | `'bad-encoding'` (BEFP) — 추후 type 추가 시 늘어남 |
| `block_height` | BIGINT | proof 대상 블록 (proof 구조에서 best-effort 추출) |
| `raw_proof` | JSONB | 노드가 반환한 원본 proof 객체 그대로 |
| `details` | JSONB | 감지 latency 등 메타 |

**인덱스**: `(da_layer, proof_type, ts DESC)`, `(da_layer, block_height)`

> 이 테이블에 행이 들어오면 **DA 레이어에 심각한 문제 발생** 의미. 알람 연결 권장.

### 6.10 `retrievals` (hypertable, **Avail 운영 중**)

자체 probe retrieval 결과. log-spaced age bucket별 시계열 (5m/15m/1h/6h/1d/3d/7d/14d/30d).

| 컬럼 | 타입 |
|---|---|
| `ts` | TIMESTAMPTZ |
| `probe_id` | BIGINT (probes FK) |
| `da_layer` | TEXT |
| `ln_instance` | TEXT |
| `attempt` | INT |
| `bucket_label` | TEXT (`'5m'`, `'15m'`, ..., `'30d'`) |
| `fetch_latency_ms` | INT |
| `fetch_success` | BOOLEAN |
| `bytes_received` | BIGINT |
| `error_type` | TEXT (`'hash_mismatch'`, `'blob_not_found'`, `'timeout'`, `'connection'`, ...) |
| `details` | JSONB |

**인덱스**: `(probe_id, bucket_label)`

### 6.11 `celestia_block_blobs` (regular, **2026-05-20 신설**)

Celestia 메인넷 매 블록의 네트워크 전체 blob 집계. 모니터링 대상 namespace 필터링 없이 ODS의 모든 user namespace 합산. `celestia/header.py` 가 새 블록 처리할 때 `share.GetEDS(h)` 호출 → `workers/celestia/share_parser.count_blobs()` 로 파싱 → upsert.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `height` | BIGINT PRIMARY KEY | Celestia block height |
| `block_time` | TIMESTAMPTZ NOT NULL | chain block timestamp (`header.time`) |
| `blob_count` | INTEGER NOT NULL | 네트워크 전체 user blob 수 (reserved namespace + namespace-padding share 제외) |
| `total_blob_bytes` | BIGINT | 모든 blob payload bytes 합 (Celenium `blobs_size` 와 정확 일치) |
| `namespace_count` | INTEGER | 블록 내 unique user namespace 수 (padding-only namespace 제외) |
| `collected_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | 워커가 INSERT/UPDATE한 시각 — 증분 pull watermark용 (UPSERT 시에도 갱신됨) |

**인덱스**: `height` (PK), `(block_time DESC)`
**권한**: `dabeat_ro` SELECT

**Share parser 동작 요약** (`workers/celestia/share_parser.py`):
1. EDS의 ODS quadrant(top-left N/2 × N/2)만 순회 — 나머지 3개 quadrant는 erasure parity
2. share 첫 29 byte = namespace prefix. 다음 1 byte = info byte (bit0 = sequence_start)
3. Reserved namespace 제외 — `v=0x00 AND ns[1..27]=0x00` (primary-reserved 전체 범위) 또는 `v=0xff` (secondary/parity)
4. `sequence_start=1 AND sequence_length>0` 만 blob 1개로 카운트 (sequence_length=0인 namespace-padding share 제외)
5. `total_bytes` = sequence_length 합

**검증** (2026-05-20, Celenium 8 sample): 모두 1:1 일치 (height/blob_count/total_blob_bytes). Celenium per-block API 응답이 ground truth.

### 6.12 `avail_block_blobs` (regular, **2026-05-20 신설**)

Avail 메인넷 매 블록의 네트워크 전체 DataAvailability blob 집계. `avail/header.py` 가 이미 호출하는 `/v2/blocks/{n}/header` 응답의 `extension.app_lookup` 에서 추출 — 추가 RPC 호출 없음.

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `height` | BIGINT PRIMARY KEY | Avail block number |
| `block_time` | TIMESTAMPTZ NOT NULL | LC `received_at` (UNIX epoch sec) — chain timestamp와 보통 0~수초 차. `headers.block_time` 과 동일 소스. |
| `blob_count` | INTEGER NOT NULL | `app_lookup.index` 길이 (블록 내 모든 `DataAvailability.submitData` 슬롯) |
| `total_blob_bytes` | BIGINT | `app_lookup.size` (모든 app data byte 합) |
| `app_id_count` | INTEGER | 블록 내 unique appId 수 (`set(e.appId for e in index)`) |
| `collected_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | UPSERT 시 갱신 — 증분 pull watermark용 |

**인덱스**: `height` (PK), `(block_time DESC)`
**권한**: `dabeat_ro` SELECT

> Avail mainnet 자체가 sparse — 약 75% 블록이 empty (blob_count=0). 7일 평균 ~1,200 blobs/day / ~1.2 MB/day. 단기 sample은 변동 크니 24h 이상 윈도우로 평가 권장.

### 6.13 외부 인테이크 — 메인 DB에서 긁어가기

`celestia_block_blobs` / `avail_block_blobs` 둘 다 `dabeat_ro` 가 SELECT 가능. 메인 DB 또는 외부 컨슈머에서 증분 pull 권장 패턴:

```sql
-- 증분 watermark 방식 (collected_at는 UPSERT에서도 NOW()로 갱신됨)
SELECT * FROM celestia_block_blobs
WHERE collected_at > $last_seen
ORDER BY collected_at;

-- 또는 height 기반 페이지네이션 (초기 backfill용)
SELECT * FROM avail_block_blobs
WHERE height > $last_height
ORDER BY height LIMIT 1000;
```

**연결 정보**:
- host: `<worker-db1-internal-ip>` (worker-db1, intra-VPC) / port: `5432` / db: `dabeat` / user: `dabeat_ro`
- `pg_hba.conf` 현재 허용 범위: `10.178.0.0/24` (같은 GCP VPC subnet)
- 다른 subnet/외부에서 붙으려면 `pg_hba.conf` 추가 + (외부면) `postgresql.conf` `listen_addresses` 확장 + 방화벽 (`allow-grafana-to-dabeat-db` 와 동일 패턴) 필요

**현재 적재 속도 (2026-05-20 측정)**:
- celestia_block_blobs: ~14,232 행/day (~1.7 MB/day with overhead)
- avail_block_blobs: ~4,327 행/day (~520 kB/day)

---

## 7. Grafana 대시보드

### 7.1 인스턴스 / 인증

- **위치**: `dashboard-asia` 인스턴스 (asia-northeast3-c, 내부 <dashboard-asia-internal-ip>)
- **버전**: Grafana 13.0.1 OSS
- **systemd**: `grafana-server` (auto-start)
- **외부 노출**: `http://<dashboard-asia-ip>:3000` (HTTP, 0.0.0.0/0 허용)
- **Anonymous**: 비활성
- **계정**: `admin` (24자 랜덤 비밀번호)
- **비밀번호 위치**: 운영 PC `/Users/wiker/.dabeat/grafana-credentials.txt` (mode 600)

### 7.2 데이터소스

- **이름/UID**: `dabeat-pg`
- **타입**: `grafana-postgresql-datasource` (TimescaleDB 옵션 ON)
- **DB**: `<worker-db1-internal-ip>:5432` / `dabeat` / 사용자 `dabeat_ro` (SELECT 전용)
- **provisioning**: `/etc/grafana/provisioning/datasources/dabeat.yaml`
- **주의**: `database`를 top-level + `jsonData.database` **둘 다** 적어야 함 (Grafana 13 frontend가 `jsonData`에서 읽음)

### 7.3 대시보드 7개 (folder: `DABEAT`)

| uid | 제목 | 패널 수 | 주요 패널 |
|---|---|---|---|
| `dabeat-overview` | DABEAT — Overview | 11 | KPI stat (height/sync/peers/confidence) + RPC latency / success / block rate 시계열 |
| `dabeat-health` | DABEAT — Node Health | 7 | sync_lag, peers, bandwidth, DAS, Avail confidence, latency p50/p95/p99 |
| `dabeat-blocks` | DABEAT — Block Production | 7 | block time, square_size/matrix, data_size, throughput, block time 분포 |
| `dabeat-availability` | DABEAT — Availability | 7 | sampling success rate, confidence 분포, latency, status 파이, coverage 게이지, pseudo survival |
| `dabeat-namespace` | DABEAT — Namespace Activity | 10 | Avail 6 패널 + Celestia 4 패널 (heatmap, bytes, top 10, fetch success) |
| `dabeat-probes` | DABEAT — Self-Probe & Fraud | 13 | Submit rate/latency, Survival Curve, retrieve latency, fraud count, worker freshness, Celestia/Avail fee trend |
| `dabeat-comparison` | DABEAT — DA Comparison | 11 | L2Beat-style 비교: Liveness / Retrieval Health / Cost / Finality / Retention claim vs measured |

### 7.4 마스터 사본 / 재배포

- **로컬 마스터**: `/Users/wiker/breakingVali/dabeat-deploy/grafana/dashboards/`
- **생성 스크립트**: `gen_dashboards.py` (panel 헬퍼 함수로 5 JSON 생성)
- **워커 백업**: `/home/wiker/dabeat/dashboards/` on worker-db1
- **provisioning**: `/var/lib/grafana/dashboards/` on dashboard-asia 인스턴스
- **재배포**: 마스터 수정 → `python3 gen_dashboards.py` → `scp` → 30초 내 자동 reload

### 7.5 Latency

모든 인스턴스 동일 zone(`asia-northeast3-c`) 동일 /24 서브넷:
- 사용자 → Grafana: 인터넷 레이턴시 (한국 기준 수십~수백ms)
- Grafana → DB: ~1ms (intra-zone)
- panel 쿼리 응답 시간: ~0.12s (intra-zone), 이전 cross-region 시 0.4-0.5s
- dashboard 전체 로드: 1-2초

---

## 8. 운영 (cron / 백업 / logrotate)

### 8.1 crontab (worker-db1, user `wiker`)

```cron
# >>> dabeat cron (managed) >>>
PYTHONPATH=/home/wiker/dabeat
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.health        >>/home/wiker/dabeat/logs/celestia_health.log     2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.header        >>/home/wiker/dabeat/logs/celestia_header.log     2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.namespace_mon >>/home/wiker/dabeat/logs/celestia_ns.log         2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.shares_check  >>/home/wiker/dabeat/logs/celestia_shares.log     2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.fraud_monitor >>/home/wiker/dabeat/logs/celestia_fraud.log      2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.avail.health           >>/home/wiker/dabeat/logs/avail_health.log        2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.avail.header           >>/home/wiker/dabeat/logs/avail_header.log        2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.avail.app_id_mon       >>/home/wiker/dabeat/logs/avail_app_id.log        2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.avail.availability_check >>/home/wiker/dabeat/logs/avail_availability.log 2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.avail.submit            >>/home/wiker/dabeat/logs/avail_submit.log         2>&1
*/5 * * * * /home/wiker/.dabeat/venv/bin/python -m workers.avail.retrieve        >>/home/wiker/dabeat/logs/avail_retrieve.log       2>&1
* * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.submit         >>/home/wiker/dabeat/logs/celestia_submit.log      2>&1
*/5 * * * * /home/wiker/.dabeat/venv/bin/python -m workers.celestia.retrieve     >>/home/wiker/dabeat/logs/celestia_retrieve.log    2>&1
0 0 * * * df -h >>/home/wiker/dabeat/logs/disk_usage.log 2>&1
0 3 * * * /home/wiker/dabeat/scripts/backup.sh >>/home/wiker/dabeat/logs/backup.log 2>&1
# <<< dabeat cron (managed) <<<
```

`install_cron.sh`가 idempotent하게 위 블록을 관리 (마커 사이만 교체).

### 8.2 백업

- **스크립트**: `/home/wiker/dabeat/scripts/backup.sh`
- **위치**: `/home/wiker/dabeat/backups/dabeat_YYYYMMDD_HHMMSS.sql.gz`
- **주기**: 매일 03:00 UTC
- **보관**: 7일 (이상 자동 삭제)
- **방식**: `pg_dump | gzip` (TimescaleDB chunk 데이터 모두 포함, NOTICE만 출력됨)

### 8.3 logrotate

- **설정**: `/etc/logrotate.d/dabeat` (root 소유, `su wiker wiker`)
- **주기**: daily
- **보관**: 7일
- **압축**: gzip

### 8.4 디스크 사용량 산정

- **현재 (steady state)**: ~36 MB/day, ~13 GB/year
- **e2-small 96 GB 디스크**: ~7년치 (압축 미적용)
- **TimescaleDB 압축 정책 적용 시**: 5-20배 추가 → 30-100년 가능

### 8.5 Avail LC 설정 변경 사항

`~/.avail/mainnet/config/config.yml`:
- `confidence=80.0` → `confidence=99.9` (10 cell 샘플링, ~99.90% 도달)
- `http_server_host="0.0.0.0"`, `http_server_port=7007` 추가

변경 후 `sudo systemctl restart avail-light` 필요.

---

## 9. 현재 한계 / 채워야 할 것

### 9.1 라이트 노드 자체 한계 (수정 불가)

| 컬럼 / 데이터 | 사유 |
|---|---|
| `node_health.das_failed_samples` | Celestia v0.30.2 API 응답에 필드 자체 없음 |
| `node_health.peers_count` (Avail) | Avail LC `/v2/peers/list` 404 (light 빌드 미노출) |
| `node_health.bandwidth_*` (Avail) | `/metrics` 404 (OTel 외부 collector 사용 중) |
| `headers.proposer_address` (Avail) | LC API 미제공 (BABE digest 디코딩 필요) |
| `namespace_observations.commitments` (Avail) | Avail KZG는 블록 단위라 namespace 단위 개념 자체가 없음 |
| 다른 app_id (1, 7, 11)의 실제 blob payload | Avail LC는 자기 app_id (46) 데이터만 sync/저장 → `/v2/blocks/{n}/data?app_id=X` 가 다른 app 데이터를 반환하지 않음. **메타데이터만** `header.app_lookup`로 수집 가능 (이미 namespace_observations에서 처리 중) |
| 실시간 fraud event push | Celestia `fraud.Subscribe`는 WebSocket 전용 → cron polling으로 `fraud.Get` (분 단위 지연 acceptable) |

**해결 가능한 영역:** LC 빌드를 metrics 활성화 옵션으로 재컴파일하거나, app별 별도 LC 인스턴스 띄워 각자 app mode로 sync. 현재 인프라 규모상 over-engineering.

### 9.2 토큰 충전 후 활성화될 것

- ~~`probes` 테이블 채워지기 시작~~ — Avail App ID 46 + Celestia DABEAT namespace 둘 다 매 분 채워짐
- ~~`retrievals` 테이블 채워지기 시작~~ — 양 레이어 모두 5분 후부터 5m bucket부터 채워짐
- ~~Celestia self-probe는 토큰 충전 후 추가~~ — 30.187 TIA 충전 후 활성화 완료

### 9.3 운영 액션 필요

- [x] ~~`monitored_namespaces` Celestia placeholder 교체~~ — 3/5 완료 (Eclipse/Lightlink/Movement). Manta/Aevo는 ASCII name이 hex에 없어 celenium 검색에 안 잡힘 — 직접 lookup 필요
- [ ] `monitored_namespaces`의 Avail app_id 1/7/11의 `rollup_name='unknown'` 실제 이름으로 교체
- [x] ~~Avail LC를 app-client 모드로 재구성~~ — 완료 (App ID 46, owner `5HBJN...`)
- [x] ~~Avail self-probe submit + retrieve 워커 작성~~ — 완료 (1분 cron submit / 5분 cron retrieve, 9 age bucket)
- [x] ~~Grafana 인스턴스를 `asia-northeast3-c`로 이동~~ — 완료 (dashboard-asia)
- [x] ~~`pg_hba.conf`의 legacy `10.128.0.0/9` 라인 정리~~ — 완료
- [ ] (선택) HTTPS 적용 (Caddy 또는 Cloudflare Tunnel)
- [ ] (선택) 외부 IP를 고정 IP로 (인스턴스 재생성 시 IP 유지)
- [ ] (선택) TimescaleDB 압축 정책 (`add_compression_policy('node_health', INTERVAL '7 days')` 등)

---

## 10. 접속 / 자격증명

### 10.1 SSH

| 인스턴스 | 명령 |
|---|---|
| celestia-lightnode | `ssh -i ~/.ssh/google_compute_engine wiker@<celestia-lightnode-ip>` |
| avail-lightnode | `ssh -i ~/.ssh/google_compute_engine wiker@<avail-lightnode-ip>` |
| worker-db1 | `ssh -i ~/.ssh/google_compute_engine wiker@<worker-db1-ip>` |
| dashboard-asia | `ssh -i ~/.ssh/google_compute_engine wiker@<dashboard-asia-ip>` |

또는 `gcloud compute ssh <name> --zone=asia-northeast3-c`.

### 10.2 Grafana

```
URL:      http://<dashboard-asia-ip>:3000
Username: admin
Password: ~/.dabeat/grafana-credentials.txt
```

### 10.3 PostgreSQL

```
Host:     <worker-db1-internal-ip> (worker-db1 내부) 또는 127.0.0.1 (worker-db1 본인)
Port:     5432
DB:       dabeat
Users:
  - dabeat (all privs, 비번은 worker-db1의 ~/.dabeat/.env)
  - dabeat_ro (SELECT only, 비번은 운영 PC ~/.dabeat/grafana-credentials.txt)
```

### 10.4 Celestia JWT 토큰

- **생성**: celestia-lightnode에서 `celestia light auth admin --p2p.network celestia`
- **위치**: `/home/wiker/celestia-token.txt` (lightnode), `/home/wiker/.dabeat/celestia-token.txt` (worker-db1)
- **권한**: 모드 600

---

## 11. 작업 이력 요약

1. **인프라 셋업 (1차)**: GCP 인스턴스 태그, 방화벽 규칙, 라이트 노드 systemd 등록 (Celestia 0.0.0.0:26658 바인딩, Avail config.yml 수정), 워커 인스턴스에서 RPC 도달 검증
2. **DB & 워커 셋업 (2차)**: PG14 + TimescaleDB 설치, dabeat DB/유저, Python venv, 6개 워커 작성, monitored_namespaces 시드 (Celestia placeholder 5 + Avail 3), cron + logrotate + 백업 스크립트, 첫 데이터 수집 검증. *(이후 14단계 거쳐 워커 13개 / 대시보드 6개로 확장)*
3. **데이터 보강**: Celestia headers의 NULL 컬럼 (block_hash, data_size_bytes) 채움, Avail headers의 data_size_bytes 채움, node.Info / SyncState / version 추가, 기존 NULL row 백필
4. **가용성 모니터링**: `share.SharesAvailable` 워커 추가 (Celestia per-block), `block_availability_samples` hypertable 신설 (양 레이어 통합), Avail availability_check 워커 추가 (settle까지 재시도). Avail LC `confidence=99.9`로 변경하여 실 가용성 99.90% 도달
5. **Grafana 셋업**: dashboard 인스턴스 (us-central1-c) 신설, Grafana 13.0.1 설치, dabeat_ro 유저 + cross-region 방화벽, datasource provisioning, 5개 대시보드 (38 패널) JSON 생성 스크립트화
6. **Grafana 디버깅**: `$__time(time_bucket(...))` 매크로 파싱 버그 수정, datasource type을 `grafana-postgresql-datasource`로 정정, `jsonData.database`도 명시 (frontend pre-check 통과)
7. **외부 공개**: `dabeat-grafana → 0.0.0.0/0:3000` 방화벽으로 팀 접근 가능
8. **Grafana 인스턴스 이전**: us-central1-c (cross-region) → `dashboard-asia` in asia-northeast3-c (intra-zone). worker-db1과 동일 /24 서브넷 → panel 쿼리 0.4s → 0.12s 단축. 옛 인스턴스 폐기.
9. **Celestia fraud 모니터링 추가**: `fraud.Get('bad-encoding')` 매분 polling, `fraud_events` hypertable 신설. `fraud.Subscribe`는 WebSocket 전용이라 polling으로 대체.
10. **Avail App Mode + Self-Probe**: App ID 46 (`protoBonDA`, owner `5HBJN...`)으로 LC를 app-client 모드 전환 (config.yml `app_id=46`, `~/.avail/mainnet/identity.toml`에 mnemonic). `submit.py` (1분 cron) + `retrieve.py` (5분 cron, 9 age bucket × ±90s tolerance) 추가. 첫 사이클 검증: block 2902050 submit → 4분 후 retrieve hash 일치. 트러블슈팅 핵심: avail-light v1.13.3는 `~/.avail/identity/identity.toml` (자동 생성 자리)이 아니라 **`~/.avail/mainnet/identity.toml`**을 실제로 읽음. 명세에 적혀있던 path가 잘못됐어서 우리 mnemonic이 무시되고 LC 자체 24단어 random key가 사용되어 5D7k... 주소가 logger에 나오던 현상이 있었음.
11. **Celestia Self-Probe**: 30.187 TIA 충전 후 DABEAT namespace (`0000...4441424541543031`, 29 bytes — "DABEAT01" ASCII) 사용. `blob.Submit`/`blob.GetAll` 패턴. 회당 비용 5회 측정 결과 모두 정확히 320 utia (gas_price 0.002), stddev 0. 첫 사이클: block 10984650 submit → 즉시 retrieve hash 일치. 8주 운영 예산 25.8 TIA / 보유 30.2 TIA = 4.4 TIA buffer. 명세 namespace hex가 30 bytes(60 chars)였는데 Celestia는 29 bytes만 받아서 trailing `00` 1 byte 제거하여 정정.
12. **Celestia health 메트릭 보강**: `p2p.ResourceState`, `p2p.NATStatus`, `p2p.PubSubPeers` 추가 호출. node_health.details에 메모리/streams/conns/FD/NAT/pubsub 정보 추가.
13. **monitored_namespaces 부분 활성화**: celenium API로 Eclipse / Lightlink / Movement 3개 namespace 식별, 4 RPC 호출/분 추가 발생, 매분 `namespace_observations` 적재 시작. Manta / Aevo는 ASCII name이 hex에 없어 자동 검색 불가 — 직접 lookup 필요.
14. **Grafana Dashboard 6 신설 (Self-Probe & Fraud)**: 11 패널 — Avail/Celestia submit rate / latency, **Survival Curve (bucket × layer)**, retrieve latency, fraud event count, worker freshness, Celestia fee 추이. Dashboard 5 (Namespace Activity)에도 Celestia 4 패널 추가 (heatmap, total bytes, top 10, fetch success). 38 → **59 패널**, 5 → **6 dashboard**. `dabeat_ro` 유저 권한 안전망 강화 (`GRANT SELECT ON ALL TABLES`).
15. **네트워크 전체 per-block blob 집계 (2026-05-20)**: 신규 테이블 `celestia_block_blobs` / `avail_block_blobs` (schema/009). 기존 header 워커에 통합 — 새 cron 라인 없음. Celestia는 `share.GetEDS` + ODS share 파싱 (`workers/celestia/share_parser.py`), Avail은 이미 받는 `extension.app_lookup` 재활용 (추가 RPC 0건). Celenium 8 sample 1:1 일치 검증. 두 차례 parser 보정:
    - **1차**: primary-reserved 필터를 `ns[28] < 0x80` 조건 → `v=0x00 AND ns[1..27]=0` 전체 범위로 확장 (TAIL_PAD `0x00...0xff` 등 누락 수정)
    - **2차**: namespace-padding share (`sequence_length=0` 인 사용자 NS share) 제외 — Celestia가 namespace 경계 정렬을 위해 끼워넣는 padding이 sequence_start=1 이라 user blob으로 오인됐었음. 영향 ~0.2~0.5%
    - 두 차례 모두 기존 row recount 적용 완료
    - `dabeat_ro` SELECT 권한 부여 → 메인 DB 측에서 같은 유저로 incremental pull 가능 (watermark: `collected_at`)

---

## 부록 A: Avail Self-Probe 운영 모니터링 SQL

### 시간당 submit 성공률
```sql
SELECT
  date_trunc('hour', ts) AS hour,
  COUNT(*) AS attempts,
  COUNT(*) FILTER (WHERE submit_success) AS ok,
  ROUND(100.0 * COUNT(*) FILTER (WHERE submit_success) / COUNT(*), 2) AS pct_ok,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY submit_latency_ms)::int AS p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY submit_latency_ms)::int AS p95_ms
FROM probes
WHERE da_layer = 'avail' AND ts > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY 1 DESC;
```

### bucket별 retrieval 성공률 + latency
```sql
SELECT
  bucket_label,
  COUNT(*) AS retrievals,
  COUNT(*) FILTER (WHERE fetch_success) AS ok,
  ROUND(100.0 * COUNT(*) FILTER (WHERE fetch_success) / COUNT(*), 2) AS pct_ok,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY fetch_latency_ms)::int AS p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY fetch_latency_ms)::int AS p95_ms,
  COUNT(*) FILTER (WHERE error_type IS NOT NULL) AS errors,
  STRING_AGG(DISTINCT error_type, ',') FILTER (WHERE error_type IS NOT NULL) AS error_types
FROM retrievals
WHERE da_layer = 'avail'
GROUP BY 1
ORDER BY CASE bucket_label
  WHEN '5m' THEN 1 WHEN '15m' THEN 2 WHEN '1h' THEN 3 WHEN '6h' THEN 4
  WHEN '1d' THEN 5 WHEN '3d' THEN 6 WHEN '7d' THEN 7 WHEN '14d' THEN 8 WHEN '30d' THEN 9
END;
```

### Survival Curve (retrieval success rate vs age)
```sql
SELECT
  r.bucket_label,
  COUNT(*) AS samples,
  ROUND(100.0 * COUNT(*) FILTER (WHERE r.fetch_success) / COUNT(*), 2) AS survival_pct
FROM retrievals r
WHERE r.da_layer = 'avail' AND r.ts > NOW() - INTERVAL '7 days'
GROUP BY 1 ORDER BY MIN(EXTRACT(EPOCH FROM r.ts - (
  SELECT ts FROM probes WHERE probe_id = r.probe_id
)));
```

### 회당 비용 (잔액 차감 explorer 확인 → 평균)
잔액 차감액은 LC API 미노출. https://avail.subscan.io/account/5HBJN... 에서 추적 권장.

### 8주 예산 추정
- 전제: 회당 fee `F` AVAIL (explorer에서 측정), 1분 주기 = 60×24×56 = 80,640회
- 8주 예산 = 80,640 × F + 안전 마진 (예: × 1.3)

```sql
-- 24시간 후 실제 회당 평균 fee 추정 (explorer로 직접 측정 필요)
SELECT
  COUNT(*) AS submits_24h,
  COUNT(*) * 56 AS estimated_8w_submits
FROM probes WHERE da_layer = 'avail' AND submit_success = TRUE
AND ts > NOW() - INTERVAL '24 hours';
```

### 실시간 헬스 체크 (alarm용)
```sql
-- 최근 10분 submit 실패 비율이 10% 넘으면 alert
SELECT
  COUNT(*) FILTER (WHERE NOT submit_success) AS fails,
  COUNT(*) AS total,
  ROUND(100.0 * COUNT(*) FILTER (WHERE NOT submit_success) / NULLIF(COUNT(*), 0), 2) AS pct_fail
FROM probes
WHERE da_layer = 'avail' AND ts > NOW() - INTERVAL '10 minutes';
```

---

## 부록 B: 자주 쓰는 SQL

```sql
-- 최근 1시간 retrieval 성공률
SELECT
  da_layer,
  100.0 * COUNT(*) FILTER (WHERE shares_available OR availability_max_confidence > 99) / COUNT(*) AS pct_available
FROM headers
WHERE ts > NOW() - INTERVAL '1 hour' AND availability_settled_at IS NOT NULL
GROUP BY 1;

-- 시간대별 처리량 (KB/s)
SELECT
  time_bucket('5 minutes', ts) AS bucket,
  da_layer,
  SUM(data_size_bytes) / 1024.0 / 300 AS kbs
FROM headers
WHERE ts > NOW() - INTERVAL '6 hours'
GROUP BY 1, 2 ORDER BY 1;

-- Avail confidence 분포 (히스토그램)
SELECT
  width_bucket(confidence, 0, 100, 20) AS bin_0_20,
  COUNT(*)
FROM block_availability_samples
WHERE da_layer='avail' AND ts > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY 1;

-- namespace별 활동 (Avail)
SELECT
  COALESCE(mn.rollup_name, no.namespace_or_appid) AS ns,
  SUM(no.blob_count) AS blobs,
  SUM(no.total_bytes) AS bytes
FROM namespace_observations no
LEFT JOIN monitored_namespaces mn USING (da_layer, namespace_or_appid)
WHERE no.da_layer='avail' AND no.ts > NOW() - INTERVAL '24 hours'
GROUP BY 1 ORDER BY blobs DESC;

-- 디스크 사용량 추이 (테이블별)
SELECT
  hypertable_name,
  pg_size_pretty(hypertable_size(format('public.%I', hypertable_name)::regclass)) AS size
FROM timescaledb_information.hypertables;
```

---

*이 문서는 `/Users/wiker/breakingVali/dabeat-deploy/README.md`로 저장되어 있습니다.*
