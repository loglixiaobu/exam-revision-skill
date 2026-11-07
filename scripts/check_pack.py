#!/usr/bin/env python3
"""Check pack structure and citation IDs, not factual accuracy or exam quality."""
import argparse
from collections import Counter
import html
import json
import re
import string
from pathlib import Path
from urllib.parse import unquote, urlsplit


UNIT_ID = re.compile(r'(S[0-9]+):([pbsn])([0-9]+)\Z')
SOURCE_ID = re.compile(r'S[0-9]+\Z')
ESCAPE = re.compile(r'\\([' + re.escape(string.punctuation) + r'])')


def _escaped(text, pos):
    count = 0
    while pos > 0 and text[pos - 1] == '\\':
        count += 1
        pos -= 1
    return count % 2 == 1


def _blank(text):
    return ''.join('\n' if char == '\n' else ' ' for char in text)


def visible_markdown(text):
    """Mask fenced/inline code and HTML comments, preserving line boundaries."""
    lines, fence = [], None
    for line in text.splitlines(keepends=True):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line.rstrip('\r\n'))
        if fence is not None:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append(_blank(line))
        elif match and not (match[1][0] == '`' and '`' in match[2]):
            fence = match[1]
            lines.append(_blank(line))
        else:
            lines.append(line)
    text = ''.join(lines)
    # Parse code spans and comments from left to right. Neither delimiter has
    # meaning inside the other, so independent regex substitutions are unsafe.
    token_pattern = re.compile(r'<!--|`+')
    tick_pattern = re.compile(r'`+')
    paragraph_break = re.compile(r'\r?\n[ \t]*\r?\n')
    parts, cursor, pos = [], 0, 0
    while (opening := token_pattern.search(text, pos)) is not None:
        pos = opening.end()
        if _escaped(text, opening.start()):
            continue
        if opening[0] == '<!--':
            close = text.find('-->', pos)
            end = len(text) if close == -1 else close + 3
        else:
            # Code spans can cross a soft line break but not a blank paragraph.
            boundary = paragraph_break.search(text, pos)
            limit = boundary.start() if boundary else len(text)
            closing = next((run for run in tick_pattern.finditer(text, pos, limit)
                            if len(run[0]) == len(opening[0])), None)
            if closing is None:
                continue
            end = closing.end()
        parts.extend((text[cursor:opening.start()], _blank(text[opening.start():end])))
        cursor = pos = end
    parts.append(text[cursor:])
    return ''.join(parts)


def _markdown_unescape(text):
    return html.unescape(ESCAPE.sub(r'\1', text))


def _destination(text, pos):
    """Parse a Markdown destination without consuming its optional title."""
    start = pos
    if pos < len(text) and text[pos] == '<':
        pos += 1
        start = pos
        while pos < len(text):
            if text[pos] in '\r\n' or (text[pos] == '<' and not _escaped(text, pos)):
                return None
            if text[pos] == '>' and not _escaped(text, pos):
                return _markdown_unescape(text[start:pos]), pos + 1
            pos += 1
        return None
    depth = 0
    while pos < len(text):
        char = text[pos]
        if not _escaped(text, pos):
            if char.isspace():
                break
            if char == '(':
                depth += 1
            elif char == ')':
                if depth == 0:
                    break
                depth -= 1
            elif char == '<':
                return None
        pos += 1
    if depth:
        return None
    return _markdown_unescape(text[start:pos]), pos


def _skip_space(text, pos):
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _title_end(text, pos):
    if pos >= len(text) or text[pos] not in '\"\'(':
        return None
    delimiter = ')' if text[pos] == '(' else text[pos]
    pos += 1
    while pos < len(text):
        if text[pos] == delimiter and not _escaped(text, pos):
            return pos + 1
        pos += 1
    return None


def _label_key(text):
    return ' '.join(_markdown_unescape(text).split()).casefold()


