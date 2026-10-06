# 来源与范围

玄译（XuanYi）是从 XuanShu 中独立提取的 Wizard101 聊天工具，按 GPL-3.0 许可提供。
聊天解析、快照去重、ControlText UTF-16 读取、API 请求及 Windows DPAPI 密钥保护、
手动文本填入及正文回读检查沿用原项目实现；独立界面、后台调度和打包配置重新接线。
只输入正文，不切换用户选择的频道或私聊对象，不自动按 Enter。
界面配色、标题栏矢量图标、按钮/滚动条样式和圆角处理沿用 XuanShu。
来源：https://github.com/ChenYatCN/Deimos-Wizard101-main

游戏连接依赖 wizwalker 1.8.2（GPL-3.0-or-later）；没有集成原 XuanShu 主程序、
自动任务、战斗脚本、采集/钓鱼、账号启动器、游戏资源修改或自动回复。
底层连接库自带的其他 API 不由本应用调用；聊天正文不会直接改写到游戏内存。

分发修改版时须遵守随附 LICENSE，并提供相应源代码。
