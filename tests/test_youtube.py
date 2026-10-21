"""Real browser interaction on local fixture pages; never touches YouTube accounts."""
import unittest
from playwright.sync_api import sync_playwright
from corner.youtube import like_short

URL = 'https://www.youtube.com/shorts/aaaaaaaaaaa'


class LikeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        errors = []
        for channel in ('chrome', None):
            try:
                cls.browser = cls.playwright.chromium.launch(headless=True, **({'channel': channel} if channel else {}))
                return
            except Exception as exc:
                errors.append(str(exc))
        cls.playwright.stop()
        raise RuntimeError('Install a test browser with python -m playwright install chromium. ' + str(errors))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 900, 'height': 600})

    def tearDown(self):
        self.page.close()

    def fixture(self, pressed='false', extra='', handler="this.setAttribute('aria-pressed','true')", label='like this video along with 1.5 thousand other people'):
        # Deliberately changeable class names; only accessible semantics matter.
        html = f'''<html><body><script>window.clicks=0</script>
        <button class="random-class-not-a-selector" aria-label="{label}" {'aria-pressed='+chr(34)+pressed+chr(34) if pressed is not None else ''}
        onclick="window.clicks++;{handler}">Heart</button>{extra}</body></html>'''
        self.page.route('https://www.youtube.com/**', lambda route: route.fulfill(content_type='text/html', body=html))
        self.page.goto(URL)

    def test_clicks_once_and_never_unlikes(self):
        self.fixture()
        self.assertEqual(like_short(self.page, URL)['status'], 'liked')
        self.assertEqual(like_short(self.page, URL)['status'], 'already_liked')
        self.assertEqual(self.page.evaluate('clicks'), 1)

    def test_existing_like_is_untouched(self):
        self.fixture(pressed='true')
        self.assertEqual(like_short(self.page, URL)['status'], 'already_liked')
        self.assertEqual(self.page.evaluate('clicks'), 0)

    def test_wrong_short_is_not_liked(self):
        self.fixture()
        self.assertEqual(like_short(self.page, 'https://www.youtube.com/shorts/bbbbbbbbbbb')['status'], 'wrong_video')
        self.assertEqual(self.page.evaluate('clicks'), 0)

    def test_sign_in_required_without_clicking(self):
        self.fixture(extra='<a href="https://accounts.google.com">Sign in</a>')
        self.assertEqual(like_short(self.page, URL)['status'], 'needs_sign_in')
        self.assertEqual(self.page.evaluate('clicks'), 0)

    def test_ambiguous_buttons_are_not_clicked(self):
        self.fixture(extra='<button aria-label="Like" aria-pressed="false" onclick="window.clicks++">Other</button>')
        self.assertEqual(like_short(self.page, URL)['status'], 'ambiguous')
        self.assertEqual(self.page.evaluate('clicks'), 0)

    def test_offscreen_buttons_are_ignored(self):
        self.fixture(extra='<button style="position:absolute;top:2000px" aria-label="Like" aria-pressed="false" onclick="window.clicks+=100">Other Short</button>')
        self.assertEqual(like_short(self.page, URL)['status'], 'liked')
        self.assertEqual(self.page.evaluate('clicks'), 1)

    def test_unconfirmed_click_is_not_retried(self):
        self.fixture(handler='')
        self.assertEqual(like_short(self.page, URL, timeout=.25)['status'], 'unconfirmed')
        self.assertEqual(self.page.evaluate('clicks'), 1)

    def test_dislike_is_never_selected(self):
        self.fixture(label='Dislike this video')
        self.assertEqual(like_short(self.page, URL, timeout=.25)['status'], 'not_found')
        self.assertEqual(self.page.evaluate('clicks'), 0)

    def test_unknown_state_and_stop_prevent_clicks(self):
        self.fixture(pressed=None)
        self.assertEqual(like_short(self.page, URL)['status'], 'unknown_state')
        self.assertEqual(like_short(self.page, URL, stopped=lambda: True)['status'], 'cancelled')
        self.assertEqual(self.page.evaluate('clicks'), 0)
