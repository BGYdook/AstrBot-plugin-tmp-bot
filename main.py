#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
AstrBot-plugin-tmp-bot
欧卡2TMP查询插件 - AstrBot版本 (最终兼容性修复：filter.message -> filter.command)
"""

import re
import asyncio
import aiohttp
import json
import os
from typing import Optional, List, Dict, Tuple, Any
# 🚨 修复：导入 filter.command (通常用于匹配命令和文本)
try:
    from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
    from astrbot.api.star import Context, Star, register, StarTools
    from astrbot.api import logger
except Exception:
    # Minimal fallbacks so the module can be inspected/run outside AstrBot environment
    class _DummyFilter:
        def command(self, pattern, **kwargs):
            def decorator(func):
                return func
            return decorator
    filter = _DummyFilter()

    class AstrMessageEvent:
        def __init__(self, message_str: str = "", sender_id: str = "0"):
            self.message_str = message_str
            self._sender_id = sender_id
        def get_sender_id(self) -> str:
            return self._sender_id
        async def plain_result(self, msg):
            return msg

    MessageEventResult = Any  # type: ignore

    class Context: pass
    class Star:
        def __init__(self, context: Context = None): pass

    def register(*args, **kwargs):
        def deco(cls):
            return cls
        return deco

    class StarTools:
        @staticmethod
        def get_data_dir(name: str):
            return os.path.join(os.getcwd(), name)

    class _Logger:
        @staticmethod
        def info(msg):
            print("[INFO]", msg)
        @staticmethod
        def error(msg):
            print("[ERROR]", msg)

    logger = _Logger()


# 自定义异常类
class TmpApiException(Exception):
    """TMP 相关异常的基类"""
    pass


class PlayerNotFoundException(TmpApiException):
    """玩家不存在异常"""
    pass


class NetworkException(Exception):
    """网络请求异常"""
    pass


class ApiResponseException(TmpApiException):
    """API响应异常"""
    pass

# 版本号更新为 1.0.2 以示修复
@register("tmp-bot", "BGYdook", "欧卡2TMP查询插件", "1.0.2", "https://github.com/BGYdook/AstrBot-plugin-tmp-bot")
class TmpBotPlugin(Star):
    def __init__(self, context: Context):
        """初始化插件，设置数据路径和HTTP会话引用。"""
        super().__init__(context)
        self.session: Optional[aiohttp.ClientSession] = None 
        self.data_dir = StarTools.get_data_dir("tmp-bot")
        self.bind_file = os.path.join(self.data_dir, "tmp_bindings.json")
        os.makedirs(self.data_dir, exist_ok=True)
        logger.info("TMP Bot 插件已加载")

    async def initialize(self):
        """在插件启动时，创建持久的HTTP会话。"""
        self.session = aiohttp.ClientSession(
            headers={'User-Agent': 'AstrBot-TMP-Plugin/1.0.2'},
            timeout=aiohttp.ClientTimeout(total=10)
        )
        logger.info("TMP Bot 插件HTTP会话已创建")

    # --- 内部工具方法 (数据持久化部分保持不变) ---
    def _load_bindings(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.bind_file):
                with open(self.bind_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logger.error(f"加载绑定数据失败: {e}")
            return {}

    def _save_bindings(self, bindings: dict) -> bool:
        try:
            with open(self.bind_file, 'w', encoding='utf-8') as f:
                json.dump(bindings, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"保存绑定数据失败: {e}")
            return False

    def _get_bound_tmp_id(self, user_id: str) -> Optional[str]:
        bindings = self._load_bindings()
        user_binding = bindings.get(user_id)
        if isinstance(user_binding, dict):
            return user_binding.get('tmp_id')
        return user_binding

    def _bind_tmp_id(self, user_id: str, tmp_id: str, player_name: str) -> bool:
        bindings = self._load_bindings()
        bindings[user_id] = {
            'tmp_id': tmp_id,
            'player_name': player_name,
            'bind_time': asyncio.get_event_loop().time()
        }
        return self._save_bindings(bindings)

    def _unbind_tmp_id(self, user_id: str) -> bool:
        bindings = self._load_bindings()
        if user_id in bindings:
            del bindings[user_id]
            return self._save_bindings(bindings)
        return False

    # --- API请求方法 (使用持久化会话) ---
    async def _get_player_info(self, tmp_id: str) -> Dict:
        if not self.session:
            raise NetworkException("插件未初始化，HTTP会话不可用")
        
        try:
            url = f"https://api.truckersmp.com/v2/player/{tmp_id}"
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    response_data = data.get('response')
                    if response_data and isinstance(response_data, dict):
                         return response_data
                    raise PlayerNotFoundException(f"玩家 {tmp_id} 不存在")
                elif response.status == 404:
                    raise PlayerNotFoundException(f"玩家 {tmp_id} 不存在")
                else:
                    raise ApiResponseException(f"API返回错误状态码: {response.status}")
        except aiohttp.ClientError:
            raise NetworkException("TruckersMP API 网络请求失败")
        except asyncio.TimeoutError:
            raise NetworkException("请求TruckersMP API超时")
        except Exception as e:
            logger.error(f"查询玩家信息失败: {e}")
            raise NetworkException("查询失败")

    async def _get_player_bans(self, tmp_id: str) -> List[Dict]:
        if not self.session: return []

        try:
            url = f"https://api.truckersmp.com/v2/player/{tmp_id}/bans"
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('response', [])
                return []
        except Exception:
            return []

    async def _get_online_status(self, tmp_id: str) -> Dict:
        if not self.session: return {'online': False}

        try:
            url = f"https://api.truckyapp.com/v3/map/online?playerID={tmp_id}"
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    response_data = data.get('response', {})
                    if isinstance(response_data, list) and response_data:
                        return response_data[0]
                    return {'online': False}
                return {'online': False}
        except Exception:
            return {'online': False}

    def _format_ban_info(self, bans_info: List[Dict]) -> Tuple[bool, int, List[Dict], str]:
        if not bans_info or not isinstance(bans_info, list):
            return False, 0, [], ""
        
        # 确保按日期排序，以获取最新的封禁信息
        sorted_bans = sorted(bans_info, key=lambda x: x.get('created_at', ''), reverse=True)
        active_bans = [ban for ban in sorted_bans if not ban.get('expired', False)]
        ban_count = len(bans_info)
        is_banned = len(active_bans) > 0
        ban_reason = active_bans[0].get('reason', '未知封禁原因') if active_bans else ""
            
        return is_banned, ban_count, active_bans, ban_reason

    # ******************************************************
    # 使用 filter.command 修复命令注册错误
    # ******************************************************
    # 🚨 修复: filter.message -> filter.command
    @filter.command(r"查询", regex=True)
    async def tmpquery(self, event: AstrMessageEvent):
        """[命令: 查询] TMP玩家完整信息查询。"""
        message_str = event.message_str.strip()

        match = re.search(r'查询\s*(\d+)', message_str)
        tmp_id = match.group(1) if match else None

        if not tmp_id:
            if message_str.strip().lower() == '查询':
                user_id = event.get_sender_id()
                tmp_id = self._get_bound_tmp_id(user_id)

        if not tmp_id:
            yield event.plain_result("请输入正确的玩家编号，格式：查询 123456，或先使用 绑定 123456 绑定您的账号。")
            return

        try:
            player_info, bans_info, online_status = await asyncio.gather(
                self._get_player_info(tmp_id),
                self._get_player_bans(tmp_id),
                self._get_online_status(tmp_id),
            )
        except PlayerNotFoundException as e:
            yield event.plain_result(str(e))
            return
        except NetworkException as e:
            yield event.plain_result(str(e))
            return
        except Exception as e:
            yield event.plain_result(f"查询失败: {str(e)}")
            return

        is_banned, ban_count, active_bans, ban_reason = self._format_ban_info(bans_info)

        # 完整的回复消息构建
        message = "🚛 **TMP玩家详细信息**\n"
        message += "=" * 20 + "\n"
        message += f"🆔TMP编号: **{tmp_id}**\n"
        message += f"😀玩家名称: **{player_info.get('name', '未知')}**\n"

        # 权限/分组信息
        perms_str = "玩家"
        if player_info.get('permissions'):
            perms = player_info['permissions']
            if isinstance(perms, dict):
                groups = [g for g in ["Staff", "Management", "Game Admin"] if perms.get(f'is{g.replace(" ", "")}')]
                if groups:
                    perms_str = ', '.join(groups)
            elif isinstance(perms, list) and perms:
                perms_str = ', '.join(perms)
        message += f"💼所属分组: **{perms_str}**\n"

        vtc_name = player_info.get('vtc', {}).get('name')
        vtc_role = player_info.get('vtc', {}).get('role')
        message += f"🚚所属车队: {vtc_name if vtc_name else '无'}\n"
        if vtc_role:
            message += f"🚚车队角色: {vtc_role}\n"

        message += f"🚫是否封禁: **{'是 🚨' if is_banned else '否 ✅'}**\n"
        if is_banned:
            latest_ban = active_bans[0] if active_bans else {}
            message += f"🚫封禁次数: {ban_count}次\n"
            message += f"🚫封禁原因: {latest_ban.get('reason', ban_reason or '未知')}\n"
            if latest_ban.get('expiration'):
                message += f"🚫封禁截止: {latest_ban['expiration']}\n"
        elif ban_count > 0:
            message += f"🚫历史封禁: {ban_count}次\n"

        if online_status and online_status.get('online'):
            server_name = online_status.get('serverName', '未知服务器')
            game_mode = "欧卡2" if online_status.get('game', 0) == 1 else "美卡2" if online_status.get('game', 0) == 2 else "未知游戏"
            city = online_status.get('city', {}).get('name', '未知城市')
            message += f"📶**在线状态: 在线 🟢**\n"
            message += f"🖥️所在服务器: {server_name}\n"
            message += f"🗺️所在位置: {city} ({game_mode})\n"
        else:
            message += f"📶**在线状态: 离线 🔴**\n"

        yield event.plain_result(message)
    # 🚨 修复: filter.message -> filter.command
    @filter.command(r"绑定", regex=True)
    async def tmpbind(self, event: AstrMessageEvent):
        """[命令: 绑定] 绑定您的聊天账号与TMP ID。"""
        message_str = event.message_str.strip()
        match = re.search(r'绑定\s*(\d+)', message_str)
        tmp_id = match.group(1) if match else None

        if not tmp_id:
            yield event.plain_result("请输入正确的玩家编号，格式：绑定 123456")
            return

        try:
            player_info = await self._get_player_info(tmp_id)
        except PlayerNotFoundException:
            yield event.plain_result("玩家不存在，请检查TMP ID是否正确")
            return
        except Exception as e:
            yield event.plain_result(f"查询失败: {str(e)}")
            return

        user_id = event.get_sender_id()
        player_name = player_info.get('name', '未知')
        if self._bind_tmp_id(user_id, tmp_id, player_name):
            yield event.plain_result(f"✅ **绑定成功！**\n已将您的账号与TMP玩家 **{player_name}** (ID: {tmp_id}) 绑定")
        else:
            yield event.plain_result("❌ 绑定失败，请稍后重试")
            yield event.plain_result("❌ 绑定失败，请稍后重试")

    # 🚨 修复: filter.message -> filter.command
    @filter.command(r"解绑", regex=True)
    async def tmpunbind(self, event: AstrMessageEvent):
        """[命令: 解绑] 解除当前用户的TruckersMP ID绑定。"""
        user_id = event.get_sender_id()
        user_binding = self._load_bindings().get(user_id, {})
        tmp_id = user_binding.get('tmp_id')
        
        if not tmp_id:
            yield event.plain_result("❌ 您还没有绑定任何TMP账号")
            return
        
        player_name = user_binding.get('player_name', '未知玩家')
        
        if self._unbind_tmp_id(user_id):
            yield event.plain_result(f"✅ **解绑成功！**\n已解除与TMP玩家 **{player_name}** (ID: {tmp_id}) 的绑定")
        else:
            yield event.plain_result("❌ 解绑失败，请稍后重试")
    # 🚨 修复: filter.message -> filter.command
    @filter.command(r"状态", regex=True)
    @filter.command(r"定位", regex=True)
    async def tmpstatus(self, event: AstrMessageEvent):
        """[命令: 状态] 查询玩家的实时在线状态。"""
        message_str = event.message_str.strip()
        match = re.search(r'状态\s*(\d+)', message_str)
        tmp_id = match.group(1) if match else None
        
        if not tmp_id:
            if message_str.strip().lower() == '状态':
                user_id = event.get_sender_id()
                tmp_id = self._get_bound_tmp_id(user_id)
            
            if not tmp_id:
                yield event.plain_result("请输入正确的玩家编号，格式：状态 123456，或先使用 绑定 123456 绑定您的账号。")
                return

        try:
            online_status, player_info = await asyncio.gather(
                self._get_online_status(tmp_id), 
                self._get_player_info(tmp_id)
            )

        except PlayerNotFoundException as e:
            yield event.plain_result(str(e))
            return
        except Exception as e:
            yield event.plain_result(f"查询失败: {str(e)}")
            return
        
        player_name = player_info.get('name', '未知')
        
        message = f"🎮 **玩家状态查询**\n"
        message += "=" * 15 + "\n"
        message += f"😀玩家名称: **{player_name}**\n"
        message += f"🆔TMP编号: **{tmp_id}**\n"
        
        if online_status and online_status.get('online'):
            server_name = online_status.get('serverName', '未知服务器')
            game_mode = "欧卡2" if online_status.get('game', 0) == 1 else "美卡2" if online_status.get('game', 0) == 2 else "未知游戏"
            city = online_status.get('city', {}).get('name', '未知城市')
            message += f"📶**在线状态: 在线 🟢**\n"
            message += f"🖥️所在服务器: {server_name}\n"
            message += f"🗺️所在位置: {city} ({game_mode})\n"
        else:
            message += f"📶**在线状态: 离线 🔴**\n"
        
        yield event.plain_result(message)

    # 🚨 修复: filter.message -> filter.command
    @filter.command(r"服务器", regex=True)
    async def tmpserver(self, event: AstrMessageEvent):
        """[命令: 服务器] 查询TruckersMP官方服务器的实时状态。"""
        if not self.session: 
            yield event.plain_result("插件初始化中，请稍后重试")
            return
            
        try:
            url = "https://api.truckersmp.com/v2/servers"
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    servers = data.get('response', [])
                    
                    if servers and isinstance(servers, list):
                        message = "🖥️ **TMP服务器状态** (显示前6个在线服务器)\n"
                        message += "=" * 25 + "\n"
                        # 仅显示在线且按人数排序
                        online_servers = sorted(
                            [s for s in servers if s.get('online')],
                            key=lambda s: s.get('players', 0),
                            reverse=True
                        )[:6]
                        
                        for server in online_servers:
                            name, players, max_players, queue = server.get('name', '未知'), server.get('players', 0), server.get('maxplayers', 0), server.get('queue', 0)
                            status_icon = '🟢' if players > 0 else '🟡'
                            
                            message += f"{status_icon} **{name}**\n"
                            message += f"   👥 在线: {players}/{max_players}"
                            if queue > 0: message += f" (排队: {queue})"
                            message += "\n"
                        
                        if not online_servers: message += "暂无在线服务器"
                        yield event.plain_result(message)
                    else:
                        yield event.plain_result("查询服务器状态失败，API数据异常。")
                else:
                    yield event.plain_result(f"查询服务器状态失败，HTTP状态码: {response.status}")
        except Exception:
            yield event.plain_result("网络请求失败，请检查网络或稍后重试。")

    # 🚨 修复: filter.message -> filter.command
    @filter.command(r"^帮助$", regex=True)
    async def tmphelp(self, event: AstrMessageEvent):
        """[命令: 帮助] 显示本插件的命令使用说明。"""
        help_text = """🚛 **TMP查询插件使用说明 (无前缀命令)**

📋 **可用命令**:
1. **查询 [ID]** - 查询玩家的完整信息（封禁、车队、权限等）。
2. **状态 [ID]** - 查询玩家的实时在线状态、所在服务器和位置。 
3. **绑定 [ID]** - 绑定您的聊天账号与TMP ID。
4. **解绑** - 解除账号绑定。
5. **服务器** - 查看主要TMP服务器的实时状态和在线人数。
6. **帮助** - 显示此帮助信息。

💡 **使用提示**: 绑定后可直接发送 **查询** 或 **状态** (无需ID参数)
"""
        yield event.plain_result(help_text)

    async def terminate(self):
        """插件卸载时的清理工作：关闭HTTP会话。"""
        if self.session:
            await self.session.close()
            self.session = None
        logger.info("TMP Bot 插件已卸载")