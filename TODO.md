# AI Influencer - TODO

## 완료
- [x] 프로젝트 구조 생성 (config, src, scripts, data 등)
- [x] Playwright 기반 Instagram 브라우저 수집기 구현
  - [x] 로그인/세션 관리
  - [x] 해시태그/검색/유저/탐색 수집
  - [x] 한국어 DOM 파싱 (좋아요, 시간, 캡션)
  - [x] 페르소나 기반 게시글 필터링
  - [x] "계정 저장하기" 오버레이 자동 닫기
  - [x] 캐러셀 이미지 순회 수집
- [x] 미디어 분석 모듈 (media_downloader.py)
  - [x] 이미지 다운로드 + 분석 (해상도, 밝기, 색온도, 채도)
  - [x] 영상 다운로드 + 분석 (ffmpeg/ffprobe, 길이, FPS)
  - [x] 썸네일 추출
- [x] 페르소나 정의 (persona.yaml - 유하나, 24세, 서울)
- [x] QLoRA 학습 파이프라인 (train_qlora.py)
  - [x] Unsloth / PEFT+bitsandbytes 듀얼 백엔드
  - [x] OOM 자동 폴백 (seq_len 축소)
  - [x] Qwen2.5-1.5B-Instruct 기반 학습 (1,289 샘플, loss 0.39~0.55)
- [x] 데이터 정제 파이프라인 (cleaner.py, dataset_builder.py)
- [x] 순환 파이프라인 구현 (cycle_pipeline.py)
  - [x] 수집 데이터 → 학습 JSONL 자동 변환
  - [x] 한국어 키워드/해시태그 자동 추출
  - [x] NFD→NFC 유니코드 정규화 처리
  - [x] 발견된 키워드 기반 수집 대상 자동 확장
  - [x] 순환 상태 관리 (cycle_state.json)
- [x] 수집 데이터 확장 (395 게시글, full 모드)
- [x] QLoRA 재학습 (페르소나 3배 업샘플링, 1,289 샘플)
- [x] LLM 캡션/해시태그 생성
  - [x] text_generator.py (base model + LoRA adapter 로드)
  - [x] prompt_builder.py (페르소나 시스템 프롬프트)
  - [x] CJK/영어 누출 클린업 (_clean_output)
  - [x] PostMemory 기반 컨텍스트 인식 생성
- [x] 이미지 분석 + 나노바나나 프롬프트 설계
  - [x] image_analyzer.py (표정, 옷, 포즈, 배경, 조명, 분위기)
  - [x] prompt_composer.py (일러스트 캐릭터 + 실사 배경 합성)
- [x] Instagram 브라우저 포스팅 (browser_poster.py)
  - [x] Playwright 기반 업로드, 세션 재사용
  - [x] 실제 테스트 포스팅 성공
- [x] 댓글 모니터링 + 자동 답글 (commenter.py)
  - [x] Playwright 기반 댓글 추출 (BrowserCommenter)
  - [x] 파인튜닝 모델로 답글 생성
  - [x] rate limiting + replied ID 영속 추적
- [x] 콘텐츠 플래너 (content_planner.py, topic_generator.py)
  - [x] 주간 콘텐츠 기획 자동 생성
  - [x] 주제/해시태그 생성
  - [x] 시즌/한국 기념일 반영
- [x] APScheduler 기반 오케스트레이터 (orchestrator.py)
  - [x] 주간 기획, 포스팅, 댓글 모니터링 스케줄
  - [x] 작업 큐 (TaskQueue) 기반 재시도
  - [x] 시그널 핸들러 (graceful shutdown)
- [x] 에러 핸들링 (error_handler.py, rate_limiter.py)
- [x] 터미널 대화 인터페이스 (chat.py)
- [x] README.md 상세 문서화

## 남은 작업

### 통합 테스트 및 안정화
- [ ] E2E 스모크 테스트 (기획 → 이미지 → 캡션 → 포스팅 → 댓글)
- [ ] 테스트 계정 3일 드라이런
- [ ] commenter.py 실제 Instagram 댓글 추출 검증
- [ ] orchestrator.py 전체 사이클 통합 테스트

### 배포
- [ ] systemd 서비스 파일 생성 (ai-influencer.service)
- [ ] requirements.txt에 apscheduler 추가

### 개선 사항
- [ ] Anti-ban 워밍업 로직 (처음 21일 저빈도 운영)
- [ ] Graph API 인사이트 연동 (analytics.py)
- [ ] Gemini API 키 갱신 → 대규모 데이터 증강
- [ ] 학습 데이터 추가 수집 및 재학습
