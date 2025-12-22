from pdb import run
from pydantic import BaseModel, Field, ValidationError
from PIL import Image, ImageDraw, ImageFont
from astrbot.api import logger
from astrbot.api.all import Star
import httpx
from .constant import *
import os
import asyncio
try:
    from .utils import get_time, to_local_time
except ImportError:
    from utils import get_time, to_local_time

class StructureStats(BaseModel):
    count: int
    avg: str

class UserSessionStats(BaseModel):
    nether: StructureStats
    bastion: StructureStats
    fortress: StructureStats
    first_structure: StructureStats
    second_structure: StructureStats
    first_portal: StructureStats
    stronghold: StructureStats
    end: StructureStats
    finish: StructureStats

class RunStats(BaseModel):
    id:int
    nether:int
    bastion:int
    fortress:int
    first_portal:int
    stronghold:int
    end:int
    finish:int
    lootBastion:int
    obtainObsidian:int
    obtainCryingObsidian:int
    obtainRod:int
    time:int
    updatedTime:int
    realUpdated:int

class Paceman:
    # imgpath = './img'
    imgpath = os.path.join(os.path.dirname(__file__), "public")
    # 背景图片
    smallfont = ImageFont.truetype(f"{imgpath}/1_Minecraft-Regular.otf", 24)
    bigfont = ImageFont.truetype(f"{imgpath}/1_Minecraft-Regular.otf", 40)

    def __init__(self,uname: str, data:UserSessionStats):
        self._uname = uname
        self.data = data
        self.background = Image.open(f"{Paceman.imgpath}/background.webp").convert("RGBA")
        self.icons = {
            "nether": Image.open(f"{Paceman.imgpath}/nether.webp").convert("RGBA"),
            "bastion": Image.open(f"{Paceman.imgpath}/bastion.webp").convert("RGBA"),
            "fortress": Image.open(f"{Paceman.imgpath}/fortress.webp").convert("RGBA"),
            "first_portal": Image.open(f"{Paceman.imgpath}/first_portal.webp").convert("RGBA"),
            "stronghold": Image.open(f"{Paceman.imgpath}/stronghold.webp").convert("RGBA"),
            "end": Image.open(f"{Paceman.imgpath}/end.webp").convert("RGBA"),
            "finish": Image.open(f"{Paceman.imgpath}/finish.webp").convert("RGBA"),
        }
        self.stats = {
            "netherstats": f'{self.data.nether.count} {self.data.nether.avg}',
            "bastionstats": f'{self.data.first_structure.count} {self.data.first_structure.avg}',
            "fortressstats": f'{self.data.second_structure.count} {self.data.second_structure.avg}',
            "first_portalstats": f'{self.data.first_portal.count} {self.data.first_portal.avg}',
            "strongholdstats": f'{self.data.stronghold.count} {self.data.stronghold.avg}',
            "endstats": f'{self.data.end.count} {self.data.end.avg}',
            "finishstats": f'{self.data.finish.count} {self.data.finish.avg}'
        }

    def generate_background_image(self):
        for index, key in enumerate(self.icons):
            pic = self.icons[key].resize((40, 40))
            position = (20, index * 46 + 20)
            self.background.paste(pic, position, mask=pic)

    def generate_skin(self):
        url = f"https://render.crafty.gg/3d/full/{self._uname}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        try:
            with httpx.Client() as client:
                response = client.get(url, headers=headers, timeout=20.0)
                if response.status_code == 200:
                    with open(f"{Paceman.imgpath}/{self._uname}.webp", "wb") as f:
                        f.write(response.content)
        except Exception as e:
            logger.info(f"获取皮肤失败: {e}")

        try:
            image = Image.open(f"{Paceman.imgpath}/{self._uname}.webp").convert("RGBA")
            image = image.resize((158, 256))
            position = (350, 70)
            self.background.paste(image, position, mask=image)
        except Exception as e:
            logger.info(f"皮肤文件不存在: {e}")

    def generate_stats(self):
        # 绘制玩家昵称
        draw = ImageDraw.Draw(self.background)
        text_width = draw.textlength(self._uname, font=Paceman.smallfont)
        x = 430 - text_width / 2
        draw.text((x, 30), self._uname, fill="white", font=Paceman.smallfont)
        # 绘制数据
        for index, key in enumerate(self.stats):
            text_position = (100, index * 46 + 20)
            draw.text(text_position, self.stats[key], fill="white", font=Paceman.bigfont)
        self.background.save(os.path.join(os.path.dirname(__file__), "result", "output.png"))
        # Paceman.background.save("./result/output.png")

    def generate_image(self):
        logger.info("Generating image...")

        self.generate_background_image()
        self.generate_skin()
        self.generate_stats()

        logger.info("Image generated successfully.")

