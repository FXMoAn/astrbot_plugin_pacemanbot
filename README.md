# pacemanbot

AstrBot 插件，用于查询 Minecraft 速通的 PaceMan 数据和 MCSR Ranked 数据。

## 安装

需要 **AstrBot 4.9.2 或更高版本**。安装插件时会通过 `requirements.txt` 声明 `httpx`、`Pillow` 和 `pydantic` 依赖。

## 命令

使用 `/bothelp` 或 `/pmhelp` 查看本插件完整帮助。下面的方括号表示可选参数，输入时不需要方括号。

| 命令 | 功能 | 示例 |
| --- | --- | --- |
| `/register 用户名` | 将游戏玩家绑定到当前聊天账号；PaceMan 或 Ranked 任意一个来源能确认玩家即可注册 | `/register LEC666888` |
| `/paceman [用户名] [小时]` | 查询 PaceMan 时间窗口内的统计，默认 24 小时 | `/paceman`、`/paceman 12`、`/paceman LEC666888 48` |
| `/run [用户名]` | 查询最近一次完成的 PaceMan 速通 | `/run`、`/run LEC666888` |
| `/pb [用户名]` | 查询 PaceMan 的个人最好完成时间 | `/pb`、`/pb LEC666888` |
| `/rank [用户名] [赛季]` | 查询 Ranked 当前或指定历史赛季的场次、Elo、排名、PB 和完成时间 | `/rank`、`/rank 10`、`/rank LEC666888 10` |
| `/recent [用户名] [条数]` | 查询最近 1–10 场 Ranked 排位比赛，默认 5 场 | `/recent`、`/recent 3`、`/recent LEC666888 10` |
| `/ldb [cn] [页码] [赛季]` | 查询 Ranked 全球或中国榜单；默认当前赛季第 1 页，每页 20 名 | `/ldb`、`/ldb cn`、`/ldb cn 2`、`/ldb 1 10` |

没有提供用户名时，`/paceman`、`/run`、`/pb`、`/rank` 和 `/recent` 使用当前账号已绑定的玩家。只提供数字时，`/paceman 12` 表示本人最近 12 小时，`/rank 10` 表示本人第 10 赛季，`/recent 3` 表示本人最近 3 场。PaceMan 的查询窗口允许 1–168 小时，Ranked 赛季为 `0` 时查询当前赛季。

`/ldb` 的数字依次是**页码、赛季**。例如 `/ldb cn 1 10` 查询第 10 赛季中国榜单第 1 页。分页在插件内完成，服务器只接收 `country` 和 `season` 筛选参数。

## 数据说明

- **PaceMan 数据范围**：数据来自 PaceMan 记录，未被记录的游戏不会出现在查询中。`/paceman` 的小时参数表示统计时间窗口；`/run` 显示完成的记录，无法保证玩家最近一次启动的游戏已经完成。
- **RNPH**：直接显示 PaceMan 返回的 `rnph`，计算方式为下界次数除以 `(wallTime + playTime)` 对应的小时数。分母计入刷墙和主世界时间，不计入刷墙挂机或下界时间；不是直接除以查询窗口的 24 小时。它只覆盖启用了 NPH 追踪的记录，与普通统计中的下界次数可能不同。`rpe = resets / nethers`，表示每次进下界平均刷种数。缺少数据时显示暂无数据；`totalResets` 来自追踪器或宏，不表示完整生涯的刷种总数。
- **阶段名称**：继续使用原有的猪堡、下要等展示方式。API 的 `first_structure`、`second_structure` 按现有界面映射展示。
- **Ranked 参赛状态**：没有赛季 PB 不等于没有参赛。插件按排位场次判断是否参加；没有完成记录或尚未定级时分别展示相应状态，避免除以 0 或直接显示 `None`。
- **历史 Ranked 分数**：指定赛季时使用该赛季的 `seasonResult.last`，避免把玩家当前 Elo 当成历史赛季成绩。
- **近期排位**：请求 `type=2`、`excludedecay=true`，并过滤 Elo 衰减记录。比赛用时是 Ranked 的整场结果用时，不一定是查询玩家的个人完成时间；弃权结束会单独标注。Elo 变化按查询玩家 UUID 匹配。
- **中国榜单**：按 Ranked 玩家资料中的 `country=cn` 筛选。列表序号表示当前筛选榜单位置，括号内显示全球排名；这不是根据玩家姓名或聊天账号推断的国籍。

