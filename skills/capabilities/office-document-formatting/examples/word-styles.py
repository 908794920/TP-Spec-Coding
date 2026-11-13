"""为无指定模板的新建普通文档设置参照样式；不用于既有文档全篇重排。"""

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor


def apply_reference_styles(document):
    """复用本文档原生样式；不写正文、编号、代码样式、页眉页脚或域。"""
    for section in document.sections:
        section.page_width = Mm(210)
        section.page_height = Mm(297)
        section.top_margin = Mm(37)
        section.left_margin = Mm(28)
        section.right_margin = Mm(26)
        section.bottom_margin = Mm(35)

    # 中文家族名避免已验 Windows LibreOffice 对英文 FangSong/KaiTi 的错误替换。
    # 小标宋未注册；普通参照标题明确采用黑体，不宣称公文全面符合。
    for name, family, size in (
        ("Normal", "仿宋", 16),
        ("Title", "黑体", 22),
        ("Heading 1", "黑体", 16),
        ("Heading 2", "楷体", 16),
        ("Heading 3", "仿宋", 16),
    ):
        style = document.styles[name]
        style.font.name = family
        style.font.size = Pt(size)
        style.font.bold = False
        style.font.italic = False
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style.element.get_or_add_rPr().rFonts
        for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{attribute}"), family)
        for attribute in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
            fonts.attrib.pop(qn(f"w:{attribute}"), None)
        # 默认模板的 Title 可能自带蓝色底线；参照基线不继承装饰线。
        properties = style.element.get_or_add_pPr()
        for border in properties.findall(qn("w:pBdr")):
            properties.remove(border)
        paragraph = style.paragraph_format
        paragraph.line_spacing = 1.5
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(0)
        paragraph.first_line_indent = Pt(32 if name == "Normal" else 0)
        paragraph.widow_control = True
        paragraph.keep_with_next = name != "Normal"
        paragraph.alignment = (
            WD_ALIGN_PARAGRAPH.CENTER if name == "Title" else WD_ALIGN_PARAGRAPH.JUSTIFY
        )

    document.styles["Title"].paragraph_format.space_after = Pt(16)
    for name in ("Heading 1", "Heading 2", "Heading 3"):
        document.styles[name].paragraph_format.space_before = Pt(12)
        document.styles[name].paragraph_format.space_after = Pt(6)
