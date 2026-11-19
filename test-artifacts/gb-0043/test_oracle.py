"""独立 oracle：暴力枚举所有可行链接子集，校验分配器三层字典序最优。"""
import itertools
import os
import random
import sys
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))

from src.services.link_allocator import allocate, parse_sessions


def brute_force(records, quotas, required_links, default_cap=1):
    edges, chapters = parse_sessions(records)
    def cap_out(c):
        return int(quotas.get(c, {}).get('out', default_cap))
    def cap_in(c):
        return int(quotas.get(c, {}).get('in', default_cap))
    req = set(tuple(x) for x in required_links)
    # 必留可行性
    feasible = True
    for a, b in req:
        if (a, b) not in edges or cap_out(a) <= 0 or cap_in(b) <= 0:
            feasible = False
    ro = {c: sum(1 for a, b in req if a == c) for c in chapters}
    ri = {c: sum(1 for a, b in req if b == c) for c in chapters}
    for c in chapters:
        if ro[c] > cap_out(c) or ri[c] > cap_in(c):
            feasible = False
    if not feasible:
        return None  # 必留冲突
    optional = [e for e in edges if e not in req]
    best = None  # (count, total_count, ordered_tuple) 全部用原生 tuple 比较
    for r in range(len(optional), -1, -1):
        for combo in itertools.combinations(optional, r):
            chosen = set(req) | set(combo)
            uo = {c: sum(1 for a, b in chosen if a == c) for c in chapters}
            ui = {c: sum(1 for a, b in chosen if b == c) for c in chapters}
            if not all(uo[c] <= cap_out(c) and ui[c] <= cap_in(c) for c in chapters):
                continue
            ordered = tuple(sorted(chosen))  # (起,止) 元组列表，原生字典序
            # 三段比较：链接数↑、次数总和↑、名单字典序↓(tuple 越小越优)
            cand = (len(chosen), sum(edges[e] for e in chosen))
            if best is None or cand > best[0] or (cand == best[0] and ordered < best[2]):
                best = (cand, set(chosen), ordered)
        if best:
            break
    return best[1]


def make_records(rng, n_sessions, chapter_pool, max_len=5):
    records = []
    for i in range(n_sessions):
        length = rng.randint(1, max_len)
        path = [rng.choice(chapter_pool) for _ in range(length)]
        records.append({'values': {'session': 'S-%04d' % i, 'path': '>'.join(path)}})
    return records


def main():
    rng = random.Random(7)
    chapters_pool = ['序章', '材料', '工艺', '案例', '附录', '结语']
    failures = 0
    for trial in range(400):
        records = make_records(rng, rng.randint(1, 14), chapters_pool[:rng.randint(2, 6)])
        edges, chaps = parse_sessions(records)
        if not edges:
            continue
        # 随机名额：0..3，部分章节用默认
        quotas = {}
        for c in chaps:
            if rng.random() < 0.7:
                quotas[c] = {'out': rng.randint(0, 3), 'in': rng.randint(0, 3)}
        default_cap = rng.randint(0, 2)
        # 随机必留
        edge_list = list(edges)
        req = [list(e) for e in rng.sample(edge_list, rng.randint(0, min(2, len(edge_list))))]
        result = allocate(records, quotas, req, default_cap)
        oracle = brute_force(records, quotas, req, default_cap)
        if oracle is None:
            if result['feasible']:
                failures += 1
                print('TRIAL', trial, 'expected conflict but got feasible', result['selected'])
            continue
        if not result['feasible']:
            failures += 1
            print('TRIAL', trial, 'unexpected conflict', result['conflicts'])
            continue
        got = set((r['from'], r['to']) for r in result['selected'])
        if got != oracle:
            failures += 1
            print('TRIAL', trial, 'MISMATCH')
            print(' got   ', sorted(got))
            print(' oracle', sorted(oracle))
            print(' req   ', req, 'quotas', quotas, 'default', default_cap)
            if failures > 5:
                break
    print('DONE failures=%d / 400' % failures)
    return failures


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
