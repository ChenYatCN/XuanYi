import struct
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from wizwalker.memory.hooks import RootWindowHook
from xuanyi.reader import ChatReader, existing_root_export


def fake_client(*, borrowed=True, unknown=False):
    jump_at, hook_at, export = 0x10000, 0x20000, 0x30000
    jump = b'\xe9' + struct.pack('<i', hook_at - jump_at - 5) + b'\x90\x90'
    code = b'\x50\x49\x8b\x85\xd8\0\0\0\x48\xa3' + struct.pack('<Q', export) + b'\x58\x49\x8b\x8d\xd8\0\0\0'
    original = b'\x49\x8b\x8d\xd8\0\0\0'
    async def read(at, size):
        return (b'unknown' if unknown else jump if borrowed else original) if at == jump_at else code[:size]
    handler = SimpleNamespace(pattern_scan=AsyncMock(return_value=[jump_at]),
        read_bytes=AsyncMock(side_effect=read), _base_addrs={}, _active_hooks={},
        activate_root_window_hook=AsyncMock(), close=AsyncMock())
    root = SimpleNamespace(read_base_address=AsyncMock(return_value=0x40000),
                           get_windows_with_name=AsyncMock(return_value=[]))
    return SimpleNamespace(hook_handler=handler, root_window=root, is_running=Mock(return_value=True),
                           _pymem=SimpleNamespace(close_process=Mock()))


class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_borrow_existing_hook_without_injection_or_unhook(self):
        client = fake_client()
        reader = ChatReader(1, client_factory=lambda _: client)
        await reader.connect()
        self.assertEqual(client.hook_handler._base_addrs['current_root_window'], 0x30000)
        client.hook_handler.activate_root_window_hook.assert_not_awaited()
        await reader.close()
        client.hook_handler.close.assert_not_awaited()
        client._pymem.close_process.assert_called_once()

    async def test_fresh_connection_only_activates_root(self):
        client = fake_client(borrowed=False)
        reader = ChatReader(1, client_factory=lambda _: client)
        await reader.connect()
        self.assertTrue(reader.owned_hook)
        client.hook_handler.activate_root_window_hook.assert_awaited_once_with(wait_for_ready=False)
        await reader.close()
        client.hook_handler.close.assert_awaited_once()

    async def test_unknown_layout_refuses_injection(self):
        client = fake_client(unknown=True)
        reader = ChatReader(1, client_factory=lambda _: client)
        with self.assertRaises(RuntimeError):
            await reader.connect()
        client.hook_handler.activate_root_window_hook.assert_not_awaited()
        client.hook_handler.close.assert_not_awaited()

    async def test_borrowed_connection_cannot_send(self):
        client = fake_client()
        reader = ChatReader(1, client_factory=lambda _: client)
        await reader.connect()
        with self.assertRaisesRegex(RuntimeError, '只读'):
            await reader.prepare_send()
        await reader.close()

    async def test_changed_hook_is_not_overwritten_on_close(self):
        client = fake_client(borrowed=False)
        hook = SimpleNamespace(jump_address=0x10000, jump_bytecode=b'different',
                               hook_address=0x20000, hook_bytecode=b'different')
        client.hook_handler._active_hooks[RootWindowHook] = hook
        reader = ChatReader(1, client_factory=lambda _: client)
        reader.client, reader.owned_hook = client, True
        with self.assertRaisesRegex(RuntimeError, '其他程序'):
            await reader.close()
        client.hook_handler.close.assert_not_awaited()
        client._pymem.close_process.assert_called_once()

    async def test_nodes_cached_and_refreshed_when_root_changes(self):
        client = fake_client()
        node = SimpleNamespace(name=AsyncMock(return_value='chatLog'))
        client.root_window.get_windows_with_name.return_value = [node]
        reader = ChatReader(1, client_factory=lambda _: client)
        await reader.connect()
        with patch('xuanyi.reader.read_control_text', new=AsyncMock(return_value='history')):
            self.assertEqual(await reader.read(), ['history'])
            self.assertEqual(await reader.read(), ['history'])
            client.root_window.get_windows_with_name.assert_awaited_once()
            client.root_window.read_base_address.return_value = 0x50000
            await reader.read()
            self.assertEqual(client.root_window.get_windows_with_name.await_count, 2)
        await reader.close()

    async def test_text_error_invalidates_cache_not_reused_as_empty(self):
        client = fake_client()
        node = SimpleNamespace(name=AsyncMock(return_value='chatLog'))
        client.root_window.get_windows_with_name.return_value = [node]
        reader = ChatReader(1, client_factory=lambda _: client)
        await reader.connect()
        with patch('xuanyi.reader.read_control_text', new=AsyncMock(side_effect=RuntimeError('bad'))):
            with self.assertRaises(RuntimeError):
                await reader.read()
        self.assertEqual(reader.nodes, [])
        await reader.close()
