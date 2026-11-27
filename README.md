# SRM 扣款与客诉导出

Windows 桌面工具，可按日期导出扣款明细和客诉账单。程序通过已授权的账号读取配置站点的数据，并在本机生成 Excel。

## 软件界面

![扣款与客诉导出软件界面](docs/screenshot.png)

本机版界面示例。GitHub 版在顶部提供「站点设置」。

## 使用

1. 从 Releases 下载 `SRMReportExporter.exe`，移到长期使用的目录，然后双击打开。登录使用已安装的 Microsoft Edge。
2. 打开 **站点设置**，填入管理员提供的 SRM HTTPS 地址。客诉地址用于补充详情。客诉模板编号可留空，程序会识别名称以「消费者索赔」开头的模板。
3. 打开 **登录设置**。手动导出可在 Edge 完成登录。需要定时运行时，可用当前 Windows 用户加密保存 SRM 凭据。
4. 选择报表和保存目录。手动运行时选择开始和结束日期，自动运行时选择每天或每周的运行时间。

每天导出昨天的数据。每周导出运行日前连续 7 天的数据。定时运行使用 Windows 任务计划，电脑需开机联网且当前 Windows 用户保持登录。

扣款明细包含客诉扣款。客诉账单单独列出这部分数据。程序使用要求扣款日期，缺失时使用创建日期。源系统未提供的客诉字段留空，具体字段见账单中的「抓取说明」。

站点设置和加密的登录信息保存在本机 `%LOCALAPPDATA%\SrmReportExporterPortable`。按公司要求保管导出的 Excel。

## 构建

使用 Windows x64、Python 3.13 和 Microsoft Edge。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\build.ps1 -Python .\.venv\Scripts\python.exe
```

构建产物位于 `dist\SRMReportExporter.exe`。
