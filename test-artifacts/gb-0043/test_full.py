"""分配器综合测试：
  A. 小样本：暴力枚举全量校验三层字典序最优（快速，大量随机）；
  B. 中大样本：独立 Edmonds-Karp 最大流校验最大基数，并校验容量、必留、候选归属等性质；
  C. 必留冲突与边界。
"""
import os
import random
import sys
from collections import deque
from itertools import combinations

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'backend')))
from src.services.link_allocator import allocate, parse_sessions  # noqa: E402


def brute_best(records, quotas, required, default_cap):
    edges, chapters = parse_sessions(records)
    co = {c: int(quotas.get(c, {}).get('out', default_cap)) for c in chapters}
    ci = {c: int(quotas.get(c, {}).get('in', default_cap)) for c in chapters}
    req = set(tuple(x) for x in required)
    ro = {c: sum(1 for a, b in req if a == c) for c in chapters}
    ri = {c: sum(1 for a, b in req if b == c) for c in chapters}
    if any(e not in edges for e in req) or any(ro[c] > co[c] or ri[c] > ci[c] for c in chapters):
        return None
    optional = [e for e in edges if e not in req]
    best = None
    for r in range(len(optional), -1, -1):
        for combo in combinations(optional, r):
            chosen = set(req) | set(combo)
            uo = {c: sum(1 for a, b in chosen if a == c) for c in chapters}
            ui = {c: sum(1 for a, b in chosen if b == c) for c in chapters}
            if not all(uo[c] <= co[c] and ui[c] <= ci[c] for c in chapters):
                continue
            cand = (len(chosen), sum(edges[e] for e in chosen))
            ordered = tuple(sorted(chosen))
            if best is None or cand > best[0] or (cand == best[0] and ordered < best[2]):
                best = (cand, set(chosen), ordered)
        if best:
            break
    return best[1]


def edmonds_karp(cap, s, t, n):
    """独立最大流实现，用于核对基数。cap: {(u,v): capacity}。"""
    graph = {i: {} for i in range(n)}
    for (u, v), c in cap.items():
        graph[u].setdefault(v, 0)
        graph[v].setdefault(u, 0)
        graph[u][v] += c
    flow = 0
    while True:
        parent = {s: s}
        q = deque([s])
        while q and t not in parent:
            u = q.popleft()
            for v, c in graph[u].items():
                if c > 0 and v not in parent:
                    parent[v] = u
                    q.append(v)
        if t not in parent:
            break
        # bottleneck
        b = float('inf')
        v = t
        while v != s:
            b = min(b, graph[parent[v]][v])
            v = parent[v]
        v = t
        while v != s:
            u = parent[v]
            graph[u][v] -= b
            graph[v][u] += b
            v = u
        flow += b
    return flow


def independent_max_cardinality(records, quotas, required, default_cap):
    edges, chapters = parse_sessions(records)
    ordered = sorted(chapters)
    idx = {c: i for i, c in enumerate(ordered)}
    n = len(ordered)
    req = set(tuple(x) for x in required) & set(edges)
    ro = {c: sum(1 for a, b in req if a == c) for c in chapters}
    ri = {c: sum(1 for a, b in req if b == c) for c in chapters}
    co = {c: int(quotas.get(c, {}).get('out', default_cap)) - ro[c] for c in chapters}
    ci = {c: int(quotas.get(c, {}).get('in', default_cap)) - ri[c] for c in chapters}
    S = 0
    T = 2 * n + 1
    cap = {}
    for c in ordered:
        cap[(S, 1 + idx[c])] = max(0, co[c])
        cap[(1 + n + idx[c], T)] = max(0, ci[c])
    for (a, b) in edges:
        if (a, b) in req:
            continue
        cap[(1 + idx[a], 1 + n + idx[b])] = 1
    return len(req) + edmonds_karp(cap, S, T, 2 * n + 2)


