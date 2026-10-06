"""Only a root-window connection and rendered history reading; no inputs/sends."""
import asyncio
import struct
import time

from wizwalker import Client, utils
from wizwalker.memory.hooks import RootWindowHook, RenderContextHook

from .window_text import read_control_text


def available_clients():
    clients = []
    for handle in utils.get_all_wizard_handles():
        pid = utils.get_pid_from_handle(handle)
        if pid:
            clients.append({'handle': handle, 'pid': pid,
                            'title': utils.get_window_title(handle) or 'Wizard101'})
    return clients


async def existing_root_export(handler, candidates):
    exports = set()
    for address in candidates:
        jump = await handler.read_bytes(address, 7)
        if jump[0] != 0xE9 or jump[5:] != b'\x90\x90':
            continue
        destination = address + 5 + struct.unpack('<i', jump[1:5])[0]
        code = await handler.read_bytes(destination, 26)
        if (code[:10] == b'\x50\x49\x8b\x85\xd8\x00\x00\x00\x48\xa3'
                and code[18:] == b'\x58\x49\x8b\x8d\xd8\x00\x00\x00'):
            exports.add(struct.unpack('<Q', code[10:18])[0])
    if len(exports) > 1:
        raise RuntimeError('检测到多个界面连接，已停止以避免重复注入。')
    return next(iter(exports), None)


class ChatReader:
    def __init__(self, handle, *, client_factory=Client):
        self.handle = handle
        self.client_factory = client_factory
        self.client = None
        self.owned_hook = False
        self.nodes = []
        self.root_address = None
        self.next_discovery = 0

    async def connect(self):
        self.client = self.client_factory(self.handle)
        handler = self.client.hook_handler
        try:
            candidates = await handler.pattern_scan(RootWindowHook.pattern,
                module='WizardGraphicalClient.exe', return_multiple=True)
            export = await existing_root_export(handler, candidates)
            if export:
                # Borrow only the existing export; never register ownership.
                handler._base_addrs['current_root_window'] = export
            else:
                if (len(candidates) != 1 or
                        await handler.read_bytes(candidates[0], 7) != b'\x49\x8b\x8d\xd8\x00\x00\x00'):
                    raise RuntimeError('界面连接指令与已知结构不符，未注入。')
                # Only this hook. Never activate player/combat/chat-send hooks.
                self.owned_hook = True
                await handler.activate_root_window_hook(wait_for_ready=False)
        except BaseException:
            await self.close()
            raise

    async def read(self):
        if not self.client or not self.client.is_running():
            raise RuntimeError('游戏客户端已关闭。')
        root = self.client.root_window
        address = await root.read_base_address()
        if not address:
            return []
        now = time.monotonic()
        if address != self.root_address or now >= self.next_discovery or not self.nodes:
            # Cache controls between discoveries; discard on root changes/errors.
            self.nodes = await asyncio.wait_for(root.get_windows_with_name('chatLog'), timeout=3)
            self.root_address = address
            self.next_discovery = now + (3 if self.nodes else 1)
        try:
            texts = []
            for node in self.nodes:
                if await node.name() != 'chatLog':
                    raise RuntimeError('聊天控件已变动，请等待重新读取。')
                texts.append(await read_control_text(node))
            return texts
        except Exception:
            self.nodes = []
            raise

    async def close(self):
        client, self.client = self.client, None
        if client is None:
            return
        try:
            if self.owned_hook and client.is_running():
                handler = client.hook_handler
                for hook in handler._active_hooks.values():
                    # Don't undo a connection another program replaced.
                    if (await handler.read_bytes(hook.jump_address, len(hook.jump_bytecode)) != hook.jump_bytecode
                            or await handler.read_bytes(hook.hook_address, len(hook.hook_bytecode)) != hook.hook_bytecode):
                        raise RuntimeError('界面连接已被其他程序改动，未覆盖；建议重启游戏。')
                await handler.close()
        finally:
            # A borrowed hook is never closed/unhooked by this application.
            client._pymem.close_process()
            self.owned_hook = False
            self.nodes = []

    async def prepare_send(self):
        if not self.client or not self.owned_hook:
            raise RuntimeError('只读复用连接不能用于发送；请退出其他工具后重新连接。')
        handler = self.client.hook_handler
        if not handler._check_if_hook_active(RenderContextHook):
            await handler.activate_render_context_hook(wait_for_ready=True, timeout=2)
        if not await handler.read_current_render_context_base():
            raise RuntimeError('输入坐标尚未就绪；未发送。')
