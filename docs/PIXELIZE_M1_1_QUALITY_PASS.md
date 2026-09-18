# PIXELIZE M1.1 QUALITY PASS

## 목적

Pixelize M1.1은 기존 Pixelize 엔진 경로를 유지하면서 전체 이미지 긴 변을 줄이던 품질 구조를 주체 우선 변환으로 바꾼다.

순서는 다음과 같다.

```text
source
→ alpha/background normalization
→ subject auto-detect 또는 manual crop
→ 선택 주체의 character height를 sprite size로 스케일
→ subject 영역 기준 palette
→ area + edge + local contrast + outline cell scoring
→ optional dither
→ thin-feature recovery
```

## 입력 계약

`target_size`/API `size`는 더 이상 입력 이미지 전체 긴 변이 아니다. 선택된 주체의 높이를 의미한다.

- `64`, `96`, `128`, `192`: character height
- `subject_mode`: `auto` 또는 `manual`
- `subject_bbox`: manual일 때 source 좌표의 `[left, top, right, bottom]`
- `detail`: `clean`, `balanced`, `detailed`
- `palette`, `dither`, `outline`, `background`, `alpha_threshold`: Advanced 옵션

Auto detect는 alpha bbox를 우선 사용하고, fully opaque 입력은 border 색상 대비와 connected-component 후보를 사용한다. 가장 큰 후보를 기본 선택하며, 여러 후보가 있으면 warning에 후보를 기록한다. 특정 캐릭터를 확실히 선택해야 하는 경우 manual crop을 사용한다.

## 품질 변경

- palette는 전체 원본이 아니라 선택된 subject crop에서 만든다.
- cell 선택은 면적만 보지 않고 edge strength와 local contrast를 함께 계산한다.
- 충분한 edge/contrast를 가진 dark candidate에는 outline bonus를 준다.
- 후처리에서 인접 셀을 가진 강한 dark thin feature를 복구하고 isolated noise는 무시한다.
- fully opaque auto source는 선택 주체 바깥을 투명 처리해 배경에 pixel budget을 쓰지 않는다.

## 출력

기존 출력은 유지한다.

- `<asset>.png`
- `<asset>.preview-4x.png`
- `<asset>.palette.json`
- `<asset>.pixel-profile.json`
- `<asset>.pixelize-report.json`

추가로 `<asset>.subject.png`를 저장한다. Report에는 `subject_bbox`, `subject_candidates`, `palette_scope`, `cell_scoring`, `thin_feature_recovered_cells`가 포함된다. Static/Quick UI는 original → subject crop → pixelized를 나란히 비교한다.

## Quick UI

Quick Pixelize는 다음 순서로 노출한다.

```text
1. Choose subject: Auto detect / Manual crop
2. Sprite size: 64 / 96 / 128 / 192
3. Detail: Clean / Balanced / Detailed
4. Pixelize
```

정확한 palette count, dither, outline, alpha threshold는 Advanced에 둔다. 기존 Original/Pixelized source 선택과 Studio 진입은 유지한다.

## 검증 샘플

테스트는 다음 유형을 대상으로 한다.

1. 투명 배경의 단일 캐릭터
2. 흰색 등 fully opaque 배경의 단일 캐릭터
3. 두 명 이상이 포함된 이미지
4. 장식이 많은 의상
5. 머리카락/프릴/무기 등 얇은 선이 많은 이미지
6. SD풍 캐릭터
7. 사실적인 애니풍 캐릭터

현재 자동 테스트는 deterministic output, subject-height logical size, manual crop, subject-scoped palette, feature-aware report, subject asset URL을 검증한다.