class Run:
    imgpath = os.path.join(os.path.dirname(__file__), "public", "img")
    smallfont = ImageFont.truetype(f"{imgpath}/1_Minecraft-Regular.otf", 24)
    bigfont = ImageFont.truetype(f"{imgpath}/1_Minecraft-Regular.otf", 40)

    def __init__(self, run:RunStats, uname:str):
        self._uname = uname
        self.run = run
        self.background = Image.open(f"{Paceman.imgpath}/background.webp").convert("RGBA")
        self.icons = {
            "nether": Image.open(f"{Paceman.imgpath}/nether.webp").convert("RGBA"),
            "bastion": Image.open(f"{Paceman.imgpath}/bastion.webp").convert("RGBA"),
            "fortress": Image.open(f"{Paceman.imgpath}/fortress.webp").convert("RGBA"),
            "first_portal": Image.open(f"{Paceman.imgpath}/first_portal.webp").convert("RGBA"),
            "stronghold": Image.open(f"{Paceman.imgpath}/stronghold.webp").convert("RGBA"),
            "end": Image.open(f"{Paceman.imgpath}/end.webp").convert("RGBA"),
            "finish": Image.open(f"{Paceman.imgpath}/finish.webp").convert("RGBA"),
        }
        self.stats = {
            "netherstats": f'{get_time(self.run.nether)[0]}:{get_time(self.run.nether)[1]:02d}',
            "bastionstats": f'{get_time(self.run.bastion)[0]}:{get_time(self.run.bastion)[1]:02d}',
            "fortressstats": f'{get_time(self.run.fortress)[0]}:{get_time(self.run.fortress)[1]:02d}',
            "first_portalstats": f'{get_time(self.run.first_portal)[0]}:{get_time(self.run.first_portal)[1]:02d}',
            "strongholdstats": f'{get_time(self.run.stronghold)[0]}:{get_time(self.run.stronghold)[1]:02d}',
            "endstats": f'{get_time(self.run.end)[0]}:{get_time(self.run.end)[1]:02d}',
            "finishstats": f'{get_time(self.run.finish)[0]}:{get_time(self.run.finish)[1]:02d}',
        }

    def generate_background_image(self):
        for index, key in enumerate(self.icons):
            pic = self.icons[key].resize((40, 40))
            position = (20, index * 46 + 20)
            self.background.paste(pic, position, mask=pic)

    def generate_skin(self):
        url = f"https://render.crafty.gg/3d/full/{self._uname}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        try:
            with httpx.Client() as client:
                response = client.get(url, headers=headers, timeout=20.0)
                if response.status_code == 200:
                    with open(f"{Run.imgpath}/{self._uname}.webp", "wb") as f:
                        f.write(response.content)
        except Exception as e:
            logger.info(f"获取皮肤失败: {e}")

        try:
            image = Image.open(f"{Run.imgpath}/{self._uname}.webp").convert("RGBA")
            image = image.resize((158, 256))
            position = (350, 70)
            self.background.paste(image, position, mask=image)
        except Exception as e:
            logger.info(f"皮肤文件不存在: {e}")
        
    def generate_stats(self):
        draw = ImageDraw.Draw(self.background)
        text_width = draw.textlength(self._uname, font=Run.smallfont)
        x = 430 - text_width / 2
        draw.text((x, 30), self._uname, fill="white", font=Run.smallfont)
        # 绘制数据
        for index, key in enumerate(self.stats):
            text_position = (100, index * 46 + 20)
            draw.text(text_position, self.stats[key], fill="white", font=Paceman.bigfont)
        # 绘制时间,在底部居中位置
        text_position = (290 - draw.textlength(to_local_time(self.run.updatedTime), font=Run.smallfont) / 2, 330)
        draw.text(text_position, to_local_time(self.run.updatedTime), fill="white", font=Paceman.smallfont)
        self.background.save(os.path.join(os.path.dirname(__file__), "result", "output.png"))

    def generate_image(self):
        logger.info("Generating image...")

        self.generate_background_image()
        self.generate_skin()
        self.generate_stats()

        logger.info("Image generated successfully.")

def load_template(template_name: str) -> str:
    template_path = get_template_path(template_name)
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

class Renderer:
    def __init__(self, star_instance: Star, uname: str, data:UserSessionStats):
        self._uname = uname
        self.data = data
        self.star = star_instance

        self.stats = {
            "uname": self._uname,
            "stats": {
                "nether": {
                    "count": self.data.nether.count,
                    "avg": self.data.nether.avg
                },
                "bastion": {
                    "count": self.data.first_structure.count,
                    "avg": self.data.first_structure.avg
                },
                "fortress": {
                    "count": self.data.second_structure.count,
                    "avg": self.data.second_structure.avg
                },
                "first_portal": {
                    "count": self.data.first_portal.count,
                    "avg": self.data.first_portal.avg
                },
                "stronghold": {
                    "count": self.data.stronghold.count,
                    "avg": self.data.stronghold.avg
                },
                "end": {
                    "count": self.data.end.count,
                    "avg": self.data.end.avg
                },
                "finish": {
                    "count": self.data.finish.count,
                    "avg": self.data.finish.avg
                }
            }
        }

    async def render_dynamic(self, template_name: str = DEFAULT_TEMPLATE):
        """
        将渲染数据字典渲染成最终图片。
        这是该类的主要入口方法。
        """
        options = {"full_page": False, "type": "png", "scale": "device"}

        tmpl = load_template(template_name)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            render_output = None
            try:
                render_output = await self.star.html_render(
                    tmpl=tmpl,
                    data=self.stats,
                    return_url=False,
                    options=options,
                )
                if (
                    render_output
                    and os.path.exists(render_output)
                    and os.path.getsize(render_output) > 4096
                ):
                    return render_output  # 成功，直接返回渲染结果
            except Exception as e:
                logger.error(f"渲染图片失败 (尝试次数: {attempt}): {e}")

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAY)
