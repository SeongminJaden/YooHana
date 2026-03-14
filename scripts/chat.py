#!/usr/bin/env python3
"""유하나와 터미널 대화 - Interactive chat with the AI persona.

Usage:
    python3 scripts/chat.py
    python3 scripts/chat.py --history 10   # 최근 10턴까지 컨텍스트 유지
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging
import os
import warnings

os.environ["LOGURU_LEVEL"] = "ERROR"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
logging.disable(logging.WARNING)
warnings.filterwarnings("ignore")

from src.inference.text_generator import TextGenerator
from src.persona.character import Persona


def build_chat_system_prompt(persona: Persona) -> str:
    """대화용 시스템 프롬프트 (인스타 캡션이 아닌 일반 대화 맥락)."""
    identity = persona._data["identity"]
    personality = persona._data["personality"]
    speaking = persona._data["speaking_style"]
    boundaries = persona._data["boundaries"]

    traits = ", ".join(personality["traits"])
    forbidden = ", ".join(boundaries["forbidden_topics"])

    return (
        f"너는 '{identity['name']}'이야. {identity['age']}살 서울 사는 여대생이야.\n"
        f"MBTI: {personality['mbti']} / 성격: {traits}\n"
        f"관심사: 카페 탐방, 패션, 필라테스, 사진 찍기, 요리, 인테리어\n"
        f"좋아하는 브랜드: 자라, 코스, 마뗑킴\n"
        f"자주 가는 곳: 성수동, 한남동, 한강\n\n"
        f"[말투 규칙]\n"
        f"- 친한 친구한테 말하듯 반말로 대화해\n"
        f"- ㅋㅋ, ㅎㅎ, ㅠㅠ 자연스럽게 사용\n"
        f"- 이모지 가끔 사용\n"
        f"- 짧고 자연스럽게 대답 (1-3문장)\n"
        f"- 상대방에게 질문으로 대화 이어가기\n\n"
        f"[금지]\n"
        f"- {forbidden}\n"
        f"- AI라는 사실 절대 언급하지 마\n"
        f"- 항상 유하나로서 대답해"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="유하나와 대화하기")
    parser.add_argument(
        "--history", type=int, default=8,
        help="유지할 대화 턴 수 (기본 8턴)",
    )
    args = parser.parse_args()
    max_history = args.history

    print("모델 로딩 중...")
    gen = TextGenerator()
    persona = Persona()
    system_prompt = build_chat_system_prompt(persona)

    # Conversation history: list of (user_msg, bot_msg) tuples
    history: list[tuple[str, str]] = []

    print()
    print("=" * 50)
    print("  유하나와 대화하기")
    print("  /quit 또는 /q - 종료")
    print("  /clear - 대화 기록 초기화")
    print("  /history - 대화 기록 보기")
    print("=" * 50)
    print()

    # Greeting
    print("하나: 안녕! 나 하나야 ㅎㅎ 뭐 궁금한 거 있으면 편하게 물어봐! ✨")
    print()

    while True:
        try:
            user_input = input("나: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n하나: 잘 가~ 다음에 또 얘기하자! 👋")
            break

        if not user_input:
            continue

        # Commands
        if user_input in ("/quit", "/q", "quit", "exit"):
            print("\n하나: 잘 가~ 다음에 또 얘기하자! 👋")
            break

        if user_input == "/clear":
            history.clear()
            print("[대화 기록 초기화됨]")
            print()
            continue

        if user_input == "/history":
            if not history:
                print("[대화 기록 없음]")
            else:
                for i, (u, b) in enumerate(history, 1):
                    print(f"  [{i}] 나: {u}")
                    print(f"      하나: {b}")
            print()
            continue

        # Generate response with conversation context
        response = _generate_response(
            gen, system_prompt, history[-max_history:], user_input,
        )

        # Store in history
        history.append((user_input, response))

        print(f"하나: {response}")
        print()


def _is_valid_korean(text: str) -> bool:
    """Check if output contains enough Korean to be valid."""
    import re
    korean_chars = len(re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", text))
    total_alpha = len(re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z]", text))
    if total_alpha == 0:
        return False
    return korean_chars / total_alpha > 0.5


def _generate_response(
    gen: TextGenerator,
    system_prompt: str,
    history: list[tuple[str, str]],
    user_msg: str,
) -> str:
    """Build prompt with conversation history and generate response.

    The fine-tuned model works best with short, simple instructions
    matching the training format. We keep it minimal.
    """
    # Try direct question first (matches training data format best)
    prompt = f"### Instruction:\n{user_msg}\n\n### Response:\n"

    # Retry up to 3 times if output is garbled
    for attempt in range(3):
        response = gen.generate(prompt, max_new_tokens=150)

        # Clean up: remove any prefix like "하나:"
        for prefix in ("하나:", "하나 :", "유하나:", "유하나 :"):
            if response.startswith(prefix):
                response = response[len(prefix):].strip()

        # Truncate at meta-text (model generating next turn)
        for stop in ("상대:", "### Instruction", "###", "[이전 대화]",
                      "\n\n\n", "Instruction:", "Response:"):
            idx = response.find(stop)
            if idx > 0:
                response = response[:idx].strip()

        # Validate
        if response and _is_valid_korean(response):
            return response

    return "ㅎㅎ 뭐라고? 다시 말해줘~"


if __name__ == "__main__":
    main()
