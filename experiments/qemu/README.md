# N-RAW header 控制实验

该实验用于研究原厂 N-RAW 与 4K 前端原型在 `0x15432004` 的配置顺序。它是默认关闭的 QEMU 控制模型假设，不是相机补丁；不产生像素、DMA 完成或 IRQ，不代表录像或真实硬件验证通过。

模型基线为 `WonderLantern/z8-qemu@d50b07dbaeebae45b2cff936e5bfcd85251ac1fd`、QEMU 11.1.1。先使用独立 checkout；准备器在写入前核对 commit 和所有目标文件，拒绝覆盖不匹配的现有改动。

```sh
python experiments/qemu/apply_model.py --qemu-repo /path/to/z8-qemu
python experiments/qemu/test_header_model.py --qemu-repo /path/to/z8-qemu
python /path/to/z8-qemu/tools/build.py \
  --qemu-source /path/to/qemu-11.1.1 --build-dir /path/to/header-build --jobs 4
```

控制模型只考虑已观测的完整四行内部端口配置、空闲 supplier 与 source；所有权、待确认事件、参数和地址均受检查。START 只锁存控制状态；普通完整 video-ready 条件通过、且当前配置仍与锁存内容一致后，才解除数据等待。停止取消等待，不清除已有完成事件。

追踪入口显式添加 `--experimental-deferred-video-header` 才启用 `og4k-header-model=on`，需要完整 Movie profile 和 selector10；4K 实验另需 selector15。原有硬件访问错误仍然使运行失败。

拒绝掩码与 `Z8_OG4K_HEADER` 日志记录的是 START 当时的状态，避免其他 CPU 随后确认事件使事后快照丢失原因：

| 位值 | 检查组 |
|---|---|
| 1 | 开关、模式、实例或控制值 |
| 2 | header 正在运行或保持 |
| 4 | 配置字或描述符完整性 |
| 8 | header/supplier 待确认事件 |
| 16 | 照片请求或编解码数据所有者 |
| 32 | supplier 初始配置 |
| 64 | source 已有配置 |
| 128 | 内部端口及高低地址配对 |

`result.json` 的 `og_model_diagnostics` 另外保存照片 NV16 状态和 header 状态。若宿主不能创建 Unix socket，可显式使用 `--transport-helper experiments/qemu/tcp_transport.py`；它只把主机连接改为 loopback TCP。

独立 C 合约检查覆盖默认关闭、13 种非法状态、控制锁存、等待、重复调用、描述符变化及取消；它提取实际生产函数执行。另跑上游 `test_video_header.py`、`test_capture_drain.py` 和 `test_movie_receiver.py`。本宿主不能运行 LSan 的进程跟踪，执行上游 ASan/UBSan 合约时使用 `ASAN_OPTIONS=detect_leaks=0`；地址和未定义行为检查保持启用。完整固件执行的结果须单独记录，合约通过不能代替录像验收。

该目录中的 QEMU 扩展和适配遵循 GPL-2.0-or-later；原模型版权归其作者所有。
