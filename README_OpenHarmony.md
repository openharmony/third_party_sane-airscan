# sane-airscan

仓库包含第三方开源软件sane-airscan，[sane-airscan](https://github.com/alexpevzner/sane-airscan)是SANE（Scanner Access Now Easy）框架的AirScan/eSCL协议实现。它允许通过IP网络访问支持Apple AirScan或eSCL协议的扫描仪设备。在OpenHarmony系统中，引入sane-airscan作为SANE的eSCL协议驱动后端。

## 引入背景简述

在OpenHarmony系统中，扫描仪的适配都是通过厂商安装私有协议驱动到SANE的后端，各厂家的驱动不通用；为了适配更多的扫描厂商和机型，需要引入sane-airscan来支持免驱扫描。

## 目录结构

```
patch/                # 补丁目录
patch_install.py      # 补丁安装脚本 
BUILD.gn              # GN构建脚本
bundle.json           # 部件描述文件
README.OpenSource     # 开源声明文件
```

## OpenHarmony如何使用sane-airscan

sane-airscan无法单独使用，编译出来的驱动文件需要作为[SANE](https://gitee.com/openharmony/third_party_backends)的后端一起使用。详细使用方式参考[SANE公开文档](http://sane-project.org/docs.html)

## 移植说明

OpenHarmony版本通过以下补丁进行了移植适配：
- oh-transplant.patch：修改了多个源文件以适配OpenHarmony环境
- 主要修改涉及：
  - 日志系统适配(hilog)
  - 网络接口适配(avahi替换为libuv)

## 相关仓库

[backends](https://gitee.com/openharmony/third_party_backends)

[print_fwk](https://gitee.com/openharmony/print_print_fwk)

## License

sane-airscan使用GPLv2协议。

## 风险提示

**sane-airscan是GPLV2协议类型的三方开源软件，使用时需履行相应的开源义务。**

## 参与贡献

[如何贡献](https://gitee.com/openharmony/docs/blob/HEAD/zh-cn/contribute/参与贡献.md)

[Commit message规范](https://gitee.com/openharmony/device_qemu/wikis/Commit%20message%E8%A7%84%E8%8C%83)