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

# Comment cache
_COMMENTS_CACHE = _PROJECT_ROOT / "data" / "comments_cache.json"
_REPLIED_IDS_FILE = _PROJECT_ROOT / "data" / "replied_comment_ids.json"


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


def _load_comments_cache() -> list[dict]:
    if not _COMMENTS_CACHE.exists():
        return []
    try:
        return json.loads(_COMMENTS_CACHE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_comments_cache(comments: list[dict]) -> None:
    _COMMENTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _COMMENTS_CACHE.write_text(
        json.dumps(comments, ensure_ascii=False, indent=2), "utf-8"
    )


def _load_replied_ids() -> set[str]:
    if not _REPLIED_IDS_FILE.exists():
        return set()
    try:
        return set(json.loads(_REPLIED_IDS_FILE.read_text("utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


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


def _generate_chat_response(user_msg: str, history: list[dict] | None = None) -> str:
    gen = _get_generator()

    # Build conversation context from history
    context = ""
    if history and len(history) > 1:
        # Exclude the last user message (it's the current one)
        prev_turns = history[:-1]
        lines = []
        for turn in prev_turns:
            role = "상대" if turn.get("role") == "user" else "하나"
            lines.append(f"{role}: {turn.get('text', '')}")
        context = "[이전 대화]\n" + "\n".join(lines) + "\n\n"

    prompt = f"### Instruction:\n{context}{user_msg}\n\n### Response:\n"

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
            history = data.get("history") or []
            reply = _generate_chat_response(user_msg, history)
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

    # ── API: Sync from Instagram profile ────────────────────────────

    @app.route("/api/sync-instagram", methods=["POST"])
    def api_sync_instagram():
        """Fetch posts from the actual Instagram profile and merge into local DB."""
        try:
            from src.instagram.browser_poster import BrowserPoster

            poster = BrowserPoster(headless=True)
            try:
                if not poster.login():
                    return jsonify({"error": "Instagram 로그인 실패"}), 500

                ig_posts = poster.get_profile_posts(max_posts=30)
            finally:
                poster.close()

            if not ig_posts:
                return jsonify({"synced": 0, "message": "가져올 게시물이 없습니다"})

            # Merge with existing posts (skip duplicates by shortcode)
            posts = _load_posts()
            existing_shortcodes = {
                p.get("shortcode", "") for p in posts if p.get("shortcode")
            }

            new_count = 0
            for ig in ig_posts:
                sc = ig.get("shortcode", "")
                if sc and sc in existing_shortcodes:
                    continue

                # Download image to local uploads
                img_url = ig.get("image_url", "")
                filename = ""
                if img_url:
                    try:
                        import urllib.request
                        ext = ".jpg"
                        filename = f"ig_{uuid.uuid4().hex[:8]}{ext}"
                        save_path = _UPLOAD_DIR / filename
                        urllib.request.urlretrieve(img_url, str(save_path))
                    except Exception:
                        filename = ""

                post = {
                    "id": uuid.uuid4().hex[:12],
                    "filename": filename,
                    "image_url": f"/uploads/{filename}" if filename else ig.get("image_url", ""),
                    "caption": "",
                    "hashtags": "",
                    "created_at": datetime.now().isoformat(),
                    "posted": True,
                    "posted_at": datetime.now().isoformat(),
                    "source": "instagram",
                    "shortcode": sc,
                    "permalink": ig.get("permalink", ""),
                }
                posts.append(post)
                existing_shortcodes.add(sc)
                new_count += 1

            if new_count > 0:
                _save_posts(posts)

            return jsonify({
                "synced": new_count,
                "total": len(ig_posts),
                "message": f"{new_count}개 새 게시물 동기화 완료",
            })

        except Exception as exc:
            return jsonify({"error": f"동기화 실패: {exc}"}), 500

    # ── API: Comments ─────────────────────────────────────────────

    @app.route("/api/comments")
    def api_get_comments():
        comments = _load_comments_cache()
        replied_ids = _load_replied_ids()
        for c in comments:
            if c["id"] in replied_ids and not c.get("replied"):
                c["replied"] = True
        return jsonify(comments)

    @app.route("/api/comments/scan", methods=["POST"])
    def api_scan_comments():
        data = request.get_json(force=True)
        max_posts = int(data.get("max_posts", 5))

        try:
            gen = _get_generator()
            from src.instagram.commenter import BrowserCommenter

            commenter = BrowserCommenter(
                text_generator=gen, headless=True
            )
            try:
                all_comments = []
                post_urls = commenter.get_recent_post_urls(max_posts=max_posts)
                for url in post_urls:
                    comments = commenter.get_comments_for_post(url)
                    all_comments.extend(comments)
            finally:
                commenter.close()

            existing = _load_comments_cache()
            existing_ids = {c["id"] for c in existing}
            replied_ids = _load_replied_ids()
            new_count = 0

            for c in all_comments:
                if c["id"] not in existing_ids:
                    c["replied"] = c["id"] in replied_ids
                    c["reply_text"] = ""
                    c["replied_at"] = None
                    c["scanned_at"] = datetime.now().isoformat()
                    existing.append(c)
                    existing_ids.add(c["id"])
                    new_count += 1

            _save_comments_cache(existing)
            return jsonify({
                "new": new_count,
                "total": len(existing),
                "message": f"새 댓글 {new_count}개 발견",
            })
        except Exception as exc:
            return jsonify({"error": f"스캔 실패: {exc}"}), 500

    @app.route("/api/comments/reply", methods=["POST"])
    def api_reply_comment():
        data = request.get_json(force=True)
        comment_id = data.get("comment_id", "")
        custom_reply = (data.get("reply_text") or "").strip()

        comments = _load_comments_cache()
        comment = next((c for c in comments if c["id"] == comment_id), None)
        if not comment:
            return jsonify({"error": "댓글을 찾을 수 없습니다"}), 404
        if comment.get("replied"):
            return jsonify({"error": "이미 답글을 단 댓글입니다"}), 400

        try:
            gen = _get_generator()

            if not custom_reply:
                custom_reply = gen.generate_reply(comment["text"])
                if not custom_reply:
                    return jsonify({"error": "답글 생성 실패"}), 500

            from src.instagram.commenter import BrowserCommenter

            commenter = BrowserCommenter(
                text_generator=gen, headless=True
            )
            try:
                success = commenter.reply_to_comment(comment, custom_reply)
            finally:
                commenter.close()

            if success:
                comment["replied"] = True
                comment["reply_text"] = custom_reply
                comment["replied_at"] = datetime.now().isoformat()
                _save_comments_cache(comments)
                return jsonify({"ok": True, "reply_text": custom_reply})
            else:
                return jsonify({"error": "답글 게시 실패"}), 500
        except Exception as exc:
            return jsonify({"error": f"답글 실패: {exc}"}), 500

    @app.route("/api/comments/auto-reply", methods=["POST"])
    def api_auto_reply_comments():
        data = request.get_json(force=True)
        max_replies = int(data.get("max_replies", 5))

        comments = _load_comments_cache()
        unreplied = [c for c in comments if not c.get("replied")]
        if not unreplied:
            return jsonify({"replied": 0, "message": "답글할 댓글이 없습니다"})

        try:
            gen = _get_generator()
            from src.instagram.commenter import BrowserCommenter

            commenter = BrowserCommenter(
                text_generator=gen, headless=True
            )
            replied_count = 0
            try:
                for comment in unreplied[:max_replies]:
                    try:
                        reply_text = gen.generate_reply(comment["text"])
                        if not reply_text:
                            continue
                        success = commenter.reply_to_comment(
                            comment, reply_text
                        )
                        if success:
                            comment["replied"] = True
                            comment["reply_text"] = reply_text
                            comment["replied_at"] = datetime.now().isoformat()
                            replied_count += 1
                    except Exception:
                        continue
            finally:
                commenter.close()

            _save_comments_cache(comments)
            return jsonify({
                "replied": replied_count,
                "message": f"{replied_count}개 답글 완료",
            })
        except Exception as exc:
            return jsonify({"error": f"자동 답글 실패: {exc}"}), 500

    # ── API: Training Monitor ───────────────────────────────────

    _CYCLE_STATE_PATH = _PROJECT_ROOT / "data" / "cycle_state.json"
    _RAW_DIR = _PROJECT_ROOT / "data" / "raw"
    _TRAINING_JSONL = _PROJECT_ROOT / "data" / "training" / "crawled_captions.jsonl"

    @app.route("/api/monitor/status")
    def api_monitor_status():
        # Cycle state
        state = {}
        if _CYCLE_STATE_PATH.exists():
            try:
                state = json.loads(_CYCLE_STATE_PATH.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        # Count raw posts
        raw_files = sorted(_RAW_DIR.glob("*.json")) if _RAW_DIR.exists() else []
        total_raw = 0
        for f in raw_files:
            try:
                total_raw += len(json.loads(f.read_text("utf-8")))
            except Exception:
                pass

        # Training samples count
        training_samples = 0
        if _TRAINING_JSONL.exists():
            try:
                training_samples = sum(
                    1 for line in _TRAINING_JSONL.open("r", encoding="utf-8") if line.strip()
                )
            except OSError:
                pass

        return jsonify({
            "cycle_count": state.get("cycle_count", 0),
            "total_samples": training_samples,
            "discovered_hashtags": state.get("discovered_hashtags", []),
            "discovered_searches": state.get("discovered_searches", []),
            "history": state.get("history", []),
            "raw_post_count": total_raw,
        })

    @app.route("/api/monitor/posts")
    def api_monitor_posts():
        limit = request.args.get("limit", 100, type=int)
        raw_files = sorted(
            _RAW_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True
        ) if _RAW_DIR.exists() else []

        posts = []
        for f in raw_files:
            try:
                data = json.loads(f.read_text("utf-8"))
                source = f.stem
                for p in data:
                    caption = p.get("caption", "").strip()
                    if not caption:
                        continue
                    posts.append({
                        "caption": caption[:200],
                        "user": p.get("user", ""),
                        "source": source,
                        "hashtags": p.get("hashtags", []),
                        "likes": p.get("likes", 0),
                        "media_type": p.get("media_type", "photo"),
                        "timestamp": p.get("timestamp", ""),
                    })
            except Exception:
                continue

        # Sort by timestamp descending, return latest
        posts.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return jsonify(posts[:limit])

    return app