## 请求与缓存

插件复用异步 HTTP 客户端，并对相同请求缓存、合并同时发起的重复查询。缓存中的数据可能稍有延迟；不同玩家、小时、赛季和国家参数分别缓存。

限流、超时、接口故障、玩家不存在和数据格式异常会给出不同提示。失败结果不会作为正常数据写入缓存；缓存到期后重新请求接口。Ranked 官方默认限制是每 10 分钟 500 次请求，其推荐 API 域名自身还有 5 秒缓存。

可在 AstrBot 插件配置中调整以下参数。默认值如下，缓存时长的 `0` 表示关闭对应缓存。

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `request_timeout` | `10` | 单次 HTTP 请求超时，单位秒 |
| `request_concurrency` | `6` | 同时进行的 HTTP 请求上限 |
| `user_cache_ttl` | `20` | 玩家、统计与近期比赛数据的缓存时长，单位秒 |
| `leaderboard_cache_ttl` | `60` | 榜单数据缓存时长，单位秒 |
| `paceman_hours` | `24` | 未指定小时参数时使用的 PaceMan 查询窗口 |
| `leaderboard_page_size` | `20` | 榜单每页人数，可设为 1–50 |
| `timezone` | `Asia/Shanghai` | 比赛与完成日期使用的时区 |
| `image_mode` | `auto` | `auto` 使用 HTML 图片并在失败后回退，`pil` 使用本地图片，`text` 直接返回文字 |
| `render_concurrency` | `2` | 同时生成的图片数量上限 |
| `render_timeout` | `12` | 单次图片渲染超时，单位秒 |
| `render_attempts` | `2` | HTML 图片渲染尝试次数，最多 2 次 |
| `skin_timeout` | `3` | 玩家皮肤请求超时，单位秒 |
| `skin_cache_ttl` | `86400` | 玩家皮肤缓存时长，单位秒 |
| `skin_cache_max_files` | `200` | 本地皮肤缓存文件数上限 |

## 绑定与升级

绑定保存游戏 UUID、规范用户名和验证来源。查询优先使用 UUID，减少改名后绑定失效的情况；仅凭 PaceMan 数据注册时仍然保留该来源，不要求玩家同时拥有 Ranked 记录。

升级会迁移旧的 `data/astrbot-pacemanbot.json` 绑定，保留原文件，并在 `data/plugin_data/pacemanbot/legacy-bindings-backup.json` 保存备份。旧记录首次成功查询后会补全 UUID 等信息。旧格式没有平台信息，因此仅在 QQ 平台首次使用时恢复到当前平台实例；其他平台可以重新 `/register`。

新绑定使用 AstrBot 的插件 KV 存储，按平台实例和聊天账号区分，避免不同平台或不同机器人实例的相同账号编号互相覆盖。JSON 备份通过临时文件后原子替换写入。

## 官方资料

- [PaceMan Stats API](https://paceman.gg/stats/api/)
- [MCSR Ranked API 文档](https://docs.mcsrranked.com/)
- [MCSR Ranked OpenAPI](https://raw.githubusercontent.com/MCSR-Ranked/api-docs/refs/heads/master/openapi.yaml)
- [AstrBot 插件开发文档](https://docs.astrbot.app/dev/star/plugin-new.html)

## 支持

如有建议，请在 [GitHub 仓库](https://github.com/FXMoAn/astrbot_plugin_pacemanbot) 提交 issue，或联系墨安 QQ：2686014341。
