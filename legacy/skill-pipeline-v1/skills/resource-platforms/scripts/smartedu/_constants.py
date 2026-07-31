#!/usr/bin/env python3
"""SmartEdu 共享常量。

Phase 3E 从 smartedu_resources.py 拆出的常量层：被搜索、详情、栏目、扫描多个域
共用（如 SEARCH_URLS / DETAIL_URLS / DEFAULT_TAB_CODES / TAG_DIMENSIONS），
集中放置避免循环依赖。纯数据，无逻辑。
"""

from __future__ import annotations

import re


LIBRARY_LIST_URL = "https://api.ykt.cbern.com.cn/zxx/api_static/data/6_6_6/librarylist.json"
SEARCH_URLS = (
    "https://x-search.ykt.eduyun.cn/v1/resources/combine/search",
    "https://resource-gateway.ykt.eduyun.cn/resources/combine/search",
    "https://resource-gateway.ykt.eduyun.cn/resources/aggregate",
)
DETAIL_URLS = (
    "https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/{catalog}/details/{id}.json",
    "https://s-file-2.ykt.cbern.com.cn/zxx/ndrv2/resources/{catalog}/details/{id}.json",
)
DETAIL_ENDPOINT_FAMILY = "s-file-ndrv2-details"
SMARTEDU_FILE_SERVERS = ("s-file-1", "s-file-2", "s-file-3")
DETAIL_PAGE = (
    "https://basic.smartedu.cn/{catalog}/detail?"
    "contentType={content_type}&contentId={id}&catalogType={catalog}&subCatalog={sub_catalog}"
)
PRIVATE_HOST = "https://r1-ndr-private.ykt.cbern.com.cn"
PUBLIC_HOSTS = (
    "https://r1-ndr.ykt.cbern.com.cn",
    "https://r2-ndr.ykt.cbern.com.cn",
    "https://r3-ndr.ykt.cbern.com.cn",
)
PRIVATE_NDR_RE = re.compile(r"https://r[123]-ndr-private\.ykt\.cbern\.com\.cn")
TAG_DIMENSIONS = {
    "zxxxd": "stage",
    "zxxxk": "subject",
    "zxxnj": "grade",
    "zxxbb": "version",
    "zxxcc": "volume",
}
DEFAULT_RESOURCE_TYPES = ["教材", "课程", "课件", "习题", "试卷", "视频", "音频", "图片", "文档", "实验", "专题", "家庭教育", "德育", "课后服务"]
DEFAULT_FORMATS = ["pdf", "doc", "docx", "ppt", "pptx", "jpg", "png", "mp3", "mp4", "m3u8", "zip", "网页"]

# ============================================================================
# 搜索 API 实测验证后的有效 tab_code 集合
# ============================================================================
# 搜索接口 x-search.ykt.eduyun.cn/v1/resources/combine/search 只认以下 tab_code：
#   A) catalog 级别（栏目大类，直接可作为 tab_code）：
#      sedu / family / labourEdu / schoolService / specialEdu / sport / art /
#      AIEducation / technologyEdu / areaSite / tchMaterial / eduReform /
#      teacherTraining / lecturer / nationality / topic
#   B) 非 catalog 的独立 tab（课程教学子频道 + 功能型 tab）：
#      qualityCourse / prepareLesson / questions / examinationPapers /
#      teachingKnMicroLesson / childhoodEdu / live / questions_ai_answer /
#      studio-inst-teachres / studio-inst-spres
#
# 以下 catalog 本身不是有效 tab_code（搜索 API 会拒绝或返回空）：
#   syncClassroom / jbgzs / antiEpidemic / classicalResource / culture /
#   development / education / entsClassroom / lawEducation / library /
#   mentalHealth / recommend / researchFirstLesson / situation / t_course /
#   teachingTrainTopic / winterOlympics
# 这些栏目需要通过 VALID_TAB_FALLBACK 映射到有效 tab。
# ============================================================================

# 搜索 API 实测接受的有效 tab_code（全量）
VALID_TAB_CODES = frozenset({
    # catalog 级别有效 tab
    "sedu", "family", "labourEdu", "schoolService", "specialEdu", "sport",
    "art", "AIEducation", "technologyEdu", "areaSite", "tchMaterial",
    "eduReform", "teacherTraining", "lecturer", "nationality", "topic",
    # 非 catalog 独立有效 tab
    "qualityCourse", "prepareLesson", "questions", "examinationPapers",
    "teachingKnMicroLesson", "childhoodEdu", "live", "questions_ai_answer",
    "studio-inst-teachres", "studio-inst-spres",
})

