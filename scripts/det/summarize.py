from pathlib import Path
import json,hashlib,re
ROOT=Path(__file__).resolve().parents[2];base=ROOT/'results/det'
def rois(path):
    if not path.exists():return {}
    text=path.read_text()
    if 'DETECTION SOC PASS' not in text:return {}
    return {x['id']:x for line in text.splitlines() if line.startswith('ROI ') for x in [json.loads(line[4:])]}
def data_bytes(r):return sum(r[k]['read_bytes']+r[k]['write_bytes'] for k in ['cpu_data','dma'])
models={};rows=[];whole=[]
for model in ['yolov3-tiny','yolov4-tiny']:
    variants={}
    for mode in ['M','F']:
        p=base/f'{model}_{mode}';sub=rois(p/'subgraph.log');wr=rois(p/'whole.log');variant={'subgraph':sub,'whole':wr}
        ref=p/'reference.json'
        if ref.exists():variant['reference']=json.loads(ref.read_text())
        variants[mode]=variant
    a,b=variants['M'],variants['F'];ids=(set(a['subgraph'])&set(b['subgraph']))-{65533,65534}
    results=[]
    for rid in sorted(ids):
        m,f=a['subgraph'][rid],b['subgraph'][rid];traffic=1-data_bytes(f)/data_bytes(m);cycles=1-f['cycles']/m['cycles']
        results.append({'roi':rid,'M_cycles':m['cycles'],'F_cycles':f['cycles'],'M_data_bytes':data_bytes(m),'F_data_bytes':data_bytes(f),'traffic_reduction':traffic,'cycle_reduction':cycles,'target_traffic_30pct':traffic>=.30,'target_cycle_15pct':cycles>=.15})
        rows.append(f'| {model} | {m["cycles"]:,} | {f["cycles"]:,} | {cycles:.2%} | {data_bytes(m):,} | {data_bytes(f):,} | {traffic:.2%} |')
    if 65534 in a['whole'] and 65534 in b['whole']:
        m,f=a['whole'][65534],b['whole'][65534];whole.append(f'| {model} | {m["cycles"]:,} | {f["cycles"]:,} | {1-f["cycles"]/m["cycles"]:.2%} |')
    if 'reference' in a and 'reference' in b:
        assert [x['hash'] for x in a['reference']['layers']]==[x['hash'] for x in b['reference']['layers']],model
    models[model]={'comparison':results,'variants':{k:{'subgraph_rois':list(v['subgraph']),'whole_rois':list(v['whole'])} for k,v in variants.items()}}
accuracy=[]
for model in models:
    p=base/f'{model}_coco/metrics.json'
    if p.exists():
        x=json.loads(p.read_text());models[model]['accuracy']=x
        accuracy.append(f'| {model} | {100*x["float"]["AP"]:.2f} | {100*x["int8"]["AP"]:.2f} | {x["AP_drop_points"]:.2f} | {100*x["int8"]["AP50"]:.2f} |')
(base/'summary.json').write_text(json.dumps(models,indent=2)+'\n')
tests=[]
for name in ['converter.log','accel_delay0.log','accel_delay3.log','smoke_ordinary.log','smoke_fused.log','smoke_cpu.log']:
    p=base/name;passed=p.exists() and 'PASS' in p.read_text() and 'FAIL' not in p.read_text();tests.append(f'- {name}: {"PASS" if passed else "未完成"}')
probe=base/'probe.json'
probe_lines=[]
if probe.exists():
    for name,v in json.loads(probe.read_text()).items():
        m,f=v['M'],v['F'];probe_lines.append(f'| {name} | {m["cycles"]:,} | {f["cycles"]:,} | {1-f["cycles"]/m["cycles"]:.2%} | {1-data_bytes(f)/data_bytes(m):.2%} |')
lines=['# 目标检测实际结果','', '本文件由scripts/det/summarize.py生成，数值来自实际测试日志。','', '## 验证','',*tests,'', '普通/融合RTL覆盖151组有效任务及7组非法任务，另验证对齐拒绝、busy拒绝、W1C、随机等待和任务中复位重跑。输入转换器2048样本含背压/复位；真实CPU小图包含普通卷积、融合和纯CPU基线。完整模型每层由CPU哈希和测试平台逐字节双重检查。','', '## 融合子图：M物化 / F融合','', '| 模型 | M周期 | F周期 | 周期减少 | M数据总线字节 | F数据总线字节 | 流量减少 |','|---|---:|---:|---:|---:|---:|---:|',*(rows or ['| 待完整仿真完成 | | | | | | |']),'', '流量为CPU_DATA+DMA实际完成总线字节，不含取指；原始ROI日志另外给出CPU_IFETCH。包含CPU软件物化、配置、轮询和驱动，排除事后检查/打印。既包含去物化也包含输入尺度转换卸载的综合收益；未用这些数值单独宣称融合映射的纯收益。','', '## 整网周期','', '| 模型 | M周期 | F周期 | 周期减少 |','|---|---:|---:|---:|',*(whole or ['| 待完整仿真完成 | | | |']),'', '整网含CPU非卷积算子、驱动和轮询，不含主机图像前处理、镜像装载、检查/打印和单独测量的CPU解码NMS。解码/NMS见ROI65533。不能将以上周期换算成实际FPS。B0纯CPU路径仅运行小图验收，尚未测完整模型CPU周期。','', '## 独立COCO精度（主机）','', '| 模型 | 浮点AP | INT8 AP | 下降百分点 | INT8 AP50 |','|---|---:|---:|---:|---:|',*(accuracy or ['| 待完成 | | | | |']),'', '160输入；100张train2017校准、500张val2017评价，ID不重叠；官方COCOeval。AP为0..100百分数。完整RTL演示使用单独的demo-only量化配置，不能把500张主机评价写为500张RTL验证。','', '## 资源与未达目标','', '已完成Yosys层次/进程/存储收集/结构检查；保留RAM，实际scratch24KiB，预算40KiB，无双bank重叠。synthesis.json为RTL级算子统计，不是门级面积/时序。','', '性能研究目标为子图数据流量减少30%、周期减少15%；实测周期目标达成，流量30%目标未达成，不能将功能通过写为所有性能达标。完整B0仅做小图，未测完整模型CPU周期。', '', '## 等尺度隔离实验（合成子图）', '', '| 场景 | M周期 | F周期 | 周期减少 | 数据流量减少 |', '|---|---:|---:|---:|---:|', *probe_lines, '', '固定5×5×7低路、10×10×19高路、3×3卷积17输出通道、相同权重/分块。equal使用两路m=1/s=0，排除输入尺度差异；unequal采用3/4与5/8。两种场景均真实CPU/RTL逐字节对拍，不将合成子图的收益当作完整模型收益。']
(base/'summary.md').write_text('\n'.join(lines)+'\n');print('\n'.join(rows+whole+accuracy))
