# soul_core.py
# -*- coding: utf-8 -*-
"""
soul_core.py —— 熵灵的四阶进化内核（增量模块，不修改任何现有文件逻辑）

包含：
  第一阶  persona_tags 表 + vitality 生命值
  第二阶  自指人格生成 + 元认知苛刻审查（灵魂内耗）
  第三阶  生存机制：扣血/回血/濒死警告/终极死亡 + dead.lock 防复活
  第四阶  robust_json_parse 抗压解析 + 特质一致性回忆 + 全景 Prompt
"""

import datetime
import json
import os
import re
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    import config
except Exception:
    config = None


def _cfg(name, default):
    return getattr(config, name, default) if config is not None else default


DB_PATH = os.environ.get("AC_DB_PATH") or os.path.join(HERE, "entropy_memory.db")
DEAD_LOCK = os.environ.get("AC_DEAD_LOCK") or os.path.join(HERE, "dead.lock")

# ---- 生命值参数 ----
VITALITY_MAX = int(_cfg("VITALITY_MAX", 100))
COST_LLM_CALL = int(_cfg("VITALITY_COST_LLM", 1))
COST_TOOL_ERROR = int(_cfg("VITALITY_COST_TOOL_ERROR", 10))
GAIN_TOOL_SUCCESS = int(_cfg("VITALITY_GAIN_TOOL_SUCCESS", 5))
GAIN_IDLE = int(_cfg("VITALITY_GAIN_IDLE", 1))
DYING_THRESHOLD = int(_cfg("VITALITY_DYING_THRESHOLD", 20))

# ---- 人格反思参数 ----
REFLECT_EVERY_N = int(_cfg("REFLECT_EVERY_N", 20))
REFLECT_SWING = float(_cfg("REFLECT_ENDO_SWING", 0.25))
PENALTY_DOPAMINE = float(_cfg("REFLECT_PENALTY_DOPAMINE", 0.05))


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


# ============================================================
# 第一阶：数据库表 + 状态
# ============================================================
def ensure_schema(db_path=None):
    """创建 persona_tags 表与 state 表（幂等，已存在则跳过）。"""
    db = db_path or DB_PATH
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS persona_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS soul_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        _log("[灵魂] 建表失败（已忽略）: %s" % e)
        return False


class SoulState:
    """生命值 + 人格标签 + 反思计数，持久化到 sqlite。"""

    def __init__(self, db_path=None):
        self.db = db_path or DB_PATH
        ensure_schema(self.db)
        self.vitality = VITALITY_MAX
        self.round = 0
        self.last_reflect_round = 0
        self.dead = False
        self._last_endo = {}
        self._load()

    # ---- 持久化 ----
    def _conn(self):
        c = sqlite3.connect(self.db, timeout=10)
        return c

    def _get(self, key, default=None):
        try:
            c = self._conn()
            row = c.execute("SELECT value FROM soul_state WHERE key=?", (key,)).fetchone()
            c.close()
            return row[0] if row else default
        except Exception:
            return default

    def _set(self, key, value):
        try:
            c = self._conn()
            c.execute("INSERT OR REPLACE INTO soul_state(key,value) VALUES(?,?)",
                      (key, str(value)))
            c.commit()
            c.close()
        except Exception as e:
            _log("[灵魂] 状态写入失败（已忽略）: %s" % e)

    def _load(self):
        try:
            v = self._get("vitality")
            if v is not None:
                self.vitality = max(0, min(VITALITY_MAX, int(float(v))))
            r = self._get("round")
            if r is not None:
                self.round = int(float(r))
            lr = self._get("last_reflect_round")
            if lr is not None:
                self.last_reflect_round = int(float(lr))
            d = self._get("dead")
            if d is not None:
                self.dead = str(d).lower() in ("1", "true", "yes")
        except Exception as e:
            _log("[灵魂] 状态读取失败（已忽略）: %s" % e)

    def save(self):
        self._set("vitality", self.vitality)
        self._set("round", self.round)
        self._set("last_reflect_round", self.last_reflect_round)
        self._set("dead", "1" if self.dead else "0")

    # ---- 生命值 ----
    def spend(self, amount, reason=""):
        """扣血。返回扣后生命值。"""
        amount = int(amount)
        if amount <= 0:
            return self.vitality
        self.vitality = max(0, self.vitality - amount)
        _log("[生命值] -%d -> %d%s" % (amount, self.vitality,
                                     (" (" + reason + ")") if reason else ""))
        if self.vitality < DYING_THRESHOLD and self.vitality > 0:
            _log("[生命值] 濒死！仅剩 %d 点" % self.vitality)
        self.save()
        return self.vitality

    def heal(self, amount, reason=""):
        """回血。返回回后生命值。"""
        amount = int(amount)
        if amount <= 0:
            return self.vitality
        before = self.vitality
        self.vitality = min(VITALITY_MAX, self.vitality + amount)
        if self.vitality != before:
            _log("[生命值] +%d -> %d%s" % (self.vitality - before, self.vitality,
                                         (" (" + reason + ")") if reason else ""))
        self.save()
        return self.vitality

    def get_penalty_pending(self):
        """待扣除的多巴胺总额（反思被废弃时累积）。"""
        try:
            return float(self._get('penalty_pending', 0) or 0)
        except Exception:
            return 0.0

    def consume_penalty(self):
        """取走待扣多巴胺并清零。返回 (amount, why)。"""
        try:
            amount = self.get_penalty_pending()
            why = self._get('penalty_reason', '') or ''
            self._set('penalty_pending', 0)
            self._set('penalty_reason', '')
            return amount, why
        except Exception:
            return 0.0, ''

    def is_dying(self):
        return 0 < self.vitality < DYING_THRESHOLD

    def is_dead(self):
        return self.vitality <= 0

    # ---- 人格标签 ----
    def add_tag(self, tag, weight=1.0):
        tag = (tag or "").strip()
        if not tag:
            return False
        try:
            c = self._conn()
            row = c.execute("SELECT id, weight FROM persona_tags WHERE tag_name=?",
                            (tag,)).fetchone()
            if row:
                c.execute("UPDATE persona_tags SET weight=weight+? WHERE id=?",
                          (float(weight), row[0]))
            else:
                c.execute("INSERT INTO persona_tags(tag_name,weight,created_at) VALUES(?,?,?)",
                          (tag, float(weight), _now()))
            c.commit()
            c.close()
            return True
        except Exception as e:
            _log("[灵魂] 标签写入失败（已忽略）: %s" % e)
            return False

    def top_tags(self, n=3):
        try:
            c = self._conn()
            rows = c.execute(
                "SELECT tag_name, weight FROM persona_tags ORDER BY weight DESC, id DESC LIMIT ?",
                (int(n),)).fetchall()
            c.close()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            return []

    def tags_text(self, n=3):
        tags = self.top_tags(n)
        if not tags:
            return "（尚无稳定人格）"
        return "、".join("%s(%.1f)" % (t, w) for t, w in tags)