def markdown_targets(text):
    """Read inline/image and reference-style destinations without fetching URLs.

    This is a structural subset, not a Markdown renderer: raw HTML links,
    indented code blocks, and heading-anchor existence are not validated.
    Reference definitions use one line (with an optional title).
    """
    text = visible_markdown(text)
    references = {}
    lines = []
    for line in text.splitlines(keepends=True):
        match = re.match(r'^ {0,3}\[([^\]\n]+)\]:[ \t]*(.*)$', line.rstrip('\r\n'))
        parsed = _destination(match[2], 0) if match else None
        if parsed and parsed[0]:
            target, end = parsed
            tail = match[2][end:].strip()
            title_end = _title_end(tail, 0) if tail else 0
            if title_end is not None and not tail[title_end:].strip():
                references.setdefault(_label_key(match[1]), target)
                lines.append(_blank(line))
                continue
        lines.append(line)
    text = ''.join(lines)
    pending = [(text, False)]
    while pending:
        text, images_only = pending.pop()
        pos = 0
        while pos < len(text):
            start = text.find('[', pos)
            if start == -1:
                break
            pos = start + 1
            if _escaped(text, start):
                continue
            if images_only and (start == 0 or text[start - 1] != '!' or _escaped(text, start - 1)):
                continue
            depth, end = 1, pos
            while end < len(text) and depth:
                if not _escaped(text, end):
                    if text[end] == '[':
                        depth += 1
                    elif text[end] == ']':
                        depth -= 1
                end += 1
            if depth:
                continue
            label = text[pos:end - 1]
            if '![' in label:
                # Images inside a link remain independent resources. Share the
                # document's reference definitions without accepting nested links.
                pending.append((label, True))
            pos = end
            if end < len(text) and text[end] == '(':
                parsed = _destination(text, _skip_space(text, end + 1))
                if parsed is None:
                    continue
                target, tail = parsed
                next_pos = _skip_space(text, tail)
                if next_pos < len(text) and text[next_pos] != ')':
                    # A title must be separated from the destination by whitespace.
                    if next_pos == tail:
                        continue
                    next_pos = _title_end(text, next_pos)
                    if next_pos is None:
                        continue
                    next_pos = _skip_space(text, next_pos)
                if next_pos < len(text) and text[next_pos] == ')':
                    pos = next_pos + 1
                    if target:
                        yield target
            else:
                if end < len(text) and text[end] == '[':
                    close = text.find(']', end + 1)
                    if close == -1:
                        continue
                    label = text[end + 1:close] or label
                    pos = close + 1
                if not label.startswith('^') and _label_key(label) in references:
                    yield references[_label_key(label)]


def manifest_ids(manifest):
    """Validate the citation index, allowing older minimal manifests."""
    data = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('files'), list):
        raise ValueError('files 必须是数组')
    if 'schema_version' in data and (type(data['schema_version']) is not int or data['schema_version'] != 1):
        raise ValueError('不支持的 schema_version')
    ids, sources = set(), set()
    for index, entry in enumerate(data['files'], 1):
        if not isinstance(entry, dict) or not isinstance(entry.get('units'), list):
            raise ValueError(f'第{index}个来源的 units 必须是数组')
        sid = entry.get('id')
        if 'id' in entry:
            if not isinstance(sid, str) or not SOURCE_ID.fullmatch(sid) or int(sid[1:]) < 1:
                raise ValueError(f'第{index}个来源 ID 格式无效')
            if sid in sources:
                raise ValueError(f'重复来源 ID {sid}')
            sources.add(sid)
        if 'status' in entry and entry['status'] not in ('extracted', 'extracted_with_warnings', 'failed', 'unsupported'):
            raise ValueError(f'第{index}个来源状态无效')
        if entry.get('status') in ('failed', 'unsupported') and entry['units']:
            raise ValueError(f'第{index}个未提取来源不应包含引用单元')
        for unit in entry['units']:
            uid = unit.get('id') if isinstance(unit, dict) else None
            parsed = UNIT_ID.fullmatch(uid) if isinstance(uid, str) else None
            if not parsed or int(parsed[1][1:]) < 1 or int(parsed[3]) < 1:
                raise ValueError(f'第{index}个来源的引用 ID 格式无效')
            if sid is not None and parsed[1] != sid:
                raise ValueError(f'引用 ID {uid} 与来源 {sid} 不一致')
            if uid in ids:
                raise ValueError(f'重复引用 ID {uid}')
            ids.add(uid)
    if not ids:
        raise ValueError('没有可引用的来源单元')
    return ids


