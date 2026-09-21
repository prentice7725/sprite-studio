import { useI18n } from '../../i18n'

export interface QuickText {
  quickGenerate: string
  sourceToSprite: string
  advancedStudio: string
  sourceFirst: string
  sourceHeading: string
  sourceDescription: string
  source: string
  uploadImage: string
  promptSource: string
  sourceImage: string
  imageHint: string
  characterPrompt: string
  referenceImage: string
  optional: string
  motion: string
  style: string
  background: string
  provider: string
  notes: string
  notesPlaceholder: string
  customMotionDescription: string
  useThisSource: string
  preparingSource: string
  generateSource: string
  sourceReady: string
  chooseSource: string
  uploadedSource: string
  generatedSource: string
  originalAvailable: string
  replaceSource: string
  openInStudio: string
  spriteSource: string
  originalSource: string
  pixelizedSource: string
  makeSprite: string
  pixelizeFirst: string
  saveSource: string
  pixelize: string
  makePixelMaster: string
  pixelizeDescription: string
  logicalSize: string
  palette: string
  advancedPixelize: string
  alphaThreshold: string
  exactSize: string
  dither: string
  backgroundAlpha: string
  outline: string
  keep: string
  cleanup: string
  preserve: string
  auto: string
  low: string
  ordered: string
  pixelizeSource: string
  pixelizing: string
  logical: string
  colors: string
  selectExplicitly: string
  useForMake: string
  createAnimation: string
  quickInternalDescription: string
  directions: string
  frames: string
  oneDirection: string
  fourDirections: string
  eightDirections: string
  pixelizeBefore: string
  pixelizeSettings: string
  selectedSource: string
  starting: string
  back: string
  progress: string
  inProgress: string
  generatingSource: string
  normalizing: string
  extractingFrames: string
  refiningFrames: string
  runningQa: string
  preparingExport: string
  complete: string
  quickGenerateFailed: string
  preparing: string
  pipelinePersisted: string
  viewDetails: string
  retry: string
  changeSettings: string
  result: string
  spriteReady: string
  downloadPng: string
  downloadGif: string
  manifest: string
  runAvailable: string
  chooseSubject: string
  autoDetect: string
  manualCrop: string
  autoSubjectHint: string
  cropLeft: string
  cropTop: string
  cropRight: string
  cropBottom: string
  detectedSubjects: string
  spriteSize: string
  detail: string
  clean: string
  balanced: string
  detailed: string
  compareSubject: string
  subjectDetected: string
  sourceStep: string
  readyStep: string
  pixelizeStep: string
  makeStep: string
  progressStep: string
  resultStep: string
  idle: string
  walk: string
  run: string
  jump: string
  attack: string
  hurt: string
  custom: string
  pixelArt: string
  celShaded: string
  handPainted: string
  render3d: string
  transparent: string
  chromaKey: string
  none: string
}

