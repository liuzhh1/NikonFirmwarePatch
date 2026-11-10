# 4K Open Gate 前端实验原型

该目录包含实际 AArch64 前端原型和独立模拟器构建入口。**它还不是可录制的 4K 固件，也不生成可刷入相机的更新包。** 生产入口 `patch.py`、原有审阅配方和原有 8.3K 功能保持不变。

## 已实现的实验部分

- 从严格匹配审阅配方的 `03.11.p0` 全功能基线生成模拟器 MAIN。
- 主菜单加入 4128×2752 的 30/25/24p LAB 行；保留三个 8.3K Open Gate 行及全部 80 个原厂行。
- 使用既有数据存储事务写入 size=4、rate=4..6、Open Gate 标志，主菜单汇总复用原厂 4.1K 速率/品质资源。
- 配置钩子区分普通模式与实验模式；前端计划类型 11 使用全高半分辨率配置。
- 独立驱动入口覆盖原厂实际到达的 variant=2 和 variant=3，避免只改 D10 的 variant=3 钩子。
- 按字段修改实际几何，保留 1920×1080 代理及取景输出。
- 13 项 Unicorn 测试执行真实 AArch64 机器码，验证边界条件、寄存器、栈、NZCV、普通模式回退和既有 8.3K 路径；另有四项真实输入的构建集成检查。

| 数值 | 在原型中的含义 |
|---|---|
| 4128×2752 | 目标有效区域 |
| 4140×2756 | 全高半分辨率物理输入几何 |
| 4140×2760 | 逻辑传感器范围，不能直接当作编码高度 |
| 4140×2756 | 有界的编码尺寸候选，尚未通过 TICO/文件解码验证 |

新增代码位于 `0x40965000`，与既有 D10 代码及运行时状态区分开。原有代码地址和反挤压接入点保留。`frontend-profile.json` 固定原型源码和机器码 SHA-256；编译结果不匹配时构建拒绝继续。

## 编译与测试

使用支持 `aarch64-none-elf` 的 Clang；编译器适配应在调用端完成，不修改本项目的原厂校验或生产编译单元配方。

```sh
python -m pip install -r requirements-opengate4k-lab.txt

OG4K_COMPILER=/path/to/clang \
OG4K_ORIGINAL=/path/to/original/Z_8_0311.bin \
OG4K_BASELINE=/path/to/reviewed-03.11.p0.bin \
python -B -m unittest discover -s tests

python tools/build_opengate4k_lab.py \
  --original /path/to/original/Z_8_0311.bin \
  --baseline /path/to/reviewed-03.11.p0.bin \
  --compiler /path/to/clang \
  --output build/opengate4k/lab-001
```

输出 `opengate4k-lab-main.bi` 是 81,807,709 字节的模拟器 MAIN，不是 99,051,117 字节的尼康更新包。构建不会封装、签名或提供刷机操作。

## 尚未完成

- i 菜单新增行、取消回滚和菜单库切换的完整集成；不要在原型中用 i 菜单修改画幅。
- 编码尺寸候选、NRMT/NCTG 裁切及尺寸元数据、四档码率预算和剩余时间。
- 回放、缩略图、代理以及反挤压对新文件身份的处理。
- TICO 码流完整解码、真实传感器读出、Bayer 排列、视角和稳定性验证。

## 本轮运行结果

实际执行本原型 MAIN，使用原生按键选择 LAB 30p 并切换视频模式后，捕获到：

| 检查 | 观测结果 |
|---|---|
| 模式快照 | kind=1、nominal=4、actual=8、size=4、rate=4、request=4 |
| 实验驱动 | variant=2 路径返回 14；物理读出是否正确仍未确认 |
| 有效区域 | 4128×2752 |
| 物理输入几何 | 4140×2756 |
| 逻辑范围 | 4140×2760 |
| 代理字段 | 1920×1080，保持原值 |
| 视频 plan11 / 编码候选 | 隔离执行通过；本次最终视频快照之后未捕获运行时到达证据 |

完整运行**未通过**：在 `PC 0x40C07C24` 读取 `0x15080014` 时被未建模访问检查停止。原厂对照停在 `0x15432004` 的 START 写操作；两者不是同一个边界。不能以原厂也会停止为由排除驱动候选引入的问题，下一步需核对 driver14 的原生硬件契约。精简的无固件字节证据见 [原型运行记录](../docs/data/opengate4k-lab-runtime.json) 与 [原厂对照](../docs/data/opengate4k-stock-runtime.json)。

本轮共 46 项测试通过，已启用 AArch64 执行和真实输入集成检查。25p、24p 的条件分支在隔离执行中覆盖，QEMU 原生设置链路本轮只观察了 LAB 30p。

## 复跑设置追踪

使用 `WonderLantern/z8-qemu` 的 `d50b07dbaeebae45b2cff936e5bfcd85251ac1fd` 模型、其 QEMU 11.1.1 构建、合成 RAW 输入及专用虚拟卡。下列环境变量只指定显式实验 MAIN；完整原厂和基线身份仍由构建器核验，原有模拟器原厂校验入口保持不变。

```sh
OG4K_STOCK_MAIN=/path/to/stock-main.bi \
OG4K_LAB_MAIN="$PWD/build/opengate4k/lab-001/opengate4k-lab-main.bi" \
OG4K_LAB_SHA256=e293e2d97e55be35b6399014afb13eebbf6666d3d532cbef83960d98b586a959 \
python tools/trace_opengate4k.py \
  --qemu-repo /path/to/z8-qemu \
  --firmware /path/to/stock-main.bi \
  --qemu /path/to/qemu-system-aarch64 \
  --raw /path/to/synthetic-liveview.raw \
  --card /path/to/development-only-exfat.raw \
  --output build/opengate4k/trace-001 \
  --replay docs/data/opengate4k-lab-replay.json --seconds 500 \
  --experimental-shared221 --experimental-boundary-inputs \
  --experimental-sensor-source-clock --experimental-yuv-channels \
  --experimental-movie-selector16 --experimental-movie-selector10
```

按键回放含切换 N-RAW 后的原生提示确认。追踪使用硬件执行断点和只读观测，不注入客体寄存器或运行时 RAM；不会绕过未建模访问错误。生成 `observations.json`、菜单图和原运行器 `result.json`，后者包含完整运行失败原因。若环境不支持 Unix socket，可显式指定自行准备的 `--transport-helper`，它只应改变主机传输。

## 模拟器主菜单截图

![QEMU 中的三档 4K LAB 行及下方保留的原厂行](../docs/images/opengate4k-lab-menu.png)

这是本轮原型 MAIN 真实执行后渲染的菜单，不代表录像或实体机身验收。原有三个 8.3K Open Gate 行在同一列表中保留，图中可见其中的 24p；其余两行位于滚动区域上方。
