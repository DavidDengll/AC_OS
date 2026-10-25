# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, r"D:\DSH-Workspace\.pylibs")

from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn

TITLE = "微光亦可成炬"
SCHOOL = "深圳亚迪学校"
CLASS_NAME = "702班"
AUTHOR = "邓蔚宸"

PARAS = [
    "“星星之火，可以燎原。”起笔于井冈山的这八个字，曾照亮一个民族最幽暗的夜。后来，那位在窑洞里看清旧中国的人说：“你们青年人朝气蓬勃，好像早晨八九点钟的太阳。”太阳是后来的事，在破晓之前，驱散死寂与黑暗的，从来不是必然降临的黎明，而是那群不甘沉默、以身为柴的青年微光。",

    "今天，没有了连天的炮火，但青年的微光，依然在现实的暗处闪烁。黄文秀从北京师范大学硕士毕业，本可以留在城里，她却转身回了大山。在百坭村，她给村里申请路灯，让村民走夜路不再打手电；她带着八十八户四百多人脱贫，把最美的青春种在了泥土里。二零一九年的暴雨夜，三十岁的生命永远停在了那条赶回村里的山路上。火炬的意义，从来不是它自己能烧多久，而是它照亮的那条路，后来的人还愿不愿意继续走。黄文秀倒下了，但她点亮的灯，百坭村的人还在走。",

    "还有一簇光，留在了喀喇昆仑的冰雪里。十八岁的陈祥榕，写下“清澈的爱，只为中国”。当外敌越线挑衅，他举着盾牌冲在最前面，把年轻的生命永远留在了高原。他用血肉之躯告诉世界：中国青年的微光，是连死亡都浇不灭的。他们不是天生的英雄，只是选择了在那一刻，用自己微弱的光，去护住身后的万家灯火。",

    "然而，现实并非全是光明。面对内卷与功利，有些青年却成了鲁迅笔下聪明的“看客”。比如遇到跌倒的老人，周围人面面相觑，默契地绕道走，怕被讹，怕惹麻烦。他们用“明哲保身”来粉饰怯懦，以为少做一件善事不过是一粒微尘。却不知，千万个冷漠的“绕道”，足以把世道人心推入冰窟。",

    "刘备曾教导后人：“勿以善小而不为，勿以恶小而为之。”这句话放在今天，字字见血。点一盏照人的灯、伸手扶起跌倒的老人是善；而敲下一句冷血的咒骂、留下一次冷漠的转头，就是恶。微光能成炬，但微小的恶同样能汇成深渊。",

    "鲁迅先生说：“愿中国青年都摆脱冷气，只是向上走。”这话放在今天，依然是最冷峻的生存法则。不需要每个人都做惊天动地的英雄，但绝不能做那个吹灭别人火把的“理中客”。哪怕只是一点微光，只要不灭，终可成炬；当这些微光汇聚，便是燎原之势，就是早晨八九点钟的太阳。",
]

FONT = "宋体"
SIZE = Pt(12)          # 小四
LINE_SPACING = 1.5     # 1.5 倍行距


def set_run(run, bold=False, size=SIZE):
    run.font.name = FONT
    run.font.size = size
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), FONT)
    rfonts.set(qn("w:hAnsi"), FONT)
    rfonts.set(qn("w:eastAsia"), FONT)
    rfonts.set(qn("w:cs"), FONT)


def fmt_para(p, align=WD_ALIGN_PARAGRAPH.JUSTIFY, first_indent=True, space_after=0):
    pf = p.paragraph_format
    pf.alignment = align
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE
    pf.line_spacing = LINE_SPACING
    pf.space_before = Pt(0)
    pf.space_after = Pt(space_after)
    if first_indent:
        pf.first_line_indent = Pt(24)   # 小四 12pt，首行缩进 2 字符
    return p


doc = Document()

# 页面设置：A4，常规页边距
sec = doc.sections[0]
sec.page_width = Cm(21.0)
sec.page_height = Cm(29.7)
sec.top_margin = Cm(2.54)
sec.bottom_margin = Cm(2.54)
sec.left_margin = Cm(3.17)
sec.right_margin = Cm(3.17)

# 默认样式也设为宋体小四
normal = doc.styles["Normal"]
normal.font.name = FONT
normal.font.size = SIZE
normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

# 标题：居中
p = doc.add_paragraph()
fmt_para(p, align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False, space_after=6)
set_run(p.add_run(TITLE), bold=True, size=Pt(16))

# 学校 班级 姓名：居中
p = doc.add_paragraph()
fmt_para(p, align=WD_ALIGN_PARAGRAPH.CENTER, first_indent=False, space_after=10)
set_run(p.add_run("{}　　{}　　{}".format(SCHOOL, CLASS_NAME, AUTHOR)))

# 正文
for text in PARAS:
    p = doc.add_paragraph()
    fmt_para(p, first_indent=True)
    set_run(p.add_run(text))

out = r"D:\DSH-Workspace\微光亦可成炬-邓蔚宸.docx"
doc.save(out)
print("saved:", out)