const en: QuickText = {
  quickGenerate: 'Quick Generate', sourceToSprite: 'Source to sprite', advancedStudio: 'Open Advanced Studio', sourceFirst: 'SOURCE FIRST', sourceHeading: 'Start with an image or a character idea', sourceDescription: 'Upload a source, or describe the character you want to create. Studio will keep the production details behind the scenes.', source: 'Source', uploadImage: 'Upload image', promptSource: 'Generate source from prompt', sourceImage: 'Source image', imageHint: 'PNG, JPEG, WEBP, or another readable image.', characterPrompt: 'Character prompt', referenceImage: 'Reference image', optional: 'optional', motion: 'Motion', style: 'Style', background: 'Background', provider: 'Provider', notes: 'Notes', notesPlaceholder: 'Keep the scarf, avoid detached effects', customMotionDescription: 'Custom motion description', useThisSource: 'Use this source', preparingSource: 'Preparing source…', generateSource: 'Generate Source', sourceReady: 'SOURCE READY', chooseSource: 'Choose the source to animate', uploadedSource: 'Uploaded source', generatedSource: 'Generated source', originalAvailable: 'The original image stays available. Pixelize is an explicit alternate source, never an automatic replacement.', replaceSource: 'Replace Source', openInStudio: 'Open in Studio', spriteSource: 'Sprite source', originalSource: 'Original source', pixelizedSource: 'Pixelized source', makeSprite: 'Make Sprite', pixelizeFirst: 'Pixelize First', saveSource: 'Save Source', pixelize: 'PIXELIZE', makePixelMaster: 'Make a pixel master', pixelizeDescription: 'C2 is the reference-guided AI Pixel Master path; Preserve remains available as a deterministic alternative.', logicalSize: 'Logical size', palette: 'Palette', advancedPixelize: 'Advanced pixelize options', alphaThreshold: 'Alpha threshold', exactSize: 'Exact size', dither: 'Dither', backgroundAlpha: 'Background alpha', outline: 'Outline', keep: 'Keep', cleanup: 'Cleanup', preserve: 'Preserve', auto: 'Auto', low: 'low', ordered: 'Ordered', pixelizeSource: 'Pixelize source', pixelizing: 'Pixelizing…', logical: 'Logical', colors: 'colors', selectExplicitly: 'select explicitly below', useForMake: 'Use for Make Sprite', createAnimation: 'Create the animation', quickInternalDescription: 'Quick Generate chooses the internal Project, Asset, State, Motion Plan, and Job automatically. You only need the output shape.', directions: 'Directions', frames: 'Frames', oneDirection: '1 direction', fourDirections: '4 directions', eightDirections: '8 directions', pixelizeBefore: 'Pixelize before creating the sprite', pixelizeSettings: 'Pixelize settings', selectedSource: 'Selected source', starting: 'Starting…', back: 'Back', progress: 'Progress', inProgress: 'IN PROGRESS', generatingSource: 'Generating source…', normalizing: 'Normalizing…', extractingFrames: 'Extracting frames…', refiningFrames: 'Refining frames…', runningQa: 'Running QA…', preparingExport: 'Preparing export…', complete: 'Complete', quickGenerateFailed: 'Quick Generate failed', preparing: 'Preparing…', pipelinePersisted: 'You can leave this view; the job remains persisted in Studio.', viewDetails: 'View details', retry: 'Retry', changeSettings: 'Change settings', result: 'RESULT', spriteReady: 'Your sprite is ready', downloadPng: 'Download PNG', downloadGif: 'Download GIF', manifest: 'Manifest', runAvailable: 'is available in Advanced Studio for repair, curation, and export.', chooseSubject: 'Choose subject', autoDetect: 'Auto detect', manualCrop: 'Manual crop', autoSubjectHint: 'Auto detect selects the largest clear subject and masks the surrounding background.', cropLeft: 'Left', cropTop: 'Top', cropRight: 'Right', cropBottom: 'Bottom', detectedSubjects: 'Detected subjects', spriteSize: 'Sprite size', detail: 'Detail', clean: 'Clean', balanced: 'Balanced', detailed: 'Detailed', compareSubject: 'Subject crop', subjectDetected: 'Subject detected', idle: 'Idle', walk: 'Walk', run: 'Run', jump: 'Jump', attack: 'Attack', hurt: 'Hurt', custom: 'Custom', pixelArt: 'Pixel Art', celShaded: 'Cel-Shaded', handPainted: 'Hand-Painted', render3d: '3D Render', transparent: 'Transparent', chromaKey: 'Chroma Key', none: 'Off', sourceStep: 'Source', readyStep: 'Ready', pixelizeStep: 'Pixelize', makeStep: 'Make Sprite', progressStep: 'Progress', resultStep: 'Result',
}