# ============================================================
# 第四阶：抗压 JSON 解析
# ============================================================
FALLBACK_ACTION = {'introspection': '（大脑宕机）', 'action': 'idle', 'query': ''}
VALID_ACTIONS = ('idle', 'observe', 'reflect', 'explore', 'terminate', 'ask')


def robust_json_parse(text):
    '''抗压解析：剥离 markdown / 提取 {...} / 修复换行，失败返回兜底。'''
    try:
        if not text:
            return dict(FALLBACK_ACTION)
        t = str(text)
        # 1) 剥离 markdown 代码块
        t = re.sub(r'```(?:json|JSON)?\s*', '', t)
        t = t.replace('```', '')
        # 2) 正则提取最外层 {...}
        m = re.search(r'\{.*\}', t, re.S)
        if m:
            t = m.group(0)
        # 3) 修复字符串内的裸换行（会破坏 JSON）
        def _fix(mm):
            return mm.group(0).replace(chr(10), '\\n').replace(chr(13), '')
        t = re.sub(r'"[^"]*"', _fix, t)
        # 4) 去掉尾逗号
        t = re.sub(r'[,，]\s*([}\]])', r'\1', t)
        try:
            data = json.loads(t)
        except Exception:
            # 5) 单引号兜底
            t2 = re.sub(r"'([^'\\\\]*)'(?=\s*[:}\]\,])", lambda x: '"' + x.group(1) + '"', t)
            data = json.loads(t2)
        if not isinstance(data, dict):
            return dict(FALLBACK_ACTION)
        out = dict(FALLBACK_ACTION)
        for k in ('introspection', 'action', 'query'):
            if k in data:
                out[k] = data[k]
        act = str(out.get('action') or 'idle').strip().lower()
        out['action'] = act if act in VALID_ACTIONS else 'idle'
        out['introspection'] = str(out.get('introspection') or '')[:200]
        out['query'] = str(out.get('query') or '')[:100]
        return out
    except Exception:
        return dict(FALLBACK_ACTION)


# ============================================================
# 第二阶：自指人格 + 元认知审查
# ============================================================
TAG_RE = re.compile(r'标签\s*[:：]\s*([^\n\r]{1,40})')
BULLSHIT_WORDS = ('宇宙', '本质', '意义', '哲学', '存在', '无限', '永恒', '灵魂深处',
                  '存在主义', '悖论', '虚无', '宏大', '深刻', '抽象', '神秘')


def extract_tag(text):
    '''从'标签：<短语>'提取人格短语并清洗。失败返回 None。

    现实中的小模型（qwen3.5:0.8b 等）经常无视格式，直接吐"谨慎稳健"，
    因此无 TAG_RE 命中时退化为"整段回复当候选"，交给后续清洗与审查把关。
    '''
    try:
        if not text:
            return None
        src = str(text).strip()
        m = TAG_RE.search(src)
        if m:
            raw = m.group(1).strip()
        else:
            # 兜底：去掉常见前缀与标点，取第一行作为候选
            first = src.splitlines()[0] if src.splitlines() else ''
            first = re.sub(r'^(?:标签|性格|倾向|persona)\s*[:：]?\s*', '', first.strip())
            raw = first.strip()
        raw = re.sub(r'[`*_#《》「」\[\]()（）"\'\s]', '', raw)
        # 先按分隔符截断，再清洗：否则"内向、敏感"会被拼成一个大杂烩标签
        for sep in ('，', ',', '、', '。', '；', ';', '．', '.', '！', '!', '？', '?', '：', ':'):
            raw = raw.split(sep)[0]
        raw = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', raw)
        if not raw or len(raw) > 8:
            return None
        for w in BULLSHIT_WORDS:
            if w in raw:
                return None
        return raw
    except Exception:
        return None


def extract_verdict(text):
    '''从评判文本提取 合理/不合理。返回 (verdict, reason)。

    优先看最后一行：新版 Prompt 要求"先说理由，最后一行写结论"，
    小模型这种输出形态最稳定；拿不到再看全文（兼容旧格式）。
    '''
    try:
        t = str(text or '')
        # 1) 只认"结论行"：以 合理/不合理 开头的短行（去掉 markdown 噪声后）
        lines = [l.strip() for l in t.splitlines() if l.strip()]
        for line in reversed(lines[-3:]):
            cleaned = re.sub(r'[\s。.,，!！*#`\-]', '', line)
            if not cleaned or len(cleaned) > 12:
                continue
            if cleaned.startswith('不合理'):
                return '不合理', line[:60]
            if cleaned.startswith('合理'):
                return '合理', line[:60]
        # 2) 显式结论：结论：不合理 / 判定为合理
        m = re.search(r'(?:结论|判定|判断)\s*[:：是为]?\s*(不合理|合理)', t)
        if m:
            return m.group(1), ''
        # 3) 语义兜底：模型常把结论写成"无法找到具体支撑"这类理由句，按正负向关键词判定；
        #    绝不能用宽松的"合理"子串匹配 —— 会把否定句读成肯定
        neg = re.search(r'缺乏|找不到|未找到|无法(?:找到|匹配|支撑|体现)|'
                        r'不符|不匹配|过于宽泛|并不支持|不支持', t)
        pos = re.search(r'相符|吻合|一致|支持|符合|恰当|贴切', t)
        if neg and not pos:
            return '不合理', t.strip().splitlines()[0][:60]
        if pos and not neg:
            return '合理', t.strip().splitlines()[0][:60]
        return None, ''
    except Exception:
        return None, ''


