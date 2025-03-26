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


PLAYER_DATA_FILE = "data/astrbot-pacemanbot.json"
SCHEDULED_TASK_FILE = "data/astrbot-pacemanbot-scheduled_task.json"

@register("pacemanbot", "Mo_An", "支持查询我的世界速通数据", "1.0.1")
class PaceManPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.semaphore = asyncio.Semaphore(10)
        self.baseUrl="https://paceman.gg/stats/api/"
        self.player_data=self.load_data(PLAYER_DATA_FILE)
        self.scheduled_data=self.load_data(SCHEDULED_TASK_FILE)
        self.message_target = None
        self.hour = 8
        self.minute = 0
        self.paceman_tasks = {}

    # 提示用法
    @filter.command("bothelp")
    async def bothelp(self, event: AstrMessageEvent):
        plain_result=("可使用的指令有\n/paceman 用户名-查询某玩家的24小时数据\n"
                      "/ldb 参数:\n   nether-下界数量榜\n   finishcount-完成数量榜\n   finishtime-完成时间榜\n"
                      "/rank 用户名-查询某玩家rank数据\n本插件基于Astrbot开发，如有建议请联系墨安QQ:2686014341")
        yield event.plain_result(plain_result)

    def load_data(self,filename):
        # 传入filename文件名，返回json
        if not os.path.exists(filename):
            return {}
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_data(self,filename,dataname):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(dataname, f, ensure_ascii=False, indent=4)

    def get_user_data(self, username):
        if username not in self.player_data:
            self.player_data[username] = {
                "username":username,
                "nether_count": 0,
                "gg_count": 0,
                "gg_username": 0
            }
        return self.player_data[username]

    # 获取PaceMan数据
    async def fetch_sessionstats(self,username:str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            response=await client.get(f"https://paceman.gg/stats/api/getSessionStats/?name={username}&hours=24")
            response.raise_for_status()
            return response.json()

    # 将用户添加到列表中
    @filter.command("adduser")
    async def adduser(self, event: AstrMessageEvent, username:str):
        try:
            data = await self.fetch_sessionstats(username) 
            if data['nether']:
                # 判断是否有数据
                self.get_user_data(username)
                self.save_data(PLAYER_DATA_FILE, self.player_data)
                yield event.plain_result(f"添加{username}成功")
            else:
                yield event.plain_result("没有找到该用户")
        except httpx.HTTPStatusError as e:
            yield event.plain_result(f"没有找到该用户")

    # 根据参数返回不同排行榜
    @filter.command("ldb")
    async def ldb(self, event: AstrMessageEvent, type:str):
        if type not in ["nether","finishcount","finishtime"]:
            yield event.plain_result("参数错误")
            return
        else:
            # 从文件中读取每个用户的信息并检索paceman榜单，然后保存
            for user_data in self.player_data.values():
                data=await self.fetch_sessionstats(user_data["username"])
                if data['nether']:
                    user_data['nether_count'] = data['nether']['count']
                    user_data['gg_count'] = data['finish']['count']
                    user_data['gg_avg'] = data['finish']['avg']
                # 这里要改的
                self.save_data(PLAYER_DATA_FILE, self.player_data)
            logger.info("数据已更新")
        # 将数据集转化为列表便于处理
        player_list = list(self.player_data.values())
        match type:
            case "nether":
                result = ""
                sorted_by_nether_count = sorted(player_list, key=lambda x: x['nether_count'], reverse=True)
                for i, user_data in enumerate(sorted_by_nether_count[:10], start=1):
                    result+=f"{i}. {user_data['username']}: {user_data['nether_count']}次下界\n"
                yield event.plain_result(result)
            case "finishcount":
                result = ""
                sorted_by_finish_count = sorted(player_list, key=lambda x: x['gg_count'], reverse=True)
                for i, user_data in enumerate(sorted_by_finish_count[:10], start=1):
                    result +=f"{i}. {user_data['username']}: {user_data['gg_count']}次完成\n"
                yield event.plain_result(result)
            case "finishtime":
                result = ""
                sorted_by_finish_time = sorted(player_list, key=lambda x: x['gg_avg'])
                sorted_by_finish_time = [time for time in sorted_by_finish_time if time != "0:00"]
                for i, user_data in enumerate(sorted_by_finish_time[:10], start=1):
                    result+=f"{i}. {user_data['username']}: 平均时间{user_data['gg_avg']}\n"
                yield event.plain_result(result)

    # 查询PaceMan个人数据
    @filter.command("paceman")
    async def paceman(self, event: AstrMessageEvent, username:str):
        try:
            data = await self.fetch_sessionstats(username)
            if data['nether']:
                nether_count=data['nether']['count']
                nether_avg=data['nether']['avg']
                fp_count=data['first_portal']['count']
                fp_avg=data['first_portal']['avg']
                gg_count=data['finish']['count']
                gg_avg=data['finish']['avg']
                result=(f"{username}24小时数据:"
                        f"下界数量:{nether_count},平均时间:{nether_avg}\n"
                        f"盲传数量:{fp_count},平均时间:{fp_avg}\n"
                        f"完成数量:{gg_count},平均时间:{gg_avg}")
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
            logger.exception("Paceman command error:")
            yield event.plain_result(f"发生未知错误: {e}")

    #定时返回PaceMan榜单
    async def start(self, event: AstrMessageEvent):
        for group_id,group_data in self.scheduled_data.items():
            try:
                if group_data['message_target'] != "None":
                    logger.info(f"群组{group_id}定时任务已开启,时间为{group_data['hour']}:{group_data['minute']}")
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
        self.save_data(SCHEDULED_TASK_FILE, self.scheduled_data)
        yield event.plain_result(f"成功设置榜单更新时间为{self.hour:02d}:{self.minute:02d}")
        await self.start(event)

    @filter.command("stop")
    async def stop(self, event:AstrMessageEvent):
        group_id = event.get_group_id()
        if group_id in self.scheduled_data:
            if group_id in self.paceman_tasks:
                self.paceman_tasks[group_id].cancel()
                del self.paceman_tasks[group_id]
            logger.info(f"目前开启任务的群组有{self.paceman_tasks}")
            del self.scheduled_data[group_id]
            self.save_data(SCHEDULED_TASK_FILE, self.scheduled_data)
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
    
    async def send_daily_leaderboard(self,message_target):
        logger.info("定时任务已执行")
        logger.info(f"消息目标: {self.message_target}")
        for user_data in self.player_data.values():
            try:
                data = await self.fetch_sessionstats(user_data["username"])
                if data:
                    user_data['nether_count'] = data.get('nether', {}).get('count', 0)
                    user_data['gg_count'] = data.get('finish', {}).get('count', 0)
                    user_data['gg_avg'] = data.get('finish', {}).get('avg', 0)
                    self.save_data(PLAYER_DATA_FILE, self.player_data)
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
        