const ko: QuickText = {
  quickGenerate: '빠른 생성', sourceToSprite: '소스에서 스프라이트까지', advancedStudio: '고급 Studio 열기', sourceFirst: '소스 우선', sourceHeading: '이미지 또는 캐릭터 아이디어로 시작하세요', sourceDescription: '소스 이미지를 업로드하거나 만들고 싶은 캐릭터를 설명하세요. 제작 세부 사항은 Studio가 내부에서 처리합니다.', source: '소스', uploadImage: '이미지 업로드', promptSource: '프롬프트로 소스 생성', sourceImage: '소스 이미지', imageHint: 'PNG, JPEG, WEBP 등 읽을 수 있는 이미지', characterPrompt: '캐릭터 프롬프트', referenceImage: '참조 이미지', optional: '선택 사항', motion: '모션', style: '스타일', background: '배경', provider: '생성기', notes: '메모', notesPlaceholder: '스카프는 유지하고 분리된 효과는 제외', customMotionDescription: '사용자 지정 모션 설명', useThisSource: '이 소스 사용', preparingSource: '소스 준비 중…', generateSource: '소스 생성', sourceReady: '소스 준비 완료', chooseSource: '애니메이션에 사용할 소스를 선택하세요', uploadedSource: '업로드한 소스', generatedSource: '생성된 소스', originalAvailable: '원본 이미지는 유지됩니다. 픽셀화 이미지는 자동으로 대체되지 않는 별도 소스입니다.', replaceSource: '소스 교체', openInStudio: 'Studio 열기', spriteSource: '스프라이트 소스', originalSource: '원본 소스', pixelizedSource: '픽셀화 소스', makeSprite: '스프라이트 만들기', pixelizeFirst: '먼저 픽셀화', saveSource: '소스 저장', pixelize: '픽셀화', makePixelMaster: '픽셀 마스터 만들기', pixelizeDescription: 'C2는 참조 기반 AI 픽셀 마스터 경로이며, Preserve는 결정론적 대안으로 남아 있습니다.', logicalSize: '논리 크기', palette: '팔레트', advancedPixelize: '고급 픽셀화 옵션', alphaThreshold: '알파 임계값', exactSize: '정확한 크기', dither: '디더링', backgroundAlpha: '배경 알파', outline: '외곽선', keep: '유지', cleanup: '정리', preserve: '보존', auto: '자동', low: '낮음', ordered: '정렬', pixelizeSource: '소스 픽셀화', pixelizing: '픽셀화 중…', logical: '논리 크기', colors: '색상', selectExplicitly: '아래에서 명시적으로 선택', useForMake: '스프라이트에 사용', createAnimation: '애니메이션 만들기', quickInternalDescription: '빠른 생성이 프로젝트, 에셋, 상태, 모션 플랜, 작업을 자동으로 선택합니다. 출력 형태만 정하면 됩니다.', directions: '방향 수', frames: '프레임 수', oneDirection: '1방향', fourDirections: '4방향', eightDirections: '8방향', pixelizeBefore: '스프라이트 생성 전에 픽셀화', pixelizeSettings: '픽셀화 설정', selectedSource: '선택한 소스', starting: '시작 중…', back: '뒤로', progress: '진행', inProgress: '진행 중', generatingSource: '소스 생성 중…', normalizing: '정규화 중…', extractingFrames: '프레임 추출 중…', refiningFrames: '프레임 보정 중…', runningQa: 'QA 실행 중…', preparingExport: '내보내기 준비 중…', complete: '완료', quickGenerateFailed: '빠른 생성 실패', preparing: '준비 중…', pipelinePersisted: '이 화면을 떠나도 작업은 Studio에 저장되어 계속됩니다.', viewDetails: '상세 보기', retry: '재시도', changeSettings: '설정 변경', result: '결과', spriteReady: '스프라이트가 준비되었습니다', downloadPng: 'PNG 다운로드', downloadGif: 'GIF 다운로드', manifest: '매니페스트', runAvailable: '에서 수리, 큐레이션, 내보내기를 계속할 수 있습니다.', chooseSubject: '주체 선택', autoDetect: '자동 감지', manualCrop: '수동 크롭', autoSubjectHint: '가장 큰 주체를 자동으로 선택하고 주변 배경을 마스킹합니다.', cropLeft: '왼쪽', cropTop: '위쪽', cropRight: '오른쪽', cropBottom: '아래쪽', detectedSubjects: '감지된 주체', spriteSize: '스프라이트 크기', detail: '디테일', clean: '클린', balanced: '균형', detailed: '상세', compareSubject: '주체 크롭', subjectDetected: '주체 감지 완료', idle: '대기', walk: '걷기', run: '달리기', jump: '점프', attack: '공격', hurt: '피격', custom: '사용자 지정', pixelArt: '픽셀 아트', celShaded: '셀 셰이딩', handPainted: '핸드 페인팅', render3d: '3D 렌더', transparent: '투명', chromaKey: '크로마 키', none: '끄기', sourceStep: '소스', readyStep: '준비', pixelizeStep: '픽셀화', makeStep: '스프라이트 만들기', progressStep: '진행', resultStep: '결과',
}

export function useQuickText(): QuickText {
  const { locale } = useI18n()
  return locale === 'ko' ? ko : en
}