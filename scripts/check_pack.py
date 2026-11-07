#!/usr/bin/env python3
"""Check pack structure and citation IDs, not factual accuracy or exam quality."""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


def markdown_targets(text):
    """Read inline-link destinations, including balanced parentheses and titles.

    This is intentionally not a full Markdown renderer. Reference-style links
    are outside this structural check; factual validation remains separate.
    """
    # Ignore fenced/inline code examples, which are not navigable links.
    lines, fence = [], None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    text = '\n'.join(lines)
    text = re.sub(r'(`+).*?\1', '', text)
    for match in re.finditer(r'\]\(', text):
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos == len(text):
            continue
        target, escaped = [], False
        angle = text[pos] == '<'
        if angle:
            pos += 1
        depth = 1
        while pos < len(text):
            char = text[pos]
            pos += 1
            if escaped:
                target.append(char)
                escaped = False
            elif char == '\\':
                escaped = True
            elif angle and char == '>':
                break
            elif not angle and char == '(':
                depth += 1
                target.append(char)
            elif not angle and char == ')':
                depth -= 1
                if depth == 0:
                    break
                target.append(char)
            elif not angle and depth == 1 and char.isspace():
                break  # optional title is not part of destination
            else:
                target.append(char)
        if target:
            yield ''.join(target)


def check(root, mode=None, expected_papers=None):
    root = Path(root).resolve()
    issues = []
    state_path = root / '_session/state.json'
    if (mode is None or expected_papers is None) and state_path.exists():
        try:
            if state_path.is_symlink() or (root / '_session').is_symlink():
                raise ValueError('session path is a link')
            settings = json.loads(state_path.read_text(encoding='utf-8'))['settings']
            if settings.get('mode') not in ('detailed', 'concise', 'both') or type(settings.get('papers')) is not int or settings['papers'] < 1:
                raise ValueError('invalid mode/paper count')
            mode = mode if mode is not None else settings['mode']
            expected_papers = expected_papers if expected_papers is not None else settings['papers']
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            issues.append(f'无法读取已保存的模式/卷数: {exc}')
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
    names = {'detailed': '02-详细复习.md', 'concise': '02-精简复习.md'}
    required_modes = list(names) if mode == 'both' else ([mode] if mode in names else [])
    for item in required_modes:
        if not (root / names[item]).is_file():
            issues.append('缺少请求模式: ' + names[item])
    papers = list((root / '练习卷').glob('*.md'))
    answers = list((root / '答案').glob('*.md'))
    if expected_papers is not None and len(papers) != expected_papers:
        issues.append(f'练习卷数量应为{expected_papers}，实际{len(papers)}')
    if not papers or not answers:
        issues.append('缺少练习卷或独立答案')
    for group in (papers, answers):
        prefixes = [p.name.split('-')[0] for p in group]
        if len(set(prefixes)) != len(prefixes):
            issues.append('练习卷或答案有重复套卷前缀')
    if {p.name.split('-')[0] for p in papers} != {p.name.split('-')[0] for p in answers}:
        issues.append('练习卷和答案前缀不一一对应')
    for path in root.rglob('*.md'):
        if '_sources' in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            issues.append(f'{path.name}: 不检查符号链接文件')
            continue
        text = path.read_text(encoding='utf-8')
        local_links = []
        for target in markdown_targets(text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(root):
                issues.append(f'{path.name}: 本地链接越出复习包 {target}')
            elif not destination.is_file():
                issues.append(f'{path.name}: 本地链接目标不存在 {target}')
            else:
                local_links.append(destination)

        for ref in re.findall(r'\[(S\d+:[pb]\d+)\]', text):
            if ref not in ids:
                issues.append(f'{path.name}: 无效引用 {ref}')
        is_chapter = '章节' in path.relative_to(root).parts
        is_navigation = path.name.startswith('02-') and any('章节' in p.relative_to(root).parts for p in local_links)
        if (path.name.startswith('02-') or is_chapter) and not is_navigation and not re.search(r'\[S\d+:[pb]\d+\]', text):
            issues.append(path.name + ': 讲义没有来源引用')
    return issues


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pack')
    p.add_argument('--mode', choices=['detailed', 'concise', 'both'])
    p.add_argument('--papers', type=int)
    args = p.parse_args()
    if args.papers is not None and args.papers < 1:
        p.error('--papers must be positive')
    try:
        issues = check(args.pack, args.mode, args.papers)
    except Exception as exc:
        issues = [f'{type(exc).__name__}: {exc}']
    print(json.dumps({'pass': not issues, 'issues': issues, 'note': '仅结构与引用ID检查；未验证引用支持关系、覆盖率、答案或分值'}, ensure_ascii=True, indent=2))
    raise SystemExit(1 if issues else 0)
