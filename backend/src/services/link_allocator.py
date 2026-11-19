"""章节链接名额分配器。

候选链接来自一次已完成接续研究（TransitionRun）冻结样本里全部会话内相邻边，
包括没进入 top_n 榜单的边（"没上榜也能选"）。

优化目标（严格字典序）：
  1) 选中的链接数最多；
  2) 在链接数相同的前提下，接续次数总和最大；
  3) 仍同分时，取按 (起章, 止章) 排序最靠前的链接名单。

两阶段求解：
  阶段一 最小费用最大流，求"基数最大、其中次数总和最大"的最优匹配（固定最优基数 K 与权重 W）；
  阶段二 在保持基数 K 与权重 W 的可行域内，按边名次贪心强制纳入，每次重解费用流校验，
          把名单字典序压到最小。
必留链接先强制占用名额；若必留本身超额，明确返回冲突，不静默裁剪。
"""
from collections import Counter, deque


def parse_sessions(records):
    """从冻结样本还原 (a,b)->count 的全部会话内相邻边及章节集合。"""
    edges = Counter()
    chapters = set()
    sessions = set()
    for r in records:
        values = r['values']
        sid = values['session']
        if sid in sessions:
            raise ValueError('会话编号重复，请将一个完整会话保存在同一行')
        sessions.add(sid)
        path = [s.strip() for s in values['path'].split('>')]
        for name in path:
            chapters.add(name)
        for a, b in zip(path, path[1:]):
            edges[(a, b)] += 1
    return edges, chapters


# --------------------------------------------------------------------------- #
# 最小费用最大流（SPFA 增广，允许负费用）
# --------------------------------------------------------------------------- #
class _MinCostFlow:
    def __init__(self, n):
        self.n = n
        self.g = [[] for _ in range(n)]

    def add_edge(self, fr, to, cap, cost):
        forward = [to, cap, cost, len(self.g[to])]
        backward = [fr, 0, -cost, len(self.g[fr])]
        self.g[fr].append(forward)
        self.g[to].append(backward)

    def flow(self, s, t, maxf):
        n = self.n
        total_flow = 0
        total_cost = 0
        INF = float('inf')
        while total_flow < maxf:
            dist = [INF] * n
            in_queue = [False] * n
            prev_v = [-1] * n
            prev_e = [-1] * n
            dist[s] = 0
            q = deque([s])
            in_queue[s] = True
            while q:
                v = q.popleft()
                in_queue[v] = False
                for ei, e in enumerate(self.g[v]):
                    to, cap, cost, _ = e
                    if cap > 0 and dist[v] + cost < dist[to]:
                        dist[to] = dist[v] + cost
                        prev_v[to] = v
                        prev_e[to] = ei
                        if not in_queue[to]:
                            q.append(to)
                            in_queue[to] = True
            if dist[t] == INF:
                break
            add = maxf - total_flow
            v = t
            while v != s:
                add = min(add, self.g[prev_v[v]][prev_e[v]][1])
                v = prev_v[v]
            v = t
            while v != s:
                e = self.g[prev_v[v]][prev_e[v]]
                e[1] -= add
                self.g[v][e[3]][1] += add
                v = prev_v[v]
            total_flow += add
            total_cost += add * dist[t]
        return total_flow, total_cost


