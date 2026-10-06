"""Bounded background reading/translation and explicit one-shot manual sends."""
import asyncio
import queue
import time
from collections import OrderedDict

from PyQt6.QtCore import QThread, pyqtSignal

from .api import ChatTranslationAPI, TranslationError
from .chat_log import ChatLogDelta
from .reader import ChatReader, available_clients
from .sender import send_once


class Backend(QThread):
    event = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.commands = queue.Queue()
        self.reader = None
        self.translation_enabled = False
        self.api = None
        self.generation = 0
        self.message_counter = 0
        self.manual_task = None
        self.listening = False
        self.running = True
        self.last_status = None
        self.last_clients = None
        self.cache = OrderedDict()

    def command(self, kind, **values):
        self.commands.put((kind, values))

    def status(self, text):
        if text != self.last_status:
            self.last_status = text
            self.event.emit({'kind': 'status', 'status': text})

    def run(self):
        try:
            asyncio.run(self.loop())
        except Exception:
            # Never include credentials, HTTP bodies or arbitrary tracebacks.
            self.event.emit({'kind': 'status', 'status': '后台已停止，请关闭后重新启动。'})

    async def disconnect(self):
        reader, self.reader = self.reader, None
        if reader:
            try:
                await reader.close()
            except Exception:
                self.status('连接清理未完整完成；请重启游戏后再使用。')

    async def invalidate(self):
        self.generation += 1
        self.cache.clear()
        while not self.translation_queue.empty():
            self.translation_queue.get_nowait()
        if self.manual_task and not self.manual_task.done():
            self.manual_task.cancel()
            await asyncio.gather(self.manual_task, return_exceptions=True)

    async def handle_command(self, kind, values):
        if kind == 'api':
            await self.invalidate()
            self.translation_enabled = bool(values['enabled'])
            self.api = None
            if values['options'].get('chat_translation_api_key_protected'):
                try:
                    self.api = ChatTranslationAPI(values['options'])
                except TranslationError as exc:
                    self.event.emit({'kind': 'translation_status', 'status': str(exc)})
            self.event.emit({'kind': 'translation_status', 'status':
                '翻译：已启用（可能产生 API 费用）' if self.translation_enabled and self.api else
                '翻译：未启用或接口未配置'})
        elif kind == 'listen':
            await self.invalidate()
            await self.disconnect()
            self.listening = bool(values['enabled'])
            self.delta = ChatLogDelta()
            if self.listening:
                reader = ChatReader(values['handle'])
                self.status('正在连接游戏聊天界面…')
                try:
                    await asyncio.wait_for(reader.connect(), timeout=10)
                    self.reader = reader
                    self.status('已连接，请展开聊天记录；只显示连接后的新消息。' if reader.owned_hook else
                                '已复用其他工具的连接（只读）；发送需退出其他工具后重新连接。')
                except Exception:
                    await reader.close()
                    self.listening = False
                    self.status('无法建立界面连接；请以管理员身份运行、进入角色，并检查是否存在其他注入工具。')
            else:
                self.status('读取：已停止')
            self.event.emit({'kind': 'listening', 'enabled': self.listening})
        elif kind == 'send':
            if self.manual_task and not self.manual_task.done():
                self.event.emit({'kind': 'send_busy', 'status': '上一条填入仍在处理中；未排队。'})
                return
            self.manual_task = asyncio.create_task(self.manual_send(values['text']))
        elif kind == 'shutdown':
            self.running = False
            self.listening = False
            await self.invalidate()

    async def manual_send(self, text):
        reader, generation, api = self.reader, self.generation, self.api
        active = lambda: self.running and self.listening and self.reader is reader and self.generation == generation

        def publish(event):
            self.event.emit({'kind': 'send_status', **event})

        publish({'status': '正在检查目标客户端与草稿…'})
        try:
            if reader is None:
                raise RuntimeError('请先开始读取。')
            result = await send_once(reader, text, api, active, publish)
            self.event.emit({'kind': 'send_done', **result})
        except asyncio.CancelledError:
            self.event.emit({'kind': 'send_done', 'status': '填入已取消；未自动发送，请检查游戏草稿。',
                             'invoked': False})
            raise
        except Exception as exc:
            # Known local/validation failures are safe; unknown errors stay generic.
            safe = str(exc) if isinstance(exc, (TranslationError, RuntimeError)) else '发送检查或输入失败；未自动重试，请检查游戏草稿。'
            self.event.emit({'kind': 'send_done', 'status': safe, 'invoked': False})

    def enqueue_message(self, channel, gid, sender, message):
        self.message_counter += 1
        event = {'kind': 'message', 'id': self.message_counter,
                 'channel': channel, 'sender': sender, 'message': message}
        self.event.emit(event)
        if not self.translation_enabled or self.api is None:
            return
        if gid == 0 and sender == '你':
            # The observed game log identifies our own echo with [你], no GID
            # link. Keep its original, regardless of how the message was sent.
            return
        try:
            self.translation_queue.put_nowait((self.generation, self.api, event, time.monotonic()))
        except asyncio.QueueFull:
            self.event.emit({'kind': 'translation_status', 'status': '翻译队列已满，部分消息仅显示原文。'})

    async def translate_pending(self):
        while True:
            generation, api, event, received = await self.translation_queue.get()
            try:
                if generation != self.generation or time.monotonic() - received > 30:
                    continue
                key = event['message']
                if key in self.cache:
                    translated = self.cache[key]
                    self.cache.move_to_end(key)
                else:
                    translated = await asyncio.to_thread(api.translate, key)
                    if generation != self.generation:
                        continue
                    self.cache[key] = translated
                    if len(self.cache) > 256:
                        self.cache.popitem(last=False)
                if generation == self.generation:
                    self.event.emit({'kind': 'translation', 'id': event['id'], 'text': translated})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if generation == self.generation:
                    safe = str(exc) if isinstance(exc, TranslationError) else '接口请求失败，已保留原文；未自动重试。'
                    self.event.emit({'kind': 'translation_status', 'status': safe})
            finally:
                self.translation_queue.task_done()

    async def loop(self):
        self.translation_queue = asyncio.Queue(maxsize=32)
        self.delta = ChatLogDelta()
        worker = asyncio.create_task(self.translate_pending())
        scan_at = read_at = 0
        failures = 0
        try:
            while self.running:
                while not self.commands.empty():
                    kind, values = self.commands.get_nowait()
                    await self.handle_command(kind, values)
                if not self.running:
                    break
                now = time.monotonic()
                if now >= scan_at:
                    try:
                        clients = available_clients()
                        if clients != self.last_clients:
                            self.last_clients = clients
                            self.event.emit({'kind': 'clients', 'clients': clients})
                    except Exception:
                        self.status('无法枚举游戏窗口；请检查管理员权限。')
                    scan_at = now + 2
                if self.reader and now >= read_at:
                    try:
                        texts = await asyncio.wait_for(self.reader.read(), timeout=4)
                        if texts:
                            for row in self.delta.update(texts):
                                self.enqueue_message(*row)
                            self.status('读取中（只显示连接后的新消息）' if self.reader.owned_hook else
                                        '读取中（复用连接、仅可读取）')
                        else:
                            self.status('等待聊天记录控件，请进入角色并展开聊天记录。')
                        failures = 0
                    except Exception:
                        failures += 1
                        self.status('聊天暂时无法读取，请等待场景加载或重新连接。')
                        if failures >= 5:
                            await self.invalidate()
                            self.listening = False
                            await self.disconnect()
                            self.event.emit({'kind': 'listening', 'enabled': False})
                            self.status('连接读取连续失败，已停止；请检查游戏后重新开始。')
                    read_at = now + .5
                await asyncio.sleep(.1)
        finally:
            await self.invalidate()
            await self.disconnect()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
