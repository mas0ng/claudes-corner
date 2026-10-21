import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from corner.media import choose_frames, demo, short_id
from corner.runner import Cancelled, Runner, browser_blocker
from development import create_app


class CoreTests(unittest.TestCase):
    def test_only_real_youtube_shorts(self):
        self.assertEqual(short_id('https://www.youtube.com/shorts/utx6V0qTx20?feature=share'), 'utx6V0qTx20')
        for url in ['https://youtube.com/shorts', 'https://evil.com/shorts/utx6V0qTx20',
                    'https://youtube.com.evil.com/shorts/utx6V0qTx20', 'https://youtube.com/watch?v=utx6V0qTx20',
                    'https://youtube.com/shorts/short', 'file://youtube.com/shorts/utx6V0qTx20']:
            self.assertIsNone(short_id(url))

    def test_scene_peaks_stay_spread_out(self):
        candidates = [(i / 10, 100 if i in (5, 25, 45, 65, 85) else 1) for i in range(100)]
        selected = choose_frames(candidates, 10)
        self.assertEqual([round(t, 1) for t, _ in selected], [.5, 2.5, 4.5, 6.5, 8.5])
        self.assertEqual(len({t for t, _ in selected}), 5)

    def test_static_video_centre_fallback(self):
        selected = choose_frames([(i / 10, 0) for i in range(100)], 10)
        self.assertEqual([round(t, 1) for t, _ in selected], [1, 3, 5, 7, 9])

    def test_demo_really_extracts_five_images(self):
        with tempfile.TemporaryDirectory() as temp:
            result = demo(Path(temp), 1)
            self.assertEqual(len(result['frames']), 5)
            self.assertTrue(result['demo'])
            self.assertTrue(all((Path(temp) / f['file']).stat().st_size > 100 for f in result['frames']))
            self.assertEqual(json.loads((Path(temp) / 'result.json').read_text())['id'], 'demo-1')

    def test_stop(self):
        runner = Runner()
        runner.stop_event.set()
        with self.assertRaises(Cancelled):
            runner.check()
        runner.stop_event.clear()
        runner.check()

    def test_api_validation_and_cross_site_protection(self):
        client = create_app().test_client()
        page = client.get('/').text
        token = page.split('name="corner-token" content="')[1].split('"')[0]
        self.assertEqual(client.post('/api/start', json={}).status_code, 403)
        self.assertEqual(client.post('/api/start', json={'browser': 'invalid'}, headers={'X-Corner-Token': token}).status_code, 400)
        self.assertEqual(client.get('/', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(client.get('/outputs/../../development.py').status_code, 404)

    def test_three_live_captures_reopen_feed_every_time(self):
        runner = Runner()
        page = SimpleNamespace(goto=lambda *a, **kw: navigations.append(a[0]), is_closed=lambda: False)
        context = SimpleNamespace(pages=[page], close=lambda: None)
        browser = SimpleNamespace(launch_persistent_context=lambda *a, **kw: context)
        playwright = SimpleNamespace(chromium=browser)
        class Manager:
            def __enter__(self):
                return playwright
            def __exit__(self, *args):
                pass
        fake = SimpleNamespace(sync_playwright=Manager)
        navigations = []
        urls = iter(f'https://www.youtube.com/shorts/aaaaaaaaaa{i}' for i in range(3))
        with tempfile.TemporaryDirectory() as temp, patch('corner.runner.OUTPUTS', Path(temp)), \
                patch('corner.runner.RUNTIME', Path(temp) / 'runtime'), \
                patch.dict('sys.modules', {'playwright.sync_api': fake}), \
                patch.object(runner, 'wait_for_short', side_effect=lambda *a: next(urls)), \
                patch.object(runner, 'export_cookies'), \
                patch.object(runner, 'run_process', return_value={'title': 'test'}):
            runner.state['run_id'] = 'test-run'
            runner.state['config'] = {'agent_mode': False}
            original = runner.record
            def record(result, folder):
                original(dict(result), folder)
                if len(runner.state['results']) == 3:
                    runner.stop_event.set()
            with patch.object(runner, 'record', side_effect=record):
                runner.run({'browser': 'chrome', 'model': 'tiny', 'agent_mode': False})
        self.assertEqual(navigations, ['https://www.youtube.com/shorts'] * 3)
        self.assertEqual(len(runner.state['results']), 3)
        self.assertFalse(runner.state['running'])

    def test_redirect_classification(self):
        self.assertEqual(browser_blocker('https://consent.youtube.com/m?continue=shorts')['kind'], 'consent')
        self.assertEqual(browser_blocker('https://accounts.google.com/signin')['kind'], 'redirect')
        self.assertEqual(browser_blocker('https://www.youtube.com/')['kind'], 'redirect')
        self.assertIsNone(browser_blocker('https://www.youtube.com/shorts'))
        self.assertIsNone(browser_blocker('https://www.youtube.com/shorts/utx6V0qTx20'))

    def test_consent_does_not_expire_and_can_be_stopped(self):
        runner = Runner()
        def tick(ms):
            self.assertEqual(runner.state['blocker']['kind'], 'consent')
            runner.stop_event.set()
        page = SimpleNamespace(url='https://consent.youtube.com/m', is_closed=lambda: False, wait_for_timeout=tick)
        with self.assertRaises(Cancelled):
            runner.wait_for_short(page, set())

    def test_reaction_handoff_persists_and_rejects_wrong_keys(self):
        runner = Runner()
        with tempfile.TemporaryDirectory() as temp, patch('corner.runner.OUTPUTS', Path(temp)):
            runner.state.update(run_id='session', config={'agent_mode': True})
            folder = Path(temp) / 'session' / 'video'
            folder.mkdir(parents=True)
            runner.record({'title': 'A scene'}, folder)
            self.assertEqual(runner.state['pending_reaction'], 'session/video')
            self.assertFalse(runner.reaction_event.is_set())
            with self.assertRaises(ValueError):
                runner.acknowledge('wrong', 'Hello')
            with self.assertRaises(ValueError):
                runner.acknowledge('session/video', '')
            runner.acknowledge('session/video', 'That jump surprised me.')
            self.assertTrue(runner.reaction_event.is_set())
            self.assertIsNone(runner.state['pending_reaction'])
            self.assertEqual(json.loads((folder / 'result.json').read_text())['reaction'], 'That jump surprised me.')

    def test_agent_next_returns_same_video_until_reacted(self):
        from corner.client import Client
        client = Client(False)
        state = {'running': True, 'pending_reaction': 'session/video', 'results': [
            {'folder': 'session/video', 'frames': [{'file': 'frame-1.jpg', 'time': 1}], 'transcript': 'hello'}]}
        with patch.object(client, 'request', return_value=state):
            first, second = client.next(0), client.next(0)
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'video')
        self.assertTrue(Path(first['images'][0]['path']).is_absolute())

    def test_invalid_feedback_does_not_release_or_change_video(self):
        from corner.feedback import validate_feedback
        for value in ({}, {'rating': True, 'would_like': True, 'would_comment': False, 'comment': ''},
                      {'rating': 6, 'would_like': True, 'would_comment': False, 'comment': ''},
                      {'rating': 4, 'would_like': 'yes', 'would_comment': False, 'comment': ''},
                      {'rating': 4, 'would_like': True, 'would_comment': True, 'comment': ''},
                      {'rating': 4, 'would_like': True, 'would_comment': False, 'comment': 'contradictory'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_feedback(value)
        runner = Runner()
        runner.state.update(pending_reaction='test', results=[{'folder': 'test'}])
        with self.assertRaises(ValueError):
            runner.acknowledge('test', 'A reaction', {})
        self.assertEqual(runner.state['pending_reaction'], 'test')
        self.assertNotIn('reaction', runner.state['results'][0])
        self.assertFalse(runner.reaction_event.is_set())

    def test_api_saves_feedback_with_reaction_and_library(self):
        runner = Runner()
        with tempfile.TemporaryDirectory() as temp, patch('corner.runner.OUTPUTS', Path(temp)):
            runner.state.update(run_id='test', config={'agent_mode': True})
            folder = Path(temp) / 'test/video'
            folder.mkdir(parents=True)
            runner.record({'id': 'test', 'title': 'Test video'}, folder)
            client = create_app(runner).test_client()
            token = client.get('/').text.split('name="corner-token" content="')[1].split('"')[0]
            feedback = {'rating': 5, 'would_like': True, 'would_comment': True, 'comment': '  What a reveal!  '}
            response = client.post('/api/react', json={'key': 'test/video', 'reaction': 'Loved the reveal.', 'feedback': feedback}, headers={'X-Corner-Token': token})
            self.assertEqual(response.status_code, 200)
            saved = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['feedback']['comment'], 'What a reveal!')
            self.assertEqual(saved['feedback']['rating'], 5)
            self.assertEqual(client.get('/api/library').json[0]['feedback'], saved['feedback'])
            self.assertTrue(runner.reaction_event.is_set())

    def test_mcp_passes_feedback_to_shared_api(self):
        import asyncio
        import mcp_server
        with patch.object(mcp_server.Client, 'react', return_value={'ok': True}) as react:
            asyncio.run(mcp_server.mcp.call_tool('acknowledge_reaction', {
                'key': 'test', 'reaction': 'Not my thing.', 'rating': 2,
                'would_like': False, 'would_comment': False, 'comment': ''}))
            react.assert_called_once_with('test', 'Not my thing.', {'rating': 2, 'would_like': False, 'would_comment': False, 'comment': ''})

    def test_mcp_returns_real_inline_image_blocks(self):
        import asyncio
        import mcp_server
        with tempfile.TemporaryDirectory() as temp:
            result = demo(Path(temp), 1)
            payload = {'status': 'video', 'key': 'test', 'video': result,
                       'images': [{'path': str(Path(temp) / f['file']), 'time': f['time']} for f in result['frames']]}
            with patch.object(mcp_server.Client, 'next', return_value=payload):
                content = asyncio.run(mcp_server.mcp.call_tool('next_video', {'wait_seconds': 0}))
            self.assertEqual(len([c for c in content if c.type == 'image']), 5)


if __name__ == '__main__':
    unittest.main()
