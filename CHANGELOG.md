# CHANGELOG

이 저장소는 [`sprite-gen`](https://github.com/aldegad/sprite-gen)을 **포크해
Asset Studio 로 새로 만드는 중**이다.

이 파일은 **포크 이후 이 저장소에서 일어난 변경만** 기록한다. 포크 이전 upstream의
버전별 이력은 이 파일이 소유하지 않는다 — 검증할 수 없는 이력을 여기 옮겨 적으면
그건 기록이 아니라 창작이 된다. 포크 시점의 상태는 아래 *Baseline*에 요약한다.

형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르고,
버전은 [유의적 버전](https://semver.org/lang/ko/)을 따른다.

---

## [Unreleased]

Asset Studio 모드 분리 (`ASSET_STUDIO_MODE_SPLIT_SPEC_v0.2` 구현).
하나의 스튜디오 아래 공통 코어를 공유하되, 파이프라인·QA·후처리를 생산물의 결에
따라 Sprite / Static 두 모드로 나눈다.

### Added

**Shared Core** (`studio/shared/`)
- Oklab 색 거리 (`color/oklab.py`) — 두 모드가 "가깝다"를 같은 뜻으로 측정한다.
  대표색 선택, 얇은 특징 연속성, 팔레트 호환성, 수리 색 선택이 모두 같은 공간을 쓴다.
- 데이터 기반 refine 설정 (`config/settings.py`) — 임계값 하드코딩 금지. 모든 수치가
  `studio/data/config/<mode>_refine.json`에 있고 프로젝트별로 덮어쓸 수 있다.
  알 수 없는 섹션·키·잘못된 가중치 곡선은 조용히 기본값으로 떨어지지 않고 즉시 실패한다.
- 격자 신호 seam (`grid/edges.py`) — 엔진의 엣지 정의를 그대로 쓰되 NumPy로 표현.
  프레임 집합 누적과 대형 씬을 위해 필요했고, 엔진 정의와 픽셀 단위로 일치함을 테스트로 고정.
- 피치/위상 탐색 (`grid/search.py`) — 두 모드가 공유. 정수 우선 동점 처리 포함.
- 연속 셀 가중치 (`grid/weighting.py`) — 하드 코어 마진 대체.
- 가중 Oklab 셀 샘플러 (`grid/sampling.py`) — 격자가 논리 픽셀이 되는 유일한 지점.
  전체 벡터화(1024² 픽스 4 = 65k 셀을 0.26초에 처리).
- 결정론 Oklab 팔레트 (`palette/`) — RNG 없음, 같은 입력이면 같은 팔레트.
- 모드 레지스트리 (`modes.py`) — 선언되지 않은 모드/에셋 타입을 거부한다.

**Sprite Mode** (`studio/sprite_mode/`) — Refine Engine v0.2
- 애니메이션 공유 격자: 셀 피치를 프레임마다 따로 잡지 않고 상태(또는 캐릭터) 단위로
  한 번 추정해 고정. 프레임별 추정은 6.0과 6.3 사이를 오가며 도트가 끓어 보인다.
- 제한된 위상 보정: 프레임마다 위상은 갖되 공유 위상 ±`phase.tolerance` 안에서만.
  경계에 걸린 프레임은 그 사실을 보고한다(`phase_clamped_frames`).
- 얇은 특징 보호: 칼끝·창대·깃털 같은 1~2셀 구조를 커버리지 완화로 살린다. 칠하거나
  잇거나 옮기지 않으며, 그래도 잃은 것은 Repair로 넘길 잔여로 보고한다.
- 행 전체가 **구조적으로** 하나의 논리 캔버스에 안착 — 절단선을 공유 격자에서 만들고
  프레임 오프셋만큼 이동시키므로 셀 개수가 프레임마다 달라질 수 없다.

**Static Mode** (`studio/static_mode/`) — Refine Engine v0.2
- FFT 후보 제안 + coarse-to-fine 대형 이미지 격자 탐색. FFT는 후보만 내고 격자는
  정밀 채점기가 고른다.
- Oklab 팔레트 매핑, 조건부 디더링(off/ordered/serpentine) — Static 전용, 기본 off.
- 씬 정리 / Static 수리: 고아 픽셀, 반투명 프린지, 갇힌 구멍.
- 타일 이음새 검사·미리보기·보정 (알파 불연속도 이음새로 계산).
- 레이어 분리 / 오브젝트 컷아웃 — 원본 픽셀 위의 마스크라 재합성하면 입력과 동일.
- Static QA, 전용 프롬프트 조립기와 **전용 검증기**.
- 프로젝트 서비스, 에셋 타입 프리셋 4종, 프롬프트 프로필 4종.

**벤치마크** (`studio/shared/benchmark/`, `studio/benchmark.py`)
- 합성 열화 벤치마크: 정답 에셋을 생성 모델이 망가뜨리는 방식대로 열화시킨 뒤
  정제 결과를 원본과 비교한다.
- `python -m studio.benchmark` — 기준선 기록 및 비교, 회귀 시 exit 1.
- 커밋된 기준선 `studio/data/benchmark/baseline.json`과 재현성 테스트.

**그 외**
- UI 모드 분리 (`studio/ui/static_mode_ui.py`) + 상단 모드 선택기.
- i18n 키 한국어/영어 동시 추가 (키 패리티 테스트 통과).
- 한글 [`README.md`](README.md), [`docs/asset-studio-modes.md`](docs/asset-studio-modes.md).
- 신규 테스트 90건 (`tests/shared` 30, `tests/sprite_mode` 26, `tests/static_mode` 34).

### Changed

- **라이선스를 상류 원본(sprite-gen)과 동일하게 Apache-2.0으로 통일했다.** `LICENSE` 전문, `pyproject.toml`
  `license`, `SKILL.md` frontmatter, SPDX 헤더 278곳.
  - **제3자 귀속은 유지된다.** perfectpixel-studio(MIT, Andrew Kim/gykim80)에서
    이식한 코드 4건이 in-tree 에 있고, MIT 는 그 저작권·허가 고지가 사본과 함께
    이동할 것을 요구하므로 `NOTICE` 파일에 해당 고지 사항을 완전하게 보존했다.
  - **포크 원본 정합성 유지**: 상류 `sprite-gen`(Apache-2.0)과의 라이선스 일치를 통해
    특허 보복 보호 조항 유지 및 다운스트림 관리 복잡도를 해소했다.
- **프로젝트 이름을 `sprite-gen` 에서 `sprite-studio` 로 옮겼다.** SKILL.md 리네임
  게이트 순서(식별자 → 키 문자열 → 라벨 → 문서 → --help → 테스트)를 따랐고, 스윕
  **전에** 구조 단정을 쓰고 mutant 로 검증했다
  (`tests/spec/test_sprite_studio_rename_migration.py`).
  - 배포명·콘솔 스크립트·`prog` 이름: `sprite-studio`
  - Python 패키지: `sprite_gen` → `sprite_studio`
  - 환경변수: `SPRITE_GEN_*` → `SPRITE_STUDIO_*`. 옛 이름이 설정돼 있으면 조용히
    무시하지 않고 새 이름을 안내하며 죽는다 (`assert_no_retired_env`).
  - 온디스크 `kind`: `sprite-gen-*` → `sprite-studio-*`. **판독부를 게이트 뒤로
    옮겼다** — 이름만 바꾸면 이관 전 런에서 그 판독부만 조용히 틀린 답을 본다.
    읽기는 메모리에서만 정규화하고 파일은 건드리지 않으며, 디스크 이관은
    `sprite-studio migrate-kinds <run-dir> --apply` 하나뿐이다 (dry-run 기본, 멱등).
  - `sprite-request.json`·`curation.json` 파일명은 **유지**했다. 프로젝트 이름을
    담고 있지 않아서, 바꾸면 이관 비용만 생기고 얻는 것이 없다.
  - 접두사 겹침 주의: Studio 계층은 `sprite-gen-studio-*` / `SPRITE_GEN_STUDIO_*`
    였으므로 단순 치환하면 `sprite-studio-studio-*` 라는 중복 이름이 된다. 게이트와
    스윕 모두 **긴 접두사를 먼저** 본다.
- `refine_service`가 런의 `mode`로 분기한다. Sprite는 기본 v2 엔진을 쓰고,
  `refine.engine: "v1"`로 고정하면 기존 `FrameRefiner` 출력이 바이트 단위로 재현된다.
- `sprite_studio/frames/extract.py`에 Studio용 **공개 seam** 추가
  (`axis_edge_histograms`, `axis_pitch_score`, `axis_pitch_seed`, `axis_pitch_refine`).
  이름만 공개했을 뿐 동작 변경은 없다 — 엣지 계산과 피치 채점의 정의가 두 벌이 되면
  Studio가 고른 격자와 엔진이 스냅하는 격자가 갈리기 때문이다.
- 프리셋 로더가 모드별로 분리됐다. 캐릭터 런에 타일셋 프리셋을 제시할 수 없다.
- 프로젝트 계약이 모드를 갖는다(`StudioRunConfig` / `StaticProjectConfig`). 서로의
  모드를 거부하며, 모드 필드가 없는 기존 런은 Sprite로 읽힌다(포크 시점엔 그것뿐이었다).

### Fixed

- **격자 피치 동점 처리** — 엔진 채점기는 참값 8.0 격자에서 7.94~8.04를 정확히
  동점으로 낸다. 먼저 만난 값을 취하면 32셀에 걸쳐 2px가 누적돼 유령 셀 2개와
  가장자리 이중 샘플링이 생겼다. 동점일 때 정수에 가까운 쪽을 고르도록 했다
  (256² 씬이 34×34 → 정확히 32×32).
- **축 붕괴 시 위상 재적합** — 한 축이 다른 축의 피치를 빌리면 그 축의 위상은 버려진
  피치에 맞춰 잰 값이라 무의미했다. 위상은 셀 *안의* 오프셋이므로 빌린 피치로 다시 잰다.
- **detail-bias에 어두움 조건 추가** — 밝기 차만 크면 *밝은* 소수 클러스터가 셀을
  차지할 수 있었다. 아웃라인·눈동자 보존이라는 규칙의 목적과 정반대였다.
- **타일 정렬 크롭 위치** — 소스 공간 피치를 이미 축소된 논리 이미지에 적용하고 있었다.
  피치 8.0에서는 무해했지만 소수 피치에서는 잘못된 위치를 잘랐다. 엔진 안,
  격자 검출과 샘플링 사이로 옮겼다.
- **리네임이 도움말을 깨뜨린 자리** — `serve_curation` 의 사용 예시가 이름이 길어지며
  `--run-` / `dir` 로 줄바꿈돼, 존재하지 않는 플래그를 광고했다. docstring 이 예시를
  들여쓴 별도 줄로 의도했으므로 `RawDescriptionHelpFormatter` 로 고정했다.
- **아무 손상도 주지 않으면서 만점을 기록하던 벤치마크 케이스 2건** —
  `chroma_contamination`은 알파 경계가 없는 전면 씬에서, `thin_feature_loss`는
  6배 확대된 스프라이트에서(6px 폭 칼날은 이웃이 4개다) 각각 아무것도 바꾸지 않았다.
  둘 다 완벽한 복원 점수를 보고하고 있었다. 손상 규모에 따라 점수가 단조 감소하는지도
  함께 확인했다.

**프로덕션 파이프라인 실연결 및 고도화 (v0.2 Complete)**
- 캐릭터 스코프 공유 래티스 (`studio/backend/refine_service.py`, `batch_service.py`): `lattice.scope == "character"` 시 전체 추출 프레임을 풀링하여 래티스를 1회 추정하고 모든 상태에 동일 피치 주입.
- Refine Residual → Repair 자동 연동 (`studio/core/repair/repair_pipeline.py`, `studio/backend/repair_service.py`): refine 손실 셀을 구조화된 잔여(`residuals`)로 RepairCandidate에 주입하여 자동 수리 제안 및 적용.
- 외부 설정 전면 이관: `sprite_qa.json`, `static_qa.json`, `benchmark.json`, `dither.json` 생성 및 dataclass 엄격한 로딩/검증(`studio/shared/config/settings.py`).
- 벤치마크 다중 메트릭 및 회귀 게이트: 모든 메트릭(silhouette, color, thin_feature, palette, edge, temporal, texture, seam)을 비교하여 게이트 메트릭 회귀 시 비정상 종료 (`studio/benchmark.py`, `harness.py`).
- Static Provider Generation 및 디더 프리셋: 공통 프로바이더 어댑터(`studio/backend/provider_service.py`) 구축 및 `static_service.generate_asset` 연동, `dither.py` preset 모드 추가.
- 배치 영속 작업 관측성 (`studio/backend/batch_service.py`, `studio/app.py`): 실시간 진행률, 단계, 경과시간, 실패 상세 표시, 중복 실행 방지 및 타이머 폴링.
- 온보딩 시작 흐름 분리: 새 프로젝트 생성 시 "새로 생성"과 "기존 이미지 사용" 진입점 분리 및 필수 검증.

**Normalize 견고화 — Subject Validity / Row-Level Acceptance Gate**
(`SPRITE_STUDIO_GENERATION_NORMALIZE_HARDENING_DIRECTIVE.md` P0)

기존 `normalize_grok_row`는 "스팬에 컴포넌트가 존재한다"를 "유효한 스프라이트
subject다"와 동일시했다 — chroma 잔여물 덩어리·파편·좁은 세그멘테이션 조각도
컴포넌트이고, 그중 가장 큰 것을 골라 셀에 끼워 넣으면 구조적으로는 "4칸 다 찼다"가
됐다. 그 결과 실패한 생성이 4칸짜리 정상 행처럼 보이는 형태로 하류(Extract/Anchor)에
승격될 수 있었다.

- **Subject Validity Gate** (`sprite_studio/gen/normalize_quality.py`) — 셀마다
  foreground 비율, bbox 폭/높이 비율, 측면(좌우) 엣지 접촉 비율, chroma 잔여 비율을
  측정해 `valid`/`reasons`/`metrics`를 매긴다. 바닥 접촉은 정책적으로 감점하지 않는다
  (다리가 셀 하단에 닿는 것은 정상). `extract.py`가 이미 갖고 있던
  `alpha_nonzero_count`/`chroma_adjacent_count`를 재사용했다 — 픽셀 로직을 새로 쓰지 않았다.
- **Row-Level Acceptance Gate** — `normalize_image()`가 이제 `report["result"]`
  ∈ `{pass, recovered_with_warning, fail}`을 낸다. 자연 분할로 전원 유효해야 `pass`,
  강제 세그멘테이션(스팬 수를 못 찾아 DP로 강제 분할)은 더 엄격한 정책으로 재평가하고
  전원 유효해도 `recovered_with_warning`까지만 — 강제 분할은 절대 평범한 `pass`가 되지
  않는다. 실패해도 정규화 결과물과 리포트는 그대로 디스크에 남아 진단에 쓸 수 있다
  (조용히 사라지지 않는다).
- **Studio 경계 강제** (`studio/backend/spritegen_bridge.py::normalize_state`) —
  `result == "fail"`이면 `NormalizeQualityFailed`를 던진다. 세그멘테이션 자체가 실패하는
  하드 실패(`SystemExit`)도 같은 타입으로 감싼다 — 전에는 `SystemExit`이
  `batch_service`의 `except Exception`을 그냥 통과해 큐가 "running"에 멈춰 있다가 나중에
  "interrupted"로 오분류되며 진짜 원인을 잃었다.
- **배치 파이프라인 차단** (`studio/backend/batch_service.py`) — normalize 실패 시
  상태를 `normalize_failed`로 명시하고 예외를 다시 던져 그 배치(앵커 포함)를 즉시
  중단한다: Extract/Refine/QA/앵커 승격/의존 방향 생성이 전혀 시작되지 않는다.
  `status_text()`가 실패 셀 번호와 사유를 사람이 읽을 수 있는 형태로 보여준다.
- **앵커 승격 게이트** (`sprite_studio/curate/anchor.py::frame_source_path`) — 앵커로
  선택된 실제 프레임의 normalize 리포트를 확인한다. `fail`은 항상 차단, 강제 복구
  (`recovered_with_warning`)는 기본 차단(`normalize_quality.anchor.allow_recovered`로
  런별 완화 가능), 선택된 프레임 자체가 `subjects[].valid == false`면 행 전체가
  괜찮아도 차단한다 — 정체성 기준은 액션 프레임보다 엄격해야 한다.
- **데이터 기반 정책** (`studio/data/config/sprite_normalize_quality.json`,
  `studio/shared/config/settings.py::load_normalize_quality_settings`) — 프로덕션
  임계값은 전부 이 설정에서 온다. 파싱은 `NormalizeQualityPolicy.from_dict`
  (엔진 모듈)가 소유 — 미지정 `subject` 섹션·미지정 키는 즉시 실패(No Silent Fallback).
  CLI/엔진 단독 사용은 여전히 `NormalizeQualityPolicy.default()`(보수적 내장값,
  `--quality-config`로 대체 가능)로 동작한다.
- 회귀 픽스처: 실제 문제 이미지(`20a93ecb-...png`)는 저장소에 없어 같은 병리를
  재현하는 합성 이미지로 대체했다 — chroma 잔여 벽 1칸, 파편 1칸, 유효 subject 1칸,
  좁은 잔여 스트립 1칸 (`tests/gen/test_normalize_quality.py`).

**v0.2 Final Audit Fix** (`SPRITE_STUDIO_V02_FINAL_AUDIT_FIX_DIRECTIVE.md` P0/P1)

### Fixed

- **배치 큐 atomic persistence** (`studio/backend/batch_service.py`) — UI polling과
  worker thread가 `batch-queue.json`을 동시에 읽고/쓰던 것이 실제 race였다
  (`Path.write_text()`는 truncate-then-write라 polling이 torn JSON을 읽을 수 있었다).
  temp-file + `os.replace()`로 발행하도록 바꿨다. Windows에서 concurrent reader가 잠깐
  파일을 열고 있는 순간과 겹치면 `os.replace`가 일시적 `PermissionError`(sharing
  violation)를 던질 수 있어, 그 경우에 한해 짧은 backoff로 재시도하는 로직을
  `sprite_studio/spec/runio.py::_atomic_replace`에 추가했다 (POSIX에서는 rename이
  디렉터리 엔트리만 바꾸므로 원래도 필요 없던 경로).
  `load_queue()`가 JSON decode 실패·최상위가 object가 아님·`job_id`/`items`/
  `total_items` 중 하나라도 없는 경우를 전부 명시적 `"corrupt"` 상태로 정규화한다
  (invariant를 갖춘 dict로) — 이전처럼 `{"status": "failed", "error": ...}`만 반환해
  호출부가 `KeyError`로 죽는 일이 없다.
- **Config strict / no silent fallback** (`studio/shared/config/settings.py`) —
  `LatticeSettings`/`PhaseSettings`/`WeightingSettings`/`ColorSettings`/
  `ThinFeatureSettings`/`PaletteSettings`/`FftSettings`/`DitherSettings`/
  `SeamSettings`/`CleanupSettings`/`SpriteQaSettings`/`StaticQaSettings`/
  `MetricGateSettings`의 모든 tuning 필드에서 코드 기본값을 제거했다 (구조적으로
  optional한 `DitherSettings.preset: str | None`만 예외). 로더가 이제 섹션마다
  "필요한 key − payload key"로 누락을 검사하고, `RefineSettings`는 모드별 필수 섹션
  10개(`lattice/grid, phase, weighting, color, thin_feature, palette, fft, dither,
  seam, cleanup`)가 전부 있는지도 검사한다 — Sprite 쪽 `dither`/`seam`도 예외가
  아니다(비활성 상태라도 명시해야 한다). 이 검증 때문에 실제로 비어 있던
  `sprite_refine.json`의 `dither`/`seam`/`cleanup` 섹션과 `lattice.coarse_to_fine`/
  `large_image_pixels`, `static_refine.json`의 `grid.scope`를 채워 넣었다 — 지금까지
  코드 기본값으로 조용히 메워지고 있던 실제 hidden-fallback이었다.
- **Refine residual provenance / stale 검증** (`studio/shared/revision.py` 신규,
  `studio/backend/refine_service.py`, `studio/backend/repair_service.py`) — refine
  residual의 신선도 검사가 파일명 비교(`report_sources == current_sources`)였던 것을
  content-hash 비교로 바꿨다: 같은 파일명으로 다시 refine된 결과는 filename 비교로는
  구분되지 않는다. `refine.report.json`에 `source_revision`/`output_revision`
  (refined frame bytes + settings/lattice fingerprint 해시)을 기록하고, Repair가
  현재 디스크의 refined frame으로 같은 해시를 재계산해 비교한다. 불일치(또는
  `output_revision`이 아예 없는 구버전 리포트)는 residual을 조용히 버리지 않고
  `residual_provenance: {"residual_status": "stale", ...}`로 분석/리페어 결과에
  명시적으로 남긴다. residual 유래 후보의 confidence(`0.69`/`0.88` 리터럴,
  `studio/core/repair/repair_pipeline.py::_residual_candidates`)를
  `RepairProfile.residual_protected_confidence`/`residual_normal_confidence`
  (`studio/data/repair/default.json`)로 옮겼다.
- **Benchmark를 실제 CI regression gate로 연결** (`.github/workflows/ci.yml`) —
  "Run Benchmark Gate" 스텝이 `--baseline` 없이 `python -m studio.benchmark`만
  실행해 점수만 찍고 아무것도 게이트하지 않고 있었다. 커밋된 SSOT
  `studio/data/benchmark/baseline.json`을 `--baseline`으로 비교하고 후보 리포트를
  `.artifacts/benchmark-current.json`으로 아티팩트 업로드하도록 바꿨다.
- **Benchmark 내부 threshold를 config화** (`studio/shared/config/settings.py`의
  `MetricPolicySettings`, `studio/data/config/benchmark.json`의 `metric_policy`
  섹션) — `studio/shared/benchmark/metrics.py` 여러 함수에 독립적으로 박혀 있던
  `128`(alpha opaque threshold), `0.02`(palette retained ΔE), `0.25`(texture
  collapse ratio)를 하나의 커밋된 섹션으로 모았다. 각 metric 함수는 이제
  `policy: MetricPolicySettings | None` 인자를 받고, `None`이면 다른 settings 객체와
  같은 관례로 `load_benchmark_settings().metric_policy`를 resolve한다.

### Known gaps

- FX는 Sprite Mode의 서브타입으로 남아 있다 (별도 FX 모드 없음).
- 벤치마크 케이스는 합성이다. 알고리즘이 알려진 열화에 대해 올바로 동작한다는 뜻이지,
  실제 생성 결과물의 품질이 좋아졌다는 뜻은 아니다.
- **normalize 견고화는 디렉티브의 P0 범위만 구현했다.** 적응형 chroma 키 추정(§8),
  largest-component 이상의 위성 컴포넌트 그룹핑(§9), 제한된 자동 재생성 정책(§11),
  배치 UI 전면 개편(§12)은 P1로 미뤘다 — 사용자 확인 하에 범위를 좁혔다. chroma 잔여
  탐지는 여전히 고정 색-거리 휴리스틱이라 마젠타/핑크 계열의 *정당한* subject 색상을
  오탐할 수 있다 (적응형 추정이 없는 한 내재된 트레이드오프).
- edge-contact/foreground 임계값은 실제 다수의 Grok 생성 실패 사례가 아니라 이 작업의
  합성 픽스처로 튜닝했다 — 실 생성물로 벤치마크하며 재조정이 필요할 수 있다.
- **v0.2 Final Audit Fix 디렉티브의 P1/P2 항목 중 i18n 전면 sweep과 Sprite UI
  파이프라인 stage rail 재구성은 이번 작업에서 다루지 않았다.** Gradio 라벨/버튼/탭
  타이틀/상태 메시지는 여전히 코드에 박힌 리터럴이고, Sprite 탭은 여전히
  `PROJECT/GENERATE/REVIEW/MATRIX/EXPORT` 구조다 — 둘 다 별도 작업으로 남겨둔다
  (`docs/asset-studio-modes.md`의 "Known gaps before v0.2 Complete" 참조).
- `RepairProfile`(`studio/core/repair/profile.py`)과 `oklab_palette.py`의
  `alpha_threshold` 기본값은 이번 config strictness 작업 범위 밖이다 — 여전히
  "JSON이 있으면 덮어쓰고 없으면 코드 기본값" 방식이라, §2가 요구하는 required-key
  검증까지는 가지 않았다.

---

## Baseline — 포크 시점 (`sprite-studio` 1.59.0)

포크해 온 시점에 이미 있던 기능이다. 이 저장소가 추가한 것이 아니라, 무엇 위에서
시작하는지 밝히기 위한 요약이다.

- **component-row 파이프라인** — `sprite-request.json`(수치 SSoT) → 레이아웃 가이드와
  프롬프트 → 상태별 행 이미지 → 크로마 알파 제거 → 연결 성분 분리 → 픽셀 언페이크
  (피치 검출/그리드 스냅/kCentroid/공유 팔레트) → 셀 배치 → 아틀라스와
  `manifest.json.frame_layout`.
- **큐레이션 웹뷰** — 후보 나란히 비교·선택·편집. 스프라이트 런뿐 아니라 임의의
  이미지 후보 묶음도 다룬다 (`unpack-atlas --pngs-dir` 반입).
- **컬러웨이 베이크** — `sprite-studio recolor`가 베이스 시트와 recolor 스펙으로 팔레트
  스왑 변형 시트를 결정론적으로 굽고, `sprite-studio recolor-palette`가 베이스 시트에서
  팔레트 맵 초안을 뽑는다. 큐레이션 뷰의 blink-compare로 고른 결과는
  `curation.json`의 `recolor.picked`에 기록된다. 자세한 내용은
  [`docs/recolor.md`](docs/recolor.md).
- **레이어 트랙** — 모든 조합을 생성하는 대신 행을 겹쳐 합성.
- **엔진 출력** — Aseprite JSON, Phaser 태그, Flame 상태별 해시.
- **QA** — 모션 연속성 검증, `inspect` → `score` → `correction-loop`.
- **Asset Studio (Gradio) 1단계** — 프로젝트/생성/정규화/추출/정제/수리/애니메이션
  QA/출력 워크플로.
