# sane-airscan

本仓库包含第三方开源软件 [sane-airscan](https://github.com/alexpevzner/sane-airscan)，它是 [SANE（Scanner Access Now Easy）](http://www.sane-project.org/) 框架的 [eSCL协议](https://mopria.org/spec-download)实现。它允许通过 IP 网络访问支持 eSCL 协议的扫描仪设备。在 OpenHarmony 系统中，引入 sane-airscan 作为 SANE 的 eSCL 协议驱动后端。

## 引入背景简述

在 OpenHarmony 系统中，扫描仪的适配通常依赖厂商提供的私有协议驱动，各厂家的驱动不通用。为了适配更多扫描厂商和机型，引入 sane-airscan 来支持免驱扫描。免驱扫描是指无需安装特定厂商的驱动程序，即可通过标准协议（如 eSCL）发现并使用网络扫描仪，极大提升了设备的兼容性和用户体验。

sane-airscan 实现了对 Mopria eSCL 协议的支持。Mopria 联盟制定的 eSCL 协议已成为行业标准，被众多主流扫描仪厂商广泛采用。通过支持这一开放标准协议，OpenHarmony 系统能够自动发现和兼容大量符合 Mopria 标准的网络扫描设备，为用户提供即插即用的扫描体验，同时降低了厂商的设备适配成本。

## 目录结构

```
patch/                # 补丁目录
patch_install.py      # 补丁安装脚本 
BUILD.gn              # GN 构建脚本
bundle.json           # 部件描述文件
README.OpenSource     # 开源声明文件
```
### 补丁说明
OpenHarmony 版本通过以下补丁进行了移植适配：
- oh-transplant.patch：修改了多个源文件以适配 OpenHarmony 环境
- 主要修改涉及：
  - 日志系统适配（使用 hilog 替代原有日志系统）
  - 网络接口适配（使用 libuv 替代 avahi）

## 编译指导

sane-airscan 作为独立的驱动库进行编译，具体步骤如下：

1. 确保已安装 OpenHarmony 的编译环境及依赖项（如 libuv、hilog 等）。
2. 将本仓库置于 `third_party/sane-airscan` 目录下。
3. 在 `productdefine/common/rich.json` 中引入 sane-airscan，在 `"subsystem": "thirdparty"` 下添加：
   ```json
   {
       "component": "sane-airscan",
       "features": []
   }
   ```
4. 执行如下编译命令生成 sane-airscan 后端的 SANE 驱动：
   ```bash
   ./build.sh --product-name rk3568 --build-target third_party/sane-airscan:third_airscan
   ```
5. 编译产物libsane-airscan.z.so在如下地址：
    ```
    //out/rk3568/thirdparty/sane-airscan/
    ```

## OpenHarmony 如何使用 sane-airscan

sane-airscan 无法单独使用，编译出来的驱动文件需要作为 [SANE](https://gitee.com/openharmony/third_party_backends) 的后端集成到系统中。使用时，需通过 SANE 接口进行扫描仪设备的发现和操作。详细使用方式可参考 [SANE 公开文档](http://sane-project.org/docs.html) 及 [OpenHarmony 打印框架文档](https://gitee.com/openharmony/print_print_fwk)。

## 南向厂商适配指南

若厂商希望新增免驱扫描仪设备支持，可参考以下步骤进行适配：

1. **确认设备协议**：确保扫描仪支持 eSCL 协议。
2. **设备发现配置**：配置网络发现机制（如 mDNS/DNS-SD），确保设备可被正确识别。
3. **功能测试**：验证设备是否正常工作。

详细适配示例和代码请参考 [sane-airscan 官方文档](https://github.com/alexpevzner/sane-airscan)。

## 相关仓库

- [backends](https://gitee.com/openharmony/third_party_backends)
- [print_fwk](https://gitee.com/openharmony/print_print_fwk)

## License

sane-airscan 使用 GPLv2 协议。

## 风险提示

**sane-airscan 是 GPLv2 协议类型的三方开源软件，使用时需履行相应的开源义务。**

## 参与贡献

- [如何贡献](https://gitee.com/openharmony/docs/blob/HEAD/zh-cn/contribute/参与贡献.md)
- [Commit message 规范](https://gitee.com/openharmony/device_qemu/wikis/Commit%20message%E8%A7%84%E8%8C%83)