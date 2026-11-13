# 已上传自制固件的校验与 QEMU 冒烟测试

## 输入身份

用户于 2026-11-10 提供完整自制固件，文件名为 `Z_8_0311 (1)(1).bin`。

| 项目 | 值 |
|---|---|
| 完整文件长度 | 99,051,117 字节 |
| 完整文件 SHA-256 | `f9d5719cec76a814044f8f705dcb60cb6331da485cb4df680be5ff549c464d53` |
| 内部身份 | `03.11.p0` |
| EG 模块 | `eg2070_0311p0.bi` |
| EG SHA-256（包含末尾 CRC16） | `cc1657099bce3c85a76ea598232822b8d8f21a101a5760de0d12b60f497fa2f1` |
| QEMU MAIN SHA-256（不包含末尾 CRC16） | `ded602c7cee9df06a696a9785ca302991c49f3ff2e8c8f94a5c5edc666ad3de9` |

`verify.py` 已用 SHA-256 严格匹配的原厂 C3.11 做完整独立核验。结果为 PASS：四组功能 `framing`、`video-quality`、`log-colour`、`photo-tools` 全选配方的 453 个修改窗口全部匹配；窗口外的 EG 字节保持原厂内容，其他四个模块也保持原厂内容。公共版本、内部版本、模块名及 CRC/SHA1 均通过一致性检查。

该文件包含仓库现有的 8.3K Open Gate 功能，没有新增 4K Open Gate 实现。输出身份 `03.11.p0` 与工具包版本分别管理，不能仅靠上传文件名判断其功能。

## 已有 QEMU 环境的自制固件入口

`tools/qemu_custom_smoke.py` 先完整核验原厂和自制固件，再提取实际执行的 MAIN。它保留 z8-qemu 原入口的原厂校验：先用已校验原厂参考初始化，然后明确将 QEMU 的 kernel 和直接加载器都指向自制 MAIN。运行收据记录自制 MAIN 的实际哈希、完整包核验结果和适配器源码哈希，不把自制镜像标成原厂镜像。

不改写运行时客体 RAM、CPU 寄存器、固件指令、超时或硬件模型。对未匹配仓库审阅配方的固件，此入口在启动 QEMU 前拒绝。

```sh
python tools/qemu_custom_smoke.py \
  --original /path/to/original/Z_8_0311.bin \
  --candidate /path/to/custom/Z_8_0311.bin \
  --qemu-repo /path/to/z8-qemu \
  --qemu /path/to/qemu-system-aarch64 \
  --raw /path/to/liveview.raw \
  --output build/custom-smoke-001
```

如当前主机的已有 QEMU 配置使用 `tcp_launcher.py`，追加 `--transport-helper /path/to/tcp_launcher.py`。该参数只复用已准备的主机传输适配器。输出目录必须是新的；默认观察预算为 95 秒主机时间。

`custom-summary.json` 只有在所有断言成功、六个菜单输入完成、最终导航阶段为 7、传感器和显示帧实际产生、无 `Z8_UNKNOWN` 且 QEMU 子进程退出后才记为 PASS。

这项测试只覆盖启动、菜单、子菜单及返回合成取景。录像、4K Open Gate 和真实机身行为需要另外验证。

## 本次运行结果

2026-11-10，本文件所列自制固件已在 QEMU 11.1.1、Z8 模型提交 `d50b07dbaeebae45b2cff936e5bfcd85251ac1fd` 上通过以上测试。模型源码未修改，使用已有 TCP 主机控制适配器；输入是合成 Bayer 彩条。

| 检查 | 结果 |
|---|---|
| 运行时断言 | 1083 项通过，0 项失败 |
| 菜单操作 | 六个输入全部完成，最终阶段 7 |
| 返回取景 | 成功，最终屏幕 1024×682 |
| 传感器 / 显示帧 | 650 / 1271 |
| 最后采样的虚拟时间 | 55.068823865 秒 |
| 未建模 MMIO | 无 |
| QEMU 子进程退出 | 正常 |
| 运行时改写客体 RAM / CPU 重定向 | 无 |

本次 QEMU 二进制 SHA-256 为 `de55bb6b8778180e611be163a5605d45304122d537f754981fd220c2d62d2d50`。新增收据判定测试四项，与现有 25 项测试合计 29 项通过。