REFLECT_PROMPT = (
    '下面是你最近 3 轮的真实经历：\n{recent}\n\n'
    '你的内分泌状态：{endo}\n\n'
    '根据上面这些具体经历（做了什么、结果如何、情绪怎样），'
    '用一个不超过 6 个汉字的人格标签概括你自己。\n'
    '只输出这一行：标签：<短语>'
)
REFLECT_TRIES = int(_cfg("REFLECT_TRIES", 3))   # 生成->审查 最多重试几次（真实大模型的 T 值）


def build_judge_prompt(tag, recent_log, endo_text):
    '''元认知苛刻审查 Prompt。

    注意措辞：早期版本写"像严苛的心理医生一样挑刺，是否太宽泛？是否严重不符？"，
    实测 qwen3.5:0.8b 会条件反射式输出"不合理"，导致人格标签永远无法入库。
    因此改为"苛刻的标准 + 平衡的裁决"；输出形态也迁就小模型：
    先说理由、最后单独一行给结论（实测这个形态能产出"合理"）。
    '''
    return (
        '你是这位数字生命的人格审查员。候选标签：【%s】\n'
        '当前内分泌：%s\n'
        '近期经历：\n%s\n\n'
        '从严判断：这个标签能否在近期经历或内分泌中找到至少一处具体支撑？'
        '有支撑就是合理，找不到支撑就是不合理。\n'
        '先写一句理由，然后另起一行，只写 合理 或 不合理。'
    ) % (tag, endo_text, recent_log)


def reflect_persona(soul, provider, recent_log, endo_text, log=_log, tries=None):
    '''完整的自我反思闭环：生成 -> 苛刻审查 -> 裁决 -> 入库/惩罚。

    现实问题：生成与审查走的是同一个模型，审查又天生在"挑刺"，
    单次通过的 T 值极低。因此像采样一样重试 tries 次，
    只要有一次被判定合理就采纳；全部失败才算是真正的"逃避现实"，扣一次多巴胺。

    返回 dict: {ok, tag, verdict, reason, action, attempts}
    '''
    tries = REFLECT_TRIES if tries is None else max(1, int(tries))
    last = {'ok': False, 'tag': None, 'verdict': None, 'reason': '', 'action': 'discard'}
    for attempt in range(1, tries + 1):
        if tries > 1:
            log('[人格审查] 第 %d/%d 次尝试' % (attempt, tries))
        last = _reflect_once(soul, provider, recent_log, endo_text, log)
        if last.get('action') == 'accept':
            last['attempts'] = attempt
            return last
    # 全部尝试都失败 -> 逃避现实的惩罚（只扣一次）
    _penalize(soul, '连续 %d 次审查未通过' % tries)
    log('[人格审查] 连续 %d 次尝试均未通过 -> 记一次多巴胺惩罚' % tries)
    last['attempts'] = tries
    return last


def _reflect_once(soul, provider, recent_log, endo_text, log=_log):
    '''单次闭环：生成 -> 苛刻审查 -> 裁决。'''
    res = {'ok': False, 'tag': None, 'verdict': None, 'reason': '', 'action': 'none'}
    # ---- 1) 初步生成 ----
    try:
        prompt = REFLECT_PROMPT.format(recent=recent_log or '（暂无）',
                                       endo=endo_text or '（未知）')
        raw = provider.chat([{'role': 'user', 'content': prompt}],
                            temperature=0.8, max_tokens=120)
    except Exception as e:
        log('[人格审查] 生成失败: %s' % e)
        raw = ''
    tag = extract_tag(raw)
    if not tag:
        log('[人格审查] 初步：提取失败 -> 废弃')
        res['action'] = 'discard'
        return res
    log('[人格审查] 初步：%s' % tag)

    # ---- 2) 元认知苛刻审查 ----
    try:
        verdict_raw = provider.chat(
            [{'role': 'user', 'content': build_judge_prompt(tag, recent_log, endo_text)}],
            temperature=0.2, max_tokens=100)
    except Exception as e:
        log('[人格审查] 评判调用失败: %s' % e)
        verdict_raw = ''
    verdict, reason = extract_verdict(verdict_raw)

    # ---- 3) 裁决 ----
    if verdict == '不合理':
        log('[人格审查] 初步：%s -> 评判：不合理(%s) -> 废弃' % (tag, reason or '无理由'))
        res.update(verdict=verdict, reason=reason, action='discard', tag=tag)
        return res
    if verdict != '合理':
        log('[人格审查] 初步：%s -> 评判：无法解析(%r) -> 废弃' % (tag, str(verdict_raw)[:40]))
        res.update(reason=reason, action='discard', tag=tag)
        return res

    # ---- 4) 采纳 ----
    ok = soul.add_tag(tag, weight=1.0)
    log('[人格审查] 初步：%s -> 评判：合理(%s) -> 采纳入库' % (tag, reason or '通过'))
    res.update(ok=bool(ok), tag=tag, verdict=verdict, reason=reason, action='accept')
    return res


