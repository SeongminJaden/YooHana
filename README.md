# AI Instagram Influencer

QLoRA 파인튜닝 기반 가상 인스타그램 인플루언서 시스템. 가상 페르소나 "유하나"(24세 서울 거주 여대생)로 인스타그램 캡션 생성, 댓글 답글, 자유 대화가 가능한 소형 한국어 LLM을 직접 학습하여 운영한다.

## Overview

```
Instagram 크롤링 → 데이터 정제 → QLoRA 파인튜닝 → 텍스트 생성 → Instagram 포스팅
         ↑                                                          |
         └──────────── 순환 파이프라인 (키워드 자동 발견) ────────────┘
```

- Qwen2.5-1.5B-Instruct 기반 4-bit 양자화 모델
- RTX 3050 4GB VRAM 단일 GPU에서 학습/추론 모두 가능
- Playwright 브라우저 자동화로 Instagram 크롤링 및 포스팅
- 페르소나 일관성 유지를 위한 메모리 시스템 (PostMemory)

---

## Architecture

```
ai_Influencer/
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
│   │   ├── browser_crawler.py # Playwright 기반 Instagram 크롤링
│   │   ├── cleaner.py         # 텍스트 정제 (이모지, 해시태그, 멘션 처리)
│   │   ├── dataset_builder.py # HuggingFace Dataset 변환
│   │   ├── cycle_pipeline.py  # 순환 파이프라인 (크롤링→변환→키워드→학습)
│   │   └── persona_data_generator.py  # Gemini API 기반 페르소나 데이터 증강
│   │
│   ├── training/              # 모델 학습
│   │   ├── train_qlora.py     # QLoRA 파인튜닝 (Unsloth / PEFT+bitsandbytes)
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
│   │   ├── image_analyzer.py  # 크롤링 이미지 분석 → NanoBanana 프롬프트
│   │   └── image_processor.py # 리사이즈, 후처리 (Pillow)
│   │
│   ├── instagram/             # Instagram 클라이언트
│   │   ├── browser_poster.py  # Playwright 기반 포스팅
│   │   ├── commenter.py       # 댓글 모니터링 + 자동 답글
│   │   ├── auth.py            # 로그인, 세션 관리
│   │   └── analytics.py       # Graph API 인사이트
│   │
│   ├── planner/               # 콘텐츠 기획
│   │   ├── content_planner.py # 주간 콘텐츠 기획 자동화
│   │   └── topic_generator.py # 주제/해시태그 생성
│   │
│   ├── scheduler/             # 자동화
│   │   ├── orchestrator.py    # APScheduler 기반 메인 루프
│   │   └── task_queue.py      # 작업 우선순위 큐
│   │
│   └── utils/                 # 유틸리티
│       ├── logger.py          # loguru 기반 로깅
│       ├── rate_limiter.py    # API 호출 제한
│       └── error_handler.py   # 재시도, 에러 분류
│
├── scripts/                   # 실행 스크립트
│   ├── chat.py                # 터미널 대화 인터페이스
│   ├── train.py               # 학습 실행
│   ├── run_cycle.py           # 순환 파이프라인 실행
│   ├── crawl_instagram.py     # 데이터 수집
│   └── test_generation.py     # 생성 품질 테스트
│
├── data/
│   ├── raw/                   # 크롤링 원본 JSON
│   ├── training/              # 학습 JSONL (페르소나 캡션, 답글, 대화)
│   ├── processed/             # HuggingFace Dataset (Arrow 포맷)
│   └── memory/                # PostMemory 영속 저장소
│
├── models/
│   ├── adapter/               # LoRA 어댑터 체크포인트 (~37MB)
│   └── merged/                # (선택) 병합된 최종 모델
│
└── outputs/
    ├── images/                # 생성된 이미지
    └── logs/                  # 앱 로그
```

---

## Model Architecture

### Base Model

| 항목 | 상세 |
|------|------|
| 모델 | **Qwen2.5-1.5B-Instruct** (Alibaba) |
| 파라미터 | 1.5B (15억) |
| 아키텍처 | Transformer Decoder-only (Qwen2 아키텍처) |
| 레이어 | 28 Transformer blocks |
| Hidden size | 1,536 |
| Attention heads | 12 (GQA: 2 KV heads) |
| Vocab size | 151,665 (BPE tokenizer) |
| Context length | 32,768 토큰 (학습 시 512로 제한) |
| 지원 언어 | 영어, 중국어, **한국어** 포함 29개 언어 |

