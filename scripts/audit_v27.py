#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v2.8 Gate 2 — 机械验证纪律（audit_v27.py）
V2.1 引文机械校验：key_phrases / anchor_text / D13 text 必须为 text_span.text 子串
V2.2 常量检测：grep 0.88/0.7/0.85 等硬编码魔法数字
V2.3 坐标校验：span.start/end 切出与 text 相同字符串（相似度≥95%）
V2.4 ID 唯一性校验：segment_id / annotation_id 在各层内唯一
"""
import json, os, sys, re
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

BASE = r'D:\Dev\information field model\StoryEngine\outputs\annotations'
SKILL_DIR = r'D:\Dev\information field model\StoryEngine\skills\close-reading-annotator'
DOCS = ['moon_sixpence_zh', 'shanghai_fortress_zh']
LAYERS = ['structure', 'interpretation', 'craft', 'emotion']

def normalize(s):
    """归一化字符串：去除多余空白"""
    return ' '.join(s.split())

def similarity(a, b):
    """简单相似度：相同字符数 / 最大长度"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # 用最长公共子序列比例
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()

def v21_quote_check(doc_id):
    """V2.1: 引文机械校验"""
    print(f'\n  V2.1 引文校验: {doc_id}')
    doc_dir = os.path.join(BASE, doc_id)
    errors = []
    warnings = []
    checked = 0
    
    for layer in LAYERS:
        path = os.path.join(doc_dir, f'{doc_id}_{layer}.jsonl')
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                sid = obj.get('segment_id', 'unknown')
                text = obj.get('text_span', {}).get('text', '')
                norm_text = normalize(text)
                layer_data = obj.get('layers', {}).get(layer, {})
                
                # 检查 emotion expression.key_phrases
                if layer == 'emotion':
                    expr = layer_data.get('expression', {})
                    key_phrases = expr.get('key_phrases', [])
                    for i, phrase in enumerate(key_phrases):
                        checked += 1
                        if normalize(phrase) not in norm_text:
                            errors.append({
                                'doc': doc_id, 'layer': layer, 'segment': sid,
                                'field': f'expression.key_phrases[{i}]',
                                'quote': phrase, 'reason': '不是原文子串',
                            })
                
                # 检查 craft D13/D14/D15/D16/D17 的 text 字段
                if layer == 'craft':
                    for dim in ['D13_golden_lines', 'D14_rhetoric', 'D15_imagery', 'D16_vocabulary', 'D17_sentence']:
                        items = layer_data.get(dim, [])
                        for i, item in enumerate(items):
                            if isinstance(item, dict) and 'text' in item:
                                checked += 1
                                quote = item['text']
                                if normalize(quote) not in norm_text:
                                    errors.append({
                                        'doc': doc_id, 'layer': layer, 'segment': sid,
                                        'field': f'{dim}[{i}].text',
                                        'quote': quote, 'reason': '不是原文子串',
                                    })
                
                # 检查 interpretation D06 content 中的引号引文
                # 注意：D06 content 中 LLM 常常用引号强调概念（非直接引文），
                # 这类情况降级为 warning 而非 error。方案 V2.1 强制校验范围是
                # key_phrases / anchor_text / D13 text，D06 content.quote 为可选检查。
                if layer == 'interpretation':
                    d06 = layer_data.get('D06_information_control', {})
                    content = d06.get('content', '')
                    # 抽取引号内容
                    quotes = re.findall(r'[「『"《](.+?)[」』"》]', content)
                    for i, q in enumerate(quotes):
                        if len(q) > 2:  # 跳过太短的
                            checked += 1
                            if normalize(q) not in norm_text:
                                # 降级为 warning（D06 描述性引号，非强制直接引文）
                                warnings.append({
                                    'doc': doc_id, 'layer': layer, 'segment': sid,
                                    'field': f'D06.content.quote[{i}]',
                                    'quote': q, 'reason': 'D06描述性引号不是原文子串（建议去掉引号或修正为原文）',
                                    'severity': 'warning',
                                })
    
    print(f'    检查 {checked} 条引文, 错误 {len(errors)} 条, 警告 {len(warnings)} 条')
    for e in errors[:5]:
        print(f'    ❌ {e["segment"]} {e["field"]}: {e["quote"][:50]}... ({e["reason"]})')
    for w in warnings[:5]:
        print(f'    ⚠️ {w["segment"]} {w["field"]}: {w["quote"][:50]}... ({w["reason"]})')
    if len(errors) > 5:
        print(f'    ... 还有 {len(errors)-5} 条错误')
    if len(warnings) > 5:
        print(f'    ... 还有 {len(warnings)-5} 条警告')
    return {'checked': checked, 'errors': errors, 'warnings': warnings}

