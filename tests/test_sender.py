import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from wizwalker import Keycode
from xuanyi.api import TranslationError
from xuanyi.sender import send_once, validate_message


class FakeMouse:
    def __init__(self):
        self.click_window = AsyncMock()
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


def setup(draft='', prefix='Say:', owned=True):
    state = {'draft': draft, 'prefix': prefix, 'active': True}
    nodes = {}
    for index, name in enumerate(('WorldView', 'WizardChatBox', 'chatContainer', 'chatEditContainer', 'chatEdit', 'chatEditPrefix')):
        nodes[name] = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            read_base_address=AsyncMock(return_value=0x20000 + index * 0x1000),
            maybe_read_type_name=AsyncMock(return_value='ControlFreeChat' if name == 'chatEdit' else 'ControlText'),
            get_child_by_name=AsyncMock(side_effect=lambda name: nodes[name]))
    nodes['chatEdit'].parent = AsyncMock(return_value=nodes['chatEditContainer'])
    root = SimpleNamespace(read_base_address=AsyncMock(return_value=0x10000),
                           get_child_by_name=AsyncMock(side_effect=lambda name: nodes[name]))
    client = SimpleNamespace(window_handle=123, title='test client', root_window=root,
        is_running=Mock(return_value=True), is_loading=AsyncMock(return_value=False),
        is_in_dialog=AsyncMock(return_value=False), mouse_handler=FakeMouse(),
        send_hotkey=AsyncMock())
    reader = SimpleNamespace(client=client, owned_hook=owned, prepare_send=AsyncMock())

    async def text(node):
        return state['prefix'] if node is nodes['chatEditPrefix'] else state['draft']

    async def type_text(client, value):
        state['draft'] = value

    return reader, nodes, state, text, type_text


class SenderTests(unittest.IsolatedAsyncioTestCase):
    async def send(self, reader, state, text, typer, value='hello', api=None):
        with patch('xuanyi.sender.read_control_text', new=AsyncMock(side_effect=text)), \
             patch('xuanyi.sender._type_chat', new=AsyncMock(side_effect=typer)) as typed:
            result = await send_once(reader, value, api, lambda: state['active'], lambda _: None)
        return result, typed

    async def test_english_fills_body_only_without_enter_or_api(self):
        reader, nodes, state, text, typer = setup()
        api = Mock()
        result, typed = await self.send(reader, state, text, typer, api=api)
        self.assertTrue(result['filled'])
        self.assertFalse(result['invoked'])
        typed.assert_awaited_once_with(reader.client, 'hello')
        reader.client.send_hotkey.assert_not_awaited()
        api.translate.assert_not_called()

    async def test_chinese_only_inputs_valid_english_translation(self):
        reader, nodes, state, text, typer = setup()
        api = SimpleNamespace(translate=Mock(return_value='hello'))
        result, typed = await self.send(reader, state, text, typer, '你好', api)
        api.translate.assert_called_once_with('你好', target_language='en')
        typed.assert_awaited_once_with(reader.client, 'hello')
        self.assertTrue(result['filled'])
        self.assertFalse(result['invoked'])
        reader.client.send_hotkey.assert_not_awaited()

    async def test_draft_and_hidden_input_block_click_and_send(self):
        for kind in ('draft', 'hidden'):
            reader, nodes, state, text, typer = setup(draft='existing' if kind == 'draft' else '')
            if kind == 'hidden':
                nodes['chatEditContainer'].is_visible.return_value = False
            with self.assertRaises(RuntimeError):
                await self.send(reader, state, text, typer)
            reader.client.mouse_handler.click_window.assert_not_awaited()
            reader.client.send_hotkey.assert_not_awaited()

    async def test_loading_and_npc_dialog_block_send(self):
        for method in ('is_loading', 'is_in_dialog'):
            reader, nodes, state, text, typer = setup()
            getattr(reader.client, method).return_value = True
            with self.assertRaises(RuntimeError):
                await self.send(reader, state, text, typer)
            reader.client.send_hotkey.assert_not_awaited()

    async def test_failed_and_invalid_translation_never_inputs_raw_chinese(self):
        for value in ('仍是中文', 'x' * 81, 'line\nbreak', RuntimeError('private-test-secret')):
            reader, nodes, state, text, typer = setup()
            api = SimpleNamespace(translate=Mock(side_effect=value) if isinstance(value, Exception) else Mock(return_value=value))
            with patch('xuanyi.sender._type_chat', new=AsyncMock()) as typed:
                with self.assertRaises(TranslationError) as caught:
                    await send_once(reader, '你好', api, lambda: True, lambda _: None)
            self.assertNotIn('private-test-secret', str(caught.exception))
            typed.assert_not_awaited()
            reader.client.send_hotkey.assert_not_awaited()

    async def test_missing_api_does_not_input_chinese(self):
        reader, nodes, state, text, typer = setup()
        with self.assertRaises(TranslationError):
            await self.send(reader, state, text, typer, '你好')
        self.assertEqual(state['draft'], '')
        reader.client.send_hotkey.assert_not_awaited()

    async def test_invalidation_during_translation_blocks_send(self):
        reader, nodes, state, text, typer = setup()
        def translate(*args, **kwargs):
            state['active'] = False
            return 'hello'
        with self.assertRaises(RuntimeError):
            await self.send(reader, state, text, typer, '你好', SimpleNamespace(translate=translate))
        self.assertEqual(state['draft'], '')
        reader.client.send_hotkey.assert_not_awaited()

    async def test_private_group_nearby_and_empty_prefix_all_preserved_without_enter(self):
        for prefix in ('马龙', 'Tell to Alex:', 'Group:', 'Say:', ''):
            with self.subTest(prefix=prefix):
                reader, nodes, state, text, typer = setup(prefix=prefix)
                result, typed = await self.send(reader, state, text, typer)
                self.assertTrue(result['filled'])
                self.assertFalse(result['invoked'])
                self.assertEqual(state['prefix'], prefix)
                typed.assert_awaited_once_with(reader.client, 'hello')
                nodes['chatEdit'].parent.assert_not_awaited()
                reader.client.send_hotkey.assert_not_awaited()

    async def test_readback_mismatch_never_presses_enter(self):
        reader, nodes, state, text, typer = setup()
        async def corrupt(client, value):
            state['draft'] = 'unexpected'
        with patch('xuanyi.sender.time', SimpleNamespace(monotonic=Mock(side_effect=[0, 2]))):
            with self.assertRaises(RuntimeError):
                await self.send(reader, state, text, corrupt)
        reader.client.send_hotkey.assert_not_awaited()

    async def test_borrowed_connection_refuses_inputs(self):
        reader, nodes, state, text, typer = setup(owned=False)
        with self.assertRaisesRegex(RuntimeError, '复用'):
            await self.send(reader, state, text, typer)
        reader.client.mouse_handler.click_window.assert_not_awaited()
        reader.client.send_hotkey.assert_not_awaited()

    def test_input_limits(self):
        for text in ('', 'x' * 81, 'x\ny', '😀', '\ud800'):
            with self.assertRaises(TranslationError):
                validate_message(text)