> 초기에 `kakaocorp/kanana-nano-2.1b-instruct` (한국어 특화)를 시도했으나 RTX 3050 4GB에서 OOM 발생하여 Qwen2.5-1.5B로 변경.

### Quantization

**NF4 (4-bit NormalFloat) + Double Quantization**

```yaml
load_in_4bit: true
bnb_4bit_quant_type: "nf4"        # NormalFloat 4-bit (정규분포 최적화)
bnb_4bit_use_double_quant: true   # 양자화 상수도 8-bit로 재양자화 → 추가 0.4GB 절약
bnb_4bit_compute_dtype: bfloat16  # 연산은 bf16 정밀도
```

| 상태 | 모델 크기 | VRAM 사용 |
|------|-----------|-----------|
| FP16 (원본) | ~3.0 GB | 3.5+ GB |
| **NF4 4-bit** | **~0.8 GB** | **~1.2 GB** (추론) |
| NF4 + QLoRA 학습 | ~0.8 GB + LoRA | **~2.8 GB** (학습) |

### LoRA Adapter

**QLoRA (Quantized Low-Rank Adaptation)** 적용:

```
LoRA rank (r): 16
LoRA alpha: 32 (scaling factor = alpha/r = 2.0)
LoRA dropout: 0.05
Target modules: q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj
Bias: none
Task type: CAUSAL_LM
```

| 항목 | 값 |
|------|-----|
| 전체 파라미터 | 1,543,714,304 (1.5B) |
| 학습 가능 파라미터 | ~7,077,888 (7M) |
| 학습 비율 | **0.46%** |
| 어댑터 크기 | **~37 MB** |

7개 Attention/MLP 모듈 모두에 LoRA를 적용하여 모델의 표현력을 최대한 활용하면서도 전체 파라미터의 0.46%만 학습한다.

---

## Training

### Training Data

| 데이터 소스 | 샘플 수 | 설명 |
|-------------|---------|------|
| 크롤링 캡션 | 377 | Instagram에서 수집한 한국어 라이프스타일 캡션 |
| 페르소나 캡션 v2 | 42 | 수동 작성 여대생 반말 캡션 |
| 페르소나 캡션 v3 | 60 | 12개 주제 카테고리 캡션 (카페, 패션, 음식 등) |
| 페르소나 답글 v1 | 30 | 댓글-답글 쌍 |
| 페르소나 답글 v2 | 80 | 9개 댓글 유형별 답글 (칭찬, 질문, 공감 등) |
| 페르소나 대화 v2 | 25 | 개인 Q&A (나이, 취미, MBTI 등) |
| 페르소나 대화 v3 | 52 | 확장 Q&A (추천, 가치관, 소통 등) |
| 기타 수동 데이터 | 15 | 초기 캡션 + 대화 |

**업샘플링 전략**: 페르소나 데이터를 **3배 업샘플링**하여 크롤링 데이터 대비 비중 확보

| 구분 | 원본 | 업샘플링 후 | 비중 |
|------|------|------------|------|
| 크롤링 데이터 | 377 | 377 | 29% |
| 페르소나 데이터 | 304 | **912** (x3) | **71%** |
| **합계** | 681 | **1,289** | 100% |

### Training Format

```
### Instruction:
{instruction}

### Response:
{output}
```

추론 시에도 동일한 포맷을 사용하여 학습-추론 불일치를 방지한다.

### Hyperparameters

```yaml
# Optimizer
optim: adamw_8bit             # 8-bit AdamW (메모리 절약)
learning_rate: 2e-4           # QLoRA 표준 학습률
lr_scheduler: cosine          # 코사인 감쇠 스케줄
warmup_steps: 1
weight_decay: 0.01
max_grad_norm: 0.3

# Batch
per_device_train_batch_size: 1
gradient_accumulation_steps: 16  # effective batch size = 16
num_train_epochs: 3

# Memory optimization
gradient_checkpointing: true  # 활성화 메모리 재계산 (VRAM 절약)
bf16: true                    # bfloat16 mixed precision
max_seq_length: 512           # 시퀀스 길이 제한

# Save
save_strategy: epoch
save_total_limit: 2
```

### Training Results

