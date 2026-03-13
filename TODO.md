# AI Influencer - TODO

## 완료
- [x] 프로젝트 구조 생성 (config, src, scripts, data 등)
- [x] Playwright 기반 Instagram 브라우저 크롤러 구현
  - [x] 로그인/세션 관리
  - [x] 해시태그/검색/유저/탐색 크롤링
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
  - [x] Qwen2.5-1.5B-Instruct 기반 첫 학습 성공 (22샘플, loss 3.4→2.6)
- [x] 데이터 정제 파이프라인 (cleaner.py, dataset_builder.py)
- [x] 순환 파이프라인 구현 (cycle_pipeline.py)
  - [x] 크롤링 데이터 → 학습 JSONL 자동 변환
  - [x] 한국어 키워드/해시태그 자동 추출
  - [x] NFD→NFC 유니코드 정규화 처리
  - [x] 발견된 키워드 기반 크롤링 타겟 자동 확장
  - [x] 순환 상태 관리 (cycle_state.json)

## 진행중
- [ ] 순환 파이프라인 통합 테스트 (run_cycle.py full)
- [ ] 크롤링 데이터 확장 (현재 166 게시글 → 목표 2,000+)

## 남은 작업

### 데이터 & 학습
- [ ] 수동 학습 데이터 보강 (캡션 300개, 댓글-답글 200개)
- [ ] Gemini API로 합성 데이터 생성 (~500개)
- [ ] 확장된 데이터셋으로 모델 재학습
- [ ] 모델 평가 (perplexity, 샘플 생성, 페르소나 일관성)
- [ ] 어댑터 병합 (merge_adapter.py)

### 추론 엔진
- [ ] text_generator.py - 파인튜닝 모델 로드 + 캡션/답글 생성
- [ ] prompt_builder.py - 페르소나 시스템 프롬프트 구성

### 이미지 생성
- [ ] Gemini API 연동 (gemini_client.py)
- [ ] 캐릭터 레퍼런스 이미지 생성 (5-8장)
- [ ] 이미지 프롬프트 조합 (prompt_composer.py)
- [ ] 후처리 (1080x1350 피드 / 1080x1920 스토리)

### Instagram 자동화
- [ ] 사진/스토리 업로드 (poster.py)
- [ ] 댓글 모니터링 + 자동 답글 (commenter.py)
- [ ] Graph API 인사이트 (analytics.py)
- [ ] Anti-ban: 랜덤 딜레이, 시간당 제한, 워밍업

### 콘텐츠 플래너
- [ ] 주간 콘텐츠 기획 자동 생성 (content_planner.py)
- [ ] 주제/해시태그 생성 (topic_generator.py)
- [ ] 시즌/한국 기념일 반영

### 스케줄러
- [ ] APScheduler 기반 자동화 루프 (orchestrator.py)
- [ ] systemd 서비스 등록

### 기타
- [ ] 에러 핸들링 강화 (rate_limiter.py, error_handler.py)
- [ ] E2E 스모크 테스트 (기획 → 이미지 → 캡션 → 포스팅)
- [ ] 테스트 계정 3일 드라이런
