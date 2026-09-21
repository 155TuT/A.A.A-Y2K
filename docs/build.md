# 原生打包与同源测试

安装构建依赖后，在项目根目录运行：

```powershell
.venv\Scripts\python.exe -m pip install ".[build,dev]"
.venv\Scripts\python.exe tools/build.py
```

其他平台使用对应 Python 命令即可。默认生成可直接分发的目录版；
Windows 可执行文件为 `dist/A.A.A-Y2K/A.A.A-Y2K.exe`，
必须与同目录的 `_internal` 一起分发。脚本还生成包含整个目录的 ZIP。
可选 `--onefile` 生成单文件版，`--console` 保留调试控制台。

构建采用 [PyInstaller](https://pyinstaller.org/en/stable/usage.html)：
将 Python 运行时、Textual、SDL/pygame-ce、Pillow、字体、许可证、TCSS 与共享测试嵌入产物。
设置、存档和自定义地图仍保存在用户数据目录，不写入安装包。

## 同一测试流程

`src/arrow_y2k/selftest.py` 是唯一的共享测试实现，依赖标准库 `unittest`，
不要求最终用户安装 Python 或 pytest。`tests/test_shared_contract.py`
直接导入相同 TestCase，没有复制另一份断言。

```powershell
.venv\Scripts\python.exe run.py --self-test --test-report build/reports/source.json
dist\A.A.A-Y2K\A.A.A-Y2K.exe --self-test --test-report build/reports/frozen.json
.venv\Scripts\python.exe tools/build.py --compare build/reports/source.json build/reports/frozen.json
```

无控制台的 Windows 产物通过 JSON 报告和退出码提供结果；通过返回 0，失败返回 1。
每次测试使用独立临时目录，不读写真实用户存档、不访问 GitHub 链接。
计时用注入时钟测试，不等待真实倒计时。

当前共享套件为 21 项：四向射线、自身阻挡、穿洞与交叉约束、种子确定性、
全部中等/困难模板可解性、新模式从第 1 关开始、难度过渡、超时、
无尽奖励与两个胜利条件、设置/档案、五槽完整快照、自定义地图与内置模板不可变、
旧地图导入与原子写入失败、成就去重/阈值、字体资产、主页/全局 ESC、
暂停计时、关闭自动保存、读档计时，以及 SDL 原生宿主截图的整数缩放。开发用 `pytest` 还运行额外回归测试；
这些额外测试不等同于最终二进制内的共享套件。

默认构建流程依次执行源代码共享测试、构建、二进制共享测试，并核对：

1. 两份报告分别来自源代码与 frozen 程序；
2. 所有用例都通过，无跳过项；
3. test ID、状态、测试数量完全相同；
4. 构建期间源代码和资源没有变化。

全部通过后才生成发布 ZIP 与 `dist/build-manifest.json`。
清单记录平台、Python 版本、测试 ID、源码/资源 SHA-256、可执行文件 SHA-256 和 ZIP SHA-256。
完整测试日志保存在 `build/reports/source.json` 与 `frozen.json`。

## 跨平台边界

`.github/workflows/build.yml` 提供 Windows、macOS、Linux 原生 runner 矩阵；
每个平台都独立安装、执行开发测试、构建并验证自身二进制。
手动工作流、相关改动的 PR 或版本标签触发构建，上传 ZIP、清单与报告，不自动发布 Release。
macOS 使用 `.app`，Linux 使用本机可执行程序。
本地 Windows 构建通过不代表 macOS/Linux 已实机验证，应以对应 runner 的成功报告为证据。
