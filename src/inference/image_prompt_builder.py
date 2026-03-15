"""캡션/글 내용 기반 이미지 생성 프롬프트 빌더.

Instagram/Threads 캡션을 분석하여 유하나 페르소나에 맞는
Gemini 이미지 생성 프롬프트를 생성한다.
"""
from __future__ import annotations

import random
import re


# ── 장소/상황별 씬 템플릿 ─────────────────────────────────
_SCENE_TEMPLATES = {
    "한강/강변/야경/밤산책": (
        "Create a natural iPhone night photo of her standing near a riverside road, "
        "with fast-moving cars in the background. Keep the overall background sharp and clear, "
        "but allow the passing cars to show natural motion blur to reflect real movement. "
        "She is wearing a dark oversized leather jacket with a simple black outfit underneath. "
        "Maintain realistic iPhone flash lighting and a clean, authentic night street atmosphere."
    ),
    "산책/걷기/바람/야외": (
        "Generate a natural side-view candid shot of her walking outdoors, "
        "with her hair gently moving in the breeze under natural daylight."
    ),
    "에스컬레이터/쇼핑몰/백화점/외출": (
        "Create a natural iPhone candid on an escalator, wearing black horn-rimmed glasses, "
        "a black bomber jacket, and a black handbag. Keep the lighting realistic and unfiltered, "
        "no artificial blur."
    ),
    "피팅룸/쇼핑/옷/코디/ootd/데일리룩": (
        "Create a natural iPhone mirror selfie in a fitting room, wearing a black oversized jacket, "
        "wide black pants, slim sunglasses, and casual accessories."
    ),
    "밤/나이트/클럽/파티/저녁": (
        "Create a night-time iPhone flash photo wearing black horn-rim glasses "
        "and a textured black leather jacket."
    ),
    "거울/셀카/셀피/미러": (
        "Create a natural iPhone mirror-selfie with direct flash, no background blur, "
        "and a clean unfiltered look. She is wearing a black hoodie and sunglasses as the only accessory, "
        "keeping the vibe simple and casually high-fashion."
    ),
    "차/드라이브/택시/이동": (
        "Create a natural iPhone-style car selfie with bright sunlight entering from the side window, "
        "captured from a low, slightly upward angle as she sits in the backseat. "
        "She wears an oversized charcoal hoodie with the hood up, layered under a black leather jacket, "
        "and has wired earphones in. Keep the lighting sharply natural, no artificial blur, "
        "and maintain a candid, unfiltered atmosphere."
    ),
    "촬영/스튜디오/화보/모델": (
        "Create a backstage photoshoot moment where she adjusts her hair under studio lights, "
        "captured from the side, with a randomly generated editorial-style portrait of the same person "
        "displayed on the studio monitor."
    ),
    "엘리베이터/건물/실내/퇴근": (
        "Create a natural iPhone flash photo inside an elevator, featuring her wearing a long black coat "
        "and standing against the wooden and metal elevator walls, with a soft, natural smile. "
        "Add a subtle handheld motion shake to mimic a slightly unsteady real iPhone capture, "
        "while keeping the overall image sharp and realistic with no artificial blur. "
        "Maintain harsh, direct iPhone flash lighting and a natural indoor color tone."
    ),
    "카페/커피/브런치/디저트": (
        "Create a natural iPhone photo of her sitting by a cafe window with warm natural light, "
        "holding a coffee cup. She wears a cream knit sweater with minimal accessories. "
        "Keep the cafe interior softly visible in the background with a cozy, warm atmosphere. "
        "Maintain realistic iPhone lighting, no artificial filters."
    ),
    "여행/비행기/공항/호텔": (
        "Create a natural iPhone travel photo of her at an airport terminal, wearing an oversized blazer "
        "over a simple white tee, with a carry-on suitcase beside her. Capture natural terminal lighting "
        "with large windows in the background. Keep the mood relaxed and candid."
    ),
    "바다/해변/제주/서핑": (
        "Create a natural iPhone beach photo of her standing on the shore with waves in the background, "
        "wearing a white linen shirt over a simple outfit, hair blowing in the ocean breeze. "
        "Maintain bright, natural sunlight and a clean, unfiltered summer atmosphere."
    ),
    "운동/필라테스/러닝/헬스": (
        "Create a natural iPhone gym mirror selfie of her wearing black athletic wear — "
        "sports bra and leggings — with airpods in, holding her phone at chest height. "
        "Keep the gym equipment softly visible in the background. Maintain realistic mirror selfie lighting."
    ),
    "음식/맛집/먹스타/요리": (
        "Create a natural overhead iPhone food photo with her hands visible holding chopsticks, "
        "showing a beautifully plated Korean meal on a wooden table. "
        "Keep warm restaurant lighting and a cozy dining atmosphere."
    ),
    "비/우산/장마/흐린날": (
        "Create a natural iPhone photo of her holding a transparent umbrella on a rainy street, "
        "wearing a black trench coat. Capture raindrops on the umbrella and wet reflections on the pavement. "
        "Maintain moody, overcast natural lighting."
    ),
}

# 기본 씬 (매칭 안 될 때)
_DEFAULT_SCENES = [
    (
        "Create a natural iPhone candid photo of her in a casual urban setting, "
        "wearing a simple black outfit with minimal accessories. "
        "Maintain realistic natural lighting and an unfiltered, authentic atmosphere."
    ),
    (
        "Create a natural iPhone selfie with soft natural window light, "
        "wearing a cozy oversized sweater, looking directly at the camera with a relaxed expression. "
        "Keep the background clean and minimal."
    ),
    (
        "Create a natural iPhone street photo of her walking through a quiet alley, "
        "wearing a long black coat and white sneakers. "
        "Capture natural daylight and maintain a clean, candid atmosphere."
    ),
]

_IDENTITY_PREFIX = (
    "Use the attached face image as the exact identity reference "
    "and generate the same person. "
)


def _match_scene(text: str) -> str:
    """캡션 텍스트에서 키워드를 매칭하여 적절한 씬 템플릿을 선택."""
    text_lower = text.lower()

    best_match = None
    best_score = 0

    for keywords_str, template in _SCENE_TEMPLATES.items():
        keywords = [k.strip() for k in keywords_str.split("/")]
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > best_score:
            best_score = score
            best_match = template

    if best_match and best_score > 0:
        return best_match

    return random.choice(_DEFAULT_SCENES)


def generate_image_prompt(caption: str, platform: str = "instagram") -> str:
    """캡션/글 내용을 분석하여 이미지 생성 프롬프트를 생성.

    Parameters
    ----------
    caption : str
        Instagram 캡션 또는 Threads 텍스트
    platform : str
        "instagram" 또는 "threads"

    Returns
    -------
    str
        Gemini 이미지 생성용 영어 프롬프트
    """
    scene = _match_scene(caption)
    prompt = _IDENTITY_PREFIX + scene

    # 플랫폼별 미세 조정
    if platform == "threads":
        # Threads는 좀 더 캐주얼/자연스러운 느낌
        prompt += " Make the overall mood more casual and spontaneous, like a quick phone snap shared on social media."

    return prompt


def generate_image_prompt_from_topic(topic: str, platform: str = "instagram") -> str:
    """주제 키워드로 이미지 생성 프롬프트를 생성.

    Parameters
    ----------
    topic : str
        주제 (예: "카페", "야경 산책", "ootd")
    platform : str
        "instagram" 또는 "threads"

    Returns
    -------
    str
        Gemini 이미지 생성용 영어 프롬프트
    """
    return generate_image_prompt(topic, platform)