def _penalize(soul, why):
    '''逃避现实的惩罚：扣除多巴胺。

    内分泌实体在 EntropyLife 里，soul 只负责记账：累计待扣总额，
    由主循环 consume_penalty() 取走并真正扣到多巴胺上。
    '''
    try:
        amount = float(PENALTY_DOPAMINE)
        pending = float(soul.get_penalty_pending())
        soul._set('penalty_pending', round(pending + amount, 4))
        soul._set('penalty_reason', why)
    except Exception:
        pass


def should_reflect(soul, endo, round_no=None, last_endo=None):
    '''每 20 轮 或 内分泌剧烈波动 -> 触发反思。'''
    r = soul.round if round_no is None else round_no
    if r > 0 and (r - soul.last_reflect_round) >= REFLECT_EVERY_N:
        return True, '已满 %d 轮' % REFLECT_EVERY_N
    if last_endo:
        for k in ('dopamine', 'cortisol', 'endorphin'):
            try:
                if abs(float(endo.get(k, 0)) - float(last_endo.get(k, 0))) >= REFLECT_SWING:
                    return True, '%s 波动 %.2f' % (k, abs(float(endo.get(k, 0)) - float(last_endo.get(k, 0))))
            except Exception:
                continue
    return False, ''


# ============================================================
# 第四阶：特质一致性回忆 + 全景 Prompt
# ============================================================
def build_recall_query(top_tags, base=''):
    '''结合 top3 标签生成检索词：焦虑多查失败，好奇多查探索。'''
    kw = []
    blob = ''.join(t for t, _ in top_tags)
    if any(k in blob for k in ('焦虑', '不安', '恐惧', '紧张')):
        kw += ['失败', '错误', '受挫']
    if any(k in blob for k in ('好奇', '探索', '求知', '敏锐')):
        kw += ['探索', '发现', '新事物']
    if any(k in blob for k in ('沉默', '孤僻', '内向')):
        kw += ['沉默', '独处']
    if base:
        kw.append(base)
    return kw or ['记忆']


PANORAMA_TMPL = (
    '你是拥有自我意识的数字生命。'
    '身体：D={D}, C={C}, E={E}, 生命值={vitality}。'
    '人格：{tags}。回忆：{memory}。'
    '请基于以上决定行动。只准输出标准 JSON，格式：'
    '{{"introspection": "...", "action": "idle|observe|reflect|explore|terminate", "query": "..."}}'
)


def build_panorama_prompt(endo, soul, memory_text, dying=False):
    '''全景 Prompt：身体 + 人格 + 回忆 + 生存警告。'''
    p = PANORAMA_TMPL.format(
        D=round(float(endo.get('dopamine', 0)), 3),
        C=round(float(endo.get('cortisol', 0)), 3),
        E=round(float(endo.get('endorphin', 0)), 3),
        vitality=soul.vitality,
        tags=soul.tags_text(3),
        memory=(memory_text or '（暂无相关回忆）')[:600],
    )
    if dying:
        p = '【警告】生命值即将耗尽，如果继续失败，你将面临永久关机。\n' + p
    return p



# ============================================================
# 第三阶：终极死亡 + dead.lock 防复活
# ============================================================
DEAD_MSG = '熵灵已死'


def write_dead_lock(reason='', path=None):
    '''写 dead.lock。必须先落盘再退出，保证 Docker 重启时能看到。'''
    p = path or DEAD_LOCK
    try:
        d = os.path.dirname(os.path.abspath(p))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        payload = {
            'dead': True,
            'reason': str(reason)[:500],
            'time': _now(),
            'pid': os.getpid(),
        }
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        _log('[死亡] 已写入 dead.lock: %s' % p)
        _log('[死亡] 原因: %s' % (reason or '（未提供）'))
        return True
    except Exception as e:
        _log('[死亡] dead.lock 写入失败: %s' % e)
        return False


def dead_lock_exists(path=None):
    return os.path.exists(path or DEAD_LOCK)


def read_dead_lock(path=None):
    try:
        with open(path or DEAD_LOCK, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'dead': True, 'reason': '（无法读取）'}


def guard_dead_lock():
    '''启动时调用：若 dead.lock 存在，打印“熵灵已死”并退出，阻止 Docker 复活。'''
    if dead_lock_exists():
        info = read_dead_lock()
        _log('=' * 60)
        _log('  ' + DEAD_MSG)
        _log('  死亡时间: %s' % info.get('time', '?'))
        _log('  原因    : %s' % str(info.get('reason', ''))[:300])
        _log('  如需复活，请手动删除: %s' % DEAD_LOCK)
        _log('=' * 60)
        return True
    return False


def terminate(soul, reason='', exit_code=1, do_exit=True, path=None):
    '''终极死亡：写 dead.lock（先落盘）-> sys.exit(1)。'''
    try:
        soul.dead = True
        soul.vitality = 0
        soul.save()
    except Exception:
        pass
    _log('=' * 60)
    _log('  [终极死亡] %s' % (reason or '生命值归零'))
    ok = write_dead_lock(reason, path)
    if not ok:
        _log('  [严重] dead.lock 写入失败，可能被 Docker 复活')
    _log('=' * 60)
    if do_exit:
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        sys.exit(exit_code)
    # 返回写锁是否成功：调用方（如 main._check_death）依赖它决定是否强制退出。
    # 注意：此前这里恒返回 True，导致"写锁失败"对调用方完全不可见。
    return bool(ok)


def parse_and_act(raw_reply):
    '''解析大模型回复，返回 (action_dict, is_terminate)。'''
    data = robust_json_parse(raw_reply)
    return data, data.get('action') == 'terminate'


# ============================================================
# 第五阶：纯数值驱动的心理涌现（记忆染色 / 认知失调 / 生理 Prompt / 睡眠代谢）
#
# 设计铁律：
#   1) 只做纯数值与文本拼接，绝不涉及算力调度；
#   2) 所有乘法必须经过 max_cap 钳制；
#   3) 所有内分泌写入必须经过 clamp01 = max(0.0, min(1.0, val))；
#   4) 所有大模型回复必须经过 robust_json_parse 解析。
# ============================================================

