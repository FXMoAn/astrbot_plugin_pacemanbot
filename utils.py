import json
import os

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
