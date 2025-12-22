"""
Jinja2 模板使用示例

这个文件展示了如何使用 pacestats.html 和 run.html 模板
"""

from jinja2 import Environment, FileSystemLoader
from pathlib import Path

# 设置模板目录
template_dir = Path(__file__).parent
env = Environment(loader=FileSystemLoader(str(template_dir)))

# ========== 示例1: 渲染 pacestats.html (对应 Paceman 类) ==========

def render_pacestats_example():
    """渲染玩家统计数据模板"""
    template = env.get_template('pacestats.html')
    
    # 示例数据 - 对应 UserSessionStats 结构
    data = {
        'uname': 'Steve',
        'stats': {
            'nether': {
                'count': 15,
                'avg': '12:34'
            },
            'first_structure': {  # bastion
                'count': 12,
                'avg': '10:20'
            },
            'second_structure': {  # fortress
                'count': 8,
                'avg': '8:15'
            },
            'first_portal': {
                'count': 10,
                'avg': '9:30'
            },
            'stronghold': {
                'count': 5,
                'avg': '15:45'
            },
            'end': {
                'count': 3,
                'avg': '18:20'
            },
            'finish': {
                'count': 2,
                'avg': '20:10'
            }
        }
    }
    
    html_output = template.render(**data)
    
    # 保存到文件
    output_path = template_dir / 'example_pacestats_output.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_output)
    
    print(f"✓ pacestats.html 渲染完成，输出到: {output_path}")
    return html_output


# ========== 示例2: 渲染 run.html (对应 Run 类) ==========

def render_run_example():
    """渲染单次运行记录模板"""
    template = env.get_template('run.html')
    
    # 示例数据 - 对应 RunStats 结构
    # 注意：时间需要格式化为 "分钟:秒" 格式（两位数秒）
    data = {
        'uname': 'Alex',
        'times': {
            'nether': '2:15',      # 格式: 分钟:秒（秒为两位数）
            'bastion': '3:45',
            'fortress': '5:20',
            'first_portal': '6:10',
            'stronghold': '8:30',
            'end': '10:15',
            'finish': '12:45'
        },
        'update_time': '2024-01-15'  # 格式: YYYY-MM-DD
    }
    
    html_output = template.render(**data)
    
    # 保存到文件
    output_path = template_dir / 'example_run_output.html'
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_output)
    
    print(f"✓ run.html 渲染完成，输出到: {output_path}")
    return html_output


# ========== 示例3: 从实际数据结构转换 ==========

def convert_paceman_data_to_template(uname: str, user_session_stats):
    """
    将 Paceman 类的数据转换为模板所需格式
    
    参数:
        uname: 玩家用户名
        user_session_stats: UserSessionStats 对象
    """
    template = env.get_template('pacestats.html')
    
    data = {
        'uname': uname,
        'stats': {
            'nether': {
                'count': user_session_stats.nether.count,
                'avg': user_session_stats.nether.avg
            },
            'first_structure': {
                'count': user_session_stats.first_structure.count,
                'avg': user_session_stats.first_structure.avg
            },
            'second_structure': {
                'count': user_session_stats.second_structure.count,
                'avg': user_session_stats.second_structure.avg
            },
            'first_portal': {
                'count': user_session_stats.first_portal.count,
                'avg': user_session_stats.first_portal.avg
            },
            'stronghold': {
                'count': user_session_stats.stronghold.count,
                'avg': user_session_stats.stronghold.avg
            },
            'end': {
                'count': user_session_stats.end.count,
                'avg': user_session_stats.end.avg
            },
            'finish': {
                'count': user_session_stats.finish.count,
                'avg': user_session_stats.finish.avg
            }
        }
    }
    
    return template.render(**data)


def convert_run_data_to_template(uname: str, run_stats, get_time_func, to_local_time_func):
    """
    将 Run 类的数据转换为模板所需格式
    
    参数:
        uname: 玩家用户名
        run_stats: RunStats 对象
        get_time_func: 时间转换函数，接受毫秒数，返回 (分钟, 秒)
        to_local_time_func: 时间戳转换函数，接受时间戳，返回 "YYYY-MM-DD" 格式字符串
    """
    template = env.get_template('run.html')
    
    def format_time(ms):
        """将毫秒转换为 "分钟:秒" 格式"""
        minutes, seconds = get_time_func(ms)
        return f"{minutes}:{seconds:02d}"
    
    data = {
        'uname': uname,
        'times': {
            'nether': format_time(run_stats.nether),
            'bastion': format_time(run_stats.bastion),
            'fortress': format_time(run_stats.fortress),
            'first_portal': format_time(run_stats.first_portal),
            'stronghold': format_time(run_stats.stronghold),
            'end': format_time(run_stats.end),
            'finish': format_time(run_stats.finish)
        },
        'update_time': to_local_time_func(run_stats.updatedTime)
    }
    
    return template.render(**data)


# ========== 主函数：运行示例 ==========

if __name__ == '__main__':
    print("=" * 50)
    print("Jinja2 模板使用示例")
    print("=" * 50)
    print()
    
    # 运行示例1
    print("示例1: 渲染 pacestats.html")
    render_pacestats_example()
    print()
    
    # 运行示例2
    print("示例2: 渲染 run.html")
    render_run_example()
    print()
    
    print("=" * 50)
    print("所有示例运行完成！")
    print("=" * 50)
    print()
    print("提示:")
    print("1. 模板文件位于: public/templates/")
    print("2. 图片资源位于: public/")
    print("3. 使用相对路径 '../' 引用图片资源")
    print("4. 玩家皮肤使用在线API: https://render.crafty.gg/3d/full/{username}")