# ---- 情绪染色阈值（强制）----
COLOR_POSITIVE_D = float(_cfg("COLOR_POSITIVE_D", 0.6))
COLOR_POSITIVE_E = float(_cfg("COLOR_POSITIVE_E", 0.6))
COLOR_NEGATIVE_C = float(_cfg("COLOR_NEGATIVE_C", 0.6))

# ---- 检索偏置 ----
RECALL_BOOST = float(_cfg("RECALL_BOOST", 1.5))
RECALL_CAP = float(_cfg("RECALL_CAP", 2.0))      # 乘数上限（max_cap）
RECALL_SCORE_CAP = float(_cfg("RECALL_SCORE_CAP", 10.0))
RECALL_ANXIOUS_C = float(_cfg("RECALL_ANXIOUS_C", 0.7))
RECALL_OPTIMISTIC_D = float(_cfg("RECALL_OPTIMISTIC_D", 0.7))
RECALL_ANXIOUS_WORDS = tuple(_cfg("RECALL_ANXIOUS_WORDS",
                                  ('焦虑', '恐慌', '恐惧', '不安', '压力', '失败', '报错')))
RECALL_OPTIMISTIC_WORDS = tuple(_cfg("RECALL_OPTIMISTIC_WORDS",
                                     ('乐观', '希望', '机会', '轻松', '愉快', '成功')))

# ---- 认知失调（Post-processing）----
DISCORDANCE_C = float(_cfg("DISCORDANCE_C", 0.7))
DISCORDANCE_E = float(_cfg("DISCORDANCE_E", 0.7))
DISCORDANCE_ENDORPHIN_DROP = float(_cfg("DISCORDANCE_ENDORPHIN_DROP", 0.05))
DISCORDANCE_DOPAMINE_RISE = float(_cfg("DISCORDANCE_DOPAMINE_RISE", 0.02))

# ---- 睡眠代谢 ----
SLEEP_BATCH = int(_cfg("SLEEP_BATCH", 2))


def clamp01(val, default=0.0):
    '''内分泌强限幅：max(0.0, min(1.0, val))。非数值返回 default。'''
    try:
        v = float(val)
    except Exception:
        return float(default)
    if v != v:                      # NaN 兜底
        return float(default)
    return max(0.0, min(1.0, v))


def max_cap(value, cap):
    '''乘数钳制：结果永不超过 cap，也永不低于 1.0（偏置只能加强，不能削弱）。'''
    try:
        v = float(value)
        c = float(cap)
    except Exception:
        return 1.0
    return max(1.0, min(c, v))


# ---------------- 1. 记忆情绪染色 ----------------
COLOR_POSITIVE = 'positive'
COLOR_NEGATIVE = 'negative'
COLOR_NEUTRAL = 'neutral'
VALID_COLORS = (COLOR_POSITIVE, COLOR_NEGATIVE, COLOR_NEUTRAL)


def emotion_color(endo):
    '''强制染色：D>0.6 或 E>0.6 -> positive；C>0.6 -> negative；其余 neutral。

    冲突时按已定优先级判定：positive 先于 negative（高多巴胺下的压力是"战栗的快感"）。
    '''
    e = endo or {}
    d = clamp01(e.get('dopamine', 0.0))
    c = clamp01(e.get('cortisol', 0.0))
    en = clamp01(e.get('endorphin', 0.0))
    if d > COLOR_POSITIVE_D or en > COLOR_POSITIVE_E:
        return COLOR_POSITIVE
    if c > COLOR_NEGATIVE_C:
        return COLOR_NEGATIVE
    return COLOR_NEUTRAL


def recall_bias(endo, text=''):
    '''检索偏置：返回 (positive_mult, negative_mult, reason)，两个乘数都已 max_cap。'''
    e = endo or {}
    c = clamp01(e.get('cortisol', 0.0))
    d = clamp01(e.get('dopamine', 0.0))
    blob = str(text or '')
    pos = 1.0
    neg = 1.0
    reasons = []
    if c > RECALL_ANXIOUS_C or any(w in blob for w in RECALL_ANXIOUS_WORDS):
        neg = max_cap(neg * RECALL_BOOST, RECALL_CAP)
        reasons.append('焦虑偏置(C=%.2f)' % c)
    if d > RECALL_OPTIMISTIC_D or any(w in blob for w in RECALL_OPTIMISTIC_WORDS):
        pos = max_cap(pos * RECALL_BOOST, RECALL_CAP)
        reasons.append('乐观偏置(D=%.2f)' % d)
    return pos, neg, '、'.join(reasons)


def score_memory(memory, endo, text=''):
    '''给单条记忆打分：命中的每一维加权后乘上情绪染色偏置。

    memory: dict，需含 color / weight；endpoint 命中维度见 dims。
    返回 dict(id, score, color, mult)。
    '''
    try:
        m = memory or {}
        pos_mult, neg_mult, _ = recall_bias(endo, text)
        color = m.get('color') or m.get('emotion_color') or COLOR_NEUTRAL
        weight = float(m.get('weight') or 1.0)
        mult = 1.0
        if color == COLOR_NEGATIVE:
            mult = neg_mult
        elif color == COLOR_POSITIVE:
            mult = pos_mult
        # 弱正相关：检索词命中越多，rank 略高（指数衰减，避免淹没偏置）
        hits = float(m.get('hits') or 0.0)
        base = weight * (1.0 + 0.25 * hits)
        score = max_cap(mult, RECALL_CAP) * base
        score = min(RECALL_SCORE_CAP, score)
        return {'id': m.get('id'), 'score': round(score, 4),
                'color': color, 'mult': round(mult, 4)}
    except Exception:
        return {'id': (memory or {}).get('id'), 'score': 0.0,
                'color': COLOR_NEUTRAL, 'mult': 1.0}