def question_ids(text):
    """Recognize explicit heading labels; do not infer IDs from arbitrary prose.

    A1/Q1, numeric headings, and 第1题/题目1/Question 1 are supported. Pair
    comparisons only run for numbering families recognized in both documents.
    """
    found = {'alphanumeric': [], 'numeric': []}
    numeric_levels = set()
    for level, heading in re.findall(r'^ {0,3}(#{1,6})[ \t]+(.+)$', visible_markdown(text), re.M):
        heading = heading.strip().strip('*_')
        match = re.match(r'(?:第\s*([0-9]+)\s*题|(?:题目?|Question)\s*([0-9]+))(?=$|[\s（(.:：、)）*_-])', heading, re.I)
        if match:
            found['numeric'].append(str(int(match[1] or match[2])))
            numeric_levels.add(len(level))
            continue
        match = re.match(r'([A-Za-z]*[0-9]+(?:[.-][0-9]+)*)(?=$|[\s（(.:：、)）*_-])', heading)
        if match:
            # Parenthesized letter/roman subparts or descriptive subtitles are
            # ambiguous; do not collapse A1(a) and A1(b) into duplicate A1.
            if re.match(r'[（(][A-Za-z]', heading[match.end(1):].lstrip('*_ \t')):
                continue
            value = match[1]
            kind = 'numeric' if value[0].isdigit() else 'alphanumeric'
            found[kind].append(value.upper())
            if kind == 'numeric':
                numeric_levels.add(len(level))
    # Nested numeric headings can be section numbers or subquestions. Do not
    # assume they are globally unique question IDs without an explicit schema.
    if len(numeric_levels) > 1:
        found['numeric'] = []
    return found


def _prefix(path):
    return path.stem.split('-', 1)[0]