```
Epochs: 3
Total steps: 219
Training time: ~21분 (RTX 3050)
Final loss: 0.39 ~ 0.55
Token accuracy: ~90%
Speed: ~5.9 sec/step
Peak VRAM: ~2.8 GB / 4.0 GB
```

### OOM Fallback 전략

학습 스크립트는 자동 OOM 폴백을 지원한다:

```
1차 시도: base_model (Kanana 2.1B) + seq_len=512
     ↓ OOM
2차 시도: fallback_model (Qwen 1.5B) + seq_len=512
     ↓ OOM
3차 시도: fallback_model (Qwen 1.5B) + seq_len=256
```

---

## Inference Pipeline

### Text Generation Flow

```
사용자 입력 (주제/댓글/질문)
      │
      ▼
┌─────────────────────┐
│  Prompt Builder     │  "### Instruction:\n{입력}\n\n### Response:\n"
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Base Model (4-bit) │  Qwen2.5-1.5B-Instruct (NF4 양자화)
│  + LoRA Adapter     │  PeftModel.from_pretrained()
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Post-processing    │  CJK/영어/키릴 문자 누출 제거
│  _clean_output()    │  빈 괄호 정리, 공백 정규화
└─────────┬───────────┘
          │
          ▼
     생성된 텍스트
```

### Generation Parameters

```yaml
temperature: 0.7          # 창의성 vs 일관성 밸런스
top_p: 0.9                # nucleus sampling
top_k: 50                 # top-k filtering
repetition_penalty: 1.15  # 반복 억제
max_new_tokens: 256       # 캡션 최대 길이
```

### Post-processing (CJK Cleanup)

Qwen 모델의 다국어 특성으로 인한 비한국어 문자 누출을 자동 제거:

```python
# 제거 대상
- 중국어 (CJK Unified Ideographs: U+4E00-U+9FFF)
- 일본어 히라가나/가타카나 (U+3040-U+30FF)
- 키릴 문자 (U+0400-U+04FF)
- 허용 목록에 없는 영어 단어 (3글자 이상)

# 허용되는 영어
OOTD, GRWM, daily, cafe, coffee, style, selfie, Seoul, ENFP, MBTI, DM, ...
```

### Memory System (PostMemory)

게시글과 댓글을 JSON 파일로 영속 저장하여 컨텍스트 인식 생성:

```
data/memory/
├── posts.json       # 모든 게시글 기록 (캡션, 해시태그, 주제, 날짜)
└── comments.json    # 모든 댓글-답글 기록
```

- 캡션 생성 시 최근 5개 게시글을 컨텍스트로 제공 → 중복 방지
- 답글 생성 시 최근 댓글 이력 참조 → 일관된 정보 제공

---

## System Requirements

### Minimum (추론만)

| 항목 | 사양 |
|------|------|
| GPU | NVIDIA GPU 2GB+ VRAM (CUDA Compute 7.0+) |
| RAM | 8 GB |
| Storage | 10 GB (모델 캐시 포함) |
| Python | 3.10+ |
| CUDA | 11.8+ |

### Recommended (학습 + 추론)

| 항목 | 사양 | 비고 |
|------|------|------|
| **GPU** | **NVIDIA RTX 3050 4GB** 이상 | 현재 개발 환경 |
| RAM | 16 GB | 데이터 전처리 시 필요 |
| CPU | 4코어+ (AMD Ryzen 7 / Intel i5 이상) | 데이터 로딩 병목 |
| Storage | 20 GB+ | 모델 캐시 + 데이터 + 체크포인트 |
| Python | 3.10 ~ 3.12 | |
| CUDA | 12.1+ | bitsandbytes 호환 |
| OS | Linux (Ubuntu 22.04+) | Windows WSL2도 가능 |

### VRAM Usage Breakdown

```
[추론 시]
Base model (NF4 4-bit):    ~800 MB
LoRA adapter:               ~37 MB
KV cache + activations:    ~300 MB
──────────────────────────────────
Total:                   ~1,200 MB  ← 2GB GPU에서 가능

[학습 시]
Base model (NF4 4-bit):    ~800 MB
LoRA weights (r=16):       ~110 MB (FP16 학습)
Optimizer states (8-bit):  ~220 MB
Gradients + activations:   ~900 MB (gradient checkpointing 적용)
Batch (seq_len=512):       ~200 MB
──────────────────────────────────
Total:                   ~2,800 MB  ← 4GB GPU에서 가능
                                     (3GB GPU는 seq_len=256으로 가능)
```