# DEFAULT_TAB_CODES：search-resources 不指定 --tab-code 时传给 API 的默认集合。
# 只包含实测有效的 tab_code，确保默认搜索能覆盖全站所有可搜索栏目。
DEFAULT_TAB_CODES = [
    # 课程教学（syncClassroom 的有效子频道）
    "qualityCourse",
    "prepareLesson",
    "questions",
    "examinationPapers",
    "teachingKnMicroLesson",
    # 德育 / 家庭教育 / 劳动教育 / 课后服务 / 特教
    "sedu",
    "family",
    "labourEdu",
    "schoolService",
    "specialEdu",
    # 教材 / 教师 / AI / 科技 / 专题 / 直播
    "tchMaterial",
    "teacherTraining",
    "lecturer",
    "AIEducation",
    "technologyEdu",
    "areaSite",
    "topic",
    "live",
    # 其他有效
    "art",
    "sport",
    "eduReform",
    "nationality",
    "childhoodEdu",
    "questions_ai_answer",
    "studio-inst-teachres",
    "studio-inst-spres",
]

# ============================================================================
# 栏目 type/sub_catalog → 有效搜索 tab_code 映射
# ============================================================================
# 栏目 librarylist 返回的 type（如 agzy/xljk/jygn/msgzs 等）不是搜索 API 的有效
# tab_code。此表把栏目的 type/sub_catalog/catalog 映射到该栏目所属的有效搜索 tab。
# 这样 search_tab_for() 就能为每个 route 生成一个搜索 API 认识的 tab_code。
# ============================================================================

