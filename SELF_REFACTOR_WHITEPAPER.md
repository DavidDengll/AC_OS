
# AC OS V6.0 自我重构白皮书 (SELF_REFACTOR_WHITEPAPER)

## 一、 核心哲学与设计原则

1. **三权分立**：将“发现问题（侦察）”、“审批问题（法官）”与“修改代码（修理工）”彻底分离，防止单一模型既当裁判又当运动员导致的幻觉连发。
2. **物理隔离**：权限白名单在代码层面焊死。侦察兵绝对不可写，修理工绝对不可网，法官绝对不可调用大模型。
3. **防爆第一**：严格控制上下文与内存。所有长文本强制截断；绝对禁止全量加载任何模型权重。

## 二、 模块一：搜索适配器 (Search Adapter)

**文件位置**：`tool_caller.py` 或新建 `search_utils.py`
**功能**：提供统一的 `web_search(query: str) -> str` 接口。
**防呆铁律**：

1. **致歉信过滤**：搜索结果若包含 `I'm sorry`, `network error`, `无法访问` 等字眼，直接返回空字符串，绝不将致歉语当做搜索结果往下传。
2. **长度截断**：返回的搜索结果文本，在代码层面强制截断至最多 **20 行**（防上下文爆炸）。
3. **前置校验**：在提取模块名时，必须校验其是否为合法的 Python 标识符（如 `q_proj`），绝不将普通英文单词（如 `Would`）误判为模块。

## 三、 模块二：侦察兵 (Scout)

**文件位置**：`self_refactor.py` -> `class Scout`
**权限白名单**：`read_file`, `grep`, `find`, `web_search`, `py_compile`（受限）
**物理剥夺**：严禁 `edit_file`, `write_file`, `shell`
**任务流逻辑**：

1. 接收目标文件路径，利用 `read_file` 和受限的 `py_compile` 扫描报错。
2. 若发现报错且自身（LLM）无法提供解决方案，构造查询词（如 `Python {error_type} {code_snippet} solution`），调用 `web_search`。
3. **输出格式**：必须输出结构化 JSON 报告：
   `{"issues": [{"file_path": "xxx.py", "error_line": 42, "evidence": "报错原文或搜到的有效代码", "suggested_fix": "修复建议"}]}`

## 四、 模块三：法官 (Judge)

**文件位置**：`self_refactor.py` -> `class Judge`
**核心约束**：纯 Python 类，**绝对禁止调用任何 LLM 接口**。
**任务流逻辑**：

1. **校验与清洗**：接收侦察兵的报告。检查 `evidence` 是否有效（剔除空字符串、致歉信）。
2. **强制截断**：将即将派发给修理工的所有文本（含 `evidence` 和 `suggested_fix`），物理截断至 **20 行** 以内。
3. **派发机制**：提取严重程度最高的 1 个问题，构建 `Task()` 对象，指定目标文件，指派给修理工。严禁一次性派发多个任务。

## 五、 模块四：修理工 (Surgeon)

**文件位置**：`self_refactor.py` -> `class Surgeon`
**权限白名单**：`read_file`, `edit_file`, `py_compile`（仅限法官指定的单一文件）
**物理剥夺**：严禁 `web_search`（拒绝外部干扰），严禁跨文件修改。
**三道门状态机（必须硬编码）**：

1. **OBSERVED 状态**：必须先调用 `read_file` 读取目标文件，才能进入 `EDITED` 状态。
2. **EDITED 状态**：在内存中生成修改后的代码，调用 `edit_file` 写入。写入成功后进入 `VERIFIED` 状态。
3. **VERIFIED 状态**：调用受限的 `py_compile` 编译目标文件。通过则任务结束。
   **熔断机制 (Circuit Breaker)**：

- 若 `py_compile` 失败，退回重新循环，**最多重试 2 次**。
- 2 次失败后，直接抛出 `RefactorFailedException` 并退出流水线。
- 主循环捕获此异常后，执行 `cortisol += 0.1`（增加压力值），并放弃该任务。

## 六、 验收与测试标准 (TDD)

开发完成后，必须通过以下自动化测试：

1. **错误文件拦截测试**：制造一个带 `SyntaxError` 的临时文件。
2. **流水线正向测试**：触发重构，终端日志必须严格打印：
   `[Scout] 发现错误并输出报告...`
   `[Judge] 证据校验通过，截断长度至20行，派发任务...`
   `[Surgeon] 状态机 OBSERVED -> EDITED -> VERIFIED 验证通过。`
3. **熔断机制测试**：故意传入一个无法修复的错误，验证修理工是否在重试 2 次后优雅退出，并成功触发皮质醇上升。