def make_records(rng, n_sessions, pool, max_len=5):
    out = []
    for i in range(n_sessions):
        path = [rng.choice(pool) for _ in range(rng.randint(1, max_len))]
        out.append({'values': {'session': 'S-%05d' % i, 'path': '>'.join(path)}})
    return out


def main():
    rng = random.Random(2026)
    pool = ['序章', '材料', '工艺', '案例', '附录', '结语']
    fails = 0

    # A. 小样本全枚举
    for t in range(600):
        records = make_records(rng, rng.randint(1, 10), pool[:rng.randint(2, 5)])
        edges, chaps = parse_sessions(records)
        if not edges:
            continue
        quotas = {c: {'out': rng.randint(0, 3), 'in': rng.randint(0, 3)}
                  for c in chaps if rng.random() < 0.7}
        default_cap = rng.randint(0, 2)
        el = list(edges)
        req = [list(e) for e in rng.sample(el, rng.randint(0, min(2, len(el))))]
        res = allocate(records, quotas, req, default_cap)
        oracle = brute_best(records, quotas, req, default_cap)
        if oracle is None:
            if res['feasible']:
                fails += 1
                print('A%d expected conflict' % t)
            continue
        got = set((r['from'], r['to']) for r in res['selected'])
        if got != oracle:
            fails += 1
            print('A%d MISMATCH\n got %s\n ora %s\n req %s q %s d %s'
                  % (t, sorted(got), sorted(oracle), req, quotas, default_cap))
            if fails > 5:
                break
    print('A brute-force done, fails=%d/600' % fails)

    # B. 中大样本性质 + 独立最大流基数
    bf = 0
    for t in range(200):
        records = make_records(rng, rng.randint(20, 80), pool[:rng.randint(3, 6)])
        edges, chaps = parse_sessions(records)
        quotas = {c: {'out': rng.randint(0, 6), 'in': rng.randint(0, 6)}
                  for c in chaps if rng.random() < 0.8}
        default_cap = rng.randint(0, 4)
        el = list(edges)
        req = [list(e) for e in rng.sample(el, rng.randint(0, min(3, len(el))))]
        res = allocate(records, quotas, req, default_cap)
        if not res['feasible']:
            continue
        got = [(r['from'], r['to']) for r in res['selected']]
        got_set = set(got)
        # 候选归属
        if any(e not in edges for e in got_set):
            bf += 1; print('B%d non-candidate selected' % t); continue
        # 必留全包含
        if not set(tuple(x) for x in req) <= got_set:
            bf += 1; print('B%d required missing' % t); continue
        # 容量
        co = {c: int(quotas.get(c, {}).get('out', default_cap)) for c in chaps}
        ci = {c: int(quotas.get(c, {}).get('in', default_cap)) for c in chaps}
        uo = {c: sum(1 for a, b in got if a == c) for c in chaps}
        ui = {c: sum(1 for a, b in got if b == c) for c in chaps}
        if any(uo[c] > co[c] or ui[c] > ci[c] for c in chaps):
            bf += 1; print('B%d capacity violated' % t); continue
        # 名额占用自洽
        for q in res['quotas']:
            if q['out_used'] != uo[q['chapter']] or q['in_used'] != ui[q['chapter']]:
                bf += 1; print('B%d quota usage mismatch' % t); break
        else:
            # 独立最大流基数
            expect_n = independent_max_cardinality(records, quotas, req, default_cap)
            if res['selected_count'] != expect_n:
                bf += 1; print('B%d cardinality %d != maxflow %d' % (t, res['selected_count'], expect_n))
            # 次数总和：与"同基数下贪心取最大次数"的上界一致性（独立加权流核对）
        # 次数总和最优性独立核对：用独立加权最大流（基数优先再次数）
        w2 = max(edges.values()) + 1
        w1 = w2 * max(edges.values()) + 1
        # 构造与 _MinCostFlow 等价但用独立 SPFA MCMF
        w = _IndependentMCMF(2 * len(chaps) + 2)
        idx = {c: i for i, c in enumerate(sorted(chaps))}
        n = len(chaps)
        S, T = 0, 2 * n + 1
        reqset = set(tuple(x) for x in req) & set(edges)
        for c in sorted(chaps):
            w.add(S, 1 + idx[c], co[c] - sum(1 for a, b in reqset if a == c), 0)
            w.add(1 + n + idx[c], T, ci[c] - sum(1 for a, b in reqset if b == c), 0)
        for (a, b) in edges:
            if (a, b) in reqset:
                continue
            w.add(1 + idx[a], 1 + n + idx[b], 1, -(w1 + w2 * edges[(a, b)]))
        w.flow(S, T, 10 ** 9)
        opt_weight = sum(edges[e] for e in reqset) + w.edge_weight(edges, w2, w1, idx, n)
        if res['total_count'] != opt_weight:
            bf += 1; print('B%d total_count %d != weighted-opt %d' % (t, res['total_count'], opt_weight))
    print('B property+independent-flow done, fails=%d/200' % bf)

    # C. 冲突与边界
    cf = 0
    recs = [{'values': {'session': 'A', 'path': '序章>材料'}},
            {'values': {'session': 'B', 'path': '序章>工艺'}}]
    if allocate(recs, {'序章': {'out': 1, 'in': 0}}, [['序章', '材料'], ['序章', '工艺']], 1)['feasible']:
        cf += 1; print('C1 conflict missed')
    if allocate(recs, {}, [['序章', '不存在']], 1)['feasible']:
        cf += 1; print('C2 missing-link conflict missed')
    if allocate(recs, {'序章': {'out': 0, 'in': 0}}, [['序章', '材料']], 0)['feasible']:
        cf += 1; print('C3 zero-cap conflict missed')
    ok = allocate(recs, {}, [['序章', '材料']], 1)
    if not ok['feasible'] or ('序章', '材料') not in {(r['from'], r['to']) for r in ok['selected']}:
        cf += 1; print('C4 feasible required failed')
    try:
        allocate(recs, {}, [], -1)
        cf += 1; print('C5 negative default accepted')
    except ValueError:
        pass
    print('C conflict/boundary done, fails=%d' % cf)

    total = fails + bf + cf
    print('ALL DONE total fails=%d' % total)
    return total


