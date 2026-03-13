"""
Topic and hashtag generation for the AI Influencer.

Draws from persona content themes, seasonal context, and Korean holidays
to produce relevant topics and mixed Korean/English hashtag sets.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from src.persona.character import Persona
from src.utils.logger import get_logger

logger = get_logger()

# Korean holidays with approximate dates (MM-DD) and content suggestions.
# Dates that move each year (e.g. Chuseok, Lunar New Year) use common
# approximations; the caller should update yearly.
_KOREAN_HOLIDAYS: list[dict] = [
    {
        "name": "신정 (New Year's Day)",
        "date": "01-01",
        "content_idea": "새해 다짐 & 감성 일상",
    },
    {
        "name": "설날 (Lunar New Year)",
        "date": "01-29",
        "content_idea": "설날 분위기 & 한복 코디",
    },
    {
        "name": "삼일절 (Independence Movement Day)",
        "date": "03-01",
        "content_idea": "봄맞이 서울 나들이",
    },
    {
        "name": "어린이날 (Children's Day)",
        "date": "05-05",
        "content_idea": "동심으로 돌아가기 & 놀이공원",
    },
    {
        "name": "어버이날 (Parents' Day)",
        "date": "05-08",
        "content_idea": "감사한 마음 전하기",
    },
    {
        "name": "현충일 (Memorial Day)",
        "date": "06-06",
        "content_idea": "의미 있는 하루 보내기",
    },
    {
        "name": "광복절 (Liberation Day)",
        "date": "08-15",
        "content_idea": "여름 휴가 & 한국 여행",
    },
    {
        "name": "추석 (Chuseok)",
        "date": "09-17",
        "content_idea": "추석 분위기 & 한복 코디",
    },
    {
        "name": "한글날 (Hangul Day)",
        "date": "10-09",
        "content_idea": "한글 감성 캘리그라피 & 독서",
    },
    {
        "name": "할로윈 (Halloween)",
        "date": "10-31",
        "content_idea": "할로윈 코스튬 & 파티",
    },
    {
        "name": "빼빼로데이 (Pepero Day)",
        "date": "11-11",
        "content_idea": "빼빼로 만들기 & 친구 선물",
    },
    {
        "name": "크리스마스 (Christmas)",
        "date": "12-25",
        "content_idea": "크리스마스 데이트 코스 & 선물",
    },
    {
        "name": "발렌타인데이 (Valentine's Day)",
        "date": "02-14",
        "content_idea": "발렌타인 감성 카페 & 초콜릿",
    },
    {
        "name": "화이트데이 (White Day)",
        "date": "03-14",
        "content_idea": "봄 데이트 & 달콤한 선물",
    },
]

# Month-to-season mapping (Korean meteorological convention)
_MONTH_SEASON: dict[int, str] = {
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
}


class TopicGenerator:
    """Generate content topics and hashtags aligned with a persona.

    Parameters
    ----------
    persona : Persona
        The loaded persona instance containing content_themes and identity.
    """

    def __init__(self, persona: Persona) -> None:
        self.persona = persona
        self._data: dict = persona._data

    # ------------------------------------------------------------------
    # Topic generation
    # ------------------------------------------------------------------

    def generate_topics(
        self,
        count: int = 10,
        theme: str | None = None,
    ) -> list[str]:
        """Generate a list of content topics drawn from persona themes.

        Mixes primary and secondary themes with some randomness. If *theme*
        is provided, topics are biased toward that specific theme.

        Parameters
        ----------
        count : int
            Number of topics to generate.
        theme : str | None
            Optional theme to focus on (e.g. "카페", "패션").

        Returns
        -------
        list[str]
            A list of topic strings.
        """
        content_themes = self._data.get("content_themes", {})
        primary: list[str] = content_themes.get("primary", [])
        secondary: list[str] = content_themes.get("secondary", [])

        # If a specific theme is requested, filter to matching entries
        if theme:
            theme_lower = theme.lower()
            matching = [
                t for t in primary + secondary if theme_lower in t.lower()
            ]
            if matching:
                primary = matching
                secondary = []

        # Expand base themes into concrete topic ideas
        topic_pool: list[str] = []
        topic_pool.extend(self._expand_theme_ideas(primary, weight=2))
        topic_pool.extend(self._expand_theme_ideas(secondary, weight=1))

        # Add seasonal flavour
        seasonal = self.get_seasonal_topics()
        topic_pool.extend(seasonal)

        # Deduplicate while preserving order, then sample
        seen: set[str] = set()
        unique: list[str] = []
        for t in topic_pool:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        if len(unique) <= count:
            result = unique
        else:
            result = random.sample(unique, count)

        logger.debug("Generated {} topics (requested {})", len(result), count)
        return result

    # ------------------------------------------------------------------
    # Hashtag generation
    # ------------------------------------------------------------------

    def generate_hashtags(
        self,
        topic: str,
        count: int = 8,
    ) -> list[str]:
        """Generate a mixed set of Korean and English hashtags for a topic.

        Includes trending-style broad tags and niche/specific tags.

        Parameters
        ----------
        topic : str
            The content topic or caption theme.
        count : int
            Target number of hashtags.

        Returns
        -------
        list[str]
            A list of hashtag strings (with leading ``#``).
        """
        identity = self._data.get("identity", {})
        name_en = identity.get("name_en", "").replace(" ", "")

        tags: list[str] = []

        # 1. Persona base tag
        if name_en:
            tags.append(f"#{name_en}")

        # 2. Topic-derived Korean hashtags
        topic_clean = topic.replace(" ", "")
        tags.append(f"#{topic_clean}")

        # 3. Map topic keywords to curated tag sets
        keyword_tags = self._keyword_hashtags(topic)
        tags.extend(keyword_tags)

        # 4. Trending-style broad Korean tags
        broad_kr: list[str] = [
            "#일상",
            "#데일리",
            "#소통",
            "#인스타그램",
            "#감성",
            "#좋아요",
            "#오늘의기록",
        ]

        # 5. Trending-style broad English tags
        broad_en: list[str] = [
            "#daily",
            "#instagood",
            "#aesthetic",
            "#lifestyle",
            "#Seoul",
            "#korean",
            "#instadaily",
        ]

        # Mix broad tags (favour Korean slightly)
        random.shuffle(broad_kr)
        random.shuffle(broad_en)
        tags.extend(broad_kr[:2])
        tags.extend(broad_en[:2])

        # Deduplicate preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                unique.append(tag)

        result = unique[:count]
        logger.debug("Generated {} hashtags for topic '{}'", len(result), topic)
        return result

    # ------------------------------------------------------------------
    # Seasonal topics
    # ------------------------------------------------------------------

    def get_seasonal_topics(self) -> list[str]:
        """Return topic ideas appropriate for the current month / season.

        Draws from the persona's ``content_themes.seasonal`` config and
        adds extra ideas based on the time of year.

        Returns
        -------
        list[str]
            A list of seasonal topic strings.
        """
        now = datetime.now()
        month = now.month
        season = _MONTH_SEASON.get(month, "spring")

        content_themes = self._data.get("content_themes", {})
        seasonal_cfg: dict = content_themes.get("seasonal", {})
        season_keywords: list[str] = seasonal_cfg.get(season, [])

        topics: list[str] = list(season_keywords)

        # Extra month-specific ideas
        month_extras: dict[int, list[str]] = {
            1: ["신년 다짐", "겨울 감성 카페"],
            2: ["발렌타인 데이트", "겨울 끝자락 감성"],
            3: ["봄맞이 코디", "벚꽃 명소 탐방"],
            4: ["벚꽃 피크닉", "봄 나들이 OOTD"],
            5: ["장미 축제", "초여름 코디"],
            6: ["초여름 카페", "비 오는 날 감성"],
            7: ["여름 휴가 준비", "시원한 디저트 카페"],
            8: ["바다 여행", "여름 페스티벌"],
            9: ["가을 맞이 코디", "추석 연휴 일상"],
            10: ["단풍 나들이", "할로윈 코스튬"],
            11: ["가을 감성 독서", "따뜻한 음료 추천"],
            12: ["크리스마스 분위기", "연말 회고"],
        }
        extras = month_extras.get(month, [])
        topics.extend(extras)

        logger.debug(
            "Seasonal topics for month {} ({}): {}",
            month,
            season,
            len(topics),
        )
        return topics

    # ------------------------------------------------------------------
    # Korean holidays
    # ------------------------------------------------------------------

    def get_korean_holidays(self) -> list[dict]:
        """Return upcoming Korean holidays (within 30 days) with content ideas.

        Returns
        -------
        list[dict]
            Each dict has keys: ``name``, ``date`` (MM-DD), ``content_idea``.
        """
        now = datetime.now()
        upcoming: list[dict] = []

        for holiday in _KOREAN_HOLIDAYS:
            try:
                h_date = datetime.strptime(
                    f"{now.year}-{holiday['date']}",
                    "%Y-%m-%d",
                )
            except ValueError:
                continue

            # Consider the holiday if it's within the next 30 days
            delta = (h_date - now).days
            if 0 <= delta <= 30:
                upcoming.append(holiday)

        logger.debug("Found {} upcoming holidays within 30 days", len(upcoming))
        return upcoming

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_theme_ideas(themes: list[str], weight: int = 1) -> list[str]:
        """Expand high-level theme descriptions into concrete topic ideas.

        Each theme string (e.g. "일상 라이프스타일 (카페, 산책, 일상)") is
        broken into the parenthetical examples as separate ideas, plus
        the theme itself. The *weight* controls how many copies are added
        to the pool for sampling bias.
        """
        ideas: list[str] = []
        for theme in themes:
            # Add the full theme description
            ideas.extend([theme] * weight)

            # Extract parenthetical examples if present
            if "(" in theme and ")" in theme:
                paren_start = theme.index("(") + 1
                paren_end = theme.index(")")
                examples = theme[paren_start:paren_end]
                for ex in examples.split(","):
                    ex = ex.strip()
                    if ex:
                        ideas.extend([ex] * weight)

            # Extract keywords separated by & or /
            for sep in ("&", "/"):
                if sep in theme:
                    parts = theme.split(sep)
                    for part in parts:
                        part = part.strip().split("(")[0].strip()
                        if part and len(part) > 1:
                            ideas.extend([part] * weight)

        return ideas

    @staticmethod
    def _keyword_hashtags(topic: str) -> list[str]:
        """Map topic keywords to curated hashtag sets."""
        topic_lower = topic.lower()

        keyword_map: dict[str, list[str]] = {
            "카페": ["#카페스타그램", "#cafehopping", "#커피", "#카페추천", "#coffeelover"],
            "패션": ["#패션스타그램", "#OOTD", "#데일리룩", "#코디", "#fashion"],
            "ootd": ["#OOTD", "#오오티디", "#데일리룩", "#whatiwore", "#outfitoftheday"],
            "맛집": ["#맛집스타그램", "#먹스타그램", "#foodie", "#맛집추천", "#foodstagram"],
            "서울": ["#서울스타그램", "#서울여행", "#seoul", "#seoullife", "#서울핫플"],
            "여행": ["#여행스타그램", "#travel", "#여행", "#travelgram", "#trip"],
            "자기계발": ["#자기계발", "#성장", "#motivation", "#독서", "#영감"],
            "음악": ["#음악스타그램", "#music", "#플레이리스트", "#감성음악", "#playlist"],
            "벚꽃": ["#벚꽃", "#벚꽃스타그램", "#cherryblossom", "#봄", "#spring"],
            "바다": ["#바다스타그램", "#beach", "#여름", "#summer", "#바다여행"],
            "단풍": ["#단풍", "#단풍스타그램", "#가을", "#autumn", "#autumnleaves"],
            "크리스마스": ["#크리스마스", "#christmas", "#merrychristmas", "#겨울", "#xmas"],
            "피크닉": ["#피크닉", "#picnic", "#나들이", "#소풍", "#봄나들이"],
            "코디": ["#코디", "#데일리룩", "#스타일", "#dailylook", "#style"],
            "한복": ["#한복", "#hanbok", "#전통", "#한복스타그램", "#koreanstyle"],
            "디저트": ["#디저트", "#dessert", "#디저트스타그램", "#맛있다", "#sweet"],
        }

        tags: list[str] = []
        for keyword, tag_list in keyword_map.items():
            if keyword in topic_lower:
                tags.extend(tag_list)

        return tags