### GPU Tier별 가이드

| GPU | VRAM | 추론 | 학습 (seq=512) | 학습 (seq=256) |
|-----|------|------|----------------|----------------|
| GTX 1650 | 4 GB | O | O | O |
| **RTX 3050** | **4 GB** | **O** | **O** | **O** |
| RTX 3060 | 12 GB | O | O (여유) | O |
| RTX 4060 | 8 GB | O | O (여유) | O |
| Tesla T4 | 16 GB | O | O (여유) | O |
| CPU only | - | X | X | X |

> 4-bit 양자화 + gradient checkpointing + 8-bit optimizer 조합으로 4GB VRAM에서도 1.5B 모델 학습이 가능하다. 더 큰 모델(7B+)은 최소 12GB VRAM 필요.

---

## Quick Start

### 1. 환경 설정

```bash
# 저장소 클론
git clone <repo-url> ai_Influencer
cd ai_Influencer

# 가상환경 생성
python3 -m venv venv
source venv/bin/activate

# 의존성 설치 (추론만)
pip install -r requirements.txt

# 학습까지 하려면
pip install -r requirements-train.txt

# Playwright 브라우저 설치 (크롤링/포스팅용)
playwright install chromium
```

### 2. 데이터 수집

```bash
# Instagram 크롤링 (로그인 필요 - .env에 계정 설정)
python3 scripts/crawl_instagram.py --headless --count 30

# 순환 파이프라인 (크롤링 → 데이터 변환 → 키워드 추출 → 학습)
python3 scripts/run_cycle.py --skip-crawl  # 크롤링 건너뛰고 기존 데이터로
```

### 3. 모델 학습

```bash
# QLoRA 파인튜닝 (RTX 3050에서 ~21분)
python3 scripts/train.py

# 학습 결과 확인
python3 scripts/test_generation.py
```

### 4. 대화 테스트

```bash
# 터미널에서 유하나와 대화
python3 scripts/chat.py
```

```
==================================================
  유하나와 대화하기
  /quit 또는 /q - 종료
  /clear - 대화 기록 초기화
  /history - 대화 기록 보기
==================================================

하나: 안녕! 나 하나야 ㅎㅎ 뭐 궁금한 거 있으면 편하게 물어봐! ✨

나: 취미가 뭐야?
하나: 카페 탐방이 제일 좋아 ☕ 새로운 카페 발견하면 진짜 기분 좋거든 ㅋㅋ
      그리고 사진 찍는 것도 좋아하고 요즘은 필라테스도 다녀!

나: 좋아하는 음식은?
하나: 파스타 진짜 좋아해! 특히 크림파스타 ㅎㅎ
      그리고 디저트도 빠질 수 없지 케이크 보면 그냥 못 지나쳐 🍰
```

### 5. Instagram 포스팅

```bash
# 테스트 이미지 생성
python3 scripts/create_test_image.py

# 드라이런 (실제 포스팅 안 함)
python3 scripts/test_posting.py --dry-run

# 실제 포스팅
python3 scripts/test_posting.py
```

---

## Tech Stack

| 분류 | 기술 | 용도 |
|------|------|------|
| Base Model | Qwen2.5-1.5B-Instruct | 한국어 텍스트 생성 |
| 양자화 | bitsandbytes (NF4) | 4-bit 모델 로딩 |
| 파인튜닝 | PEFT + QLoRA / TRL SFTTrainer | LoRA 어댑터 학습 |
| 데이터 | HuggingFace Datasets | 학습 데이터 관리 |
| 이미지 | Gemini API (google-genai) | AI 이미지 생성 |
| 브라우저 | Playwright | Instagram 크롤링/포스팅 |
| 스케줄링 | APScheduler | 자동화 루프 |
| 로깅 | Loguru | 구조화된 로깅 |
| 설정 | PyYAML + python-dotenv | 설정/환경변수 관리 |

---

## Development Environment

이 프로젝트는 다음 환경에서 개발 및 테스트되었다:

```
CPU: AMD Ryzen 7 5800H (8코어 16스레드)
GPU: NVIDIA GeForce RTX 3050 Laptop GPU (4GB GDDR6)
RAM: 16GB DDR4
OS:  Ubuntu Linux (kernel 6.8.0)
CUDA: 12.8
PyTorch: 2.10.0+cu128
Python: 3.10.12
```

---

## License

This project is for educational and research purposes.
