# sprite-studio

생성형 이미지 모델로 **깨끗한 2D 게임 스프라이트와 애니메이션 아틀라스**를 만드는
component-row 파이프라인. AI는 원본 한 장을 그리는 데만 쓰고, 그 뒤의 모든 변환은
같은 입력이면 항상 같은 출력이 나오는 **결정론 코드 경로**가 담당한다.

```text
sprite-request.json  ->  레이아웃 가이드 + 프롬프트  ->  상태별 행 이미지 생성
  ->  크로마 알파 제거  ->  연결 성분 분리  ->  투명 셀 배치
  ->  sprite-sheet-alpha.png + manifest.json.frame_layout
```

- **라이선스**: MIT
- **버전**: 1.59.0 (`pyproject.toml`과 `SKILL.md`의 `version:`은 같은 릴리스 커밋에서 함께 올린다)

> **이 저장소는 [`sprite-gen`](https://github.com/aldegad/sprite-gen)을 포크해
> Asset Studio 로 새로 만드는 중이다.** 포크 시점의 상태와 그 이후 변경은
> [`CHANGELOG.md`](CHANGELOG.md)가 구분해 기록한다. 현재 진행 중인 작업은
> Studio를 Sprite / Static 두 모드로 나누는 것이다 (아래
> [Asset Studio](#asset-studio) 참조).

---

## 핵심 원칙 — AI raw는 최종 에셋이 아니다

이 저장소에서 가장 중요한 규칙이다.

- **AI가 개입하는 지점은 `raw/<state>.png` 생성 한 곳뿐이다.** 그 파일은 중간
  산출물이고, 최종 에셋은 반드시 `extract` 경로(크로마 제거 → 컴포넌트 분리 →
  피치 검출/그리드 스냅 → kCentroid → 공유 팔레트 → 셀 배치)를 거친다.
- **단순 다운스케일 쇼트컷 금지.** raw를 `resize()` 한 줄로 줄여 최종 경로에 놓는
  것은 픽셀 언페이크가 아니다 — 안티에일리어싱 가장자리 열화와 그리드 미정렬이
  그대로 남는다.
- **베이스가 스타일의 SSoT다.** 이미지 모델은 첨부 레퍼런스를 프롬프트 텍스트보다
  강하게 따른다. 도트 결과물을 원하면 베이스부터 진짜 도트여야 한다.
- **조용한 폴백 금지.** 확신이 없으면 그리드를 추측해 스냅하지 않고, 스냅하지
  않았다는 사실을 보고한다.

전체 게이트 목록은 [`SKILL.md`](SKILL.md)가 소유한다.

---

## 요구사항

- **CPython 3.10+** — `pyproject.toml`의 `requires-python`이 선언하는 하한이고,
  CI 매트릭스도 같은 값을 최소값으로 갖는다.
- 표준 라이브러리의 `venv`/`ensurepip` — 아래 부트스트랩 한 줄이 이것에 의존한다.
  배포판에 따라 별도 패키지로 빠져 있을 수 있다(예: Debian/Ubuntu의
  `python3-venv`).
- 런타임 의존성은 두 개뿐이며 둘 다 직접 의존성이다: **Pillow** (`>=12.0,<13`),
  **NumPy** (`>=2.2.6,<3`). NumPy는 다른 패키지가 딸려 오는 것에 기대지 않는다 —
  추출 경로가 직접 import 하고, 바이트 동일성 계약이 NEP 50 승격 규칙에 걸려 있다.

---

## 설치

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
source .venv/bin/activate
```

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\pip install -e .
.\.venv\Scripts\Activate.ps1
```

### 인터프리터 규칙 (중요)

`.venv`가 이 프로젝트의 **유일한** 인터프리터다. 전역 `python3`는 그날 `$PATH`가
가리키는 아무 인터프리터이고, 거기 든 패키지는 손으로 넣은 것이라 선언과 실물이
갈린다(실측: Pillow만 있고 NumPy가 없어서, 하나가 깔려 있다는 이유로 다 깔린
것처럼 보이는 상태).

- 이 README의 예제는 **활성화된 셸**을 전제로 상대 경로를 쓴다.
- 셸을 활성화하지 않는 에이전트/문서(`SKILL.md`, `docs/*.md`)는 인터프리터를
  절대경로로 명시한다: `$SPRITE_STUDIO_ROOT/.venv/bin/python ...`
- "있으면 venv, 없으면 python3" 같은 폴백은 두지 않는다. 없으면 만들거나 요란하게
  실패한다.

설치하면 콘솔 스크립트 `sprite-studio`이 생기고, 그 스크립트의 shebang이 설치된
환경의 인터프리터를 가리키므로 "어느 python?" 질문이 사라진다.

---

## 빠른 시작

```bash
# 1. 런 준비 — sprite-request.json(수치 SSoT) + 레이아웃 가이드 + 프롬프트 생성
sprite-studio prepare --out-dir runs/hero --character-id hero --base-image base.png

# 2. 상태 행 생성 (AI가 개입하는 유일한 단계)
#    gen 은 런 디렉터리를 모른다 — 프롬프트와 출력 경로를 직접 받는다.
sprite-studio gen --provider grok \
  --prompt-file runs/hero/prompts/side_attack.txt \
  --out runs/hero/raw/side_attack.png \
  --ref runs/hero/references/anchors/side-anchor-x8.png

# 3. 행을 프레임으로 추출 (결정론 변환)
sprite-studio extract --run-dir runs/hero

# 4. 아틀라스 + 런타임 매니페스트 합성
sprite-studio compose-atlas --run-dir runs/hero

# 5. 모션을 모션으로 검수
sprite-studio preview --run-dir runs/hero
sprite-studio curation --run-dir runs/hero      # 웹뷰로 후보 비교·선택
```

`gen`은 provider 바이너리를 필요로 한다: `codex`(ChatGPT OAuth image_gen) 또는
`grok`(xAI Imagine). 생성 단계 없이 기존 이미지를 들고 와도 파이프라인은 동작한다.
크로마 키는 소재색을 보고 고른다 — 핑크/보라 소재면 그린 키, 녹색 식물이면 마젠타
키 (`--transparent --chroma-key ...`, 분기표는 [`docs/chroma-alpha.md`](docs/chroma-alpha.md)).

---

## CLI 도구

`sprite-studio <tool>` 형태로 호출한다. `scripts/<tool>.py`는 파일 이름으로 부르던
호출자를 위한 하위 호환 래퍼일 뿐이며, 문서가 가르치는 형태는 아니다.

| 분류 | 도구 |
|---|---|
| 런 구성 | `prepare` · `migrate-request` · `migrate-breathe` |
| 생성 | `gen` · `normalize-grok-row` · `cutout` |
| 추출 | `extract` · `slice-sheet` · `unpack-atlas` |
| 합성 | `compose-atlas` · `compose-cycle` · `compose-gif` · `compose-layers` |
| 출력 | `export-pngs` · `export-aseprite` |
| 큐레이션 | `curation` · `compose` · `anchor` |
| 컬러웨이 | `recolor` · `recolor-palette` |
| QA | `preview` · `inspect` · `score` · `correction-loop` |

---

## Asset Studio

Gradio 기반 오퍼레이터 레이어. 엔진(`sprite_studio`)을 SSoT로 두고 그 위에 워크플로를
얹는다.

```bash
pip install -e ".[studio]"
python -m studio.app          # http://127.0.0.1:7860
```

Studio는 **하나의 스튜디오, 두 개의 생산 모드**로 나뉜다
(`ASSET_STUDIO_MODE_SPLIT_SPEC_v0.2`).

```text
Asset Studio
├─ Shared Core      studio/shared/       공통 코어
├─ Sprite Mode      studio/sprite_mode/  캐릭터/유닛 애니메이션
└─ Static Mode      studio/static_mode/  배경·타일·오브젝트·정지 이미지
```

두 모드는 색 거리·셀 가중치·격자 채점을 **똑같이** 측정하되(그래서 공통 코어),
파이프라인과 QA와 후처리는 만드는 물건의 결에 따라 **나뉜다**.

| | Sprite Mode | Static Mode |
|---|---|---|
| 작업 단위 | 프레임 행 | 이미지 한 장 |
| 셀 피치 | 상태 전체에 **고정** | 이미지마다 자유 |
| 위상(phase) | 프레임마다 **제한된 범위 안에서만** 보정 | 자유 |
| 얇은 특징 | 보호(커버리지 완화) | 해당 없음 |
| 디더링 | **절대 사용 안 함** | 선택적, 기본 off |
| 이음새(seam) | 해당 없음 | 검사 · 선택적 보정 |

설계 근거와 각 알고리즘의 실패 사례는
[`docs/asset-studio-modes.md`](docs/asset-studio-modes.md)에 있다.

### 알고리즘 변경의 게이트 — 합성 열화 벤치마크

정답을 아는 에셋을 일부러 열화시킨 뒤(블러, 서브픽셀 오프셋, 안티에일리어싱
리사이즈, 경계 번짐, 얇은 특징 손실 등) 정제 결과를 원본과 비교한다. 결정론적이라
점수가 바뀌면 알고리즘이 바뀐 것이고, 케이스별로 비교하므로 평균만 올리고 몇
케이스를 망가뜨리는 변경이 개선으로 통과하지 못한다.

```bash
python -m studio.benchmark --out runs/benchmark/baseline.json      # 기준 기록
python -m studio.benchmark --baseline runs/benchmark/baseline.json # 회귀 시 exit 1
python -m studio.benchmark --list-degradations
```

---

## 컬러웨이 — 팔레트 스왑 베이크

베이스 시트 하나와 팔레트 맵으로 N개의 색상 변형 시트를 결정론적으로 굽는다.
`recolor`는 스펙대로 변형을 만들고, `recolor-palette`는 베이스 시트에서 팔레트 맵
초안을 뽑는다. 큐레이션 뷰가 결과를 blink-compare로 비교하고 채택하면
`curation.json`의 `recolor.picked`에 기록된다.

```bash
# 베이스 시트에서 팔레트 맵 초안 뽑기 (기본 출력은 stdout)
sprite-studio recolor-palette --base runs/hero/sprite-sheet-alpha.png --out palette.json

# 스펙대로 variants/ 에 변형 시트 굽기
sprite-studio recolor --run-dir runs/hero --spec recolor-spec.json
```

자세한 내용은 [`docs/recolor.md`](docs/recolor.md).

---

## 큐레이션 뷰

에이전트 채팅은 이미지를 렌더링하지 못하지만 이 웹뷰는 할 수 있다. 스프라이트
런뿐 아니라 **임의의 이미지 후보 묶음**(아이콘, 로고, 생성 초안)도 나란히 비교하고
고를 수 있다.

```bash
sprite-studio unpack-atlas --pngs-dir ./candidates --out-dir runs/pick   # 임의 이미지 반입
sprite-studio curation --run-dir runs/pick
```

---

## 문서

`SKILL.md`가 동작 계약이자 허브이고, 각 문서가 자기 표를 소유한다.

| 관심사 | 문서 |
|---|---|
| 계약·구조 | [`docs/run-contract.md`](docs/run-contract.md) · [`docs/architecture.md`](docs/architecture.md) |
| 요청 작성 | [`docs/states-and-frames.md`](docs/states-and-frames.md) · [`docs/subject-profiles.md`](docs/subject-profiles.md) · [`docs/pixel-unfake.md`](docs/pixel-unfake.md) · [`docs/chroma-alpha.md`](docs/chroma-alpha.md) |
| 생성 | [`docs/gen.md`](docs/gen.md) · [`docs/frame-interpolation.md`](docs/frame-interpolation.md) · [`docs/seamless-video-loop.md`](docs/seamless-video-loop.md) |
| 큐레이션 | [`docs/curation.md`](docs/curation.md) |
| 컬러웨이 | [`docs/recolor.md`](docs/recolor.md) |
| 레이어 트랙 | [`docs/layer-tracks.md`](docs/layer-tracks.md) |
| 엔진 출력 | [`docs/engine-export.md`](docs/engine-export.md) |
| 특수 입력 | [`docs/directional-anchor-workflow.md`](docs/directional-anchor-workflow.md) · [`docs/sheet-slicing.md`](docs/sheet-slicing.md) |
| QA | [`docs/qa-motion.md`](docs/qa-motion.md) · [`docs/locomotion-curation.md`](docs/locomotion-curation.md) |
| Studio | [`docs/studio.md`](docs/studio.md) · [`docs/asset-studio-modes.md`](docs/asset-studio-modes.md) |
| 문제 해결 | [`docs/troubleshooting.md`](docs/troubleshooting.md) |

---

## 개발

```bash
pip install -e ".[dev]"
pytest                      # 전체
pytest tests/frames         # 도메인 하나만
```

테스트는 도메인별 폴더(`tests/<domain>/`)로 묶여 있고, `conftest.py`는 `tests/`
루트에서 이름으로 import 된다. 서브프로세스를 띄우는 테스트가 조용히 멈추지 않도록
`pytest-timeout`을 `signal` 방식으로 강제한다.

---

## 라이선스

MIT. 전문은 [`LICENSE`](LICENSE).

[`NOTICE`](NOTICE)는 MIT 자체가 요구하는 파일은 아니지만, 거기 적힌 제3자 귀속은
**선택이 아니다**: perfectpixel-studio(MIT, Andrew Kim)에서 이식한 코드가 in-tree 에
있고, MIT 는 그 저작권·허가 고지가 사본과 함께 이동할 것을 요구한다. 이 프로젝트의
라이선스를 바꾼다고 그 의무가 사라지지 않는다.

이 저장소는 Apache-2.0 으로 배포되던 `sprite-gen` 의 포크에서 출발했다 — 그 경위도
[`NOTICE`](NOTICE)에 적혀 있다.

보안 문제 신고 절차는 [`SECURITY.md`](SECURITY.md)에 있다.
