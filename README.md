<div align="center">

<img src="assets/profile.jpg" alt="유하나" width="280" style="border-radius: 50%;">

# YooHana (유하나)

**AI Instagram Influencer**

24살, 서울 사는 여대생. 카페 탐방과 사진 찍는 걸 좋아하는 가상 인플루언서.

QLoRA 파인튜닝 기반 소형 한국어 LLM이 만들어낸 페르소나로,
Instagram 캡션 생성, 댓글 답글, 자유 대화, 자동 포스팅까지 가능합니다.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.10-red.svg)](https://pytorch.org)
[![Model](https://img.shields.io/badge/Model-Qwen2.5--1.5B-green.svg)](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
[![GPU](https://img.shields.io/badge/GPU-RTX%203050%204GB-yellow.svg)](#system-requirements)

</div>

---

## About YooHana

| | |
|---|---|
| **이름** | 유하나 (Yoo Hana) |
| **나이** | 24세 |
| **거주지** | 서울 |
| **직업** | 디지털 아티스트 & 라이프스타일 크리에이터 |
| **MBTI** | ENFP |
| **관심사** | 카페 탐방, 패션, 필라테스, 사진, 요리, 인테리어 |
| **좋아하는 브랜드** | 자라, 코스, 마뗑킴 |
| **자주 가는 곳** | 성수동, 한남동, 한강 |
| **말투** | 친근한 반말, ㅋㅋ ㅎㅎ, 이모지 적절히 사용 |

```
나: 취미가 뭐야?
하나: 카페 탐방이 제일 좋아 ☕ 새로운 카페 발견하면 진짜 기분 좋거든 ㅋㅋ
      그리고 사진 찍는 것도 좋아하고 요즘은 필라테스도 다녀!

나: 좋아하는 음식은?
하나: 파스타 진짜 좋아해! 특히 크림파스타 ㅎㅎ
      그리고 디저트도 빠질 수 없지 케이크 보면 그냥 못 지나쳐 🍰
```

---

## Overview

```
데이터 수집 → 데이터 정제 → QLoRA 파인튜닝 → 텍스트 생성 → Instagram 포스팅
     ↑                                                          |
     └──────────── 순환 파이프라인 (키워드 자동 발견) ────────────┘
```

- **Qwen2.5-1.5B-Instruct** 기반 4-bit 양자화 모델
- **RTX 3050 4GB** VRAM 단일 GPU에서 학습/추론 모두 가능
- **Playwright** 브라우저 자동화로 Instagram 데이터 수집 및 포스팅
- **PostMemory** 기반 컨텍스트 인식 생성 (중복 방지)
- **Flask 웹 UI** — 대화, 게시물 작성/관리, Instagram 동기화
- **APScheduler** 기반 자동화 (포스팅, 댓글 모니터링, 콘텐츠 기획)

---

## Web Management UI

왼쪽 패널에 Instagram 스타일 피드 그리드, 오른쪽에 대화/게시물 작성 탭.

```bash
python3 scripts/run_web.py
# http://localhost:5000
```

**기능:**
- 유하나와 실시간 대화 (대화 맥락 유지)
- 이미지 직접 업로드 또는 AI(Gemini) 생성
- 캡션/해시태그 AI 자동 생성
- 저장 후 Instagram 게시
- 실제 Instagram 프로필 게시물 동기화

---

## Architecture

```
YooHana/
├── config/
│   ├── settings.yaml          # 모델, 생성, Instagram, 스케줄 등 전역 설정
│   ├── persona.yaml           # 캐릭터 정의 (외모, 성격, 말투, 금지 주제)
│   └── schedule.yaml          # 포스팅 스케줄 규칙
│
├── src/
│   ├── persona/               # 페르소나 관리
│   │   ├── character.py       # Persona 클래스 - persona.yaml 로드, 시스템 프롬프트 생성
│   │   └── consistency.py     # 생성 텍스트 검증 (톤, 이모지, 금지 주제)
│   │
│   ├── data_pipeline/         # 데이터 수집 및 전처리
│   │   ├── browser_crawler.py # Playwright 기반 Instagram 수집
│   │   ├── cleaner.py         # 텍스트 정제 (이모지, 해시태그, 멘션 처리)
│   │   ├── dataset_builder.py # HuggingFace Dataset 변환
│   │   ├── cycle_pipeline.py  # 순환 파이프라인 (수집→변환→키워드→학습)
│   │   └── persona_data_generator.py  # Gemini API 기반 페르소나 데이터 증강
│   │
│   ├── training/              # 모델 학습
│   │   ├── train_qlora.py     # QLoRA 파인튜닝 (PEFT+bitsandbytes)
│   │   ├── merge_adapter.py   # LoRA 어댑터 병합
│   │   └── evaluate.py        # 모델 평가
│   │
│   ├── inference/             # 추론 엔진
│   │   ├── text_generator.py  # 4-bit 모델 로드 + 텍스트 생성 + CJK 클린업
│   │   ├── prompt_builder.py  # 페르소나 시스템 프롬프트 구성
│   │   └── memory.py          # PostMemory - 게시글/댓글 영속 기억 시스템
│   │
│   ├── image_gen/             # 이미지 생성
│   │   ├── gemini_client.py   # Gemini API 래퍼
│   │   ├── prompt_composer.py # 이미지 프롬프트 조합 (외모 + 장면 + 스타일)
│   │   ├── image_analyzer.py  # 수집 이미지 분석 → NanoBanana 프롬프트
│   │   └── image_processor.py # 리사이즈, 후처리 (Pillow)
│   │
│   ├── instagram/             # Instagram 클라이언트
│   │   ├── browser_poster.py  # Playwright 기반 포스팅 + 프로필 스크래핑
│   │   ├── commenter.py       # 댓글 모니터링 + 자동 답글
│   │   ├── auth.py            # 로그인, 세션 관리
│   │   └── analytics.py       # Graph API 인사이트
│   │
│   ├── web/                   # 웹 관리 UI
│   │   ├── app.py             # Flask 앱 (채팅, 게시물 CRUD, Instagram 연동 API)
│   │   ├── templates/         # HTML 템플릿
│   │   └── static/            # CSS, JavaScript
│   │
│   ├── planner/               # 콘텐츠 기획
│   │   ├── content_planner.py # 주간 콘텐츠 기획 자동화
│   │   └── topic_generator.py # 주제/해시태그 생성
│   │
│   ├── scheduler/             # 자동화
│   │   ├── orchestrator.py    # APScheduler 기반 메인 루프 + Anti-ban 워밍업
│   │   └── task_queue.py      # 작업 우선순위 큐
│   │
│   └── utils/                 # 유틸리티
│       ├── logger.py          # loguru 기반 로깅
│       ├── rate_limiter.py    # API 호출 제한
│       └── error_handler.py   # 재시도, 에러 분류
│
├── scripts/                   # 실행 스크립트
│   ├── run_web.py             # 웹 UI 서버 실행
│   ├── chat.py                # 터미널 대화 인터페이스
│   ├── run_bot.py             # 봇 실행 (자동화)
│   ├── train.py               # 학습 실행
│   └── test_e2e.py            # E2E 스모크 테스트
│
├── models/
│   ├── adapter/               # LoRA 어댑터 체크포인트 (~37MB)
│   └── merged/                # (선택) 병합된 최종 모델
│
├── assets/                    # 프로필 이미지 등 정적 자산
└── outputs/
    ├── posts/                 # 게시물 데이터 + 이미지
    ├── images/                # 생성된 이미지
    └── logs/                  # 앱 로그
```

---

## Model

### Base Model

| 항목 | 상세 |
|------|------|
| 모델 | **Qwen2.5-1.5B-Instruct** (Alibaba) |
| 파라미터 | 1.5B (15억) |
| 양자화 | NF4 4-bit + Double Quantization |
| LoRA | rank=16, alpha=32, 7개 모듈 (q/k/v/o/gate/up/down_proj) |
| 학습 파라미터 | 7M / 1.5B (**0.46%**) |
| 어댑터 크기 | **~37 MB** |

### Training

| 항목 | 값 |
|------|-----|
| 학습 데이터 | 1,289 샘플 (수집 377 + 페르소나 304 x3 업샘플링) |
| Epochs | 3 |
| 학습 시간 | ~21분 (RTX 3050) |
| Final loss | 0.39 ~ 0.55 |
| Token accuracy | ~90% |
| Peak VRAM | ~2.8 GB / 4.0 GB |

### Generation

```yaml
temperature: 0.7          # 창의성 vs 일관성 밸런스
top_p: 0.9                # nucleus sampling
top_k: 50                 # top-k filtering
repetition_penalty: 1.15  # 반복 억제
```

후처리로 중국어/일본어/키릴 문자 누출 자동 제거, 허용 영단어 화이트리스트 적용.

---

## Quick Start

### 1. 환경 설정

```bash
git clone https://github.com/SeongminJaden/YooHana.git
cd YooHana

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt          # 추론
pip install -r requirements-train.txt    # 학습까지
playwright install chromium              # 브라우저 자동화
```

### 2. 설정

```bash
# .env 파일에 계정 정보 설정
cp .env.example .env
# INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, GEMINI_API_KEY 입력
```

### 3. 학습

```bash
python3 scripts/train.py                 # QLoRA 파인튜닝 (~21분)
python3 scripts/test_generation.py       # 생성 품질 확인
```

### 4. 실행

```bash
python3 scripts/chat.py                  # 터미널 대화
python3 scripts/run_web.py               # 웹 UI (http://localhost:5000)
python3 scripts/run_bot.py               # 자동화 봇
```

---

## System Requirements

| 항목 | 최소 (추론) | 권장 (학습+추론) |
|------|-------------|-----------------|
| GPU | NVIDIA 2GB+ VRAM | **RTX 3050 4GB+** |
| RAM | 8 GB | 16 GB |
| Python | 3.10+ | 3.10 ~ 3.12 |
| CUDA | 11.8+ | 12.1+ |
| OS | Linux / WSL2 | Ubuntu 22.04+ |

```
[VRAM 사용량]
추론: ~1.2 GB (2GB GPU에서 가능)
학습: ~2.8 GB (4GB GPU에서 가능, gradient checkpointing)
```

---

## Tech Stack

| 분류 | 기술 | 용도 |
|------|------|------|
| Base Model | Qwen2.5-1.5B-Instruct | 한국어 텍스트 생성 |
| 양자화 | bitsandbytes (NF4) | 4-bit 모델 로딩 |
| 파인튜닝 | PEFT + QLoRA / TRL SFTTrainer | LoRA 어댑터 학습 |
| 이미지 생성 | Gemini API (google-genai) | AI 이미지 생성 |
| 브라우저 | Playwright | Instagram 수집/포스팅 |
| 웹 UI | Flask | 관리 대시보드 |
| 스케줄링 | APScheduler | 자동화 루프 |
| 로깅 | Loguru | 구조화된 로깅 |

---

## Roadmap & Improvements

### Known Issues
- [ ] 대화 시 맥락 이탈 — 소형 모델(1.5B) 한계로 긴 대화에서 주제 벗어남 가능
- [ ] 이미지 캐릭터 일관성 — Gemini 생성 이미지 간 얼굴/스타일 편차
- [ ] Instagram 프로필 스크래핑 — headless 모드에서 그리드 로딩 불완전 가능

### Short-term
- [ ] 학습 데이터 확충 (현재 1,289 → 목표 5,000+ 샘플)
- [ ] Gemini API 키 갱신 후 대규모 페르소나 데이터 증강
- [ ] 테스트 계정 3일 드라이런 검증
- [ ] Graph API 인사이트 연동 (좋아요, 도달, 팔로워 추이)
- [ ] 웹 UI에서 게시물 캡션/해시태그 편집 기능

### Mid-term
- [ ] 더 큰 모델(3B~7B) 실험 — 대화 맥락 유지력 개선
- [ ] RAG (Retrieval-Augmented Generation) — 외부 지식 활용
- [ ] 이미지 레퍼런스 시스템 — 캐릭터 일관성 향상 (LoRA 이미지 모델)
- [ ] 스토리/릴스 자동 생성
- [ ] 팔로워 분석 기반 최적 포스팅 시간 자동 조정

### Long-term
- [ ] 멀티 페르소나 지원 — 여러 캐릭터를 하나의 시스템으로 관리
- [ ] 실시간 트렌드 반영 — 인기 해시태그/주제 자동 탐지
- [ ] DM 자동 응답
- [ ] 다국어 지원 (영어, 일본어)
- [ ] 모바일 관리 앱

---

## Development Environment

```
CPU:     AMD Ryzen 7 5800H (8-core 16-thread)
GPU:     NVIDIA GeForce RTX 3050 Laptop (4GB GDDR6)
RAM:     16GB DDR4
OS:      Ubuntu Linux (kernel 6.8.0)
CUDA:    12.8
PyTorch: 2.10.0+cu128
Python:  3.10.12
```

---

## License

This project is for educational and research purposes.