class _IndependentMCMF:
    """与生产代码独立的另一套 SPFA 费用流，仅用于核对。"""
    def __init__(self, n):
        self.n = n
        self.g = [[] for _ in range(n)]

    def add(self, u, v, cap, cost):
        self.g[u].append([v, cap, cost, len(self.g[v])])
        self.g[v].append([u, 0, -cost, len(self.g[u]) - 1])

    def flow(self, s, t, maxf):
        f = 0
        while f < maxf:
            dist = [float('inf')] * self.n
            pv = [-1] * self.n
            pe = [-1] * self.n
            inq = [False] * self.n
            dist[s] = 0
            q = deque([s]); inq[s] = True
            while q:
                x = q.popleft(); inq[x] = False
                for i, (y, cap, cost, _) in enumerate(self.g[x]):
                    if cap > 0 and dist[x] + cost < dist[y]:
                        dist[y] = dist[x] + cost; pv[y] = x; pe[y] = i
                        if not inq[y]:
                            q.append(y); inq[y] = True
            if dist[t] == float('inf'):
                break
            a = maxf - f
            y = t
            while y != s:
                a = min(a, self.g[pv[y]][pe[y]][1]); y = pv[y]
            y = t
            while y != s:
                e = self.g[pv[y]][pe[y]]
                e[1] -= a
                self.g[y][e[3]][1] += a
                y = pv[y]
            f += a
        return f

    def edge_weight(self, edges, w2, w1, idx, n):
        total = 0
        for u in range(1, n + 1):
            for (y, cap, cost, rev) in self.g[u]:
                if n + 1 <= y <= 2 * n and self.g[y][rev][1] > 0:
                    total += (-cost - w1) // w2
        return total


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
