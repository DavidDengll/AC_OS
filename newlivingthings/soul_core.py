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
    return True


def parse_and_act(raw_reply):
    '''解析大模型回复，返回 (action_dict, is_terminate)。'''
    data = robust_json_parse(raw_reply)
    return data, data.get('action') == 'terminate'

