"""只读复算本次状态、研究版本与接口清单；不调用外部AI。"""
from pathlib import Path
import hashlib
import json
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server import logic
from server.main import app

OUT = Path(__file__).resolve().parent
BASELINE = Path('C:/Users/lenovo/Desktop/出海预测/archives/pre_current_demand_mainline_20260901/outputs/06_exploratory_attempts/keyword_llm_extraction_attempts/baseline/classified_all_478.csv')


def metrics(d):
    a, b = d.manual_demand.eq(1), d.program_demand.eq(1)
    tp, fp, fn, tn = (int(x.sum()) for x in [a & b, ~a & b, a & ~b, ~a & ~b])
    n = len(d)
    return {'n': n, 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'accuracy': (tp + tn) / n,
            'precision': tp / (tp + fp), 'recall': tp / (tp + fn), 'f1': 2 * tp / (2 * tp + fp + fn)}


def main():
    d = pd.read_csv(BASELINE)
    cl = logic._claims()
    g = logic.agg()
    result = {'meta': logic.meta(), 'active_chunks': logic._conn().execute('SELECT COUNT(*) FROM chunks').fetchone()[0],
              'excluded_chunks': logic._conn().execute('SELECT COUNT(*) FROM excluded_chunks').fetchone()[0],
              'claim_labels': cl.program_label.value_counts().to_dict(),
              'windows': g.window_type.value_counts().to_dict(),
              'segments': logic.segments(), 'country_dictionary_count': len(logic.rules()['countries']['countries']),
              'baseline_path': str(BASELINE), 'baseline_sha256': hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
              'baseline_candidate': metrics(d[d.keyword_hit.eq(1)]), 'baseline_all': metrics(d)}
    (OUT / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    g[g.window_type.isin(['layout_unknown', 'label_incomplete'])].to_csv(OUT / 'uncertain_firm_years.csv', index=False, encoding='utf-8-sig')
    routes = sorted((m, r.path) for r in app.routes if hasattr(r, 'methods') and r.path.startswith('/api/') for m in r.methods)
    lines = ['# 当前接口清单', '', '由 FastAPI 实际路由导出；非按旧文档手工计数。', '', '| 方法 | 路径 |', '|---|---|']
    lines += [f'| {m} | `{p}` |' for m, p in routes]
    lines += ['', '年份协议：详情/评分/推理链/简报/子图/供应链统一采用显式year；不指定则取该企业最新数据年度。指定年度不存在不回退。', '', '/api/radar 返回 total（企业-年总数）和 items（展示条目）；/api/segments 支持 year、province、industry。', '', '/api/meta 返回六维数量、国家/地区字典数量、全部主张/需求主张数量及有效/排除文本数量。', '', 'industry 使用现有七个细分名称；旧参数“光伏”兼容映射为光伏主链，“电气设备”指全部现有样本。']
    (ROOT / 'docs/当前接口清单.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