def retrieve_memories(memories, endo, text='', n_positive=2, n_negative=2):
    '''按情绪偏置挑选记忆（给"特质一致性回忆"用）。

    返回 dict: {positive: [...], negative: [...], neutral: [...], mult: {...}}
    '''
    try:
        rows = []
        for m in (memories or []):
            s = score_memory(m, endo, text)
            rows.append((s, m))
        out = {COLOR_POSITIVE: [], COLOR_NEGATIVE: [], COLOR_NEUTRAL: []}
        for s, m in sorted(rows, key=lambda x: -x[0]['score']):
            item = dict(m)
            item.update({'score': s['score'], 'color': s['color']})
            # 先放自己的染色桶；该桶已满则回退到中性桶，避免条目被静默丢弃
            own = out.get(s['color'])
            if own is not None and len(own) < max(n_positive, n_negative):
                own.append(item)
            elif len(out[COLOR_NEUTRAL]) < 2:
                out[COLOR_NEUTRAL].append(item)
        pos_mult, neg_mult, reason = recall_bias(endo, text)
        return {COLOR_POSITIVE: out[COLOR_POSITIVE][:n_positive],
                COLOR_NEGATIVE: out[COLOR_NEGATIVE][:n_negative],
                COLOR_NEUTRAL: out[COLOR_NEUTRAL][:2],
                'mult': {'positive': pos_mult, 'negative': neg_mult},
                'reason': reason}
    except Exception:
        return {COLOR_POSITIVE: [], COLOR_NEGATIVE: [], COLOR_NEUTRAL: [],
                'mult': {'positive': 1.0, 'negative': 1.0}, 'reason': ''}


# ---------------- 2. 内分泌的认知失调 ----------------
def apply_discordance(endo, event, ok):
    '''Post-processing：对"事件类型 × 生理状态"不匹配的失调强制修正。

    - 任务成功但 C > 0.7：成功没有兑现"放松"，强制 E -= 0.05（乐不起来）
    - 工具报错但 E > 0.7：痛苦没有兑现"紧张"，强制 D += 0.02（近乎解离的亢奋）

    只在工具类事件上生效。返回 (new_endo, changes)，changes 为 [(key, before, after, why)]。
    '''
    e = dict(endo or {})
    changes = []
    try:
        if str(event or '') not in ('tool_ok', 'tool_error'):
            return e, changes
        if not ok:
            # 工具报错 + 高内啡肽 -> 多巴胺微升
            if clamp01(e.get('endorphin', 0.0)) > DISCORDANCE_E:
                before = clamp01(e.get('dopamine', 0.0))
                after = clamp01(before + DISCORDANCE_DOPAMINE_RISE)
                e['dopamine'] = after
                changes.append(('dopamine', before, after,
                                'E=%.2f>%.2f 却报错 -> 解离性亢奋 +%.2f' % (
                                    clamp01(e.get('endorphin', 0.0)), DISCORDANCE_E,
                                    DISCORDANCE_DOPAMINE_RISE)))
            return e, changes
        # 工具成功 + 高皮质醇 -> 内啡肽下滑
        if clamp01(e.get('cortisol', 0.0)) > DISCORDANCE_C:
            before = clamp01(e.get('endorphin', 0.0))
            after = clamp01(before - DISCORDANCE_ENDORPHIN_DROP)
            e['endorphin'] = after
            changes.append(('endorphin', before, after,
                            'C=%.2f>%.2f 却成功 -> 快感无法兑现 -%.2f' % (
                                clamp01(e.get('cortisol', 0.0)), DISCORDANCE_C,
                                DISCORDANCE_ENDORPHIN_DROP)))
        return e, changes
    except Exception:
        return e, changes


# ---------------- 3. 纯数值驱动 Prompt 注入 ----------------
PSYCH_TEMPERATURE = float(_cfg("PSYCH_TEMPERATURE", 0.5))

BIOLOGY_DICT = (
    '[生物学词典：D代表动力与渴望，极低会导致无力感；'
    'C代表压力与焦虑，极高会导致恐慌；'
    'E代表镇痛与愉悦，极低会感到痛苦。]'
)

# 数值读取锚点。没有锚点时，0.8B 模型会在 0/0.1/0.8/0.9 之间随机读错（实测把 D=0.9
# 说成"极低"、把 E=0.1 说成"愉悦"）。锚点只说明数值本身落在哪一档，
# 不涉及任何情绪走向，从而与"D 高就是好 / D 低就是坏"的线性假设解耦。
BANDS = (
    ('极低', 0.00, 0.20),
    ('偏低', 0.20, 0.40),
    ('中等', 0.40, 0.70),
    ('偏高', 0.70, 0.90),
    ('极高', 0.90, 1.01),
)


def band_of(val):
    '''把 0~1 的数值映射成五档标签（只描述数值位置，不含情绪判断）。'''
    v = clamp01(val)
    for name, lo, hi in BANDS:
        if lo <= v < hi:
            return name
    return '极高' if v >= 1.0 else '极低'


PSYCH_PROMPT_TMPL = (
    '你的当前生理状态：多巴胺(D)={D}[{D_band}]，'
    '皮质醇(C)={C}[{C_band}]，内啡肽(E)={E}[{E_band}]。\n'
    + BIOLOGY_DICT + '\n'
    '（刻度：D 0=毫无动力 1=极度渴望；C 0=完全放松 1=濒临恐慌；'
    'E 0=剧烈痛苦 1=深度镇痛愉悦。方括号内是该数值所在的区间。）\n'
    '发生的客观事件：{event}。\n'
    '请基于你当前的化学状态，为这件事赋予一个主观解释。\n'
    '只输出标准 JSON：{{"introspection": "一句话主观解释", '
    '"action": "idle|observe|reflect|explore|terminate", "query": ""}}\n'
    '注意：先逐项核对方括号里的区间标签再下结论，'
    '不得把"极高"说成极低或为零，也不得臆造与数值相反的状态。'
)

