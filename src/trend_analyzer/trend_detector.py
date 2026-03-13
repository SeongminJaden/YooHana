"""
Trend pattern detection and content brief generation.

Takes a batch of media analyses produced by ``MediaAnalyzer`` and
identifies recurring patterns in visual style, audio, captions, and
themes.  The ``generate_content_brief`` method translates those patterns
into actionable instructions for the AI persona's next piece of content.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger()


class TrendDetector:
    """Detect recurring patterns across multiple analysed media items.

    This class is stateless – all data is passed via method arguments.
    """

    # ------------------------------------------------------------------
    # Pattern detection
    # ------------------------------------------------------------------

    def detect_patterns(self, analyses: list[dict]) -> dict:
        """Find common patterns across a list of full media analyses.

        Parameters
        ----------
        analyses : list[dict]
            Each element is the output of ``MediaAnalyzer.full_analysis()``
            (keys: ``"video"``, ``"audio"``, ``"caption"``).

        Returns
        -------
        dict
            ``{"visual_trends", "audio_trends", "caption_trends",
            "top_themes", "recommended_style"}``
        """
        if not analyses:
            return {
                "visual_trends": [],
                "audio_trends": [],
                "caption_trends": [],
                "top_themes": [],
                "recommended_style": {},
            }

        visual_trends = self._detect_visual_patterns(analyses)
        audio_trends = self._detect_audio_patterns(analyses)
        caption_trends = self._detect_caption_patterns(analyses)
        top_themes = self._detect_themes(analyses)
        recommended_style = self._build_recommended_style(
            visual_trends, audio_trends, caption_trends,
        )

        result = {
            "visual_trends": visual_trends,
            "audio_trends": audio_trends,
            "caption_trends": caption_trends,
            "top_themes": top_themes,
            "recommended_style": recommended_style,
        }

        logger.info(
            "Pattern detection complete: {} visual, {} audio, {} caption trends",
            len(visual_trends),
            len(audio_trends),
            len(caption_trends),
        )
        return result

    # ------------------------------------------------------------------
    # Engagement ranking
    # ------------------------------------------------------------------

    @staticmethod
    def rank_by_engagement(items: list[dict]) -> list[dict]:
        """Sort media metadata dicts by a weighted engagement score.

        The score formula is::

            score = likes + comments_count * 2 + views * 0.1

        Parameters
        ----------
        items : list[dict]
            Metadata dicts (from ``TrendScraper``), each containing
            ``likes``, ``comments_count``, and ``views`` fields.

        Returns
        -------
        list[dict]
            The same list sorted in descending order of engagement, with
            an ``"engagement_score"`` key injected into each item.
        """
        for item in items:
            likes = item.get("likes", 0) or 0
            comments = item.get("comments_count", 0) or 0
            views = item.get("views", 0) or 0
            item["engagement_score"] = likes + comments * 2 + views * 0.1

        ranked = sorted(items, key=lambda x: x["engagement_score"], reverse=True)
        logger.info(
            "Ranked {} items by engagement (top score: {:.0f})",
            len(ranked),
            ranked[0]["engagement_score"] if ranked else 0,
        )
        return ranked

    # ------------------------------------------------------------------
    # Trending audio
    # ------------------------------------------------------------------

    @staticmethod
    def get_trending_audio_ids(items: list[dict]) -> list[dict]:
        """Identify the most frequently used audio tracks.

        Parameters
        ----------
        items : list[dict]
            Metadata dicts containing ``"audio_id"`` and ``"audio_name"``.

        Returns
        -------
        list[dict]
            ``[{"audio_id", "audio_name", "usage_count"}, ...]``
            sorted by usage count descending.
        """
        audio_counter: Counter[str] = Counter()
        audio_names: dict[str, str] = {}

        for item in items:
            aid = item.get("audio_id")
            if aid:
                audio_counter[aid] += 1
                name = item.get("audio_name") or "Unknown"
                audio_names.setdefault(aid, name)

        trending = [
            {
                "audio_id": aid,
                "audio_name": audio_names.get(aid, "Unknown"),
                "usage_count": count,
            }
            for aid, count in audio_counter.most_common()
        ]

        logger.info("Found {} distinct audio tracks", len(trending))
        return trending

    # ------------------------------------------------------------------
    # Content brief generation
    # ------------------------------------------------------------------

    def generate_content_brief(
        self,
        patterns: dict,
        persona: Any,
    ) -> dict:
        """Create a content brief tailored to the AI persona.

        The brief adapts detected trends to fit the persona's identity,
        suggesting topic, visual style, music choice, caption approach,
        and hashtags.

        Parameters
        ----------
        patterns : dict
            Output of ``detect_patterns()``.
        persona
            A ``Persona`` instance (``src.persona.character.Persona``).

        Returns
        -------
        dict
            ``{"topic", "visual_style", "music_suggestion", "caption_style",
            "hashtags", "duration", "composition", "color_palette"}``
        """
        recommended = patterns.get("recommended_style", {})
        top_themes = patterns.get("top_themes", [])
        visual_trends = patterns.get("visual_trends", [])
        audio_trends = patterns.get("audio_trends", [])
        caption_trends = patterns.get("caption_trends", [])

        # --- Topic ---
        topic = self._select_topic(top_themes, persona)

        # --- Visual style ---
        visual_style = recommended.get("visual_style", "natural lighting, clean composition")
        color_palette = recommended.get("color_palette", [])
        composition = recommended.get("composition", "medium")

        # Adapt visual style to persona
        if hasattr(persona, "appearance_prompt"):
            visual_style = f"{persona.appearance_prompt}. Trending style: {visual_style}"

        # --- Music ---
        music_suggestion = self._build_music_suggestion(audio_trends, recommended)

        # --- Caption style ---
        caption_style = self._build_caption_style(caption_trends, recommended, persona)

        # --- Hashtags ---
        hashtags: list[str] = []
        if hasattr(persona, "get_hashtags"):
            hashtags = persona.get_hashtags(topic)
        # Merge trending hashtags from caption analysis
        for trend in caption_trends:
            if isinstance(trend, dict) and "trending_hashtags" in trend:
                hashtags.extend(trend["trending_hashtags"])
        # Deduplicate
        seen: set[str] = set()
        unique_hashtags: list[str] = []
        for tag in hashtags:
            if tag not in seen:
                seen.add(tag)
                unique_hashtags.append(tag)
        hashtags = unique_hashtags[:15]

        # --- Duration ---
        duration = recommended.get("duration", 15.0)

        brief = {
            "topic": topic,
            "visual_style": visual_style,
            "music_suggestion": music_suggestion,
            "caption_style": caption_style,
            "hashtags": hashtags,
            "duration": duration,
            "composition": composition,
            "color_palette": color_palette,
        }

        logger.info(
            "Content brief generated – topic: '{}', duration: {}s",
            topic, duration,
        )
        return brief

    # ------------------------------------------------------------------
    # Private helpers – visual patterns
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_visual_patterns(analyses: list[dict]) -> list[dict]:
        """Extract common visual patterns from analyses."""
        all_colors: list[str] = []
        all_compositions: list[str] = []
        all_scene_types: list[str] = []
        all_transitions: list[str] = []
        durations: list[float] = []
        has_text_count = 0
        total = len(analyses)

        for analysis in analyses:
            video = analysis.get("video", {})
            all_colors.extend(video.get("dominant_colors", []))
            all_compositions.append(video.get("composition", "unknown"))
            all_scene_types.extend(video.get("scene_types", []))
            all_transitions.append(video.get("transition_style", "cut"))
            duration = video.get("duration", 0.0)
            if duration > 0:
                durations.append(duration)
            if video.get("has_text_overlay", False):
                has_text_count += 1

        trends: list[dict] = []

        # Dominant colours
        color_counter = Counter(all_colors)
        if color_counter:
            trends.append({
                "type": "dominant_colors",
                "top_colors": [c for c, _ in color_counter.most_common(5)],
                "sample_size": total,
            })

        # Compositions
        comp_counter = Counter(all_compositions)
        if comp_counter:
            trends.append({
                "type": "composition",
                "most_common": comp_counter.most_common(1)[0][0],
                "distribution": dict(comp_counter),
            })

        # Scene types
        scene_counter = Counter(all_scene_types)
        if scene_counter:
            trends.append({
                "type": "scene_types",
                "top_scenes": [s for s, _ in scene_counter.most_common(3)],
            })

        # Transitions
        trans_counter = Counter(all_transitions)
        if trans_counter:
            trends.append({
                "type": "transitions",
                "most_common": trans_counter.most_common(1)[0][0],
                "distribution": dict(trans_counter),
            })

        # Duration stats
        if durations:
            avg_dur = sum(durations) / len(durations)
            trends.append({
                "type": "duration",
                "average": round(avg_dur, 1),
                "min": round(min(durations), 1),
                "max": round(max(durations), 1),
            })

        # Text overlay prevalence
        if total > 0:
            trends.append({
                "type": "text_overlay",
                "prevalence": round(has_text_count / total, 2),
                "count": has_text_count,
                "total": total,
            })

        return trends

    # ------------------------------------------------------------------
    # Private helpers – audio patterns
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_audio_patterns(analyses: list[dict]) -> list[dict]:
        """Extract common audio patterns from analyses."""
        voice_count = 0
        music_count = 0
        tempos: list[float] = []
        energies: list[str] = []
        total = len(analyses)

        for analysis in analyses:
            audio = analysis.get("audio", {})
            if audio.get("has_voice"):
                voice_count += 1
            if audio.get("has_music"):
                music_count += 1
            tempo = audio.get("music_tempo")
            if tempo and tempo > 0:
                tempos.append(tempo)
            energy = audio.get("music_energy", "unknown")
            if energy != "unknown":
                energies.append(energy)

        trends: list[dict] = []

        if total > 0:
            trends.append({
                "type": "voice_vs_music",
                "voice_ratio": round(voice_count / total, 2),
                "music_ratio": round(music_count / total, 2),
                "voice_count": voice_count,
                "music_count": music_count,
                "total": total,
            })

        if tempos:
            avg_tempo = sum(tempos) / len(tempos)
            trends.append({
                "type": "tempo",
                "average": round(avg_tempo, 1),
                "min": round(min(tempos), 1),
                "max": round(max(tempos), 1),
            })

        energy_counter = Counter(energies)
        if energy_counter:
            trends.append({
                "type": "energy",
                "most_common": energy_counter.most_common(1)[0][0],
                "distribution": dict(energy_counter),
            })

        return trends

    # ------------------------------------------------------------------
    # Private helpers – caption patterns
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_caption_patterns(analyses: list[dict]) -> list[dict]:
        """Extract common caption style patterns from analyses."""
        lengths: list[int] = []
        emoji_counts: list[int] = []
        hashtag_counts: list[int] = []
        tones: list[str] = []
        cta_count = 0
        total = len(analyses)

        for analysis in analyses:
            caption = analysis.get("caption", {})
            length = caption.get("length", 0)
            if length > 0:
                lengths.append(length)
            emoji_counts.append(caption.get("emoji_count", 0))
            hashtag_counts.append(caption.get("hashtag_count", 0))
            tone = caption.get("tone", "neutral")
            tones.append(tone)
            if caption.get("has_cta"):
                cta_count += 1

        trends: list[dict] = []

        if lengths:
            avg_len = sum(lengths) / len(lengths)
            trends.append({
                "type": "caption_length",
                "average": round(avg_len, 0),
                "min": min(lengths),
                "max": max(lengths),
            })

        if emoji_counts:
            avg_emoji = sum(emoji_counts) / len(emoji_counts)
            trends.append({
                "type": "emoji_usage",
                "average": round(avg_emoji, 1),
                "max_seen": max(emoji_counts),
            })

        if hashtag_counts:
            avg_hashtags = sum(hashtag_counts) / len(hashtag_counts)
            trends.append({
                "type": "hashtag_usage",
                "average": round(avg_hashtags, 1),
                "max_seen": max(hashtag_counts),
            })

        tone_counter = Counter(tones)
        if tone_counter:
            trends.append({
                "type": "tone",
                "most_common": tone_counter.most_common(1)[0][0],
                "distribution": dict(tone_counter),
            })

        if total > 0:
            trends.append({
                "type": "cta_presence",
                "ratio": round(cta_count / total, 2),
                "count": cta_count,
                "total": total,
            })

        return trends

    # ------------------------------------------------------------------
    # Private helpers – themes
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_themes(analyses: list[dict]) -> list[str]:
        """Infer top content themes from scene types and transcripts."""
        theme_signals: list[str] = []

        for analysis in analyses:
            video = analysis.get("video", {})
            audio = analysis.get("audio", {})

            # Scene types as theme proxies
            for scene in video.get("scene_types", []):
                theme_signals.append(scene)

            # Keywords from transcripts
            transcript = audio.get("transcript")
            if transcript:
                # Simple keyword extraction
                for word in transcript.split():
                    clean = word.strip(".,!?;:").lower()
                    if len(clean) > 3:
                        theme_signals.append(clean)

        counter = Counter(theme_signals)
        top_themes = [theme for theme, _ in counter.most_common(10)]
        return top_themes

    # ------------------------------------------------------------------
    # Private helpers – recommended style
    # ------------------------------------------------------------------

    @staticmethod
    def _build_recommended_style(
        visual_trends: list[dict],
        audio_trends: list[dict],
        caption_trends: list[dict],
    ) -> dict:
        """Synthesise a single recommended style from detected trends."""
        style: dict[str, Any] = {}

        # Visual
        for trend in visual_trends:
            if trend.get("type") == "dominant_colors":
                style["color_palette"] = trend.get("top_colors", [])
            elif trend.get("type") == "composition":
                style["composition"] = trend.get("most_common", "medium")
            elif trend.get("type") == "transitions":
                style["transition"] = trend.get("most_common", "cut")
            elif trend.get("type") == "duration":
                style["duration"] = trend.get("average", 15.0)
            elif trend.get("type") == "text_overlay":
                prevalence = trend.get("prevalence", 0)
                style["use_text_overlay"] = prevalence > 0.5

        # Build visual style description
        colors = style.get("color_palette", [])
        comp = style.get("composition", "medium")
        color_desc = ", ".join(colors[:3]) if colors else "warm tones"
        style["visual_style"] = (
            f"{comp} shot, {color_desc} colour palette, "
            f"{style.get('transition', 'smooth')} transitions"
        )

        # Audio
        for trend in audio_trends:
            if trend.get("type") == "voice_vs_music":
                voice_ratio = trend.get("voice_ratio", 0)
                if voice_ratio > 0.6:
                    style["audio_type"] = "voiceover"
                elif voice_ratio > 0.3:
                    style["audio_type"] = "voice_and_music"
                else:
                    style["audio_type"] = "music_only"
            elif trend.get("type") == "tempo":
                style["target_tempo"] = trend.get("average", 120.0)
            elif trend.get("type") == "energy":
                style["music_energy"] = trend.get("most_common", "medium")

        # Caption
        for trend in caption_trends:
            if trend.get("type") == "caption_length":
                style["caption_length"] = trend.get("average", 100)
            elif trend.get("type") == "emoji_usage":
                style["emoji_count"] = round(trend.get("average", 2))
            elif trend.get("type") == "tone":
                style["caption_tone"] = trend.get("most_common", "conversational")
            elif trend.get("type") == "cta_presence":
                style["include_cta"] = trend.get("ratio", 0) > 0.4

        return style

    # ------------------------------------------------------------------
    # Private helpers – brief building
    # ------------------------------------------------------------------

    @staticmethod
    def _select_topic(top_themes: list[str], persona: Any) -> str:
        """Pick a topic that aligns with both trends and persona."""
        if not top_themes:
            return "trending daily content"

        # If persona has content themes, try to intersect
        persona_themes: list[str] = []
        if hasattr(persona, "_data"):
            content_cfg = persona._data.get("content_themes", {})
            main = content_cfg.get("main", [])
            persona_themes = [t.lower() for t in main] if main else []

        # Try to find overlap
        for theme in top_themes:
            for pt in persona_themes:
                if theme in pt or pt in theme:
                    return theme

        # Fall back to the top trending theme
        return top_themes[0]

    @staticmethod
    def _build_music_suggestion(
        audio_trends: list[dict], recommended: dict
    ) -> dict:
        """Build a music / audio suggestion dict."""
        suggestion: dict[str, Any] = {
            "type": recommended.get("audio_type", "music_only"),
            "energy": recommended.get("music_energy", "medium"),
            "target_tempo": recommended.get("target_tempo", 120.0),
        }

        # Add genre hint based on energy and tempo
        tempo = suggestion["target_tempo"]
        energy = suggestion["energy"]

        if energy == "high" and tempo > 130:
            suggestion["genre_hint"] = "EDM / upbeat pop"
        elif energy == "high":
            suggestion["genre_hint"] = "pop / dance"
        elif energy == "medium" and tempo > 100:
            suggestion["genre_hint"] = "indie pop / R&B"
        elif energy == "medium":
            suggestion["genre_hint"] = "chill pop / acoustic"
        elif energy == "low":
            suggestion["genre_hint"] = "lo-fi / ambient"
        else:
            suggestion["genre_hint"] = "trending audio"

        return suggestion

    @staticmethod
    def _build_caption_style(
        caption_trends: list[dict],
        recommended: dict,
        persona: Any,
    ) -> dict:
        """Build caption style guidance."""
        style: dict[str, Any] = {
            "target_length": int(recommended.get("caption_length", 100)),
            "emoji_count": recommended.get("emoji_count", 2),
            "tone": recommended.get("caption_tone", "conversational"),
            "include_cta": recommended.get("include_cta", True),
        }

        # Respect persona emoji limits
        if hasattr(persona, "max_emoji_per_post"):
            max_emoji = persona.max_emoji_per_post
            if style["emoji_count"] > max_emoji:
                style["emoji_count"] = max_emoji

        return style
