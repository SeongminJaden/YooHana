"""순환 파이프라인: 수집 → 학습 데이터 변환 → 키워드 추출 → 재수집.

수집한 게시글에서 캡션을 학습 JSONL로 변환하고,
새로운 해시태그/키워드를 자동으로 발견하여 다음 수집에 활용한다.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.data_pipeline.cleaner import DataCleaner
from src.data_pipeline.dataset_builder import DatasetBuilder
from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAW_DIR = _PROJECT_ROOT / "data" / "raw"
_TRAINING_DIR = _PROJECT_ROOT / "data" / "training"
_PROCESSED_DIR = _PROJECT_ROOT / "data" / "processed"
_CYCLE_STATE_PATH = _PROJECT_ROOT / "data" / "cycle_state.json"
_PERSONA_PATH = _PROJECT_ROOT / "config" / "persona.yaml"


# ── 한국어 불용어 (학습/수집에 불필요한 일반 단어) ──────────────
_STOPWORDS = {
    "그리고", "하지만", "그래서", "때문에", "이렇게", "저렇게", "그렇게",
    "너무", "정말", "진짜", "완전", "진심", "댓글", "좋아요", "팔로우",
    "모두", "보기", "사진", "동영상", "게시글", "게시물", "프로필",
    "이거", "저거", "그거", "여기", "저기", "거기", "이건", "저건",
    "오늘", "내일", "어제", "지금", "나는", "우리", "저는", "제가",
    "하는", "하고", "해서", "했는", "합니다", "합니당", "입니다",
    "있는", "없는", "같은", "이런", "저런", "한번", "아직",
    "광고", "협찬", "제공", "리뷰", "이벤트",
}


def _load_persona_themes() -> list[str]:
    """persona.yaml에서 콘텐츠 테마 키워드를 추출."""
    if not _PERSONA_PATH.exists():
        return []
    with open(_PERSONA_PATH, "r", encoding="utf-8") as f:
        persona = yaml.safe_load(f)

    keywords: list[str] = []
    themes = persona.get("content_themes", {})
    for category in ("primary", "secondary"):
        for theme in themes.get(category, []):
            # "일상 라이프스타일 (카페, 산책, 일상)" → 개별 단어 추출
            words = re.findall(r"[가-힣]{2,}", theme)
            keywords.extend(words)

    seasonal = themes.get("seasonal", {})
    for season_items in seasonal.values():
        if isinstance(season_items, list):
            for item in season_items:
                words = re.findall(r"[가-힣]{2,}", item)
                keywords.extend(words)

    return list(set(keywords))


# ══════════════════════════════════════════════════════════════════
# 1. 수집 데이터 → 학습 JSONL 변환
# ══════════════════════════════════════════════════════════════════


def _derive_instruction(caption: str, source: str, media_type: str) -> str:
    """캡션 내용과 출처를 기반으로 instruction 생성."""
    # 캡션에서 핵심 주제어 추출 (NFC 정규화 보장)
    normalized = unicodedata.normalize("NFC", caption)
    korean_words = re.findall(r"[가-힣]{2,}", normalized)
    topic_words = [w for w in korean_words if w not in _STOPWORDS and len(w) >= 2]

    # 미디어 타입 힌트
    media_hint = ""
    if media_type == "video":
        media_hint = "릴스/영상"
    elif media_type == "carousel":
        media_hint = "캐러셀 게시물"
    else:
        media_hint = "사진 게시물"

    # 주제어가 있으면 구체적 instruction 생성
    if topic_words:
        topic = ", ".join(topic_words[:3])
        templates = [
            f"{topic}에 대한 인스타그램 {media_hint} 캡션을 작성해줘",
            f"{topic} 관련 인스타 캡션을 써줘",
            f"인스타그램에 {topic} {media_hint}을 올릴 때 어울리는 캡션을 작성해줘",
        ]
        # 해시 기반으로 템플릿 선택 (결정적이지만 다양하게)
        idx = hash(caption) % len(templates)
        return templates[idx]

    # 주제어 없으면 일반적 instruction
    return f"인스타그램 {media_hint}에 어울리는 감성 캡션을 작성해줘"


def convert_crawled_to_training(
    raw_dir: Path = _RAW_DIR,
    output_path: Path | None = None,
    min_caption_len: int = 10,
    max_caption_len: int = 500,
) -> tuple[Path, int]:
    """수집된 raw JSON → instruction-output JSONL 변환.

    Returns
    -------
    tuple[Path, int]
        (출력 JSONL 경로, 변환된 샘플 수)
    """
    if output_path is None:
        output_path = _TRAINING_DIR / "crawled_captions.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cleaner = DataCleaner()
    json_files = sorted(raw_dir.glob("*.json"))

    if not json_files:
        logger.warning("raw 디렉토리에 JSON 파일 없음: {}", raw_dir)
        return output_path, 0

    seen_captions: set[str] = set()
    records: list[dict[str, str]] = []

    # 기존 JSONL이 있으면 로드하여 중복 방지
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    seen_captions.add(rec.get("output", ""))
                    records.append(rec)
        logger.info("기존 학습 데이터 {} 개 로드", len(records))

    new_count = 0
    for jf in json_files:
        with jf.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            continue

        # 소스 정보 (파일명에서 추출)
        source = jf.stem  # e.g., "hashtag_카페스타그램_20260313_205526"

        for post in data:
            caption = post.get("caption", "").strip()
            if not caption or len(caption) < min_caption_len:
                continue
            if len(caption) > max_caption_len:
                continue

            # NFD → NFC 정규화 (macOS/Instagram 수집 데이터)
            caption = unicodedata.normalize("NFC", caption)

            # 텍스트 정제
            cleaned = cleaner.clean_caption(caption)
            if len(cleaned) < min_caption_len:
                continue

            # 중복 체크
            if cleaned in seen_captions:
                continue
            seen_captions.add(cleaned)

            # media type 결정
            media_type = post.get("media_type", "photo")
            carousel_count = post.get("carousel_count", 1)
            if carousel_count > 1:
                media_type = "carousel"

            instruction = _derive_instruction(
                caption, source, media_type
            )

            records.append({
                "instruction": instruction,
                "output": cleaned,
                "source": source,
                "user": post.get("user", ""),
                "media_type": media_type,
            })
            new_count += 1

    # 저장 (전체)
    with output_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 플랫폼별 분리 저장
    ig_records = [r for r in records if not r.get("source", "").startswith("threads")]
    th_records = [r for r in records if r.get("source", "").startswith("threads")]

    ig_path = _TRAINING_DIR / "instagram_captions.jsonl"
    th_path = _TRAINING_DIR / "threads_captions.jsonl"

    with ig_path.open("w", encoding="utf-8") as f:
        for rec in ig_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with th_path.open("w", encoding="utf-8") as f:
        for rec in th_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info(
        "학습 데이터 변환 완료: 신규 {} + 기존 {} = 총 {} 샘플 (IG={}, Threads={}) → {}",
        new_count, len(records) - new_count, len(records),
        len(ig_records), len(th_records), output_path,
    )
    return output_path, len(records)


# ══════════════════════════════════════════════════════════════════
# 2. 키워드/해시태그 추출
# ══════════════════════════════════════════════════════════════════


def extract_keywords_from_crawled(
    raw_dir: Path = _RAW_DIR,
    top_n: int = 30,
) -> dict[str, Any]:
    """수집 데이터에서 트렌딩 키워드와 해시태그를 추출.

    Returns
    -------
    dict
        {
            "hashtags": [("#카페", count), ...],
            "keywords": [("브런치", count), ...],
            "bigrams": [("서울 카페", count), ...],
            "potential_targets": ["새해시태그1", ...],
        }
    """
    persona_themes = _load_persona_themes()

    all_hashtags: list[str] = []
    all_words: list[str] = []
    all_bigrams: list[str] = []

    json_files = sorted(raw_dir.glob("*.json"))
    for jf in json_files:
        with jf.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            continue

        for post in data:
            caption = post.get("caption", "")
            if not caption:
                continue

            # NFD → NFC 정규화
            caption = unicodedata.normalize("NFC", caption)

            # 해시태그 추출
            hashtags = re.findall(r"#([가-힣\w]{2,})", caption)
            all_hashtags.extend(hashtags)

            # 한국어 단어 추출 (2글자 이상)
            words = re.findall(r"[가-힣]{2,}", caption)
            filtered = [w for w in words if w not in _STOPWORDS and len(w) >= 2]
            all_words.extend(filtered)

            # 바이그램 (연속 2단어 조합)
            for i in range(len(filtered) - 1):
                bigram = f"{filtered[i]} {filtered[i+1]}"
                all_bigrams.append(bigram)

    hashtag_counts = Counter(all_hashtags).most_common(top_n)
    word_counts = Counter(all_words).most_common(top_n)
    bigram_counts = Counter(all_bigrams).most_common(top_n)

    # 페르소나 테마와 관련된 새로운 수집 대상 생성
    potential_targets = _generate_new_targets(
        hashtag_counts, word_counts, bigram_counts, persona_themes
    )

    result = {
        "hashtags": hashtag_counts,
        "keywords": word_counts,
        "bigrams": bigram_counts,
        "potential_targets": potential_targets,
        "extracted_at": datetime.now().isoformat(),
    }

    logger.info(
        "키워드 추출: 해시태그 {}종, 키워드 {}종, 바이그램 {}종, 신규 타겟 {}개",
        len(hashtag_counts), len(word_counts), len(bigram_counts),
        len(potential_targets),
    )

    return result


def _generate_new_targets(
    hashtag_counts: list[tuple[str, int]],
    word_counts: list[tuple[str, int]],
    bigram_counts: list[tuple[str, int]],
    persona_themes: list[str],
) -> list[dict[str, str]]:
    """추출된 키워드를 기반으로 새 수집 대상 생성.

    Returns
    -------
    list[dict]
        [{"type": "hashtag"|"search", "value": "..."}, ...]
    """
    # 기존 수집 대상 (crawl_instagram.py에서 하드코딩된 것)
    existing_hashtags = {
        "일상스타그램", "카페스타그램", "데일리룩", "서울카페",
        "오오티디", "감성스타그램", "맛집스타그램", "봄코디",
        "패션스타그램", "셀스타그램", "코디추천", "서울맛집",
        "한강", "피크닉",
    }
    existing_searches = {
        "일상 브이로그", "서울 카페 추천", "봄 데일리룩",
        "한국 패션 코디", "감성 사진", "서울 핫플레이스",
    }

    # 페르소나 관련 키워드 세트
    theme_set = set(persona_themes)

    new_targets: list[dict[str, str]] = []

    # 1. 빈도 높은 해시태그 중 기존에 없는 것 → 새 해시태그 타겟
    for tag, count in hashtag_counts:
        if count >= 2 and tag not in existing_hashtags:
            # 페르소나와 관련 있는지 체크 (2글자 이상의 한국어)
            tag_words = set(re.findall(r"[가-힣]{2,}", tag))
            if tag_words & theme_set or len(tag) >= 4:
                new_targets.append({"type": "hashtag", "value": tag})

    # 2. 빈도 높은 바이그램 → 새 검색 키워드
    for bigram, count in bigram_counts:
        if count >= 2 and bigram not in existing_searches:
            words = bigram.split()
            # 적어도 하나의 단어가 페르소나 테마와 관련
            if any(w in theme_set for w in words) or count >= 3:
                new_targets.append({"type": "search", "value": bigram})

    # 3. 고빈도 단어 + 페르소나 키워드 조합
    high_freq_words = [w for w, c in word_counts if c >= 3 and w in theme_set]
    for w in high_freq_words[:5]:
        combo = f"{w}스타그램"
        if combo not in existing_hashtags and not any(
            t["value"] == combo for t in new_targets
        ):
            new_targets.append({"type": "hashtag", "value": combo})

    # 중복 제거
    seen = set()
    unique: list[dict[str, str]] = []
    for t in new_targets:
        key = f"{t['type']}:{t['value']}"
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique[:20]  # 최대 20개


# ══════════════════════════════════════════════════════════════════
# 3. HuggingFace Dataset 빌드
# ══════════════════════════════════════════════════════════════════


def build_training_dataset(
    persona_name: str = "유하나",
    persona_upsample: int = 3,
) -> Path:
    """모든 학습 JSONL을 병합하여 HuggingFace Dataset 생성.

    data/training/ 아래의 모든 JSONL을 읽어 하나의 Dataset으로 합친다.
    페르소나 데이터는 ``persona_upsample`` 배로 업샘플링하여
    수집 데이터 대비 비중을 높인다.

    Parameters
    ----------
    persona_name : str
        페르소나 이름
    persona_upsample : int
        페르소나 데이터 반복 횟수 (기본 3배)

    Returns
    -------
    Path
        저장된 dataset 경로
    """
    builder = DatasetBuilder()
    crawled_datasets = []
    persona_datasets = []

    # ── 수집 데이터 (업샘플링 안 함) ──
    crawled_path = _TRAINING_DIR / "crawled_captions.jsonl"
    if crawled_path.exists():
        ds = builder.build_caption_dataset(str(crawled_path), persona_name)
        crawled_datasets.append(ds)
        logger.info("수집 캡션 데이터셋: {} 샘플", len(ds))

    # ── 페르소나 데이터 (업샘플링 대상) ──
    persona_files = [
        ("captions.jsonl", "수동 캡션"),
        ("persona_dialogues.jsonl", "페르소나 대화"),
        ("persona_captions_v2.jsonl", "페르소나 캡션 v2"),
        ("persona_captions_v3.jsonl", "페르소나 캡션 v3"),
        ("persona_replies.jsonl", "페르소나 답글"),
        ("persona_replies_v2.jsonl", "페르소나 답글 v2"),
        ("persona_dialogues_v2.jsonl", "페르소나 대화 v2"),
        ("persona_dialogues_v3.jsonl", "페르소나 대화 v3"),
        ("persona_style_data.jsonl", "Gemini 생성 페르소나"),
    ]

    for filename, label in persona_files:
        path = _TRAINING_DIR / filename
        if path.exists():
            ds = builder.build_caption_dataset(str(path), persona_name)
            persona_datasets.append(ds)
            logger.info("{} 데이터셋: {} 샘플", label, len(ds))

    if not crawled_datasets and not persona_datasets:
        raise FileNotFoundError(
            f"학습 데이터가 없습니다. {_TRAINING_DIR}에 JSONL 파일을 생성하세요."
        )

    # ── 페르소나 데이터 업샘플링 ──
    datasets_to_merge = list(crawled_datasets)
    for _ in range(persona_upsample):
        datasets_to_merge.extend(persona_datasets)

    crawled_total = sum(len(d) for d in crawled_datasets)
    persona_total = sum(len(d) for d in persona_datasets) * persona_upsample
    logger.info(
        "데이터 비율: 수집 {} vs 페르소나 {} ({}배 업샘플링)",
        crawled_total, persona_total, persona_upsample,
    )

    # 병합 및 분할
    merged = builder.merge_datasets(datasets_to_merge)
    split = builder.split_train_val(merged, val_ratio=0.1)
    save_path = builder.save(split, "final_dataset")

    logger.info(
        "최종 데이터셋: train {} / val {} → {}",
        len(split["train"]), len(split["validation"]), save_path,
    )
    return save_path


def build_platform_datasets(
    persona_name: str = "유하나",
    persona_upsample: int = 3,
) -> dict[str, Path]:
    """플랫폼별(Instagram/Threads) 학습 데이터셋을 각각 빌드.

    Returns
    -------
    dict[str, Path]
        {"instagram": Path, "threads": Path}
    """
    builder = DatasetBuilder()
    result = {}

    # ── 페르소나 데이터 (양쪽 공통) ──
    persona_datasets = []
    persona_files = [
        ("captions.jsonl", "수동 캡션"),
        ("persona_dialogues.jsonl", "페르소나 대화"),
        ("persona_captions_v2.jsonl", "페르소나 캡션 v2"),
        ("persona_captions_v3.jsonl", "페르소나 캡션 v3"),
        ("persona_replies.jsonl", "페르소나 답글"),
        ("persona_replies_v2.jsonl", "페르소나 답글 v2"),
        ("persona_dialogues_v2.jsonl", "페르소나 대화 v2"),
        ("persona_dialogues_v3.jsonl", "페르소나 대화 v3"),
        ("persona_style_data.jsonl", "Gemini 생성 페르소나"),
    ]
    for filename, label in persona_files:
        path = _TRAINING_DIR / filename
        if path.exists():
            ds = builder.build_caption_dataset(str(path), persona_name)
            persona_datasets.append(ds)

    # ── Instagram 데이터셋 ──
    ig_path = _TRAINING_DIR / "instagram_captions.jsonl"
    if ig_path.exists():
        ig_ds = builder.build_caption_dataset(str(ig_path), persona_name)
        datasets = [ig_ds]
        for _ in range(persona_upsample):
            datasets.extend(persona_datasets)
        merged = builder.merge_datasets(datasets)
        split = builder.split_train_val(merged, val_ratio=0.1)
        save_path = builder.save(split, "instagram_dataset")
        result["instagram"] = save_path
        logger.info(
            "Instagram 데이터셋: train {} / val {} → {}",
            len(split["train"]), len(split["validation"]), save_path,
        )

    # ── Threads 데이터셋 ──
    th_path = _TRAINING_DIR / "threads_captions.jsonl"
    if th_path.exists():
        th_ds = builder.build_caption_dataset(str(th_path), persona_name)
        datasets = [th_ds]
        for _ in range(persona_upsample):
            datasets.extend(persona_datasets)
        merged = builder.merge_datasets(datasets)
        split = builder.split_train_val(merged, val_ratio=0.1)
        save_path = builder.save(split, "threads_dataset")
        result["threads"] = save_path
        logger.info(
            "Threads 데이터셋: train {} / val {} → {}",
            len(split["train"]), len(split["validation"]), save_path,
        )

    return result


# ══════════════════════════════════════════════════════════════════
# 4. 순환 상태 관리
# ══════════════════════════════════════════════════════════════════


def load_cycle_state() -> dict[str, Any]:
    """순환 파이프라인 상태 로드."""
    if _CYCLE_STATE_PATH.exists():
        with _CYCLE_STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "cycle_count": 0,
        "total_samples": 0,
        "discovered_hashtags": [],
        "discovered_searches": [],
        "history": [],
    }


def save_cycle_state(state: dict[str, Any]) -> None:
    """순환 파이프라인 상태 저장."""
    _CYCLE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _CYCLE_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    logger.info("순환 상태 저장: {}", _CYCLE_STATE_PATH)


def update_crawl_targets(
    keyword_result: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """키워드 추출 결과를 기반으로 수집 대상 업데이트.

    Parameters
    ----------
    keyword_result : dict
        extract_keywords_from_crawled() 결과
    state : dict
        순환 상태 딕셔너리

    Returns
    -------
    dict
        업데이트된 상태
    """
    new_targets = keyword_result.get("potential_targets", [])

    new_hashtags = [t["value"] for t in new_targets if t["type"] == "hashtag"]
    new_searches = [t["value"] for t in new_targets if t["type"] == "search"]

    # 기존 발견된 것과 병합 (중복 제거)
    existing_h = set(state.get("discovered_hashtags", []))
    existing_s = set(state.get("discovered_searches", []))

    existing_h.update(new_hashtags)
    existing_s.update(new_searches)

    state["discovered_hashtags"] = sorted(existing_h)
    state["discovered_searches"] = sorted(existing_s)

    logger.info(
        "수집 대상 업데이트: 해시태그 {}개, 검색어 {}개 (신규: +{}h, +{}s)",
        len(state["discovered_hashtags"]),
        len(state["discovered_searches"]),
        len(new_hashtags),
        len(new_searches),
    )

    return state


# ══════════════════════════════════════════════════════════════════
# 5. 전체 순환 실행
# ══════════════════════════════════════════════════════════════════


def run_cycle(
    skip_crawl: bool = False,
    skip_train: bool = False,
    crawl_count: int = 20,
    headless: bool = False,
) -> dict[str, Any]:
    """순환 파이프라인 1회 실행.

    1. 수집 (기존 + 발견된 타겟)
    2. 학습 데이터 변환
    3. 키워드 추출 → 타겟 업데이트
    4. Dataset 빌드
    5. 모델 재학습

    Parameters
    ----------
    skip_crawl : bool
        True면 수집 건너뜀 (기존 데이터만 사용)
    skip_train : bool
        True면 모델 학습 건너뜀 (데이터 변환/키워드 추출만)
    crawl_count : int
        소스당 수집할 게시글 수
    headless : bool
        브라우저 헤드리스 모드

    Returns
    -------
    dict
        순환 결과 요약
    """
    state = load_cycle_state()
    cycle_num = state["cycle_count"] + 1
    logger.info("═" * 50)
    logger.info("순환 #{} 시작", cycle_num)
    logger.info("═" * 50)

    result: dict[str, Any] = {
        "cycle": cycle_num,
        "started_at": datetime.now().isoformat(),
    }

    # ── Step 1: 수집 ──
    if not skip_crawl:
        crawl_stats = _run_crawl(state, crawl_count, headless)
        result["crawl"] = crawl_stats
    else:
        logger.info("[Step 1] 수집 건너뜀 (skip_crawl=True)")

    # ── Step 2: 학습 데이터 변환 ──
    logger.info("[Step 2] 수집 데이터 → 학습 JSONL 변환")
    jsonl_path, total_samples = convert_crawled_to_training()
    result["training_samples"] = total_samples

    # ── Step 3: 키워드 추출 & 타겟 업데이트 ──
    logger.info("[Step 3] 키워드 추출 및 수집 대상 업데이트")
    keywords = extract_keywords_from_crawled()
    state = update_crawl_targets(keywords, state)
    result["keywords"] = {
        "top_hashtags": keywords["hashtags"][:10],
        "top_keywords": keywords["keywords"][:10],
        "new_targets": len(keywords["potential_targets"]),
    }

    # ── Step 4: HuggingFace Dataset 빌드 ──
    logger.info("[Step 4] HuggingFace Dataset 빌드")
    try:
        ds_path = build_training_dataset()
        result["dataset_path"] = str(ds_path)
    except FileNotFoundError as e:
        logger.error("Dataset 빌드 실패: {}", e)
        result["dataset_error"] = str(e)

    # ── Step 5: 모델 재학습 ──
    if not skip_train and total_samples >= 20:
        logger.info("[Step 5] 모델 재학습 (QLoRA)")
        try:
            from src.training.train_qlora import train
            train()
            result["training"] = "completed"
        except Exception as exc:
            logger.error("학습 실패: {}", exc)
            result["training"] = f"failed: {exc}"
    elif skip_train:
        logger.info("[Step 5] 학습 건너뜀 (skip_train=True)")
        result["training"] = "skipped"
    else:
        logger.warning("[Step 5] 학습 데이터 부족 ({} < 20), 학습 건너뜀", total_samples)
        result["training"] = f"skipped (only {total_samples} samples)"

    # ── 상태 업데이트 ──
    state["cycle_count"] = cycle_num
    state["total_samples"] = total_samples
    state["history"].append({
        "cycle": cycle_num,
        "date": datetime.now().isoformat(),
        "samples": total_samples,
        "new_targets": len(keywords.get("potential_targets", [])),
    })
    save_cycle_state(state)

    result["finished_at"] = datetime.now().isoformat()
    logger.info("═" * 50)
    logger.info("순환 #{} 완료: {} 샘플", cycle_num, total_samples)
    logger.info("═" * 50)

    return result


def _run_crawl(
    state: dict[str, Any],
    count: int,
    headless: bool,
) -> dict[str, int]:
    """기존 + 발견된 타겟으로 수집 실행."""
    from src.data_pipeline.browser_crawler import InstagramBrowserCrawler

    # 기본 타겟
    base_hashtags = [
        "일상스타그램", "카페스타그램", "데일리룩", "서울카페",
        "오오티디", "감성스타그램", "맛집스타그램", "패션스타그램",
    ]
    base_searches = [
        "일상 브이로그", "서울 카페 추천", "봄 데일리룩",
    ]

    # 발견된 타겟 추가
    discovered_h = state.get("discovered_hashtags", [])
    discovered_s = state.get("discovered_searches", [])

    all_hashtags = list(dict.fromkeys(base_hashtags + discovered_h))
    all_searches = list(dict.fromkeys(base_searches + discovered_s))

    logger.info(
        "수집 대상: 해시태그 {}개, 검색어 {}개",
        len(all_hashtags), len(all_searches),
    )

    crawler = InstagramBrowserCrawler(headless=headless, slow_mo=300)
    try:
        if not crawler.login():
            logger.error("로그인 실패!")
            return {"error": 1}

        stats = crawler.bulk_crawl(
            hashtags=all_hashtags,
            search_keywords=all_searches,
            posts_per_source=count,
            posts_per_user=5,
            crawl_explore=True,
            crawl_reels_feed=False,
        )
        return stats
    finally:
        crawler.close()