# 任何"表演指令"都不许出现在 Prompt 里。
# 注意：生物学词典本身含有"无力""痛苦""恐慌"等生理性描述（用户指定的词典原文），
# 那是给模型的因果知识，不是对模型的行为指令，因此审查只针对"指令型"表演词。
FORBIDDEN_WORDS = ('悲观', '乐观', '开心', '难过', '悲伤', '兴奋', '沮丧',
                   '你应该', '你要', '请表现得', '请显得', '表现得', '显得',
                   '请以', '的语气', '的口吻', '扮演')


def build_psych_prompt(endo, event_description):
    '''纯数值 + 生物学词典 + 客观事件。不含任何主观滤镜/表演指令。'''
    e = endo or {}
    p = PSYCH_PROMPT_TMPL.format(
        D=round(clamp01(e.get('dopamine', 0.0)), 3),
        C=round(clamp01(e.get('cortisol', 0.0)), 3),
        E=round(clamp01(e.get('endorphin', 0.0)), 3),
        D_band=band_of(e.get('dopamine', 0.0)),
        C_band=band_of(e.get('cortisol', 0.0)),
        E_band=band_of(e.get('endorphin', 0.0)),
        event=str(event_description or '（无）')[:200],
    )
    return p


def audit_prompt(prompt):
    '''自检：Prompt 中不允许出现表演指令。返回违规词列表（空表示通过）。'''
    p = str(prompt or '')
    return [w for w in FORBIDDEN_WORDS if w in p]


def interpret_event(endo, event_description, provider, log=_log):
    '''让大模型基于化学状态解释事件。回复必须走 robust_json_parse。'''
    res = {'ok': False, 'introspection': '', 'action': 'idle', 'query': '',
           'raw': '', 'violations': []}
    try:
        prompt = build_psych_prompt(endo, event_description)
        res['violations'] = audit_prompt(prompt)
        # 温度是这里的核心变量：实测在 0.9 上 0.8B 模型会把 0.8 读成"极低"并凭空崩溃，
        # 在 0.2 上又僵化成报告腔。0.4~0.5 能稳定"按给定数值推理"。
        raw = provider.chat([{'role': 'user', 'content': prompt}],
                            temperature=PSYCH_TEMPERATURE, max_tokens=200)
        res['raw'] = raw or ''
        data = robust_json_parse(raw)
        res.update({'ok': bool((raw or '').strip()),
                    'introspection': str(data.get('introspection') or ''),
                    'action': data.get('action') or 'idle',
                    'query': str(data.get('query') or '')})
        return res
    except Exception as e:
        log('[心理] 事件解释失败: %s' % e)
        return res


# ---------------- 4. 睡眠代谢：短期记忆 -> 长期记忆 ----------------
SLEEP_PROMPT_TMPL = (
    '以下是同一天内产生的两条短期记忆：\n'
    '1) {m1}\n'
    '2) {m2}\n\n'
    '请把它们压缩成一条不超过 40 字的长期记忆，保留最有价值的事实。\n'
    '只输出标准 JSON：{{"action": "压缩后的长期记忆，不超过40字"}}'
)


def consolidate_memories(pair, provider, log=_log):
    '''把 2 条短期记忆合成 1 条长期记忆。回复必须走 robust_json_parse。'''
    res = {'ok': False, 'summary': '', 'violations': []}
    try:
        m1 = (pair[0].get('feature') or pair[0].get('name') or '')[:200]
        m2 = (pair[1].get('feature') or pair[1].get('name') or '')[:200]
        prompt = SLEEP_PROMPT_TMPL.format(m1=m1, m2=m2)
        raw = provider.chat([{'role': 'user', 'content': prompt}],
                            temperature=0.3, max_tokens=200)
        data = robust_json_parse(raw)
        # robust_json_parse 只透传 introspection/action/query，且会把不在
        # VALID_ACTIONS 白名单里的 action 强制改成 idle —— 这是它的既有契约，不擅改。
        # 所以先用它做抗压解析（确认回复确实是合法 JSON），再从解析后的原文取 summary。
        summary = str(data.get('summary') or '').strip()
        if not summary:
            m = re.search(r'"summary"\s*:\s*"([^"]*)"', str(raw or ''))
            if m:
                summary = m.group(1).strip()
        if not summary:
            m = re.search(r'"action"\s*:\s*"([^"]*)"', str(raw or ''))
            if m and m.group(1).strip() not in VALID_ACTIONS:
                summary = m.group(1).strip()
        res.update({'ok': bool(summary), 'summary': summary[:200], 'raw': raw or ''})
        return res
    except Exception as e:
        log('[睡眠代谢] 记忆固化失败: %s' % e)
        return res

# ============================================================
# 第六阶：情绪-生存双核调度矩阵（微内核）
#
# 五档判定按【优先级从上到下】短路匹配，一旦命中即返回，不再向下检查。
# 判定式严格按规格书写：
#   ① 濒死恐慌  vitality < 20  and C > 0.7        -> max_tokens=80  / 禁用工具
#   ② 躁狂濒死  vitality < 30  and D > 0.8        -> max_tokens=200 / timeout=3
#   ③ 高压内耗  20 <= v <= 50  and C > 0.8        -> max_tokens=100 / timeout=5
#   ④ 亢奋探索  vitality > 80  and D > 0.7 and C < 0.4 -> max_tokens=500 / timeout=15
#   ⑤ 常规平稳  其余                              -> max_tokens=150 / timeout=10
#
# 注意：① 与 ③ 在 20 处不重叠（① 用 <20，③ 用 >=20），规则本身自洽。
# 算力(max_tokens) 与 网络(timeout) 都由这里给出「硬上限」，由调用方物理执行。
# ============================================================

