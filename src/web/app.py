"""Flask web application for managing the AI Influencer."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POSTS_DIR = _PROJECT_ROOT / "outputs" / "posts"
_POSTS_META = _POSTS_DIR / "posts.json"
_UPLOAD_DIR = _POSTS_DIR / "images"

# Allowed image extensions
_ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _load_posts() -> list[dict]:
    if not _POSTS_META.exists():
        return []
    try:
        return json.loads(_POSTS_META.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_posts(posts: list[dict]) -> None:
    _POSTS_DIR.mkdir(parents=True, exist_ok=True)
    _POSTS_META.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2), "utf-8"
    )


# ---------------------------------------------------------------------------
# Lazy model singleton
# ---------------------------------------------------------------------------
_model_cache: dict[str, Any] = {}


def _get_generator():
    """Lazy-load TextGenerator (heavy — loads GPU model)."""
    if "gen" not in _model_cache:
        from src.inference.text_generator import TextGenerator

        _model_cache["gen"] = TextGenerator()
    return _model_cache["gen"]


def _get_persona():
    if "persona" not in _model_cache:
        from src.persona.character import Persona

        _model_cache["persona"] = Persona()
    return _model_cache["persona"]


def _get_topic_generator():
    if "topic_gen" not in _model_cache:
        from src.planner.topic_generator import TopicGenerator

        _model_cache["topic_gen"] = TopicGenerator(_get_persona())
    return _model_cache["topic_gen"]


# ---------------------------------------------------------------------------
# Chat helpers (adapted from scripts/chat.py)
# ---------------------------------------------------------------------------

def _is_valid_korean(text: str) -> bool:
    korean = len(re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", text))
    alpha = len(re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣA-Za-z]", text))
    if alpha == 0:
        return False
    return korean / alpha > 0.5


def _generate_chat_response(user_msg: str) -> str:
    gen = _get_generator()
    prompt = f"### Instruction:\n{user_msg}\n\n### Response:\n"

    for _ in range(3):
        response = gen.generate(prompt, max_new_tokens=150)

        # Strip persona prefixes
        for prefix in ("하나:", "하나 :", "유하나:", "유하나 :"):
            if response.startswith(prefix):
                response = response[len(prefix):].strip()

        # Truncate at meta-text
        for stop in ("상대:", "### Instruction", "###", "[이전 대화]",
                      "\n\n\n", "Instruction:", "Response:"):
            idx = response.find(stop)
            if idx > 0:
                response = response[:idx].strip()

        if response and _is_valid_korean(response):
            return response

    return "ㅎㅎ 뭐라고? 다시 말해줘~"


# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # ── Pages ──────────────────────────────────────────────────────

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── Static uploads ─────────────────────────────────────────────

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        return send_from_directory(str(_UPLOAD_DIR), filename)

    # ── API: Posts ─────────────────────────────────────────────────

    @app.route("/api/posts")
    def api_get_posts():
        posts = _load_posts()
        return jsonify(posts)

    @app.route("/api/posts/<post_id>", methods=["DELETE"])
    def api_delete_post(post_id: str):
        posts = _load_posts()
        posts = [p for p in posts if p["id"] != post_id]
        _save_posts(posts)
        return jsonify({"ok": True})

    # ── API: Chat ──────────────────────────────────────────────────

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = request.get_json(force=True)
        user_msg = (data.get("message") or "").strip()
        if not user_msg:
            return jsonify({"error": "빈 메시지"}), 400

        try:
            reply = _generate_chat_response(user_msg)
            return jsonify({"reply": reply})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ── API: Upload image ──────────────────────────────────────────

    @app.route("/api/upload-image", methods=["POST"])
    def api_upload_image():
        if "image" not in request.files:
            return jsonify({"error": "이미지 파일이 없습니다"}), 400

        file = request.files["image"]
        if not file.filename:
            return jsonify({"error": "파일명이 없습니다"}), 400

        ext = Path(file.filename).suffix.lower()
        if ext not in _ALLOWED_EXT:
            return jsonify({"error": f"허용되지 않는 형식: {ext}"}), 400

        filename = f"{uuid.uuid4().hex[:12]}{ext}"
        save_path = _UPLOAD_DIR / filename
        file.save(str(save_path))

        return jsonify({
            "filename": filename,
            "url": f"/uploads/{filename}",
        })

    # ── API: Generate caption ──────────────────────────────────────

    @app.route("/api/generate-caption", methods=["POST"])
    def api_generate_caption():
        data = request.get_json(force=True)
        topic = (data.get("topic") or "").strip()
        if not topic:
            topic = "일상"

        try:
            gen = _get_generator()
            caption = gen.generate_caption(topic)
            return jsonify({"caption": caption})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ── API: Generate hashtags ─────────────────────────────────────

    @app.route("/api/generate-hashtags", methods=["POST"])
    def api_generate_hashtags():
        data = request.get_json(force=True)
        topic = (data.get("topic") or "").strip()
        if not topic:
            topic = "일상"

        try:
            tg = _get_topic_generator()
            tags = tg.generate_hashtags(topic)
            return jsonify({"hashtags": tags})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    # ── API: Generate image (Gemini) ───────────────────────────────

    @app.route("/api/generate-image", methods=["POST"])
    def api_generate_image():
        data = request.get_json(force=True)
        topic = (data.get("topic") or "").strip()
        if not topic:
            return jsonify({"error": "주제를 입력해주세요"}), 400

        try:
            persona = _get_persona()
            scene = topic
            image_prompt = persona.get_image_prompt(scene)

            from src.image_gen.gemini_client import GeminiImageClient

            client = GeminiImageClient()
            image_path = client.generate(image_prompt)

            # Copy to uploads dir
            src = Path(image_path)
            filename = f"ai_{uuid.uuid4().hex[:8]}{src.suffix}"
            dst = _UPLOAD_DIR / filename
            import shutil
            shutil.copy2(str(src), str(dst))

            return jsonify({
                "filename": filename,
                "url": f"/uploads/{filename}",
            })
        except ImportError:
            return jsonify({"error": "Gemini API 모듈 없음"}), 500
        except Exception as exc:
            return jsonify({"error": f"이미지 생성 실패: {exc}"}), 500

    # ── API: Save post ─────────────────────────────────────────────

    @app.route("/api/save-post", methods=["POST"])
    def api_save_post():
        data = request.get_json(force=True)
        filename = data.get("filename", "")
        caption = data.get("caption", "")
        hashtags = data.get("hashtags", "")

        if not filename:
            return jsonify({"error": "이미지가 없습니다"}), 400

        post = {
            "id": uuid.uuid4().hex[:12],
            "filename": filename,
            "image_url": f"/uploads/{filename}",
            "caption": caption,
            "hashtags": hashtags,
            "created_at": datetime.now().isoformat(),
            "posted": False,
            "source": data.get("source", "upload"),
        }

        posts = _load_posts()
        posts.insert(0, post)
        _save_posts(posts)

        return jsonify({"ok": True, "post": post})

    # ── API: Post to Instagram ─────────────────────────────────────

    @app.route("/api/post-instagram", methods=["POST"])
    def api_post_instagram():
        data = request.get_json(force=True)
        post_id = data.get("post_id", "")

        posts = _load_posts()
        post = next((p for p in posts if p["id"] == post_id), None)
        if not post:
            return jsonify({"error": "게시물을 찾을 수 없습니다"}), 404

        image_path = str(_UPLOAD_DIR / post["filename"])
        if not Path(image_path).exists():
            return jsonify({"error": "이미지 파일이 없습니다"}), 404

        full_caption = post["caption"]
        if post.get("hashtags"):
            full_caption = f"{full_caption}\n\n{post['hashtags']}"

        try:
            from src.instagram.browser_poster import BrowserPoster

            poster = BrowserPoster(headless=True)
            try:
                if not poster.login():
                    return jsonify({"error": "Instagram 로그인 실패"}), 500

                success = poster.post_photo(image_path, full_caption)
                if success:
                    # Mark as posted
                    post["posted"] = True
                    post["posted_at"] = datetime.now().isoformat()
                    _save_posts(posts)
                    return jsonify({"ok": True})
                else:
                    return jsonify({"error": "포스팅 실패"}), 500
            finally:
                poster.close()
        except Exception as exc:
            return jsonify({"error": f"포스팅 에러: {exc}"}), 500

    return app
