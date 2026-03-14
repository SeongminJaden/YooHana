#!/usr/bin/env python3
"""수집 + 미디어 다운로드 + 분석 통합 스크립트."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.utils.logger import get_logger
from src.data_pipeline.browser_crawler import InstagramBrowserCrawler
from src.data_pipeline.media_downloader import (
    download_image, download_video, analyze_image,
    analyze_video_basic, extract_thumbnail_from_video,
)

logger = get_logger()

MEDIA_DIR = PROJECT_ROOT / "data" / "media"
RAW_DIR = PROJECT_ROOT / "data" / "raw"


def analyze_post_media(post: dict) -> dict:
    """Download and analyze all media from a single post."""
    analysis = {
        "media_id": post.get("media_id", ""),
        "media_type": post.get("media_type", "photo"),
        "carousel_count": post.get("carousel_count", 1),
        "instagram_descriptions": post.get("image_descriptions", []),
        "images": [],
        "video": None,
    }

    # Download and analyze images
    for url in post.get("image_urls", []):
        img_path = download_image(url)
        if img_path:
            img_info = analyze_image(img_path)
            analysis["images"].append(img_info)

    # Download and analyze video
    video_url = post.get("video_url", "")
    if video_url:
        vid_path = download_video(video_url)
        if vid_path:
            vid_info = analyze_video_basic(vid_path)
            # Extract thumbnail and analyze it too
            thumb = extract_thumbnail_from_video(vid_path)
            if thumb:
                vid_info["thumbnail_analysis"] = analyze_image(thumb)
            analysis["video"] = vid_info

    return analysis


def main():
    import argparse

    parser = argparse.ArgumentParser(description="수집 + 미디어 분석")
    parser.add_argument("--source", choices=["hashtag", "search", "explore", "user"],
                       default="hashtag", help="수집 소스")
    parser.add_argument("--target", type=str, default="일상스타그램", help="해시태그/검색어/유저네임")
    parser.add_argument("--count", type=int, default=5, help="수집할 게시글 수")
    args = parser.parse_args()

    crawler = InstagramBrowserCrawler(headless=False, slow_mo=300)

    try:
        if not crawler.login():
            logger.error("로그인 실패!")
            sys.exit(1)

        logger.info("로그인 성공! 수집+분석 시작...")

        # Crawl
        if args.source == "hashtag":
            posts = crawler.crawl_hashtag(args.target, max_posts=args.count)
        elif args.source == "search":
            posts = crawler.search_and_crawl(args.target, max_results=args.count)
        elif args.source == "explore":
            posts = crawler.crawl_explore(max_posts=args.count)
        elif args.source == "user":
            posts = crawler.crawl_user(args.target, max_posts=args.count)
        else:
            posts = []

        logger.info("수집된 게시글: {} 개", len(posts))

        # Analyze media for each post
        all_analyses = []
        for i, post in enumerate(posts):
            logger.info("[{}/{}] @{} - 미디어 분석 중...", i + 1, len(posts), post.get("user", "?"))
            analysis = analyze_post_media(post)

            # Merge analysis back into post data
            post["media_analysis"] = analysis
            all_analyses.append(analysis)

            # Print summary
            n_imgs = len(analysis["images"])
            has_vid = analysis["video"] is not None
            descs = analysis["instagram_descriptions"]

            logger.info(
                "  이미지 {}장, 영상 {}, 캐러셀 {}장",
                n_imgs,
                "있음" if has_vid else "없음",
                analysis["carousel_count"],
            )
            if descs:
                logger.info("  Instagram 설명: {}", descs[0][:100])
            if analysis["images"]:
                img = analysis["images"][0]
                logger.info(
                    "  첫 이미지: {}x{} {} {} {} 채도={:.2f}",
                    img.get("width", "?"), img.get("height", "?"),
                    img.get("orientation", "?"),
                    img.get("tone", "?"),
                    img.get("temperature", "?"),
                    img.get("saturation", 0),
                )
            if has_vid:
                vid = analysis["video"]
                logger.info(
                    "  영상: {:.1f}초 {}x{} {} fps={}",
                    vid.get("duration_sec", 0),
                    vid.get("width", "?"), vid.get("height", "?"),
                    vid.get("duration_category", "?"),
                    vid.get("fps", "?"),
                )

        # Save combined results
        out_path = RAW_DIR / f"analyzed_{args.source}_{args.target.replace(' ', '_')}.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2, default=str)
        logger.info("분석 결과 저장: {}", out_path)

        # Summary stats
        print("\n" + "=" * 60)
        print("미디어 분석 요약")
        print("=" * 60)
        total_imgs = sum(len(a["images"]) for a in all_analyses)
        total_vids = sum(1 for a in all_analyses if a["video"])
        total_carousel = sum(1 for a in all_analyses if a["carousel_count"] > 1)

        print(f"  게시글: {len(posts)}개")
        print(f"  이미지: {total_imgs}장")
        print(f"  영상: {total_vids}개")
        print(f"  캐러셀: {total_carousel}개")

        # Image style distribution
        if all_analyses:
            tones = [img.get("tone") for a in all_analyses for img in a["images"] if "tone" in img]
            temps = [img.get("temperature") for a in all_analyses for img in a["images"] if "temperature" in img]
            styles = [img.get("color_style") for a in all_analyses for img in a["images"] if "color_style" in img]
            orientations = [img.get("orientation") for a in all_analyses for img in a["images"] if "orientation" in img]

            if tones:
                from collections import Counter
                print(f"\n  톤 분포: {dict(Counter(tones))}")
                print(f"  색온도: {dict(Counter(temps))}")
                print(f"  색감: {dict(Counter(styles))}")
                print(f"  방향: {dict(Counter(orientations))}")

            # Video stats
            if total_vids:
                durations = [a["video"]["duration_sec"] for a in all_analyses if a["video"] and "duration_sec" in a["video"]]
                if durations:
                    print(f"\n  영상 길이: 평균 {sum(durations)/len(durations):.1f}초, 최소 {min(durations):.1f}초, 최대 {max(durations):.1f}초")

    finally:
        crawler.close()


if __name__ == "__main__":
    main()
