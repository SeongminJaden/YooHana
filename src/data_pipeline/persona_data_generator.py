"""
Persona-style training data generator using Gemini API.

Converts raw crawled captions into 유하나's speaking style (여대생 반말),
and generates comment-reply pairs for training.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

logger = get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_persona_prompt() -> str:
    """Load persona system prompt for Gemini."""
    import yaml
    persona_path = _PROJECT_ROOT / "config" / "persona.yaml"
    with open(persona_path, "r", encoding="utf-8") as f:
        persona = yaml.safe_load(f)

    identity = persona["identity"]
    speaking = persona["speaking_style"]
    features = "\n".join(f"- {f}" for f in speaking["features"])

    return (
        f"너는 '{identity['name']}'이야. {identity['age']}세 여대생이고 "
        f"{identity['occupation']}이야.\n\n"
        f"[말투 규칙 - 반드시 지켜야 함]\n"
        f"{features}\n"
        f"- 반말을 써 (존댓말 ~~입니다/~~해요 절대 금지)\n"
        f"- 20대 여대생처럼 자연스럽게 써\n"
        f"- 이모지는 1-2개만 (과하게 쓰지 마)\n"
        f"- ㅋㅋ, ㅎㅎ, ㅠㅠ 같은 표현 자연스럽게 사용\n"
        f"- 짧고 감성적으로 써 (너무 길지 않게)\n"
        f"- 팔로워한테 질문 던지기 (소통 유도)\n"
        f"- 절대 AI인 것을 드러내지 마\n"
    )


class PersonaDataGenerator:
    """Generate persona-style training data using Gemini API."""

    def __init__(self) -> None:
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")

        self._client = genai.Client(api_key=api_key)
        self._model = "gemini-2.0-flash"
        self._persona_prompt = _load_persona_prompt()
        self._data_dir = _PROJECT_ROOT / "data"
        self._call_count = 0

    def _call_gemini(self, prompt: str, max_retries: int = 3) -> str:
        """Call Gemini API with rate limiting."""
        from google.genai import types

        for attempt in range(max_retries):
            try:
                # Rate limit: ~15 RPM for free tier
                if self._call_count > 0:
                    time.sleep(4.5)

                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.8,
                        top_p=0.9,
                        max_output_tokens=512,
                    ),
                )
                self._call_count += 1

                if response.text:
                    return response.text.strip()
                return ""

            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    wait = 30 * (attempt + 1)
                    logger.warning("Rate limited, waiting {}s...", wait)
                    time.sleep(wait)
                elif attempt < max_retries - 1:
                    logger.warning("Gemini error (attempt {}): {}", attempt + 1, e)
                    time.sleep(5)
                else:
                    logger.error("Gemini failed after {} retries: {}", max_retries, e)
                    return ""
        return ""

    # ──────────────────────────────────────────────────────────────
    # 1. Caption style conversion
    # ──────────────────────────────────────────────────────────────

    def convert_caption_to_persona(self, original_caption: str) -> str:
        """Convert a crawled caption to 유하나's speaking style."""
        prompt = (
            f"{self._persona_prompt}\n\n"
            f"아래 인스타그램 캡션의 내용을 유지하면서, "
            f"유하나의 말투(20대 여대생 반말)로 다시 써줘.\n"
            f"해시태그는 빼고 캡션 본문만 써줘.\n"
            f"존댓말이나 ~~입니다 같은 말 쓰지 마.\n\n"
            f"원본 캡션: {original_caption}\n\n"
            f"유하나 버전:"
        )
        return self._call_gemini(prompt)

    def batch_convert_captions(self, limit: int = 200) -> list[dict[str, str]]:
        """Convert crawled captions to persona style in batch.

        Returns list of {instruction, output} dicts.
        """
        # Load crawled captions
        crawled_path = self._data_dir / "training" / "crawled_captions.jsonl"
        if not crawled_path.exists():
            logger.error("No crawled captions found")
            return []

        originals: list[dict] = []
        with open(crawled_path, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                caption = data.get("output", "").strip()
                # Filter: only captions with enough content
                if len(caption) > 10 and not caption.startswith("["):
                    originals.append(data)

        # Shuffle and limit
        random.shuffle(originals)
        originals = originals[:limit]

        results: list[dict[str, str]] = []
        logger.info("Converting {} captions to persona style...", len(originals))

        for i, orig in enumerate(originals):
            caption = unicodedata.normalize("NFC", orig["output"])
            converted = self.convert_caption_to_persona(caption)

            if converted and len(converted) > 5:
                # Clean up
                converted = converted.strip().strip('"').strip("'")
                # Remove any "유하나 버전:" prefix if echoed
                converted = re.sub(r'^유하나\s*(버전|스타일)\s*[:：]\s*', '', converted)

                results.append({
                    "instruction": orig["instruction"],
                    "output": converted,
                    "source": "persona_converted",
                })
                logger.debug("[{}/{}] {} → {}", i + 1, len(originals),
                             caption[:40], converted[:40])
            else:
                logger.debug("[{}/{}] Skipped (empty result)", i + 1, len(originals))

            if (i + 1) % 10 == 0:
                logger.info("Progress: {}/{}", i + 1, len(originals))
                # Save intermediate results
                self._save_intermediate(results, "persona_captions")

        return results

    # ──────────────────────────────────────────────────────────────
    # 2. Comment-reply pair generation
    # ──────────────────────────────────────────────────────────────

    def generate_comment_replies(self, count: int = 100) -> list[dict[str, str]]:
        """Generate realistic comment-reply training pairs."""
        # Common comment types on Instagram
        comment_templates = [
            # 칭찬
            "언니 너무 예뻐요!", "진짜 분위기 좋다", "사진 잘 찍으셨어요~",
            "이거 어디에요??", "옷 정보 알려주세요!", "이 카페 어디에요?",
            "머리 예쁘다 ㅠㅠ", "피부 진짜 좋다", "인스타 감성 최고",
            # 공감
            "나도 가보고 싶다!", "진짜 맛있겠다 ㅠ", "부럽다 ㅋㅋ",
            "나도 이런 카페 가고싶어", "완전 내 스타일이야",
            # 질문
            "이거 어디서 산 거예요?", "립 뭐 발랐어요?", "카메라 뭐로 찍었어요?",
            "여기 예약 필요해요?", "가격 어떤가요?", "혼자 가도 괜찮아요?",
            "오늘 뭐 먹었어요?", "서울 어디 살아요?",
            # 인사
            "좋은 하루 되세요 ☀️", "오늘도 예쁘다 💕", "응원해요!",
            "맞팔해요~", "팔로우 했어요 ♥",
            # 대화
            "나 오늘 여기 갔는데 진짜 좋았어!", "저도 여기 가봤는데 맛있었어요",
            "저 이 브랜드 좋아하는데!", "언제 또 올려주세요~",
        ]

        # Post contexts for replies
        post_contexts = [
            "오늘 새로 발견한 카페 ☕ 분위기 진짜 좋았어",
            "봄 데일리룩 ✨ 오늘 날씨 너무 좋아서 가볍게 입었어",
            "서울숲 산책하다가 찍은 사진 🌸",
            "요즘 빠진 브런치 맛집! 여기 진짜 맛있어 ㅠㅠ",
            "새로 산 가방이랑 오오티디 💕",
            "한강에서 피크닉 🧺 날씨 완전 소풍일 ㅋㅋ",
            "오늘의 셀카 📸 메이크업 좀 바꿔봤어 어때?",
            "성수동 핫플 다녀왔어! 인테리어가 미쳤어 ✨",
            "집에서 혼자 영화 보면서 먹은 야식 ㅋㅋ",
            "드디어 기다리던 딸기 시즌 🍓",
        ]

        results: list[dict[str, str]] = []
        logger.info("Generating {} comment-reply pairs...", count)

        for i in range(count):
            comment = random.choice(comment_templates)
            post_context = random.choice(post_contexts)

            prompt = (
                f"{self._persona_prompt}\n\n"
                f"너는 인스타그램에 글을 올렸고, 팔로워가 댓글을 달았어.\n"
                f"유하나로서 짧고 친근하게 답글을 써줘.\n\n"
                f"[내 게시글 캡션]: {post_context}\n"
                f"[팔로워 댓글]: {comment}\n\n"
                f"조건:\n"
                f"- 반말로 (존댓말 금지)\n"
                f"- 1-2문장으로 짧게\n"
                f"- 이모지 0-1개\n"
                f"- 상대방에게 관심 보여주기\n"
                f"- 진짜 사람처럼 자연스럽게\n\n"
                f"답글:"
            )

            reply = self._call_gemini(prompt)
            if reply and len(reply) > 2:
                reply = reply.strip().strip('"').strip("'")
                reply = re.sub(r'^답글\s*[:：]\s*', '', reply)

                instruction = (
                    f"[내 게시글] {post_context}\n"
                    f"[팔로워 댓글] {comment}\n"
                    f"이 댓글에 답글을 써줘"
                )

                results.append({
                    "instruction": instruction,
                    "output": reply,
                    "source": "persona_reply",
                })
                logger.debug("[{}/{}] '{}' → '{}'", i + 1, count, comment[:30], reply[:40])

            if (i + 1) % 10 == 0:
                logger.info("Progress: {}/{}", i + 1, count)
                self._save_intermediate(results, "persona_replies")

        return results

    # ──────────────────────────────────────────────────────────────
    # 3. Original caption generation (from scratch)
    # ──────────────────────────────────────────────────────────────

    def generate_original_captions(self, count: int = 100) -> list[dict[str, str]]:
        """Generate original Instagram captions in 유하나's voice."""
        topics = [
            "카페 탐방", "봄 데일리룩", "서울 산책", "맛집 방문",
            "한강 피크닉", "셀카", "브런치", "쇼핑", "영화 감상",
            "독서", "운동", "일상", "비 오는 날", "노을 사진",
            "주말 나들이", "야경", "새로운 도전", "친구 만남",
            "집순이 일상", "계절 변화", "디저트", "전시회",
            "OOTD", "헤어 변신", "네일아트", "아침 루틴",
            "저녁 일기", "음악 추천", "넷플릭스", "요리 도전",
        ]

        results: list[dict[str, str]] = []
        logger.info("Generating {} original persona captions...", count)

        for i in range(count):
            topic = random.choice(topics)

            prompt = (
                f"{self._persona_prompt}\n\n"
                f"'{topic}' 주제로 인스타그램 캡션을 써줘.\n\n"
                f"조건:\n"
                f"- 20대 여대생 말투 (반말, ㅋㅋ/ㅎㅎ 사용)\n"
                f"- 존댓말/~~입니다 절대 금지\n"
                f"- 이모지 1-2개\n"
                f"- 2-4문장으로\n"
                f"- 마지막에 팔로워에게 질문 하나\n"
                f"- 해시태그 없이 캡션만\n"
                f"- 진짜 여대생이 쓴 것처럼 자연스럽게\n\n"
                f"캡션:"
            )

            caption = self._call_gemini(prompt)
            if caption and len(caption) > 10:
                caption = caption.strip().strip('"').strip("'")
                caption = re.sub(r'^캡션\s*[:：]\s*', '', caption)
                # Remove hashtags if any
                caption = re.sub(r'#\S+', '', caption).strip()

                results.append({
                    "instruction": f"{topic}에 대한 인스타그램 캡션을 작성해줘",
                    "output": caption,
                    "source": "persona_generated",
                })
                logger.debug("[{}/{}] {} → {}", i + 1, count, topic, caption[:50])

            if (i + 1) % 10 == 0:
                logger.info("Progress: {}/{}", i + 1, count)
                self._save_intermediate(results, "persona_originals")

        return results

    # ──────────────────────────────────────────────────────────────
    # Save helpers
    # ──────────────────────────────────────────────────────────────

    def _save_intermediate(self, data: list[dict], prefix: str) -> None:
        """Save intermediate results."""
        path = self._data_dir / "training" / f"{prefix}_intermediate.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def save_all(
        self,
        captions: list[dict],
        replies: list[dict],
        originals: list[dict],
    ) -> str:
        """Save all generated data to a single JSONL file."""
        all_data = captions + replies + originals
        random.shuffle(all_data)

        output_path = self._data_dir / "training" / "persona_style_data.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for item in all_data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        logger.info(
            "Saved {} persona-style samples "
            "(captions: {}, replies: {}, originals: {}) → {}",
            len(all_data), len(captions), len(replies), len(originals),
            output_path,
        )
        return str(output_path)
