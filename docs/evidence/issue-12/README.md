# Issue #12 官方表接口与候选包保护证据

日期：2026-10-24。基线 `e5732b4024d90cc190aedb77f98f626b11e982cd`，独立分支 `feature/12-official-submission`。本轮没有修改冻结实验，也没有替换历史 DOCX、PPT、视频或候选 ZIP。

## 实际执行

Windows / Python 3.11 环境运行：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
<BASE_ENV>/Scripts/python.exe -X utf8 -m pytest -q --junitxml=artifacts/issue-12/pytest.xml
```

[真实测试日志](pytest.txt)：**318 passed in 72.34s**。其中原有 289 项测试文件保持不变，新增 29 项使用明确标记 TEST_ONLY 的合成表格及身份，覆盖一至三名成员、300 字边界、原件和输出保护、表格与段落布局、额外部件修改、身份/哈希不匹配、规则 PDF 排除、补充材料及 DRAFT 拒绝正式验收。合成 ZIP 不是比赛包。

真实主办方原件从 Git ignored 本地目录读取并校验 SHA256，生成独立 `DRAFT`，219 字描述只写稳定版客观能力。八行原表保留，队名和八项成员字段待填；没有虚构姓名或电话。原件哈希在写后再次一致。

```powershell
python tools/fill_official_submission.py --config local_data/submission/config-issue12-draft.json --draft
# DRAFT_IDENTITY_MISSING
python tools/fill_official_submission.py --config local_data/submission/config-issue12-draft.json --check
# exit 2, BLOCKED
python tools/build_submission.py --config local_data/submission/config-issue12-draft.json --check
# exit 2, BLOCKED: official_application / team_name
```

命令使用本分支源码，解释器跨工作区时显式设置 `PYTHONPATH=src`，避免误用另一个分支的 editable 安装。脱敏运行事实及拒绝输出见 [validation.json](validation.json)。原 DOCX、草稿、PDF、截图和身份配置均只在本地忽略目录。

`<BASE_ENV>` 是公开文档中的路径占位，指本机已安装 dev/vision 的基础虚拟环境；真实命令和完整本地输出保留在 ignored artifacts，未在公开日志保留用户目录。

## Word 页面检查

bundled LibreOffice 不可用。使用本机 Microsoft Word 以只读打开原件/草稿，`ExportAsFixedFormat` 输出 PDF，再用 bundled Poppler 转三页 PNG。已查看草稿全部三页并与原件对照：主表文字可读、身份明确待填；原件和草稿在表后原有说明部分出现局部段落/项目符号重叠，仍需负责人检查 Word 版式。Poppler 另提示 Symbol/ArialUnicode 字体警告。本轮保留原表结构及原有说明，没有为绕过问题重写官方格式；不声称视觉验收通过。

## 验收结论

代码、离线回归和真实拒绝路径可交 PM 审查。正式交付仍 **BLOCKED**：身份未齐、正式填表与人工版式核验未完成、P4 媒体须等待对应功能审核合并后同步、平台截止具体小时和其他提交限制未人工核验。没有生成新的实名 ZIP，没有上传，也没有修改旧 candidate。

不依赖 LLM、GPU 或神经网络运行即可完成本阶段填表和打包。所有模拟导航与真实照片结果沿用各自原始证据边界；本轮没有新的视觉实验或机器人实验。