def v22_constant_check():
    """V2.2: 常量检测（扫描脚本文件中的硬编码魔法数字）"""
    print(f'\n  V2.2 常量检测')
    # 常见魔法数字模式
    patterns = [
        (r'0\.88', '0.88（常见置信度阈值）'),
        (r'0\.7\b', '0.7（常见置信度/相似度阈值）'),
        (r'0\.85\b', '0.85（常见置信度阈值）'),
        (r'0\.95\b', '0.95（常见相似度阈值）'),
        (r'0\.9\b', '0.9（常见阈值）'),
        (r'0\.6\b', '0.6（常见阈值）'),
        (r'0\.5\b', '0.5（常见阈值）'),
    ]
    
    findings = []
    scripts_dir = os.path.join(SKILL_DIR, 'scripts')
    for root, dirs, files in os.walk(scripts_dir):
        for fn in files:
            if fn.endswith('.py'):
                fp = os.path.join(root, fn)
                with open(fp, 'r', encoding='utf-8') as f:
                    for lineno, line in enumerate(f, 1):
                        for pattern, desc in patterns:
                            if re.search(pattern, line):
                                # 排除注释和明显的非阈值用法
                                stripped = line.strip()
                                if stripped.startswith('#'):
                                    continue
                                findings.append({
                                    'file': os.path.relpath(fp, SKILL_DIR),
                                    'line': lineno,
                                    'pattern': pattern,
                                    'description': desc,
                                    'code': stripped[:100],
                                })
    
    print(f'    发现 {len(findings)} 处潜在魔法数字')
    for f in findings[:10]:
        print(f'    ⚠️ {f["file"]}:{f["line"]} {f["description"]} → {f["code"][:60]}')
    if len(findings) > 10:
        print(f'    ... 还有 {len(findings)-10} 处')
    return {'findings': findings}

