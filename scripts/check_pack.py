#!/usr/bin/env python3
"""Check pack structure and citation IDs, not factual accuracy or exam quality."""
import argparse
import json
import re
from pathlib import Path


def check(root):
    root = Path(root)
    issues = []
    manifest = root / '_sources/manifest.json'
    if not manifest.exists():
        return ['缺少 _sources/manifest.json']
    data = json.loads(manifest.read_text(encoding='utf-8'))
    ids = {u['id'] for f in data['files'] for u in f['units']}
    for name in ['00-开始阅读.md', '01-知识地图.md', '03-考前速查.md', '04-覆盖与待核对.md']:
        if not (root / name).exists():
            issues.append('缺少 ' + name)
    if not any((root / p).exists() for p in ['02-详细复习.md', '02-精简复习.md']):
        issues.append('缺少详细或精简讲义')
    papers = list((root / '练习卷').glob('*.md'))
    answers = list((root / '答案').glob('*.md'))
    if not papers or not answers:
        issues.append('缺少练习卷或独立答案')
    if {p.name.split('-')[0] for p in papers} != {p.name.split('-')[0] for p in answers}:
        issues.append('练习卷和答案前缀不一一对应')
    for path in root.rglob('*.md'):
        if '_sources' in path.relative_to(root).parts:
            continue
        text = path.read_text(encoding='utf-8')
        for ref in re.findall(r'\[(S\d+:[pb]\d+)\]', text):
            if ref not in ids:
                issues.append(f'{path.name}: 无效引用 {ref}')
        if path.name.startswith('02-') and not re.search(r'\[S\d+:[pb]\d+\]', text):
            issues.append(path.name + ': 讲义没有来源引用')
    return issues


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pack')
    args = p.parse_args()
    try:
        issues = check(args.pack)
    except Exception as exc:
        issues = [f'{type(exc).__name__}: {exc}']
    print(json.dumps({'pass': not issues, 'issues': issues, 'note': '仅结构与引用ID检查；未验证引用支持关系、覆盖率、答案或分值'}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if issues else 0)
