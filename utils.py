import json
import os
from datetime import timedelta
import httpx

PACEMAN_BASE_URL="https://paceman.gg/stats/api"
RANKED_BASE_URL="https://api.mcsrranked.com"

# 封装请求方法
async def request(type,url):
    if type=="paceman":
        base_url=PACEMAN_BASE_URL
    elif type=="ranked":
        base_url=RANKED_BASE_URL
    else:
        raise ValueError(f"Invalid type: {type}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response=await client.get(f"{base_url}{url}")
        response.raise_for_status()
        return response.json()

# 加载json数据
def load_data(filename):
    # 传入filename文件名，返回json
    if not os.path.exists(filename):
        return {}
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

# 保存json数据
def save_data(filename,dataname):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(dataname, f, ensure_ascii=False, indent=4)

def get_time(seconds):
    stdtime = timedelta(seconds=seconds/1000)
    minutes = stdtime.seconds // 60
    seconds = stdtime.seconds % 60
    return minutes,seconds
