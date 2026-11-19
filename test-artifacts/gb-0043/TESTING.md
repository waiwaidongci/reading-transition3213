# 章节链接配名额 — 测试说明

本目录的测试不依赖 MySQL / Redis / Docker，可在隔离虚拟环境直接运行；脚本与源码分离，不混入 `backend/`、`frontend/`。

## 准备

```bash
python3 -m venv --without-pip .venv && . .venv/bin/activate
# 若环境无 pip：先 curl https://bootstrap.pypa.io/get-pip.py | python
pip install fastapi==0.115.6 "sqlalchemy==2.0.36" "pydantic>=2" PyJWT==2.10.1 httpx redis==5.2.1
```

前端渲染测试仅需 Node（>=18，使用 ESM）。

## 测试矩阵

| 文件 | 类型 | 覆盖 |
|---|---|---|
| `test_oracle.py` | 暴力枚举 oracle（400 随机用例） | 三层字典序最优：链接数最多 → 次数总和最大 → 名单按 (起,止) 排序最靠前 |
| `test_full.py` | 600 全枚举 + 200 独立流校验 + 边界 | 独立 Edmonds-Karp 核最大基数、独立 SPFA 费用流核次数权重、容量/必留/名额占用自洽、必留超额冲突 |
| `test_http.py` | FastAPI TestClient 端到端（SQLite） | 试算、建版、改版失效、原子批准、并发只生效一次、权限、CSV、审计、唯一约束 |
| `test_frontend.mjs` | Node 渲染冒烟（17 项） | 三角色视图、表单、名额表、冲突提示、旧草案标签、生效标识与导出 |

运行：

```bash
python test_oracle.py
python test_full.py
python test_http.py            # 自管临时 SQLite，自动建表
node test_frontend.mjs
```

## 关键正确性论证

1. **三层字典序**。单条边代价的线性求和无法表达“集合排序元组的字典序”，因此采用两阶段：
   - 阶段一最小费用最大流，权重严格分层（`w1 > w2*max_count + 字典序跨度`），固定最优基数 K 与最优次数权重 W；
   - 阶段二按 `(起章,止章)` 名次贪心强制纳入，每次重解费用流，仅当锁定后仍能保持 `(K,W)` 才接受，从而得到字典序最小名单。
   `test_oracle.py` 对小样本穷举所有可行子集直接比对，`test_full.py` 在更大样本上用相互独立的最大流/加权流交叉核对。

2. **必留超额即冲突**。必留链接不存在、起/止章名额为 0、或必留条数超出进/出名额时返回 `feasible=false` 与逐条原因；冲突版本可留存但不可批准（HTTP 422）。

3. **改版失效与并发安全**。每次名额/必留改版新增不可变版本并以输入 SHA256 作 `config_checksum`；只允许批准该研究的最新可行版本，旧草案批准返回 409。唯一生效行写 `active_key='ACTIVE'`，其余为 NULL（MySQL/SQLite 均允许多个 NULL），唯一索引使并发批准同版只生效一次，冲突整体回滚并保留旧生效版。`test_http.py` 用两个并行会话验证结果恰为 `[200,409]` 且生效行始终唯一。
