from pydantic import BaseModel, Field, ValidationError
from PIL import Image, ImageDraw, ImageFont
from astrbot.api import logger
import httpx

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

class Service:
    # imgpath = './img'
    imgpath = "/root/astrbot/data/plugins/astrbot_plugin_pacemanbot/img"
    # 背景图片
    smallfont = ImageFont.truetype(f"{imgpath}/1_Minecraft-Regular.otf", 24)
    bigfont = ImageFont.truetype(f"{imgpath}/1_Minecraft-Regular.otf", 40)


    def __init__(self,uname: str, data:UserSessionStats):
        self._uname = uname
        self.data = data
        self.background = Image.open(f"{Service.imgpath}/background.webp").convert("RGBA")
        self.icons = {
            "nether": Image.open(f"{Service.imgpath}/nether.webp").convert("RGBA"),
            "bastion": Image.open(f"{Service.imgpath}/bastion.webp").convert("RGBA"),
            "fortress": Image.open(f"{Service.imgpath}/fortress.webp").convert("RGBA"),
            "first_portal": Image.open(f"{Service.imgpath}/first_portal.webp").convert("RGBA"),
            "stronghold": Image.open(f"{Service.imgpath}/stronghold.webp").convert("RGBA"),
            "end": Image.open(f"{Service.imgpath}/end.webp").convert("RGBA"),
            "finish": Image.open(f"{Service.imgpath}/finish.webp").convert("RGBA"),
        }
        self.stats = {
            "netherstats": f'{self.data.nether.count} {self.data.nether.avg}',
            "bastionstats": f'{self.data.bastion.count} {self.data.bastion.avg}',
            "fortressstats": f'{self.data.fortress.count} {self.data.fortress.avg}',
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
        with httpx.Client() as client:
            response = client.get(url, headers=headers)
            if response.status_code == 200:
                with open(f"{Service.imgpath}/{self._uname}.webp", "wb") as f:
                    f.write(response.content)

        try:
            image = Image.open(f"{Service.imgpath}/{self._uname}.webp").convert("RGBA")
            image = image.resize((158, 256))
            position = (350, 70)
            self.background.paste(image, position, mask=image)
        except Exception as e:
            logger.info(f"获取皮肤错误: {e}")

    def generate_stats(self):
        # 绘制玩家昵称
        draw = ImageDraw.Draw(self.background)
        text_width = draw.textlength(self._uname, font=Service.smallfont)
        x = 430 - text_width / 2
        draw.text((x, 30), self._uname, fill="white", font=Service.smallfont)
        # 绘制数据
        for index, key in enumerate(self.stats):
            text_position = (100, index * 46 + 20)
            draw.text(text_position, self.stats[key], fill="white", font=Service.bigfont)
        self.background.save("/root/astrbot/data/plugins/astrbot_plugin_pacemanbot/result/output.png")
        # Service.background.save("./result/output.png")

    def generate_image(self):
        logger.info("Generating image...")

        self.generate_background_image()
        self.generate_skin()
        self.generate_stats()

        logger.info("Image generated successfully.")

if __name__ == "__main__":
    data = {
        "nether": {"count": 10, "avg": "1.23"},
        "bastion": {"count": 3, "avg": "4.56"},
        "fortress": {"count": 2, "avg": "5.67"},
        "first_structure": {"count": 1, "avg": "6.78"},
        "second_structure": {"count": 0, "avg": "7.89"},
        "first_portal": {"count": 4, "avg": "8.90"},
        "stronghold": {"count": 1, "avg": "9.01"},
        "end": {"count": 1, "avg": "10.11"},
        "finish": {"count": 1, "avg": "11.12"},
    }
    test = UserSessionStats(**data)

    Service('doogile',test).generate_image()
