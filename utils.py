import json
import os
from datetime import timedelta
import httpx
from astrbot.api import logger

PACEMAN_BASE_URL="https://paceman.gg/stats/api"
RANKED_BASE_URL="https://api.mcsrranked.com"

API_ENDPOINTS = {
    "paceman": {
        "session_stats": "/getSessionStats/?name={username}&hours=24&hoursBetween=24",
        "nph_stats": "/getNPH/?name={username}&hours=24&hoursBetween=24",
        "recent_runs": "/getRecentRuns/?name={username}&hours=240&limit=50"
    },
    "ranked": {
        "user_stats": "/users/{username}"
    }
}

async def fetch_api_data(api_type: str, endpoint_type: str, username: str, timeout: float = 10.0):
    if api_type not in API_ENDPOINTS:
        raise ValueError(f"无效的API类型: {api_type}")
    
    if endpoint_type not in API_ENDPOINTS[api_type]:
        raise ValueError(f"无效的端点类型: {endpoint_type}")
    
    # 基础URL
    if api_type == "paceman":
        base_url = PACEMAN_BASE_URL
    elif api_type == "ranked":
        base_url = RANKED_BASE_URL
    else:
        raise ValueError(f"不支持的API类型: {api_type}")
    
    # 完整URL
    endpoint = API_ENDPOINTS[api_type][endpoint_type]
    url = f"{base_url}{endpoint.format(username=username)}"
    
    logger.info(f"请求 {api_type} API: {url}")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            return data
    except httpx.HTTPStatusError as e:
        logger.error(f"{api_type} API HTTP错误: {e}")
        raise
    except httpx.TimeoutException as e:
        logger.error(f"{api_type} API 请求超时: {e}")
        raise
    except httpx.HTTPError as e:
        logger.error(f"{api_type} API 网络错误: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"{api_type} API JSON解析错误: {e}")
        raise


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
