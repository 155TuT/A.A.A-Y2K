# 原生安装包与自动发布

正式发布提供 Windows x64 安装器、macOS arm64/x64 的 PKG 与 DMG，以及 Linux x64 便携 ZIP。每个平台必须在对应系统构建；PyInstaller 不负责跨操作系统编译。

## 本地构建

使用 Python 3.11+ 创建并激活虚拟环境，在项目根目录执行：

```sh
python -m pip install -c packaging/constraints.txt setuptools
python -m pip install --no-build-isolation -c packaging/constraints.txt -e ".[build,dev]"
python -m ruff check src tools tests run.py
python -m pytest -q --junitxml=build/reports/pytest.xml
python tools/build.py
```

默认命令生成完整目录包和便携 ZIP，用于本地诊断。Windows 程序位于 `dist/A.A.A-Y2K/A.A.A-Y2K.exe`，同目录 `_internal` 必须保留。macOS 生成 `dist/A.A.A-Y2K.app`。正式 Windows/macOS 发布使用：

```sh
python tools/build.py --installer
```

Windows 需要 [Inno Setup 6](https://jrsoftware.org/isdl.php)，可通过环境变量 `ISCC` 指定 `ISCC.exe`；CI 下载固定的 6.7.3 并核验 SHA-256。macOS 使用系统的 `pkgbuild`、`hdiutil` 和 `ditto`。构建配方统一保存在 `packaging/arrow_y2k.spec`，不再提供单文件游戏 EXE 构建选项。

`src/arrow_y2k/__init__.py` 中的 `__version__` 是程序版本的唯一来源。Setuptools 动态读取它，构建校验安装元数据与源码版本，并要求发布标签恰为 `v<版本>`。更新版本后需重新安装项目以刷新元数据。

生成的发布文件位于 `dist/release/<平台-架构>/`，文件名包含版本、平台与架构。旧版本的文件不会被自动当成新版本发布。

## 安装行为

| 平台 | 产物 | 安装行为 |
| --- | --- | --- |
| Windows x64 | `A.A.A-Y2K-<版本>-windows-x64-Setup.exe` | 当前用户安装，默认到 `%LOCALAPPDATA%/Programs/ArrowAfterArrowY2K`；开始菜单入口、可选桌面快捷方式、系统卸载入口 |
| macOS Apple Silicon | `A.A.A-Y2K-<版本>-macos-arm64.pkg` / `.dmg` | PKG 安装到 `/Applications`；DMG 拖拽应用到 Applications |
| macOS Intel | `A.A.A-Y2K-<版本>-macos-x64.pkg` / `.dmg` | 同上，为 Intel 独立原生构建 |
| Linux x64 | `A.A.A-Y2K-<版本>-linux-x64-portable.zip` | 用支持 Unix 权限和符号链接的解压工具完整解压 |

游戏数据始终使用 `platformdirs` 的用户数据目录，不写入安装目录。Windows 卸载只移除应用文件与快捷方式，保留玩家进度；macOS 可移除 Applications 中的应用，用户数据仍独立保留。PKG 安装可能请求系统管理员授权，DMG 也可按本机权限复制到用户应用目录。

本版没有发布者代码签名证书：Windows 安装包未做 Authenticode 签名，macOS 应用只有 PyInstaller 的 ad-hoc 签名，未使用 Developer ID 或 Apple 公证。首次打开可能出现系统来源提示；应先确认下载来自本仓库并核对 SHA-256，再按系统界面选择是否允许。不要全局关闭 Gatekeeper 或其他系统保护。参见 [Apple 关于安全打开应用的说明](https://support.apple.com/en-us/102445)。

## 源码、冻结程序与安装后验证

`selftest.py` 是源码、pytest 和冻结程序共同使用的 unittest 套件。所有用例使用临时数据；windowed 程序以 JSON 报告和退出码返回结果。可以单独复现：

```powershell
python run.py --self-test --test-report build/reports/source.json
.\dist\A.A.A-Y2K\A.A.A-Y2K.exe --self-test --test-report build/reports/frozen.json
python tools/build.py --compare build/reports/source.json build/reports/frozen.json
```

构建门禁要求：版本相同、测试 ID 与数量相同、所有用例成功且没有跳过项、构建期间源码和资源没有变化。每次执行先移除对应旧报告，防止陈旧结果误通过。清单记录源码与打包脚本、资源、依赖版本、提交及资产哈希。

`tools/verify_installers.py` 在一次性 GitHub runner 上执行安装验证：Windows 静默安装与重复安装，运行已安装程序，再卸载并确认玩家目录中的标记文件保留；macOS 实际安装 PKG，并挂载 DMG、复制应用、检查签名；Linux 完整解压 ZIP。每种产物都运行同一共享套件，正常启动程序、输出 1024×768 内屏截图并完成退出。

Windows 安装和 macOS PKG 检查会写系统安装状态，因此脚本限制在一次性 CI 环境执行，不在玩家本机替换已有安装。Windows 本机窗口、三档分辨率、原生区域和交互验证仍可通过 `python tools/verify_native.py --output output/native-release-040` 执行。

## GitHub Actions

工作流 `.github/workflows/build.yml` 使用 Windows 2022 x64、macOS 14 arm64、macOS 15 Intel 与 Ubuntu 22.04 x64 的独立原生 runner，Python 固定为 3.13.5。主要构建和测试依赖固定在 `packaging/constraints.txt`；实际解析到的全部依赖版本写入每个平台的清单。官方 Action 依赖固定到提交 SHA。

- `main` 推送、相关 PR 和手动运行：检查、构建、安装验证，上传 Actions artifacts。
- 推送 `v<版本>` 标签：上述四个平台全部成功后自动发布。
- 手动运行勾选 `publish`：同样在整个矩阵通过后发布当前源码版本。

推荐发布步骤：

```sh
# 先修改 __version__，更新 docs/releases/v<版本>.md，提交并推送代码。
# 在 main 的原生矩阵通过后，为同一提交创建标签。
git tag -a v0.4.0 -m "A.A.A-Y2K 0.4.0"
git push origin v0.4.0
```

仅最终发布作业具有 `contents: write` 权限。`release.py` 要求四个目标齐全，核对版本、提交、干净工作区、源码指纹、共享测试清单、安装验证与文件哈希；先上传草稿 Release，核验 GitHub 返回的资产数量、大小和 SHA-256 后再公开。任何失败都不发布部分平台包，不覆盖已公开版本，也不移动已存在的版本标签。

Release 除安装文件外还附带各平台 `*-manifest.json`、`*-verification.zip` 和总校验文件 `SHA256SUMS.txt`。验证归档包括 pytest XML、源码与冻结程序报告、安装报告、正常运行截图和 Windows 安装/卸载日志。

这些证据表示对应 runner 上的自动验证通过。Linux 启动验证使用 Xvfb；音频使用 dummy 设备，不等同于真实扬声器试听。Windows 轮廓裁切、macOS/Linux 退化呈现和更多系统版本的实机兼容性分别按证据说明，不能从一个平台的通过推导其他平台的结果。
