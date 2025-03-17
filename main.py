import asyncio
import httpx
import json
import os
import pytz
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.message.components import At, Plain
from datetime import datetime, timedelta


DATA_FILE = "data/astrbot-pacemanbot.json"

@register("pacemanbot", "Mo_An", "支持查询我的世界速通数据", "1.0.1")
class PaceManPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.semaphore = asyncio.Semaphore(10)
        self.baseUrl="https://paceman.gg/stats/api/"
        self.player_data=self.load_data()
        self.message_target = None
        self.hour = 8
        self.minute = 0
        asyncio.create_task(self.send_scheduled_paceman_leaderboard())

    # 提示用法
    @filter.command("bothelp")
    async def bothelp(self, event: AstrMessageEvent):
        chain = [
                    Plain("可使用的指令有\n"),
                    Plain("/paceman 用户名-查询某玩家的24小时数据\n"),
                    Plain("/ldb 参数:\n"),
                    Plain("   nether-地狱数量榜\n"),
                    Plain("   finishcount-完成数量榜\n"),
                    Plain("   finishtime-完成时间榜\n"),
                    Plain("/rank 用户名-查询某玩家rank数据\n"),
                    Plain("本插件基于Astrbot开发，如有建议请联系墨安QQ:2686014341")
                ]
        yield event.chain_result(chain)

    def load_data(self):
        if not os.path.exists(DATA_FILE):
            return {}
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_data(self):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.player_data, f, ensure_ascii=False, indent=4)

    def get_user_data(self, username):
        if username not in self.player_data:
            self.player_data[username] = {
                "username":username,
                "nether_count": 0,
                "gg_count": 0,
                "gg_username": 0
            }
        return self.player_data[username]

    #获取PaceMan数据
    async def fetch_sessionstats(self,username:str):
        async with httpx.AsyncClient(timeout=10.0) as client:
            response=await client.get(f"https://paceman.gg/stats/api/getSessionStats/?name={username}&hours=24&hoursBetween=2")
            response.raise_for_status()
            return response.json()

    #将用户添加到列表中
    @filter.command("adduser")
    async def adduser(self, event: AstrMessageEvent, username:str):
        try:
            data = await self.fetch_sessionstats(username) 
            if data['nether']:#判断是否有数据
                self.get_user_data(username)
                self.save_data()
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
                user_data['nether_count'] = data['nether']['count']
                user_data['gg_count'] = data['finish']['count']
                user_data['gg_avg'] = data['finish']['avg']
                self.save_data()
        # 将数据集转化为列表便于处理
        player_list = list(self.player_data.values())
        match type:
            case "nether":
                chain = []
                sorted_by_nether_count = sorted(player_list, key=lambda x: x['nether_count'], reverse=True)
                for i, user_data in enumerate(sorted_by_nether_count[:10], start=1):
                    chain.append(Plain(f"{i}. {user_data['username']}: {user_data['nether_count']}次下界\n"))
                yield event.chain_result(chain)
            case "finishcount":
                chain = []
                sorted_by_finish_count = sorted(player_list, key=lambda x: x['gg_count'], reverse=True)
                for i, user_data in enumerate(sorted_by_finish_count[:10], start=1):
                    chain.append(Plain(f"{i}. {user_data['username']}: {user_data['gg_count']}次完成\n"))
                yield event.chain_result(chain)
            case "finishtime":
                chain = []
                sorted_by_finish_time = sorted(player_list, key=lambda x: x['gg_avg'], reverse=True)
                for i, user_data in enumerate(sorted_by_finish_time[:10], start=1):
                    chain.append(Plain(f"{i}. {user_data['username']}: 平均时间{user_data['gg_avg']}\n"))
                yield event.chain_result(chain)


    #查询PaceMan个人数据
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
                chain = [
                    Plain(f"下界数量:{nether_count},平均时间:{nether_avg}"),
                    Plain(f"\n盲传数量:{fp_count},平均时间:{fp_avg}"),
                    Plain(f"\n完成数量:{gg_count},平均时间:{gg_avg}"),
                ]
                yield event.chain_result(chain)
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
            self.context.logger.exception("Paceman command error:") 
            yield event.plain_result(f"发生未知错误: {e}")


    #定时返回PaceMan榜单
    @filter.command("run")
    async def set_schedule_task_state(self,event:AstrMessageEvent,stateNum:int):
        if stateNum == 1:
            self.message_target = event.unified_msg_origin
        else:
            self.message_target = None

    @filter.command("settime")
    async def settime(self,event:AstrMessageEvent,hour:int,minute:int):
        self.hour = hour
        self.minute = minute
        logger.info(f"成功设置时间为{self.hour}:{self.minute}")

    async def send_scheduled_paceman_leaderboard(self, event: AstrMessageEvent):
         tz = pytz.timezone("Asia/Shanghai")  # 设置时区
         while True:
            now = datetime.now(tz)
            # 计算下一次的时间
            next_run = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
            if now >= next_run:
                next_run += timedelta(days=1)  # 如果当前时间已经过了固定时间，则设置为明天的时间
            delay = (next_run - now).total_seconds()
            await asyncio.sleep(delay)  # 等待到固定时间
            await self.send_daily_leaderboard()
    
    async def send_daily_leaderboard(self):
        for user_data in self.player_data.values():
            data=await self.fetch_sessionstats(user_data["username"])
            user_data['nether_count'] = data['nether']['count']
            user_data['gg_count'] = data['finish']['count']
            user_data['gg_avg'] = data['finish']['avg']
            self.save_data()
        player_list = list(self.player_data.values())
        chain = [Plain("昨日PaceMan排行榜:\n")]
        sorted_by_nether_count = sorted(player_list, key=lambda x: x['nether_count'], reverse=True)
        sorted_by_finish_count = sorted(player_list, key=lambda x: x['gg_count'], reverse=True)
        sorted_by_finish_time = sorted(player_list, key=lambda x: x['gg_avg'], reverse=True)
        chain.append(Plain("下界数量:\n"))
        for i, user_data in enumerate(sorted_by_nether_count[:3], start=1):
            chain.append(Plain(f"{i}. {user_data['username']}: {user_data['nether_count']}次下界\n"))
        chain.append(Plain("完成数量:\n"))
        for i, user_data in enumerate(sorted_by_finish_count[:3], start=1):
            chain.append(Plain(f"{i}. {user_data['username']}: {user_data['gg_count']}次完成\n"))
        chain.append(Plain("完成时间:\n"))
        for i, user_data in enumerate(sorted_by_finish_time[:3], start=1):
            chain.append(Plain(f"{i}. {user_data['username']}: 平均时间{user_data['gg_avg']}\n"))
        
        # 发送消息
        await self.context.send_message(self.message_target, chain)
        logger.info("消息已发送")


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

                    chain = [
                        Plain(f"{user}:\n"),
                        Plain(f"当前elo:{elorate}\n"),
                        Plain(f"当前elo排名:{elorank}\n"),
                        Plain(f"赛季PB:{minutes}分{seconds}秒")
                    ]
                    yield event.chain_result(chain)
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
        
