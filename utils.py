import json
import os
from datetime import timedelta

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
