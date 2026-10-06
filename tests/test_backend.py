import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xuanyi.backend import Backend


class BackendTests(unittest.IsolatedAsyncioTestCase):
    def backend(self):
        backend = Backend()
        backend.translation_queue = asyncio.Queue(maxsize=32)
        backend.reader = SimpleNamespace(handle=123)
        backend.translation_enabled = True
        backend.api = SimpleNamespace(translate=Mock(return_value='你好'))
        events = []
        backend.event.connect(events.append)
        return backend, events

    async def wait_for(self, condition):
        async with asyncio.timeout(1):
            while not condition():
                await asyncio.sleep(.005)

    async def test_original_immediate_correlated_translation_and_cache(self):
        backend, events = self.backend()
        worker = asyncio.create_task(backend.translate_pending())
        try:
            backend.enqueue_message('附近', 31, 'Amber', 'hello')
            self.assertEqual(events[0]['kind'], 'message')
            await self.wait_for(lambda: any(e['kind'] == 'translation' for e in events))
            backend.enqueue_message('附近', 31, 'Amber', 'hello')
            await self.wait_for(lambda: len([e for e in events if e['kind'] == 'translation']) == 2)
            self.assertEqual([e['id'] for e in events if e['kind'] == 'translation'], [1, 2])
            backend.api.translate.assert_called_once_with('hello')
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def test_disabled_never_queues_or_requests(self):
        backend, events = self.backend()
        backend.translation_enabled = False
        backend.enqueue_message('附近', 31, 'Amber', 'hello')
        self.assertEqual(events[0]['kind'], 'message')
        self.assertTrue(backend.translation_queue.empty())
        backend.api.translate.assert_not_called()

    async def test_queue_bounded_keeps_all_originals(self):
        backend, events = self.backend()
        for i in range(40):
            backend.enqueue_message('附近', 31, 'Amber', str(i))
        self.assertEqual(backend.translation_queue.qsize(), 32)
        self.assertEqual(len([e for e in events if e['kind'] == 'message']), 40)

    async def test_stale_inflight_translation_not_published(self):
        backend, events = self.backend()
        def translate(text):
            backend.generation += 1
            return 'stale'
        backend.api.translate.side_effect = translate
        worker = asyncio.create_task(backend.translate_pending())
        try:
            backend.enqueue_message('附近', 31, 'Amber', 'hello')
            await self.wait_for(lambda: backend.api.translate.called)
            await backend.translation_queue.join()
            self.assertFalse(any(e['kind'] == 'translation' for e in events))
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def test_unknown_error_sanitized_and_never_retried(self):
        backend, events = self.backend()
        backend.api.translate.side_effect = RuntimeError('private-test-secret')
        worker = asyncio.create_task(backend.translate_pending())
        try:
            backend.enqueue_message('附近', 31, 'Amber', 'hello')
            await backend.translation_queue.join()
            backend.api.translate.assert_called_once()
            self.assertNotIn('private-test-secret', str(events))
            self.assertTrue(any(e['kind'] == 'translation_status' for e in events))
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def test_all_verified_self_echoes_keep_original_without_translation(self):
        backend, events = self.backend()
        for channel, message in [('附近', 'hello'), ('附近', 'who am i?'), ('队伍', '中文原文')]:
            backend.enqueue_message(channel, 0, '你', message)
        self.assertTrue(backend.translation_queue.empty())
        self.assertEqual([e['message'] for e in events], ['hello', 'who am i?', '中文原文'])
        backend.api.translate.assert_not_called()

    async def test_other_player_same_body_is_still_translated(self):
        backend, events = self.backend()
        backend.enqueue_message('附近', 0, '你', 'hello')
        backend.enqueue_message('附近', 42, 'Other', 'hello')
        self.assertEqual(backend.translation_queue.qsize(), 1)

    async def test_linked_player_named_self_label_is_not_suppressed(self):
        backend, events = self.backend()
        backend.enqueue_message('附近', 42, '你', 'hello')
        self.assertEqual(backend.translation_queue.qsize(), 1)

    async def test_main_loop_stops_with_no_game_and_no_requests(self):
        backend = Backend()
        backend.command('shutdown')
        with patch('xuanyi.backend.available_clients', return_value=[]), \
             patch('xuanyi.backend.ChatTranslationAPI') as api:
            await backend.loop()
        api.assert_not_called()
        self.assertFalse(backend.running)
