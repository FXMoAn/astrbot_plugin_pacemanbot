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

class Paceman:
    # imgpath = './img'
    imgpath = "/root/astrbot/data/plugins/astrbot_plugin_pacemanbot/img"
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
                with open(f"{Paceman.imgpath}/{self._uname}.webp", "wb") as f:
                    f.write(response.content)

        try:
            image = Image.open(f"{Paceman.imgpath}/{self._uname}.webp").convert("RGBA")
            image = image.resize((158, 256))
            position = (350, 70)
            self.background.paste(image, position, mask=image)
        except Exception as e:
            logger.info(f"获取皮肤错误: {e}")

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
        self.background.save("/root/astrbot/data/plugins/astrbot_plugin_pacemanbot/result/output.png")
        # Paceman.background.save("./result/output.png")

    def generate_image(self):
        logger.info("Generating image...")

        self.generate_background_image()
        self.generate_skin()
        self.generate_stats()

        logger.info("Image generated successfully.")

if __name__ == "__main__":
    data = {
        "nether": StructureStats(count=10, avg="1.23"),
        "bastion": StructureStats(count=3, avg="4.56"),
        "fortress": StructureStats(count=2, avg="5.67"),
        "first_structure": StructureStats(count=1, avg="6.78"),
        "second_structure": StructureStats(count=0, avg="7.89"),
        "first_portal": StructureStats(count=4, avg="8.90"),
        "stronghold": StructureStats(count=1, avg="9.01"),
        "end": StructureStats(count=1, avg="10.11"),
        "finish": StructureStats(count=1, avg="11.12"),
    }
    test = UserSessionStats(**data)

    Paceman('doogile',test).generate_image()
