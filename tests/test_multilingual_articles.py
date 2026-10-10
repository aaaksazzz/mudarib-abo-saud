import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class MultilingualArticleTests(unittest.TestCase):
    def test_catalog_defines_20_topics_and_five_languages(self):
        source = (ROOT / "multilingual_articles.py").read_text(encoding="utf-8")
        self.assertIn('LANGS = ("ar", "en", "es", "fr", "hi")', source)
        topic_slugs = [line for line in source.splitlines() if line.startswith('("') and '", {"ar":' in line]
        self.assertEqual(len(topic_slugs), 25)
        self.assertIn('f"/learn/{l}/{slug}"', source)
        self.assertEqual(len(topic_slugs) * 5, 125)

    def test_article_pages_include_seo_metadata_and_safety_note(self):
        source = (ROOT / "multilingual_articles.py").read_text(encoding="utf-8")
        self.assertIn('rel="canonical"', source)
        self.assertIn('hreflang="{l}"', source)
        self.assertIn('hreflang="x-default"', source)
        self.assertIn('application/ld+json', source)
        self.assertIn('not a buy or sell recommendation', source)

    def test_sitemap_includes_localized_article_urls(self):
        source = (ROOT / "seo_routes.py").read_text(encoding="utf-8")
        self.assertIn('urls.add(f"/learn/{lang}/{slug}")', source)
        self.assertIn('router.include_router(multilingual_router)', source)


if __name__ == "__main__":
    unittest.main()