def allocate(records, quotas, required_links, default_cap=1):
    """计算最优链接名单，返回候选、选中、名额占用、目标值与必留冲突。"""
    default_cap = int(default_cap)
    if default_cap < 0:
        raise ValueError('默认名额不能为负')
    edges, chapters = parse_sessions(records)
    if not edges:
        raise ValueError('没有相邻章节转移；单章会话不形成接续边，无法配名额')

    ordered = sorted(chapters)
    n = len(ordered)
    idx = {name: i for i, name in enumerate(ordered)}
    out_map = {c: int(quotas.get(c, {}).get('out', default_cap)) for c in ordered}
    in_map = {c: int(quotas.get(c, {}).get('in', default_cap)) for c in ordered}
    for c in ordered:
        if out_map[c] < 0 or in_map[c] < 0:
            raise ValueError('章节名额不能为负：%s' % c)
    for name in quotas:
        if name not in chapters:
            raise ValueError('名额章节不在研究样本中：%s' % name)

    # 规整必留链接
    req_set = set()
    req_conflicts = []
    for pair in required_links:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('必留链接需为 [起章, 止章] 两元素数组')
        a, b = str(pair[0]).strip(), str(pair[1]).strip()
        if not a or not b:
            raise ValueError('必留链接章节名不能为空')
        req_set.add((a, b))
    for (a, b) in sorted(req_set):
        if (a, b) not in edges:
            req_conflicts.append({'from': a, 'to': b, 'reason': '该接续在研究样本中不存在，无法必留'})
        elif out_map.get(a, default_cap) <= 0:
            req_conflicts.append({'from': a, 'to': b, 'reason': '起章「%s」出名额为 0，必留超额' % a})
        elif in_map.get(b, default_cap) <= 0:
            req_conflicts.append({'from': a, 'to': b, 'reason': '止章「%s」进名额为 0，必留超额' % b})

    feasible_req = set(p for p in req_set if p in edges)
    req_out = Counter(a for a, _ in feasible_req)
    req_in = Counter(b for _, b in feasible_req)
    for c in ordered:
        if req_out[c] > out_map[c]:
            for a, b in sorted(p for p in feasible_req if p[0] == c):
                if not any(x['from'] == a and x['to'] == b for x in req_conflicts):
                    req_conflicts.append({'from': a, 'to': b,
                                          'reason': '起章「%s」必留出站 %d 条，超出出名额 %d' % (c, req_out[c], out_map[c])})
        if req_in[c] > in_map[c]:
            for a, b in sorted(p for p in feasible_req if p[1] == c):
                if not any(x['from'] == a and x['to'] == b for x in req_conflicts):
                    req_conflicts.append({'from': a, 'to': b,
                                          'reason': '止章「%s」必留入站 %d 条，超出进名额 %d' % (c, req_in[c], in_map[c])})

    candidate_rows = [{'from': a, 'to': b, 'count': edges[(a, b)]} for a, b in sorted(edges)]
    if req_conflicts:
        return {
            'feasible': False,
            'conflicts': req_conflicts,
            'candidates': candidate_rows,
            'chapters': ordered,
            'quotas': _chapter_quotas(ordered, out_map, in_map, quotas, req_out, req_in),
            'selected': [], 'selected_count': 0, 'total_count': 0,
        }

    # 必留占用后的剩余容量
    rem_out = {c: out_map[c] - req_out[c] for c in ordered}
    rem_in = {c: in_map[c] - req_in[c] for c in ordered}
    optional = sorted((a, b) for (a, b) in edges if (a, b) not in feasible_req)

    # 阶段一：最小费用最大流。权重严格分层：先基数(W1)，再次数(W2)。
    max_count = max(edges.values())
    w2 = max_count + 1
    w1 = w2 * max_count + 1

    def solve(forced):
        """在锁定 forced 可选边的前提下，返回 (最优可选基数, 可选边最大次数权重, 选中集)。"""
        f_out = Counter(a for a, _ in forced)
        f_in = Counter(b for _, b in forced)
        if any(f_out[c] > rem_out[c] or f_in[c] > rem_in[c] for c in ordered):
            return None
        S0 = 0
        T0 = 2 * n + 1
        net = _MinCostFlow(2 * n + 2)
        for c in ordered:
            net.add_edge(S0, 1 + idx[c], rem_out[c] - f_out[c], 0)
            net.add_edge(1 + n + idx[c], T0, rem_in[c] - f_in[c], 0)
        refs = []
        for (a, b) in optional:
            if (a, b) in forced:
                continue
            ei = len(net.g[1 + idx[a]])
            net.add_edge(1 + idx[a], 1 + n + idx[b], 1, -(w1 + w2 * edges[(a, b)]))
            refs.append((1 + idx[a], ei, (a, b)))
        got, _ = net.flow(S0, T0, maxf=sum(rem_out.values()))
        chosen = set(forced)
        weight = sum(edges[e] for e in forced)
        for fr, ei, key in refs:
            forward = net.g[fr][ei]
            reverse = net.g[forward[0]][forward[3]]
            if reverse[1] > 0:
                chosen.add(key)
                weight += edges[key]
        return got + len(forced), weight, chosen

    first = solve(set())
    k_optional = first[0]
    best_weight = first[1]

    # 阶段二：按 (起,止) 名次贪心强制纳入；只要锁定后仍能保持全局最优 (基数, 权重) 就接受。
    locked = set()
    for e in optional:  # optional 已按 (from,to) 升序
        trial = locked | {e}
        result = solve(trial)
        if result is not None and result[0] == k_optional and result[1] == best_weight:
            locked = trial

    chosen = feasible_req | locked
    selected_rows = [{'from': a, 'to': b, 'count': edges[(a, b)], 'required': (a, b) in feasible_req}
                     for a, b in sorted(chosen)]
    used_out = Counter(a for a, _ in chosen)
    used_in = Counter(b for _, b in chosen)
    return {
        'feasible': True,
        'conflicts': [],
        'candidates': candidate_rows,
        'chapters': ordered,
        'quotas': _chapter_quotas(ordered, out_map, in_map, quotas, used_out, used_in),
        'selected': selected_rows,
        'selected_count': len(selected_rows),
        'total_count': sum(r['count'] for r in selected_rows),
        'required_count': len(feasible_req),
        'optional_count': len(locked),
    }


def _chapter_quotas(ordered, out_map, in_map, raw_quotas, used_out, used_in):
    return [{
        'chapter': c,
        'out_cap': out_map[c],
        'in_cap': in_map[c],
        'out_used': used_out.get(c, 0),
        'in_used': used_in.get(c, 0),
        'custom': c in raw_quotas,
    } for c in ordered]