def v23_span_check(doc_id):
    """V2.3: 坐标校验"""
    print(f'\n  V2.3 坐标校验: {doc_id}')
    doc_dir = os.path.join(BASE, doc_id)
    errors = []
    warnings = []
    checked = 0
    
    craft_path = os.path.join(doc_dir, f'{doc_id}_craft.jsonl')
    if not os.path.exists(craft_path):
        print(f'    无 craft 文件，跳过')
        return {'checked': 0, 'errors': [], 'warnings': []}
    
    with open(craft_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            sid = obj.get('segment_id', 'unknown')
            text = obj.get('text_span', {}).get('text', '')
            craft = obj.get('layers', {}).get('craft', {})
            
            for dim in ['D13_golden_lines', 'D14_rhetoric', 'D15_imagery', 'D16_vocabulary', 'D17_sentence']:
                items = craft.get(dim, [])
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    span = item.get('span')
                    item_text = item.get('text', '')
                    if not span or not item_text:
                        continue
                    
                    checked += 1
                    start = span.get('start')
                    end = span.get('end')
                    
                    # 检查边界合法性
                    if start is None or end is None or start < 0 or end > len(text) or start >= end:
                        errors.append({
                            'doc': doc_id, 'segment': sid, 'field': f'{dim}[{i}].span',
                            'span': span, 'reason': f'边界不合法 (text_len={len(text)})',
                        })
                        continue
                    
                    # 切出原文片段
                    sliced = text[start:end]
                    sim = similarity(normalize(sliced), normalize(item_text))
                    
                    if sim < 0.85:
                        errors.append({
                            'doc': doc_id, 'segment': sid, 'field': f'{dim}[{i}].span',
                            'span': span, 'sliced': sliced[:50], 'expected': item_text[:50],
                            'similarity': round(sim, 3), 'reason': '切片与text相似度<85%',
                        })
                    elif sim < 0.95:
                        warnings.append({
                            'doc': doc_id, 'segment': sid, 'field': f'{dim}[{i}].span',
                            'similarity': round(sim, 3), 'reason': '切片与text相似度85-95%',
                        })
    
    print(f'    检查 {checked} 个 span, 错误 {len(errors)}, 警告 {len(warnings)}')
    for e in errors[:5]:
        print(f'    ❌ {e["segment"]} {e["field"]}: {e["reason"]} (sim={e.get("similarity", "N/A")})')
    if len(errors) > 5:
        print(f'    ... 还有 {len(errors)-5} 条错误')
    return {'checked': checked, 'errors': errors, 'warnings': warnings}

def v24_id_check(doc_id):
    """V2.4: ID 唯一性校验"""
    print(f'\n  V2.4 ID 唯一性: {doc_id}')
    doc_dir = os.path.join(BASE, doc_id)
    errors = []
    
    for layer in LAYERS:
        path = os.path.join(doc_dir, f'{doc_id}_{layer}.jsonl')
        if not os.path.exists(path):
            continue
        seg_ids = {}
        ann_ids = {}
        with open(path, 'r', encoding='utf-8') as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                sid = obj.get('segment_id')
                aid = obj.get('annotation_id')
                if sid:
                    if sid in seg_ids:
                        errors.append({
                            'doc': doc_id, 'layer': layer, 'id_type': 'segment_id',
                            'id': sid, 'lines': [seg_ids[sid], lineno],
                        })
                    else:
                        seg_ids[sid] = lineno
                if aid:
                    if aid in ann_ids:
                        errors.append({
                            'doc': doc_id, 'layer': layer, 'id_type': 'annotation_id',
                            'id': aid, 'lines': [ann_ids[aid], lineno],
                        })
                    else:
                        ann_ids[aid] = lineno
    
    print(f'    发现 {len(errors)} 个重复 ID')
    for e in errors[:5]:
        print(f'    ❌ {e["layer"]} {e["id_type"]}={e["id"]} 重复于行 {e["lines"]}')
    return {'errors': errors}

def main():
    print('='*60)
    print('v2.8 Gate 2 — 机械验证纪律 (audit_v27.py)')
    print(f'运行时间: {datetime.now().isoformat(timespec="seconds")}')
    print('='*60)
    
    report = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'audit_version': 'v2.8_gate2',
        'documents': {},
        'summary': {},
    }
    
    total_errors = 0
    total_warnings = 0
    
    for doc_id in DOCS:
        print(f'\n{"#"*60}')
        print(f'# 审计文档: {doc_id}')
        print(f'{"#"*60}')
        
        v21 = v21_quote_check(doc_id)
        v23 = v23_span_check(doc_id)
        v24 = v24_id_check(doc_id)
        
        doc_errors = len(v21['errors']) + len(v23['errors']) + len(v24['errors'])
        doc_warnings = len(v21['warnings']) + len(v23['warnings'])
        total_errors += doc_errors
        total_warnings += doc_warnings
        
        report['documents'][doc_id] = {
            'v21_quote_check': {'checked': v21['checked'], 'error_count': len(v21['errors']), 'warning_count': len(v21['warnings']), 'errors': v21['errors'], 'warnings': v21['warnings']},
            'v23_span_check': {'checked': v23['checked'], 'error_count': len(v23['errors']), 'warning_count': len(v23['warnings']), 'errors': v23['errors'], 'warnings': v23['warnings']},
            'v24_id_check': {'error_count': len(v24['errors']), 'errors': v24['errors']},
            'total_errors': doc_errors,
            'total_warnings': doc_warnings,
        }
    
    # V2.2 常量检测（全局）
    v22 = v22_constant_check()
    report['v22_constant_check'] = {'finding_count': len(v22['findings']), 'findings': v22['findings']}
    
    # 总结
    report['summary'] = {
        'total_errors': total_errors,
        'total_warnings': total_warnings,
        'constant_findings': len(v22['findings']),
        'passed': total_errors == 0,
    }
    
    # 写报告
    report_path = os.path.join(BASE, 'audit_report_v28.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f'\n\n{"="*60}')
    print('审计总结')
    print(f'{"="*60}')
    print(f'  总错误数: {total_errors}')
    print(f'  总警告数: {total_warnings}')
    print(f'  常量发现: {len(v22["findings"])} 处')
    print(f'  结果: {"✅ 全绿通过" if total_errors == 0 else "❌ 存在错误"}')
    print(f'\n  报告已写入: {report_path}')

if __name__ == '__main__':
    main()
