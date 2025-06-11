import asyncio
import httpx
import json
import os
import pytz
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.core.message.components import At, Plain
from datetime import datetime, timedelta

try:
    from .pacemanService import *
    from .utils import *
except ImportError:
    from pacemanService import *
    from utils import *


PLAYER_DATA_FILE = "data/astrbot-pacemanbot.json"
SCHEDULED_TASK_FILE = "data/astrbot-pacemanbot-scheduled_task.json"

@register("pacemanbot", "Mo_An", "支持查询我的世界速通数据", "1.2.0")
class PaceManPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.semaphore = asyncio.Semaphore(10)
        self.baseUrl="https://paceman.gg/stats/api"
        self.player_data=load_data(PLAYER_DATA_FILE)
        self.scheduled_data=load_data(SCHEDULED_TASK_FILE)
        self.message_target = None
        self.hour = 8
        self.minute = 0
        self.paceman_tasks = {}

    # 提示用法
    @filter.command("bothelp")
    async def bothelp(self, event: AstrMessageEvent):
        plain_result=("可使用的指令有\n/register 用户名-注册\n"
                      "/paceman-查询自己的24小时数据\n"
                      "/rank 用户名-查询某玩家rank数据\n"
                      "本插件基于Astrbot开发，如有建议请联系墨安QQ:2686014341或者去github上提issue\n"
                      "仓库地址：https://github.com/FXMoAn/astrbot_plugin_pacemanbot")
        yield event.plain_result(plain_result)

    def get_user_data(self, userid, username):
        if userid not in self.player_data:
            self.player_data[userid] = {
                "username":username,
                "nether_count": 0,
                "gg_count": 0,
                "gg_avg": "0:00"
            }
        return self.player_data[userid]

    # 获取PaceMan数据
    async def fetch_sessionstats(self,username:str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            response=await client.get(f"{self.baseUrl}/getSessionStats/?name={username}&hours=24&hoursBetween=24")
            response.raise_for_status()
            return response.json()

    async def fetch_nphstats(self,username:str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            response=await client.get(f"{self.baseUrl}/getNPH/?name={username}&hours=24&hoursBetween=24")
            response.raise_for_status()
            return response.json()

    # 将用户添加到列表中
    @filter.command("register")
    async def register(self, event: AstrMessageEvent, username:str):
        try:
            userid = event.get_sender_id()
            # username = self.player_data[userid]['username']
            data = await self.fetch_sessionstats(username) 
            if data['nether']:
                # 判断是否有数据
                self.get_user_data(userid, username)
                save_data(PLAYER_DATA_FILE, self.player_data)
                yield event.plain_result(f"{userid}注册成功，当前游戏名为{username}")
            else:
                yield event.plain_result("Paceman没有找到该用户，无法注册")
        except httpx.HTTPStatusError as e:
            yield event.plain_result(f"没有找到该用户")

    # 查询PaceMan个人数据
    @filter.command("paceman")
    async def paceman(self, event: AstrMessageEvent):
        try:
            userid = event.get_sender_id()
            if userid not in self.player_data.keys():
                yield event.plain_result("请先使用/register命令注册")
                return
            username = self.player_data[userid]['username']
            sessiondata = await self.fetch_sessionstats(username)
            nphdata = await self.fetch_nphstats(username)
            data = UserSessionStats(**sessiondata)
            service = Service(username,data)
            if data.nether:
                sessionresult=(f"{username}\n"
                        f"下界数量:{data.nether.count},平均时间:{data.nether.avg}\n"
                        f"猪堡数量:{data.bastion.count},平均时间:{data.bastion.avg}\n"
                        f"下要数量:{data.fortress.count},平均时间:{data.fortress.avg}\n"
                        f"盲传数量:{data.first_portal.count},平均时间:{data.first_portal.avg}\n"
                        f"要塞数量:{data.stronghold.count},平均时间:{data.stronghold.avg}\n"
                        f"末地数量:{data.end.count},平均时间:{data.end.avg}\n"
                        f"完成数量:{data.finish.count},平均时间:{data.finish.avg}")
                nphresult = (f"{username}\n"
                        f"每小时下界数nph:{nphdata['rnph']}\n"
                        f"每次下界重置数rpe:{nphdata['rpe']}\n"
                        f"24小时刷种数:{nphdata['resets']}\n"
                        f"生涯刷种数:{nphdata['totalResets']}\n"
                        f"分段统计见下图:"
                        )
                try:
                    service.generate_image()
                    chain = [
                        Comp.Plain(nphresult),
                        Comp.Image.fromFileSystem("/root/astrbot/data/plugins/astrbot_plugin_pacemanbot/result/output.png"),  # 从本地文件目录发送图片
                    ]
                    yield event.chain_result(chain)
                except Exception as e:
                    logger.exception("Generate image error:")
                    yield event.plain_result(sessionresult)

            else:
                yield event.plain_result("没有找到该用户。")
        except httpx.HTTPStatusError as e:
            yield event.plain_result(f"没有找到该用户")
        except httpx.TimeoutException:
            yield event.plain_result("超时，请稍后重试。")
        except httpx.HTTPError as e:
            yield event.plain_result(f"发生网络错误: {e}")
        except json.JSONDecodeError as e:
            yield event.plain_result(f"解析JSON时发生错误: {e}")
        except Exception as e:
            logger.exception("Paceman command error:")
            yield event.plain_result(f"发生未知错误: {e}")

    #定时返回PaceMan榜单
    async def start(self, event: AstrMessageEvent):
        for group_id,group_data in self.scheduled_data.items():
            try:
                if group_data['message_target'] != "None":
                    logger.info(f"群组{group_id}定时任务已开启,paceman日报时间为{group_data['hour']}:{group_data['minute']}")
                    if group_id in self.paceman_tasks:
                        self.paceman_tasks[group_id].cancel()
                        del self.paceman_tasks[group_id]
                    task = asyncio.create_task(self.send_scheduled_paceman_leaderboard(group_data['hour'],group_data['minute'],group_data['message_target']))
                    self.paceman_tasks[group_id] = task
            except Exception as e:
                logger.exception(f"群组{group_id}定时任务开启失败:{e}")
        logger.info(f"目前开启任务的群组有{self.paceman_tasks}")

    from astrbot.api.event import filter, AstrMessageEvent

    @filter.command("settime")
    async def settime(self, event:AstrMessageEvent, hour:int, minute:int):
        userid = event.get_sender_id()
        if userid != '2686014341':
            yield event.plain_result("你没有权限使用此命令")
        group_id = event.get_group_id()
        self.message_target = event.unified_msg_origin
        self.hour = hour
        self.minute = minute
        logger.info(f"当前对象：{self.message_target}")
        if group_id not in self.scheduled_data:
            self.scheduled_data[group_id] = {
                "group_id":group_id,
                "hour": self.hour,
                "minute": self.minute,
                "message_target":self.message_target,
            }
        else:
            self.scheduled_data[group_id]['hour']=self.hour
            self.scheduled_data[group_id]['minute']=self.minute
            self.scheduled_data[group_id]['message_target']=self.message_target
        save_data(SCHEDULED_TASK_FILE, self.scheduled_data)
        yield event.plain_result(f"成功设置paceman榜单更新时间为{self.hour:02d}:{self.minute:02d}")
        await self.start(event)

    @filter.command("stop")
    async def stop(self, event:AstrMessageEvent):
        userid = event.get_sender_id()
        if userid != '2686014341':
            yield event.plain_result("你没有权限使用此命令")
        group_id = event.get_group_id()
        if group_id in self.scheduled_data:
            if group_id in self.paceman_tasks:
                self.paceman_tasks[group_id].cancel()
                del self.paceman_tasks[group_id]
            logger.info(f"目前开启任务的群组有{self.paceman_tasks}")
            del self.scheduled_data[group_id]
            save_data(SCHEDULED_TASK_FILE, self.scheduled_data)
            yield event.plain_result("已关闭功能")
        else:
            yield event.plain_result("未开启定时功能")

    async def send_scheduled_paceman_leaderboard(self,hour,minute,message_target):
         logger.info("定时任务已启动")
         tz = pytz.timezone("Asia/Shanghai")  # 设置时区
         while True:
            now = datetime.now(tz)
            # 计算下一次的时间
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)  # 如果当前时间已经过了固定时间，则设置为明天的时间
            logger.info(f"当前时间: {now}, 下一次触发时间: {next_run}")
            delay = (next_run - now).total_seconds()
            await asyncio.sleep(delay)  # 等待到固定时间
            await self.send_daily_leaderboard(message_target)
    
    async def send_daily_leaderboard(self, message_target):
        logger.info("定时任务已执行")
        logger.info(f"消息目标: {self.message_target}")
        for user_data in self.player_data.values():
            try:
                data = await self.fetch_sessionstats(user_data["username"])
                if data:
                    user_data['nether_count'] = data.get('nether', {}).get('count', 0)
                    user_data['gg_count'] = data.get('finish', {}).get('count', 0)
                    user_data['gg_avg'] = data.get('finish', {}).get('avg', 0)
                    save_data(PLAYER_DATA_FILE, self.player_data)
            except Exception as e:
                logger.error(f"Error processing user {user_data['username']}: {e}")
        logger.info("数据已获取")
        player_list = list(self.player_data.values())
        result="24小时PaceMan排行榜:\n"
        sorted_by_nether_count = sorted(player_list, key=lambda x: x['nether_count'], reverse=True)
        sorted_by_finish_count = sorted(player_list, key=lambda x: x['gg_count'], reverse=True)
        sorted_by_finish_time = sorted(player_list, key=lambda x: x['gg_avg'])
        sorted_by_finish_time = [item for item in sorted_by_finish_time if item["gg_avg"] != "0:00"]
        result+="下界数量:\n"
        for i, user_data in enumerate(sorted_by_nether_count[:3], start=1):
            result+=f"{i}. {user_data['username']}: {user_data['nether_count']}次下界\n"
        result+="完成数量:\n"
        for i, user_data in enumerate(sorted_by_finish_count[:3], start=1):
            result+=f"{i}. {user_data['username']}: {user_data['gg_count']}次完成\n"
        result +="完成时间:\n"
        for i, user_data in enumerate(sorted_by_finish_time[:3], start=1):
            result+=f"{i}. {user_data['username']}: 平均时间{user_data['gg_avg']}\n"
        logger.info(f"消息内容: {result}")
        chain=[]
        chain.append(Comp.Plain(result))
        # 发送消息
        try:
            await self.context.send_message(message_target, MessageChain(chain))
            logger.info("消息已发送")
        except Exception as e:
            logger.info(f"消息发送失败，错误原因{e}")
        return result
    
    # @filter.command("showldb")
    # async def showldb(self,event:AstrMessageEvent):
    #     for user_data in self.player_data.values():
    #         try:
    #             data = await self.fetch_sessionstats(user_data["username"])
    #             if data:
    #                 user_data['nether_count'] = data.get('nether', {}).get('count', 0)
    #                 user_data['gg_count'] = data.get('finish', {}).get('count', 0)
    #                 user_data['gg_avg'] = data.get('finish', {}).get('avg', 0)
    #                 self.save_data(PLAYER_DATA_FILE, self.player_data)
    #         except Exception as e:
    #             logger.error(f"Error processing user {user_data['username']}: {e}")
    #     logger.info("数据已获取")
    #     player_list = list(self.player_data.values())
    #     chain = []
    #     chain.append(Comp.Plain("24小时PaceMan排行榜:\n"))
    #     sorted_by_nether_count = sorted(player_list, key=lambda x: x['nether_count'], reverse=True)
    #     sorted_by_finish_count = sorted(player_list, key=lambda x: x['gg_count'], reverse=True)
    #     sorted_by_finish_time = sorted(player_list, key=lambda x: x['gg_avg'])
    #     sorted_by_finish_time = [item for item in sorted_by_finish_time if item["gg_avg"] != "0:00"]
    #     chain.append(Comp.Plain("下界数量:\n"))
    #     for i, user_data in enumerate(sorted_by_nether_count[:3], start=1):
    #         chain.append(Comp.Plain(f"{i}. {user_data['username']}: {user_data['nether_count']}次下界\n"))
    #     chain.append(Comp.Plain("完成数量:\n"))
    #     for i, user_data in enumerate(sorted_by_finish_count[:3], start=1):
    #         chain.append(Comp.Plain(f"{i}. {user_data['username']}: {user_data['gg_count']}次完成\n"))
    #     chain.append(Comp.Plain("完成时间:\n"))
    #     for i, user_data in enumerate(sorted_by_finish_time[:3], start=1):
    #         chain.append(Comp.Plain(f"{i}. {user_data['username']}: 平均时间{user_data['gg_avg']}\n"))
    #     logger.info(f"消息内容: {chain}")
    #     yield event.chain_result(chain)


    #获取Ranked数据
    async def fetch_rankstats(self,username:str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            response=await client.get(f"https://api.mcsrranked.com/users/{username}")
            response.raise_for_status()
            return response.json()

    #查询Ranked个人数据
    @filter.command("rank")
    async def rank(self, event: AstrMessageEvent, username: str):
        try:
            data = await self.fetch_rankstats(username)
            if data['status']=='success':
                user=data['data']['nickname']
                elorate=data['data']['eloRate']
                elorank=data['data']['eloRank']
                personalbest=data['data']['statistics']['season']['bestTime']['ranked']
                if personalbest is None:
                    yield event.plain_result("该玩家本赛季未参加ranked。")
                else:
                    stdtime = timedelta(seconds=personalbest/1000)
                    minutes = stdtime.seconds // 60
                    seconds = stdtime.seconds % 60

                    result = (f"{user}:\n"
                        f"当前elo:{elorate}\n"
                        f"当前elo排名:{elorank}\n"
                        f"赛季PB:{minutes}分{seconds}秒")
                    yield event.plain_result(result)
            else:
                yield event.plain_result("没有找到该用户。")
        except httpx.HTTPStatusError as e:
            yield event.plain_result(f"没有找到该用户")
        except httpx.TimeoutException:
            yield event.plain_result("超时，请稍后重试。")
        except httpx.HTTPError as e:
            yield event.plain_result(f"发生网络错误: {e}")
        except json.JSONDecodeError as e:
            yield event.plain_result(f"解析JSON时发生错误: {e}")
        except Exception as e:
            yield event.plain_result(f"发生未知错误: {e}")
        
