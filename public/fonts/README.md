# PaceManUIChinese

随插件提供的中文界面字体，运行时无需安装系统字体或下载字体。
数字和玩家名继续使用插件原有的 Minecraft 字体。

- 上游：Noto Sans SC Regular，Noto CJK 官方仓库提交
  `523d033d6cb47f4a80c58a35753646f5c3608a78`。
- 原文件：<https://raw.githubusercontent.com/notofonts/noto-cjk/523d033d6cb47f4a80c58a35753646f5c3608a78/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf>
- 原文件 SHA-256：`faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9`。
- 授权：SIL Open Font License 1.1，完整版权及许可见 [OFL.txt](OFL.txt)。
  许可副本来源：<https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt>。
- 修改：保留当前图片界面所需汉字、可打印 ASCII 及标点，移除字体指令；
  将字体家族、完整名、PostScript 名与 CFF 名改为独立名称
  `PaceManUIChinese`，保留原版权及许可元数据。

## 更新文案后重建

`subset_font.py` 从 `paceman.py`、`pacestats.html`、`run.html`
收集汉字，再生成字体。fontTools 只用于开发，不是插件运行依赖。

在插件根目录执行，原字体请从上面固定提交下载并核对 SHA-256：

```sh
python -m pip install --target /tmp/paceman-font-build-tools fonttools==4.60.1
PYTHONPATH=/tmp/paceman-font-build-tools python public/fonts/subset_font.py /tmp/NotoSansSC-Regular.otf
python -m unittest discover -s tests -p test_render.py
```

测试会检查现有界面汉字能否由内置字体实际绘制；新增汉字后必须一并更新字体。
测试只依赖 Pillow，不需要 fontTools 或系统中文字体。