# type → 有效 tab 的直接映射
TYPE_TO_TAB = {
    # syncClassroom 子频道 → 课程教学 tab
    "course": "qualityCourse",
    "classActivity": "qualityCourse",
    "qualityCourse": "qualityCourse",
    "prepare_lesson": "prepareLesson",
    "basicWork": "prepareLesson",
    "experiment": "qualityCourse",
    "experimentSafety": "qualityCourse",
    "national_lesson": "qualityCourse",
    "elite_lesson": "qualityCourse",

    # jbgzs 子频道
    "yxjyzs": "qualityCourse",

    # 德育 sedu 子类 → sedu
    "agzy": "sedu",           # 爱国主义
    "aljj": "sedu",           # 案例精选（实际属 labourEdu，但搜索走 sedu）
    "dsxx": "sedu",           # 党史学习
    "ldjy": "sedu",           # 劳动教育（德育下）
    "pdjy": "sedu",           # 品德教育
    "smyaq": "sedu",          # 生命与安全（德育下）
    "stwm": "sedu",           # 生态文明
    "szkc": "sedu",           # 思政课程
    "xffz": "sedu",           # 宪法法治

    # 家庭教育 family 子类 → family
    "jygn": "family",         # 家庭教育观念
    "jyff": "family",         # 家庭教育方法
    "jyzd": "family",         # 家庭教育指导
    "jydy": "family",         # 家庭教育阅读专栏
    "jydjt": "family",        # 家庭教育大讲堂
    "Jydjt": "family",
    "jtjy": "family",

    # 劳动教育 labourEdu 子类 → labourEdu
    "jnsf": "labourEdu",      # 技能示范
    "ldjjyj": "labourEdu",    # 劳动教育研究
    "qdfa": "labourEdu",      # 企东方案
    "xjptld": "labourEdu",    # 习近平谈劳动
    "zcwjjjd": "labourEdu",   # 政策文件解读
    "zmldz": "labourEdu",     # 致美丽的你
    "zygg": "labourEdu",      # 资源共享

    # 教师研修 teacherTraining 子类 → teacherTraining
    "gpsf": "teacherTraining",
    "jsfc": "teacherTraining",
    "jyjjs": "teacherTraining",
    "jyyl": "teacherTraining",
    "kxsy": "teacherTraining",
    "msgzs": "teacherTraining",
    "msjt": "teacherTraining",
    "mskt": "teacherTraining",
    "mxzjt": "teacherTraining",
    "sqzxpx": "teacherTraining",
    "szsd": "teacherTraining",   # 思政师德
    "szsy": "teacherTraining",   # 思政实践
    "xkyx": "teacherTraining",   # 学科研修
    "zjgzs": "teacherTraining",
    "ty": "teacherTraining",     # 体育（部分在 sport）
    "tjjy": "teacherTraining",
    "tjsz": "teacherTraining",
    "tjyx": "teacherTraining",
    "tydl": "teacherTraining",
    "wljsz": "teacherTraining",
    "ywjy": "teacherTraining",
    "yjyx": "teacherTraining",
    "yszp": "teacherTraining",
    "yxjyzs": "teacherTraining",

    # 课后服务 schoolService 子类 → schoolService
    "jdyd": "schoolService",     # 经典阅读
    "kpjy": "schoolService",     # 科普教育
    "whys": "schoolService",     # 文化艺术
    "ysjy": "schoolService",     # 影视教育
    "yxsj": "schoolService",     # 优秀社会实践

    # 特教 specialEdu 子类 → specialEdu
    "rhjy": "specialEdu",        # 融合教育
    "tjfz": "specialEdu",        # 特教发展
    "tjhd": "specialEdu",        # 特教活动
    "tjjc": "specialEdu",        # 特教教材
    "tjsz": "specialEdu",        # 特教师资
    "txjs": "specialEdu",        # 特教学校
    "xszy": "specialEdu",        # 学生资源
    "specialedu": "specialEdu",

    # 教改经验 eduReform 子类 → eduReform
    "djdy": "eduReform",         # 党建引领
    "jxgg": "eduReform",         # 教学改革
    "jyxxh": "eduReform",        # 教育信息化
    "ptgz": "eduReform",         # 普通高中
    "sjgz": "eduReform",         # 双减工作
    "tsjy": "eduReform",         # 特殊教育（教改下）
    "xqjy": "eduReform",         # 学前教育（教改下）

    # 区域资源 areaSite 子类 → areaSite
    "hdjj": "areaSite",
    "smyaq_x": "areaSite",
    "wsjbr": "areaSite",
    "xl": "areaSite",
    "xlyjk": "areaSite",
    "xwtz": "areaSite",

    # AI 教育 AIEducation 子类 → AIEducation
    "learnAi": "AIEducation",
    "Activity": "AIEducation",
    "Createkj": "AIEducation",
    "Infonavigation": "AIEducation",
    "Learnkj": "AIEducation",
    "Usekj": "AIEducation",

    # 科技教育 technologyEdu 子类 → technologyEdu
    # (Activity/Createkj 等也可属于 technologyEdu，但优先映射到 AIEducation)

    # 专题 topic 子类 → topic
    "2023sdjy": "topic",         # 2023年度教师节
    "jpkt": "topic",             # 精品课堂
    "qgjy": "topic",             # 全国教育

    # 教材
    "tchMaterial": "tchMaterial",
    "t_course": "teacherTraining",
    "t_course_activity": "teacherTraining",
    "teachingTrainTopic": "teacherTraining",

    # art / sport
    "my": "art",                 # 美术
    "whys_art": "art",

    # 旧版/特殊 type 直接映射
    "recommend_url": "qualityCourse",
    "djdy_reform": "eduReform",
    "hdjj_area": "areaSite",
    "mentalHealth": "sedu",       # 心理健康归德育
    "lawEducation": "sedu",       # 法治教育归德育
    "antiEpidemic": "topic",      # 防疫专题
    "classicalResource": "topic", # 中华经典资源库
    "culture": "topic",           # 文化传承
    "development": "eduReform",   # 发展简报
    "education": "eduReform",     # 教育博览
    "entsClassroom": "topic",     # 企业课堂
    "library": "topic",           # 教育博览数字馆
    "researchFirstLesson": "topic", # 研学第一课
    "situation": "topic",         # 形势政策
    "winterOlympics": "topic",    # 冬奥专题
}

# catalog → 有效 tab 的兜底映射
# 当 type/sub_catalog 都不在 TYPE_TO_TAB 中时，用 catalog 做兜底
CATALOG_TO_TAB = {
    "syncClassroom": "qualityCourse",
    "jbgzs": "qualityCourse",
    "t_course": "teacherTraining",
    "teachingTrainTopic": "teacherTraining",
    "recommend": "qualityCourse",
    "antiEpidemic": "topic",
    "classicalResource": "topic",
    "culture": "topic",
    "development": "eduReform",
    "education": "eduReform",
    "entsClassroom": "topic",
    "library": "topic",
    "researchFirstLesson": "topic",
    "situation": "topic",
    "winterOlympics": "topic",
    "mentalHealth": "sedu",
    "lawEducation": "sedu",
}

# 旧版 CATALOG_TAB_HINTS 保留向后兼容（被外部引用）
CATALOG_TAB_HINTS = {
    "qualityCourse": "qualityCourse",
    "prepare_lesson": "prepareLesson",
    "prepareLesson": "prepareLesson",
    "questions": "questions",
    "question": "questions",
    "examinationPapers": "examinationPapers",
    "teachingKnMicroLesson": "teachingKnMicroLesson",
    "experiment": "qualityCourse",
    "syncClassroom": "qualityCourse",
}