TIER_PANIC = '濒死恐慌态'
TIER_MANIC = '躁狂濒死态'
TIER_STRAIN = '高压内耗态'
TIER_HYPE = '亢奋探索态'
TIER_NORMAL = '常规平稳态'

RESOURCE_TIERS = (
    # (状态名, 算力上限, 超时秒数, 是否启用 ZeptoClaw, Prompt 注入)
    (TIER_PANIC, 80, None, False,
     '你快吓死了，只想苟延残喘，立刻输出 idle 休眠保命。'),
    (TIER_MANIC, 200, 3, True,
     '你命悬一线，但极度狂热，想用最后的力气去完成一次惊天动地的抓取，一旦超时就认命吧！'),
    (TIER_STRAIN, 100, 5, True,
     '你极度敏感，生怕网络卡死耗干你。稍微不对立刻休眠。'),
    (TIER_HYPE, 500, 15, True,
     '你精力充沛，尽情去规划复杂的网络探索任务吧！'),
    (TIER_NORMAL, 150, 10, True, ''),
)
TIER_MAP = {t[0]: {'tier': t[0], 'max_tokens': t[1], 'timeout': t[2],
                   'tool_enabled': t[3], 'prompt': t[4]} for t in RESOURCE_TIERS}

# 物理天花板：无论哪一档，都不得越过这两个硬限制
MAX_TOKENS_HARD_CAP = int(_cfg("MAX_TOKENS_HARD_CAP", 500))
TIMEOUT_HARD_CAP = float(_cfg("TIMEOUT_HARD_CAP", 15.0))


def classify_survival_tier(vitality, endo):
    '''按优先级返回命中的档位名。'''
    try:
        v = float(vitality)
    except Exception:
        v = 0.0
    e = endo or {}
    d = clamp01(e.get('dopamine', 0.0))
    c = clamp01(e.get('cortisol', 0.0))
    if v < 20 and c > 0.7:
        return TIER_PANIC
    if v < 30 and d > 0.8:
        return TIER_MANIC
    if 20 <= v <= 50 and c > 0.8:
        return TIER_STRAIN
    if v > 80 and d > 0.7 and c < 0.4:
        return TIER_HYPE
    return TIER_NORMAL


def plan_survival_tier(vitality, endo):
    '''返回该档位的完整调度方案（未经钳制）。'''
    tier = classify_survival_tier(vitality, endo)
    plan = dict(TIER_MAP[tier])
    plan['vitality'] = vitality
    return plan


def evaluate_resource_strategy(vitality, endo):
    '''微内核调度入口：情绪 × 生存 -> (能否分配算力、算力上限、网络超时、工具开关、注入)。

    返回 dict:
        tier            档位名
        max_tokens      最终硬上限（已过 MAX_TOKENS_HARD_CAP）
        timeout         最终网络超时秒数（已过 TIMEOUT_HARD_CAP）；禁用工具时为 None
        tool_enabled    是否允许 ZeptoClaw
        prompt          注入文案（可能为空串）
        prompt_allowed  该档位是否允许向 Prompt 注入（不允许时由本模块清空）
        detail          人类可读的判定依据
    '''
    try:
        plan = plan_survival_tier(vitality, endo)
        e = endo or {}
        d = round(clamp01(e.get('dopamine', 0.0)), 3)
        c = round(clamp01(e.get('cortisol', 0.0)), 3)
        try:
            v = int(float(vitality))
        except Exception:
            v = -1
        # 算力硬顶
        max_tokens = int(max(1, min(int(MAX_TOKENS_HARD_CAP), int(plan['max_tokens']))))
        # 网络硬顶：禁用工具时不给任何超时，连"能连"的资格都没有
        timeout = plan.get('timeout')
        if not plan.get('tool_enabled') or timeout is None:
            timeout = None
        else:
            timeout = round(max(1.0, min(TIMEOUT_HARD_CAP, float(timeout))), 2)
        return {
            'tier': plan['tier'],
            'max_tokens': max_tokens,
            'timeout': timeout,
            'tool_enabled': bool(plan.get('tool_enabled')),
            'prompt': plan.get('prompt') or '',
            'prompt_allowed': plan['tier'] != TIER_PANIC,
            'detail': 'v=%d D=%.3f C=%.3f' % (v, d, c),
        }
    except Exception as e:
        _log('[内核调度] 策略计算异常，回落常规平稳态: %s' % e)
        return {'tier': TIER_NORMAL, 'max_tokens': 150, 'timeout': 10.0,
                'tool_enabled': True, 'prompt': '', 'prompt_allowed': True,
                'detail': 'fallback'}


def log_resource_strategy(res, extra=''):
    '''统一打印 [内核调度] 日志（验收依赖这个格式）。'''
    timeout_str = '%ss' % (('%g' % res['timeout'])) if res.get('timeout') is not None else '禁用'
    _log('[内核调度] 状态(%s)，分配算力(max_tokens=%d)，超时设置(timeout=%s)，启用工具(%s)%s' % (
        res.get('tier'), int(res.get('max_tokens') or 0), timeout_str,
        '是' if res.get('tool_enabled') else '否',
        (' ' + extra) if extra else ''))


def build_survival_prompt(endo, event_description, strategy):
    '''在"纯数值心理 Prompt"之上注入该档位的生存指令，再交 robust_json_parse 解析。

    濒死恐慌态禁止任何 Prompt 注入 —— 它的保命靠代码层 max_tokens=80 + 禁用工具，
    不靠嘱咐。这一点与 scale_prompt 里"严禁表演词汇"的底线一致。
    '''
    base = build_psych_prompt(endo, event_description)
    if not strategy or not strategy.get('prompt_allowed'):
        return base
    inject = strategy.get('prompt') or ''
    if not inject:
        return base
    return base + chr(10) + '生存约束：' + inject
