# N-RAW header 控制实验

该实验用于研究原厂 N-RAW 与 4K 前端原型在 `0x15432004` 的配置顺序。它是默认关闭的 QEMU 控制模型假设，不是相机补丁；不产生像素、DMA 完成或 IRQ，不代表录像或真实硬件验证通过。

模型基线为 `WonderLantern/z8-qemu@d50b07dbaeebae45b2cff936e5bfcd85251ac1fd`、QEMU 11.1.1。先使用独立 checkout；准备器在写入前核对 commit 和所有目标文件，拒绝覆盖不匹配的现有改动。

```sh
python experiments/qemu/apply_model.py --qemu-repo /path/to/z8-qemu
python experiments/qemu/test_header_model.py --qemu-repo /path/to/z8-qemu
python /path/to/z8-qemu/tools/build.py \
  --qemu-source /path/to/qemu-11.1.1 --build-dir /path/to/header-build --jobs 4
```

控制模型只考虑已观测的完整四行内部端口配置与空闲 source0；所有权、待确认事件、参数和地址均受检查。supplier 是否仍是初始配置以位值32记录为非阻塞信息，其内容由后续完整数据就绪检查判断。START 只锁存控制状态；普通完整 video-ready 条件通过、且当前配置仍与锁存内容一致后，才解除数据等待。停止取消等待，不清除已有完成事件。

追踪入口显式添加 `--experimental-deferred-video-header` 才启用 `og4k-header-model=on`，需要完整 Movie profile 和 selector10；4K 实验另需 selector15。原有硬件访问错误仍然使运行失败。

拒绝掩码与 `Z8_OG4K_HEADER` 日志记录的是 START 当时的状态，避免其他 CPU 随后确认事件使事后快照丢失原因：

| 位值 | 检查组 |
|---|---|
| 1 | 开关、模式、实例或控制值 |
| 2 | header 正在运行或保持 |
| 4 | 配置字或描述符完整性 |
| 8 | header/supplier 待确认事件 |
| 16 | 照片请求或编解码数据所有者 |
| 32 | supplier 初始配置（非阻塞；数据仍需完整 video-ready 校验） |
| 64 | source0 已有配置 |
| 128 | 内部端口及高低地址配对 |

`result.json` 的 `og_model_diagnostics` 另外保存照片 NV16 状态和 header 状态。若宿主不能创建 Unix socket，可显式使用 `--transport-helper experiments/qemu/tcp_transport.py`；它只把主机连接改为 loopback TCP。

独立 C 合约检查覆盖默认关闭、13种检查状态、supplier未就绪时的控制锁存与数据等待、重复调用、描述符变化及取消；它提取实际生产函数执行。另跑上游 `test_video_header.py`、`test_capture_drain.py` 和 `test_movie_receiver.py`。本宿主不能运行 LSan 的进程跟踪，执行上游 ASan/UBSan 合约时使用 `ASAN_OPTIONS=detect_leaks=0`；地址和未定义行为检查保持启用。完整固件执行的结果须单独记录，合约通过不能代替录像验收。

后续审查修复了等待分支跳过轮询重排的问题：`og4k_header_poll` 现在位于原有 `timer_mod` 之后，保留原来的33.3ms重试、已完成输出的2ms重试及无待交付帧时的边界等待。C合约执行实际 `raw_pipeline_tick` 的调度前缀，覆盖“先等待、下一次才就绪”的情况。旧版零视频帧记录存在此调度混杂因素，不能用于判断源链路能力。

2026-11-12 的原厂与 LAB 30p 都接受一次控制 START；原厂81.7虚拟秒和 LAB 较长72.5虚拟秒观察看到原生 STOP。另一次显式核对 N-RAW 格式的 LAB 运行在23.7虚拟秒仍等待，不能混淆不同观察时长。三次等待释放计数、视频帧及视频 source/ISP 确认计数均为0。START 日志显示 supplier 当时已经是1920×1080、pitch5888，不能从早先结束快照推断它尚未配置。原生后续配置了 source2/ISP1，而既有 `engine1543_video_ready` 只检查 source0；本实验没有放宽该数据检查或启动 source2。结构化记录见 [header 对照证据](../../docs/data/opengate4k-header-runtime.json)。

该目录中的 QEMU 扩展和适配遵循 GPL-2.0-or-later；原模型版权归其作者所有。

## 原始 EX 的触点观察

`tools/trace_opengate4k_native.py` 调用上游原生 EX 运行器，保留原厂 MAIN/EX 哈希校验，不接收实验 MAIN，不生成主机 MCU 消息。示例使用另行取得并核验的原厂 MAIN、EX、合成 RAW、独立虚拟卡与新输出目录：

```sh
python tools/trace_opengate4k_native.py \
  --qemu-repo /path/to/z8-qemu \
  --transport-helper experiments/qemu/tcp_transport.py \
  --firmware /path/to/stock-main.bi --mcu /path/to/stock-ex.bi \
  --qemu /path/to/qemu-header --raw /path/to/synthetic.raw \
  --card /path/to/native-card.raw --output build/opengate4k/native-001 \
  --contact-replay /path/to/contacts.json \
  --mcu-pins G1=1:G13=1:G14=1:G15=1 --seconds 1200 --virtual-seconds 160 \
  --experimental-shared221 --experimental-boundary-inputs \
  --experimental-sensor-source-clock --experimental-yuv-channels \
  --experimental-movie-selector16 --experimental-movie-selector10 \
  --experimental-movie-selector15 --experimental-deferred-video-header
```

触点文件使用上游的 `at/property/value` 格式，只能在末尾增加动作，不能修改已经列出的未来动作。以正常释放状态启动，先核对 Menu 与 `file_type=6`，再单独追加 expander `22.12` 的低/高电平 Record 脉冲。创建同名 `.done` 文件走原生停止和清理路径；仍按下的已知瞬时触点会释放，Photo/Movie选择器保留。释放触点不等于原始 EX 已确认处理，取消收据明确区分二者。

运行中 `native-observation.json` 保存暂停时的只读配置与帧计数，`native-live.json` 保存上游 EX 报告；最终 `result.json` 保存首个UART异常及模型状态。端口自动选择loopback临时端口，未开放交互控制。额外4项回放检查验证追加Record触点、拒绝修改既有动作、停止时释放/保留选择器及拒绝非法批次：

后续观察器另外读取secondary模型状态，保存最多2048次控制变化及触点消费数量，避免从相隔较远的快照推断因果。若QOM属性不可用，记录缺失而不是当作硬件零值。

```sh
python experiments/qemu/test_native_replay.py --qemu-repo /path/to/z8-qemu
```
