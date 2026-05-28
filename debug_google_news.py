from app import create_app
from app.services.google_news_service import (
    GOOGLE_NEWS_SEARCHES,
    build_google_news_url,
    clean_html_text,
    choose_best_article_url,
)
from app.services.article_fetch_service import extract_article_context
from app.services.news_ai_service import extract_news_signal_with_ai, extract_candidate_names

import feedparser


app = create_app()


def run_debug(limit_per_query=1):
    with app.app_context():
        print("=" * 80)
        print("PeopleSignal Google News Debug")
        print("=" * 80)

        for search in GOOGLE_NEWS_SEARCHES:
            print()
            print("-" * 80)
            print(f"SEARCH QUERY: {search['query']}")
            print("-" * 80)

            url = build_google_news_url(search["query"])
            feed = feedparser.parse(url)

            entries = feed.entries[:limit_per_query]

            if not entries:
                print("No entries returned.")
                continue

            for index, entry in enumerate(entries, start=1):
                raw_title = getattr(entry, "title", "") or "Untitled news item"
                raw_summary_html = getattr(entry, "summary", "") or ""

                title = clean_html_text(raw_title)
                summary = clean_html_text(raw_summary_html)

                article_url = choose_best_article_url(entry, raw_summary_html)
                article_context = extract_article_context(article_url)

                combined_text = " ".join(
                    [
                        title or "",
                        summary or "",
                        article_context.get("page_title", "") or "",
                        article_context.get("meta_title", "") or "",
                        article_context.get("meta_description", "") or "",
                        article_context.get("h1", "") or "",
                        article_context.get("body_preview", "") or "",
                    ]
                )

                candidates = extract_candidate_names(combined_text)

                extracted = extract_news_signal_with_ai(
                    title=title,
                    summary=summary,
                    link=article_url,
                    default_signal_type=search["signal_type"],
                    default_confidence=search["confidence_score"],
                    article_context=article_context,
                )

                print()
                print(f"ITEM {index}")
                print("=" * 80)

                print()
                print("GOOGLE NEWS TITLE:")
                print(title)

                print()
                print("GOOGLE NEWS SUMMARY:")
                print(summary[:800])

                print()
                print("RESOLVED ARTICLE URL:")
                print(article_url)

                print()
                print("ARTICLE CONTEXT")
                print("-" * 40)
                print("Final URL:", article_context.get("final_url"))
                print("Page title:", article_context.get("page_title"))
                print("Meta title:", article_context.get("meta_title"))
                print("Meta description:", article_context.get("meta_description"))
                print("H1:", article_context.get("h1"))
                print("Body preview length:", len(article_context.get("body_preview") or ""))

                print()
                print("BODY PREVIEW SAMPLE:")
                print((article_context.get("body_preview") or "")[:1000])

                print()
                print("CANDIDATE NAMES:")
                print(candidates)

                print()
                print("AI EXTRACTION RESULT:")
                print("-" * 40)
                for key, value in extracted.items():
                    print(f"{key}: {value}")

                print()
                print("=" * 80)


if __name__ == "__main__":
    run_debug(limit_per_query=1)