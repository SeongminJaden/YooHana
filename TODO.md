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
- [x] 순환 파이프라인 통합 테스트 (91샘플, train81/val10)

- [x] 크롤링 데이터 확장 (395 게시글, full 모드)
- [x] 순환 파이프라인 2차 실행 (377 크롤링 + 15 수동 = 392 샘플, train352/val40)
- [x] QLoRA 재학습 (Qwen2.5-1.5B, loss 3.8→1.27, 7분)
- [x] LLM 캡션/해시태그 생성
  - [x] text_generator.py (base model + LoRA adapter 로드)
  - [x] prompt_builder.py (페르소나 시스템 프롬프트)
  - [x] test_generation.py (캡션 4개 + 댓글 답글 3개 생성 테스트)
  - [x] 생성 파이프라인 동작 확인 (품질은 데이터 양/질 개선 필요)
- [x] 이미지 분석 + 나노바나나 프롬프트 설계
  - [x] image_analyzer.py (표정, 옷, 포즈, 배경, 조명, 분위기 분석)
  - [x] 나노바나나 프롬프트 포맷 설계 (일러스트 캐릭터 + 실사 배경 합성)
  - [x] prompt_composer.py 확장 (compose_composite_prompt)
  - [x] 10개 이미지 분석 테스트 완료 (※ API 미보유로 생성 테스트 안함)
- [x] Instagram 브라우저 포스팅
  - [x] create_test_image.py (Pillow 1080x1350 테스트 이미지)
  - [x] browser_poster.py (Playwright 기반 업로드, 세션 재사용)
  - [x] 실제 테스트 포스팅 성공 ("사진이 게시되었습니다" 확인)

## 남은 작업 (이후)

### Instagram 자동화
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
