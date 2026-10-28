# 协作与复验

这是public仓库，任何人都可以通过HTTPS clone或fork。public不授予任意用户直接push权限。仓库所有者和受邀且接受邀请的collaborator可在认证后push；其他贡献者请fork、创建分支并提交PR。GitHub的写权限与本机Git凭据是两个条件，本机push需配置SSH密钥或GitHub支持的HTTPS认证。

```bash
git clone https://github.com/PimeGiano/ai-soc.git
cd ai-soc
git switch -c feature/your-change
# 按README安装依赖，修改并验证
bash scripts/run_all.sh quick
git add <changed-files>
git commit -m "Describe the behavior change"
git push -u origin feature/your-change  # 仅限拥有仓库写权限的协作者
```

fork流程应clone自己的fork，origin指向自己的仓库，然后向PimeGiano/ai-soc发起PR。不要使用force push覆盖共享main的历史。

修改寄存器/描述符时先更新spec/det/registers.json，再运行scripts/det/gen_spec.py；C/SV常量一起提交。涉及数值或数据流的修改应通过独立参考、RTL和真实CPU验证；完整模型行为改变时再运行full，量化/预处理变化时再运行accuracy。

不得提交build/、.venv/、本机工具链、权重、COCO图片、凭据或临时文件。results/det保留紧凑的原始测量、汇总和代表性检测图片；批量预测JSON和COCO可视化由脚本重建。

当前实现状态、测量边界和未达目标见docs/detection/implementation.md及results/det/summary.md；每位成员在docs/detection/schedule.md的模板中填写真实贡献。
