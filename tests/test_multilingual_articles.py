import unittest

from multilingual_articles import DATA, LANGS, article_index, article_page


class MultilingualArticleTests(unittest.TestCase):
    def test_catalog_has_100_localized_pages(self):
        self.assertEqual(len(DATA), 20)
        self.assertEqual(len(LANGS), 5)
        self.assertEqual(len(DATA) * len(LANGS), 100)

    def test_article_page_has_seo_metadata_in_each_language(self):
        for lang in LANGS:
            with self.subTest(lang=lang):
                response = article_page(lang, "trading-for-beginners")
                self.assertEqual(response.status_code, 200)
                self.assertIn('rel="canonical"', response.body.decode("utf-8"))
                self.assertIn('hreflang="x-default"', response.body.decode("utf-8"))
                self.assertIn('application/ld+json', response.body.decode("utf-8"))

    def test_unknown_article_returns_404(self):
        self.assertEqual(article_page("en", "missing-topic").status_code, 404)
        self.assertEqual(article_page("xx", "trading-for-beginners").status_code, 404)

    def test_index_links_to_language_specific_articles(self):
        response = article_index()
        html = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/learn/ar/trading-for-beginners", html)
        self.assertIn("/learn/hi/trading-for-beginners", html)


if __name__ == "__main__":
    unittest.main()
