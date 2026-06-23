import asyncio
import httpx
import json
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api import logger
from .paceman import *
from .utils import *


PLAYER_DATA_FILE = "data/astrbot-pacemanbot.json"

@register("pacemanbot", "Mo_An", "支持查询我的世界速通数据", "1.4.0")
class PaceManPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.semaphore = asyncio.Semaphore(10)
        self.player_data=load_data(PLAYER_DATA_FILE)
        self.message_target = None

    # 提示用法
    @filter.command("bothelp")
    async def bothelp(self, event: AstrMessageEvent):
        plain_result=("可使用的指令有\n/register 用户名-注册\n"
                      "/paceman [用户名]-查询24小时PaceMan数据\n"
                      "/run [用户名]-查询最近一次完成的速通数据\n"
                      "/rank [用户名]-查询MCSR Ranked数据\n"
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
        else:
            self.player_data[userid]['username'] = username
        return self.player_data[userid]

    # 将用户添加到列表中
    @filter.command("register")
    async def register(self, event: AstrMessageEvent, username:str):
        try:
            userid = event.get_sender_id()
            # username = self.player_data[userid]['username']
            data = await fetch_api_data("paceman", "session_stats", username)
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
    async def paceman(self, event: AstrMessageEvent, name = None, test = None):
        try:
            if name is None:
                userid = event.get_sender_id()
                if userid not in self.player_data.keys():
                    yield event.plain_result("请先使用 '/register 用户名' 命令注册")
                    return
                username = self.player_data[userid]['username']
            else:
                username = name
            
            sessiondata = await fetch_api_data("paceman", "session_stats", username)
            nphdata = await fetch_api_data("paceman", "nph_stats", username)
            data = UserSessionStats(**sessiondata)
            render = Renderer(self, username, data, nphdata)
            if data.nether:
                sessionresult=(f"{username}\n"
                        f"下界数量:{data.nether.count},平均时间:{data.nether.avg}\n"
                        f"猪堡数量:{data.first_structure.count},平均时间:{data.first_structure.avg}\n"
                        f"下要数量:{data.second_structure.count},平均时间:{data.second_structure.avg}\n"
                        f"盲传数量:{data.first_portal.count},平均时间:{data.first_portal.avg}\n"
                        f"要塞数量:{data.stronghold.count},平均时间:{data.stronghold.avg}\n"
                        f"末地数量:{data.end.count},平均时间:{data.end.avg}\n"
                        f"完成数量:{data.finish.count},平均时间:{data.finish.avg}")
                try:
                    render_output = await render.render_dynamic(template_name="pacestats")
                    if not render_output:
                        logger.info("HTML render failed, falling back to PIL renderer.")
                        service = Paceman(username, data)
                        service.generate_image()
                        render_output = result_image_path()
                    chain = [
                        Comp.Image.fromFileSystem(render_output),
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
    
    @filter.command("run")
    async def run(self, event: AstrMessageEvent, name = None):
        try:
            if name is None:
                userid = event.get_sender_id()
                if userid not in self.player_data.keys():
                    yield event.plain_result("请先使用 '/register 用户名' 命令注册")
                    return
                username = self.player_data[userid]['username'] 
            else:
                username = name
            runs = await fetch_api_data("paceman", "recent_runs", username)
            if runs:
                recent_run=None
                for run in runs:
                    if run['finish']:
                        recent_run=RunStats(**run)
                        break
                if recent_run:
                    run_result=(f"{username}的最近一次速通数据:\n"
                            f"时间:{to_local_time(recent_run.updatedTime)}\n"
                            f"下界:{get_time(recent_run.nether)[0]}:{get_time(recent_run.nether)[1]:02d}\n"
                            f"猪堡:{get_time(recent_run.bastion)[0]}:{get_time(recent_run.bastion)[1]:02d}\n"
                            f"下要:{get_time(recent_run.fortress)[0]}:{get_time(recent_run.fortress)[1]:02d}\n"
                            f"盲传:{get_time(recent_run.first_portal)[0]}:{get_time(recent_run.first_portal)[1]:02d}\n"
                            f"要塞:{get_time(recent_run.stronghold)[0]}:{get_time(recent_run.stronghold)[1]:02d}\n"
                            f"末地:{get_time(recent_run.end)[0]}:{get_time(recent_run.end)[1]:02d}\n"
                            f"完成:{get_time(recent_run.finish)[0]}:{get_time(recent_run.finish)[1]:02d}\n")
                    try:
                        run_service = RunRenderer(self, username, recent_run)
                        render_output = await run_service.render_dynamic(template_name="run")
                        if not render_output:
                            logger.info("HTML render failed, falling back to PIL renderer.")
                            fallback_service = Run(recent_run, username)
                            fallback_service.generate_image()
                            render_output = result_image_path()
                        chain = [
                            Comp.Plain(f"{username}的最近一次速通数据:"),
                            Comp.Image.fromFileSystem(render_output),
                        ]
                        yield event.chain_result(chain)
                    except Exception as e:
                        logger.exception("Generate image error:")
                        yield event.plain_result(run_result)
                else:
                    yield event.plain_result("该玩家最近没有完成的run")
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
            logger.exception("Run command error:")
            yield event.plain_result(f"发生未知错误: {e}")

    async def start(self, event: AstrMessageEvent):
        logger.info("Paceman scheduled broadcast has been removed.")

    async def settime(self, event:AstrMessageEvent, hour:int, minute:int):
        yield event.plain_result("定时播报功能已移除")

    async def stop(self, event:AstrMessageEvent):
        yield event.plain_result("定时播报功能已移除")

    async def send_scheduled_paceman_leaderboard(self,hour,minute,message_target):
         logger.info("Paceman scheduled broadcast has been removed.")
    
    async def send_daily_leaderboard(self, message_target):
        logger.info("Paceman scheduled broadcast has been removed.")
        return "定时播报功能已移除"

    #查询Ranked个人数据
    @filter.command("rank")
    async def rank(self, event: AstrMessageEvent, name = None):
        try:
            if name is None:
                userid = event.get_sender_id()
                if userid not in self.player_data.keys():
                    yield event.plain_result("请先使用 '/register 用户名' 命令注册")
                    return
                username = self.player_data[userid]['username']
            else:
                username = name
            data = await fetch_api_data("ranked", "user_stats", username)
            if data['status']=='success':
                user=data['data']['nickname']
                elorate=data['data']['eloRate']
                elorank=data['data']['eloRank']
                personalbest=data['data']['statistics']['season']['bestTime']['ranked']
                forfeits=data['data']['statistics']['season']['forfeits']['ranked']
                playedMatches=data['data']['statistics']['season']['playedMatches']['ranked']
                completions=data['data']['statistics']['season']['completions']['ranked']
                completionTime=data['data']['statistics']['season']['completionTime']['ranked']
                wins=data['data']['statistics']['season']['wins']['ranked']
                if personalbest is None:
                    yield event.plain_result(f"{username}本赛季未参加ranked。")
                else:
                    forfeits_rate=forfeits/playedMatches
                    avg_completion_time=completionTime/completions
                    win_rate=wins/playedMatches
                    pb_m,pb_s=get_time(personalbest)
                    avg_m,avg_s=get_time(avg_completion_time)

                    result = (f"{user}:\n"
                        f"当前elo:{elorate}\n"
                        f"当前elo排名:{elorank}\n"
                        f"赛季PB:{pb_m}分{pb_s}秒\n"
                        f"赛季胜率:{win_rate*100:.2f}%\n"
                        f"赛季弃权率:{forfeits_rate*100:.2f}%\n"
                        f"赛季平均完成时间:{avg_m}分{avg_s}秒")
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
    
