from datetime import date

from django.test import TestCase
from django.urls import reverse

from core.models import News


class NewsItemTest(TestCase):
    def test_paragraphs_and_line_breaks_are_kept(self):
        news = News.objects.create(title='Neu', publish_date=date(2026, 11, 13),
                                   news_text='Absatz eins.\r\n\r\nSo geht\'s:\r\n1. Schritt\r\n2. <b>Schritt</b>')
        html = self.client.get(reverse('news-item'), {'item': news.pk}).content.decode()
        self.assertIn('<p>Absatz eins.</p>', html)
        self.assertIn('So geht&#x27;s:<br>1. Schritt<br>', html)
        self.assertIn('&lt;b&gt;Schritt&lt;/b&gt;', html)  # weiterhin escaped