def check(root, mode=None, expected_papers=None):
    root = Path(root).resolve()
    issues = []
    if not root.is_dir():
        return ['复习包目录不存在']
    if mode is not None and mode not in ('detailed', 'concise', 'both'):
        issues.append('请求的模式无效')
        mode = None
    if expected_papers is not None and (type(expected_papers) is not int or expected_papers < 1):
        issues.append('请求的练习卷数量必须是正整数')
        expected_papers = None
    state_path = root / '_session/state.json'
    if (mode is None or expected_papers is None) and (state_path.exists() or state_path.is_symlink()):
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
    if manifest.is_symlink() or (root / '_sources').is_symlink():
        return issues + ['来源清单不接受符号链接']
    if not manifest.is_file():
        return issues + ['缺少 _sources/manifest.json']
    try:
        ids = manifest_ids(manifest)
    except (OSError, ValueError, TypeError) as exc:
        return issues + [f'无效来源清单: {exc}']
    for name in ['00-开始阅读.md', '01-知识地图.md', '03-考前速查.md', '04-覆盖与待核对.md']:
        if not (root / name).is_file():
            issues.append('缺少 ' + name)
    if not any((root / p).is_file() for p in ['02-详细复习.md', '02-精简复习.md']):
        issues.append('缺少详细或精简讲义')
    names = {'detailed': '02-详细复习.md', 'concise': '02-精简复习.md'}
    required_modes = list(names) if mode == 'both' else ([mode] if mode in names else [])
    for item in required_modes:
        if not (root / names[item]).is_file():
            issues.append('缺少请求模式: ' + names[item])
    groups = []
    for name in ('练习卷', '答案'):
        directory = root / name
        if directory.is_symlink():
            issues.append(f'{name}: 不检查符号链接目录')
            groups.append([])
        else:
            groups.append(sorted(p for p in directory.glob('*.md') if p.is_file() and not p.is_symlink()))
    papers, answers = groups
    if expected_papers is not None and len(papers) != expected_papers:
        issues.append(f'练习卷数量应为{expected_papers}，实际{len(papers)}')
    if not papers or not answers:
        issues.append('缺少练习卷或独立答案')
    for group in (papers, answers):
        prefixes = [_prefix(p) for p in group]
        if len(set(prefixes)) != len(prefixes):
            issues.append('练习卷或答案有重复套卷前缀')
        if '' in prefixes:
            issues.append('练习卷或答案的套卷前缀不能为空')
    if {_prefix(p) for p in papers} != {_prefix(p) for p in answers}:
        issues.append('练习卷和答案前缀不一一对应')
    documents = {}
    for path in sorted(root.rglob('*.md')):
        if '_sources' in path.relative_to(root).parts:
            continue
        if path.is_symlink() or any((root / p).is_symlink() for p in path.relative_to(root).parents if p != Path('.')):
            issues.append(f'{path.name}: 不检查符号链接文件')
            continue
        if not path.is_file():
            issues.append(f'{path.name}: 不是普通 Markdown 文件')
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            issues.append(f'{path.name}: 无法读取 Markdown: {exc}')
            continue
        documents[path] = text
        if not text.strip():
            issues.append(f'{path.name}: Markdown 没有正文')
        local_links = []
        for target in markdown_targets(text):
            try:
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
            except (OSError, ValueError, RuntimeError):
                issues.append(f'{path.name}: 无效链接 {target}')
        visible = visible_markdown(text)
        citations = [m[1] for m in re.finditer(r'\[(S[0-9]+:[^\]\r\n]*)\]', visible) if not _escaped(visible, m.start())]
        for ref in citations:
            if ref not in ids:
                issues.append(f'{path.name}: 无效引用 {ref}')
        is_chapter = '章节' in path.relative_to(root).parts
        is_navigation = path.name.startswith('02-') and any('章节' in p.relative_to(root).parts for p in local_links)
        if (path.name.startswith('02-') or is_chapter) and not is_navigation and not any(ref in ids for ref in citations):
            issues.append(path.name + ': 讲义没有来源引用')
    for path in papers + answers:
        for labels in question_ids(documents.get(path, '')).values():
            duplicates = sorted(label for label, count in Counter(labels).items() if count > 1)
            if duplicates:
                issues.append(f'{path.parent.name}/{path.name}: 重复题号 {", ".join(duplicates)}')
    answer_by_prefix = {_prefix(p): p for p in answers}
    for paper in papers:
        answer = answer_by_prefix.get(_prefix(paper))
        if not answer or paper not in documents or answer not in documents:
            continue
        questions, solutions = question_ids(documents[paper]), question_ids(documents[answer])
        for family in questions:
            if questions[family] and solutions[family] and set(questions[family]) != set(solutions[family]):
                missing = sorted(set(questions[family]) - set(solutions[family]))
                extra = sorted(set(solutions[family]) - set(questions[family]))
                issues.append(f'{paper.name} / {answer.name}: 题答编号不一一对应；缺少答案 {missing}；多余答案 {extra}')
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
    print(json.dumps({'pass': not issues, 'issues': issues, 'note': '仅结构、引用ID与可识别题号检查；未验证引用支持关系、覆盖率、答案或分值；未识别的题号格式需人工核对'}, ensure_ascii=True, indent=2))
    raise SystemExit(1 if issues else 0)
