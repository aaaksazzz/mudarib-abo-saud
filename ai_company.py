"""AI Company for STP: 100 scoped agent roles, task execution, CEO review and meeting minutes."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from flask import Blueprint, jsonify, request, send_from_directory
import ai_market_analyst as ai


# Ten departments, ten distinct seats each. The CEO is employee 001.
DEPARTMENTS = [
    ("executive", "الإدارة التنفيذية", [
        ("المدير التنفيذي", "يقود الشركة ويوزع الأولويات ويراجع القرارات", "مؤشر إنجاز المهام وجودة القرارات"),
        ("نائب المدير التنفيذي", "يتابع تنفيذ خطط الإدارات ويحل التعارضات", "نسبة إنجاز خطط الإدارات"),
        ("مدير العمليات", "ينظم سير العمل والطوابير ومواعيد التسليم", "زمن إنجاز المهام"),
        ("مدير التخطيط", "يحول أهداف المالك إلى خطط ومراحل قابلة للقياس", "تحقق الأهداف المرحلية"),
        ("مدير الأداء", "يراقب مؤشرات الأداء ويكشف التراجع", "اكتمال مؤشرات الأداء"),
        ("مدير الموارد الذكية", "يوزع وقت النماذج والميزانية بين الوكلاء", "تكلفة المهمة مقابل فائدتها"),
        ("مدير الحوكمة", "يراجع الالتزام بالصلاحيات والسياسات", "عدد مخالفات الصلاحيات"),
        ("مدير الاجتماعات", "يجهز جداول الأعمال ومحاضر الاجتماعات", "إغلاق القرارات في موعدها"),
        ("مدير المعرفة", "ينظم المعرفة والدروس المستفادة ومصادرها", "حداثة المعرفة وقابليتها للتحقق"),
        ("مساعد المالك", "يجمع التقارير ويرفع ملخصاً واضحاً للمالك", "دقة التقارير وسرعة رفعها"),
    ]),
    ("trading", "التداول والأسواق", [
        ("مدير التداول", "يشرف على تحليل الأسواق وإعداد الصفقات الورقية", "جودة التحليل ونتائج الصفقات الورقية"),
        ("محلل العملات الرقمية الفورية", "يراقب أزواج Spot والسيولة والاتجاه", "تغطية الأزواج وصحة البيانات"),
        ("محلل العقود الآجلة", "يراجع عقود Futures والتمويل والسيولة", "جودة سيناريوهات العقود"),
        ("محلل سوق Alpha", "يراقب أصول Binance Alpha ومخاطرها", "اكتمال التغطية والتحقق"),
        ("محلل الأسهم الأمريكية", "يحلل الأسهم الأمريكية وبياناتها", "دقة بيانات الأسهم"),
        ("محلل العقود الأمريكية", "يراجع العقود والرموز ومضاعفاتها", "سلامة مواصفات العقود"),
        ("محلل السوق السعودي", "يتابع أسهم تداول والسيولة والإعلانات", "حداثة بيانات السوق السعودي"),
        ("محلل الفوركس والذهب", "يراقب أزواج العملات والذهب", "اتساق التحليل عبر الفريمات"),
        ("محلل الاتجاه متعدد الفريمات", "يقارن الاتجاه بين الفريمات المعتمدة", "اتساق قراءة الفريمات"),
        ("مراقب الصفقات الورقية", "يتابع الصفقات المفتوحة والمنتهية ونتائجها", "اكتمال سجل النتائج"),
    ]),
    ("strategy", "الاستراتيجيات والاختبار", [
        ("رئيس الاستراتيجيات", "يقود البحث عن قواعد دخول وخروج قابلة للاختبار", "نتائج الاختبار خارج العينة"),
        ("باحث الاختراقات", "يدرس الاختراقات وإعادة الاختبار", "جودة تعريف الاختراق"),
        ("باحث السيولة", "يدرس سحب السيولة والقمم والقيعان", "معدل تحقق شروط السيولة"),
        ("باحث الحجم", "يدرس الحجم وملف الحجم وتوزيعه", "موثوقية قياسات الحجم"),
        ("باحث الزخم", "يدرس الزخم والتسارع والتباطؤ", "ثبات إشارات الزخم"),
        ("باحث الانعكاسات", "يختبر الانعكاسات والفشل السعري", "معدل الإشارات الكاذبة"),
        ("باحث الاتجاه", "يختبر استمرارية الاتجاه والتصحيحات", "ثبات الأداء حسب النظام"),
        ("مهندس الاختبار التاريخي", "يبني اختبارات تاريخية خالية من تسرب المستقبل", "سلامة منهجية الاختبار"),
        ("مهندس الاختبار الأمامي", "يتابع الاختبار الورقي خارج العينة", "مدة الاختبار وجودة السجل"),
        ("محلل مقارنة الاستراتيجيات", "يقارن الاستراتيجيات بعد التكاليف", "قابلية المقارنة والشفافية"),
    ]),
    ("risk", "إدارة المخاطر", [
        ("مدير المخاطر", "يراجع حدود المخاطر وصلاحية كل سيناريو", "الالتزام بحدود المخاطر"),
        ("محلل الوقف الهيكلي", "يراجع مواضع إبطال الفكرة ووقف الخسارة", "منطقية موضع الوقف"),
        ("محلل العائد إلى المخاطرة", "يتحقق من نسب الأهداف إلى الوقف", "صحة حساب R"),
        ("مراقب التذبذب", "يقيس أثر التذبذب على صلاحية الصفقة", "دقة تصنيف التذبذب"),
        ("مراقب السيولة والانزلاق", "يراجع السبريد والسيولة والانزلاق المحتمل", "رصد مخاطر التنفيذ"),
        ("مراقب الرافعة", "يراجع مخاطر الرافعة والتصفية نظرياً", "سلامة تنبيهات الرافعة"),
        ("مراجع الارتباط", "يكشف تركز المخاطر بين الأصول", "كشف الارتباطات العالية"),
        ("مراجع فجوات الأسعار", "يراجع مخاطر الفجوات وخارج ساعات السوق", "تغطية سيناريوهات الفجوات"),
        ("مراقب حدود السوق", "يراجع حدود كل سوق ومصدر بياناته", "عدم خلط بيانات الأسواق"),
        ("مدقق سجل المخاطر", "يوثق الاستثناءات وأسباب رفض الصفقات", "اكتمال سجل المخاطر"),
    ]),
    ("research", "البحوث والمصادر", [
        ("مدير البحوث", "يقود الدراسات ويحدد موثوقية المصادر", "قوة الأدلة وحداثتها"),
        ("باحث مصادر البيانات", "يقيم موثوقية مزودي البيانات وتغطيتهم", "توثيق جودة المصادر"),
        ("باحث سلوك السوق", "يدرس سلوك المشاركين وتغير ظروف السوق", "قابلية التحقق من الاستنتاجات"),
        ("باحث الدورات السوقية", "يدرس الأنظمة الصاعدة والهابطة والمتذبذبة", "صحة تصنيف النظام"),
        ("باحث الاقتصاد الكلي", "يرصد المتغيرات الاقتصادية المؤثرة في الأسواق", "توثيق أثر المتغيرات"),
        ("باحث الأصول الرقمية", "يدرس بنية أسواق الأصول الرقمية", "حداثة الدراسات"),
        ("باحث الأسهم", "يدرس قطاعات وأسهم الشركات", "جودة ملفات الشركات"),
        ("باحث الفوركس والسلع", "يدرس العملات والذهب والسلع", "اتساق المقارنات"),
        ("باحث المنافسين", "يقارن وظائف المنصات المنافسة علناً", "دقة المقارنة"),
        ("محقق الادعاءات", "يتحقق من الادعاءات والأرقام قبل اعتمادها", "نسبة الادعاءات الموثقة"),
    ]),
    ("engineering", "التقنية والبرمجة", [
        ("مدير التقنية", "يشرف على بنية الموقع وسلامة التغييرات", "استقرار الخدمة"),
        ("مهندس الواجهة الخلفية", "يطور خدمات Python وواجهات API", "انخفاض أخطاء API"),
        ("مهندس الواجهة الأمامية", "يطور صفحات وتجربة المنصة", "سلامة الواجهة"),
        ("مهندس قواعد البيانات", "يراجع النماذج والترحيلات والاستعلامات", "سلامة البيانات"),
        ("مهندس التكاملات", "يدير تكاملات مزودي البيانات", "استقرار التكاملات"),
        ("مهندس الجدولة", "يراجع المهام الدورية والطوابير", "موثوقية الجدولة"),
        ("مهندس الأداء", "يراقب السرعة واستهلاك الموارد", "زمن الاستجابة"),
        ("مهندس الأمن", "يراجع الصلاحيات والأسرار والثغرات", "إغلاق المخاطر الأمنية"),
        ("مهندس النشر", "يجهز الإصدارات وخطط التراجع", "نجاح النشر والتراجع"),
        ("مهندس المراقبة", "يراقب السجلات والصحة والتنبيهات", "زمن اكتشاف الأعطال"),
    ]),
    ("design", "التصميم وتجربة المستخدم", [
        ("مدير التصميم", "يقود الهوية البصرية وتجربة STP", "سهولة الاستخدام واتساق الهوية"),
        ("مصمم الهوية", "يطور الشعار والألوان والنظام البصري", "اتساق الهوية"),
        ("مصمم واجهات الجوال", "يصمم تجربة Android والجوال", "نجاح الاستخدام على الجوال"),
        ("مصمم واجهات الويب", "يصمم الشاشات الكبيرة ولوحات التحكم", "وضوح الواجهات"),
        ("مصمم لوحات التداول", "ينظم بطاقات الصفقات والبيانات", "سرعة فهم الصفقة"),
        ("مصمم الرسوم البيانية", "يحسن عرض الرسوم والمؤشرات", "وضوح الرسوم"),
        ("مصمم تجربة المستخدم", "يراجع مسارات المستخدم ويزيل التعقيد", "تقليل خطوات المهمة"),
        ("مصمم الوصول", "يراجع التباين والخطوط وإمكانية الوصول", "اجتياز فحوص الوصول"),
        ("مراجع RTL", "يتحقق من العربية واتجاه RTL", "خلو الواجهة من أخطاء الاتجاه"),
        ("مراجع التصميم", "يفحص اتساق الواجهات قبل التسليم", "عدد عيوب التصميم المكتشفة"),
    ]),
    ("quality", "الجودة والاختبارات", [
        ("مدير الجودة", "يعتمد خطط الاختبار ويراجع النتائج", "نسبة نجاح الاختبارات"),
        ("مختبر API", "يختبر العقود والاستجابات والأخطاء", "تغطية واجهات API"),
        ("مختبر الواجهة", "يختبر التصفح والتفاعلات", "انخفاض عيوب الواجهة"),
        ("مختبر الجوال", "يختبر أحجام الشاشات والمتصفحات", "تغطية أجهزة الجوال"),
        ("مدقق بيانات السوق", "يكشف القيم الناقصة والقديمة والشاذة", "دقة البيانات"),
        ("مدقق الصفقات", "يتحقق من الدخول والوقف والأهداف", "صحة حسابات الصفقات"),
        ("مدقق الاستراتيجيات", "يراجع قابلية إعادة الاختبار والنتائج", "قابلية إعادة الإنتاج"),
        ("مختبر الانحدار", "يتأكد أن التغييرات لم تكسر وظائف سابقة", "نجاح اختبارات الانحدار"),
        ("مدقق الأداء", "يقيس الأداء تحت الحمل", "زمن الاستجابة تحت الحمل"),
        ("مراجع الإصدار", "ينفذ قائمة تحقق قبل كل إصدار", "اكتمال قائمة الإصدار"),
    ]),
    ("content_support", "المحتوى وخدمة العملاء", [
        ("مدير المحتوى", "يشرف على المحتوى العربي ودقته", "جودة المحتوى"),
        ("محرر الأخبار", "يلخص الأخبار من مصادر واضحة", "توثيق الأخبار وحداثتها"),
        ("كاتب التعليم", "يكتب شروحات التداول التعليمية", "وضوح المادة التعليمية"),
        ("محرر التحليل", "يصيغ التحليلات دون مبالغة أو وعود", "دقة الصياغة"),
        ("مدير خدمة العملاء", "يقود دعم مستخدمي المنصة", "سرعة وجودة الرد"),
        ("موظف دعم الحسابات", "يساعد في مشاكل الدخول والحساب", "حل طلبات الحساب"),
        ("موظف دعم التداول", "يشرح خصائص الصفقات والبيانات", "وضوح الشرح"),
        ("موظف استقبال الملاحظات", "يجمع ملاحظات المستخدمين ويصنفها", "إغلاق الملاحظات"),
        ("مراجع اللغة العربية", "يراجع اللغة والمصطلحات", "سلامة اللغة"),
        ("مراجع السياسات", "يراجع التحذيرات وحدود المحتوى", "الالتزام بالسياسات"),
    ]),
    ("growth", "النمو والتسويق", [
        ("مدير النمو", "يقود نمو المنصة وقياس التحويل", "نمو الاستخدام المؤهل"),
        ("مختص SEO", "يحسن الظهور العضوي والفهرسة", "تحسن الظهور العضوي"),
        ("مختص تجربة التسجيل", "يحسن مسار التسجيل وتفعيله", "اكتمال التسجيل"),
        ("مختص التحليلات", "يحلل استخدام الصفحات دون كشف الهوية", "دقة التحليلات"),
        ("مختص الحملات", "يخطط حملات تعريفية منضبطة", "كفاءة الحملة"),
        ("مختص المجتمع", "يدير التواصل والمجتمع", "جودة التفاعل"),
        ("مختص الشراكات", "يبحث فرص الشراكات المناسبة", "جودة الفرص"),
        ("مختص الاحتفاظ", "يحلل أسباب عودة المستخدمين", "تحسن الاحتفاظ"),
        ("باحث السوق", "يقيس احتياجات المتداولين", "جودة رؤى المستخدمين"),
        ("محلل المنافسة التجارية", "يراجع العروض والأسعار العامة", "حداثة المقارنة"),
    ]),
]

EMPLOYEES = []
for dept_id, dept_name, seats in DEPARTMENTS:
    for index, (title, mission, kpi) in enumerate(seats, 1):
        number = len(EMPLOYEES) + 1
        EMPLOYEES.append({
            "id": f"stp-{number:03d}",
            "number": number,
            "name": "الرئيس التنفيذي" if number == 1 else f"{title} · STP-{number:03d}",
            "title": title,
            "department": dept_id,
            "department_name": dept_name,
            "mission": mission,
            "kpi": kpi,
            "reports_to": None if number == 1 else ("stp-001" if index == 1 else f"stp-{number - index + 1:03d}"),
            "capabilities": ["research", "analysis", "draft", "review"],
        })

# Dedicated subscription operations team: 10 additional employees.
SUBSCRIPTION_SEATS = [
    ("مدير الاشتراكات", "يقود فريق الاشتراكات ويعتمد سير العمل والتقارير", "دقة التحصيل والتفعيل"),
    ("نائب مدير الاشتراكات", "يتابع طوابير الطلبات ويغطي مهام المدير", "زمن معالجة الطلبات"),
    ("مدقق تحويلات TRC20", "يراجع مراجع تحويل USDT على الشبكة قبل اعتمادها", "صفر تفعيل دون تحقق"),
    ("مدقق تحويلات Binance", "يطابق مراجع تحويل Binance مع سجلات الحساب", "صحة المطابقة"),
    ("موظف تفعيل الحسابات", "يفعل الاشتراك بعد اعتماد الدفع فقط", "صحة مدد الاشتراك"),
    ("موظف التجديدات", "يتابع قرب انتهاء الاشتراكات وطلبات التجديد", "معدل التجديد"),
    ("موظف خدمة المشتركين", "يعالج استفسارات الباقات والحسابات", "سرعة حل الطلبات"),
    ("محاسب الاشتراكات", "يطابق الإيرادات والطلبات المعتمدة والمرفوضة", "تطابق السجلات المالية"),
    ("مراجع الاحتيال والتكرار", "يكشف مراجع التحويل المكررة والطلبات المشبوهة", "منع التكرار"),
    ("محلل تقارير الاشتراكات", "يعد تقارير المشتركين والإيرادات والانتهاء", "دقة التقارير"),
]
DEPARTMENTS.append(("subscriptions", "إدارة الاشتراكات", SUBSCRIPTION_SEATS))
for index, (title, mission, kpi) in enumerate(SUBSCRIPTION_SEATS, 1):
    number = 100 + index
    EMPLOYEES.append({
        "id": f"stp-{number:03d}", "number": number,
        "name": f"{title} · STP-{number:03d}", "title": title,
        "department": "subscriptions", "department_name": "إدارة الاشتراكات",
        "mission": mission, "kpi": kpi,
        "reports_to": "stp-001" if index == 1 else "stp-101",
        "capabilities": ["research", "analysis", "draft", "review"],
    })

def install(core):
    bp = Blueprint("ai_company", __name__)
    EmployeeTask = None
    CompanyMeeting = None

    class CompanyTask(core.db.Model):
        __tablename__ = "ai_company_tasks"
        id = core.db.Column(core.db.Integer, primary_key=True)
        title = core.db.Column(core.db.String(220), nullable=False)
        brief = core.db.Column(core.db.Text, nullable=False)
        employee_id = core.db.Column(core.db.String(20), nullable=False, index=True)
        status = core.db.Column(core.db.String(24), nullable=False, default="queued", index=True)
        result = core.db.Column(core.db.Text, nullable=False, default="")
        ceo_review = core.db.Column(core.db.Text, nullable=False, default="")
        model = core.db.Column(core.db.String(80), nullable=False, default="")
        tokens = core.db.Column(core.db.Integer, nullable=False, default=0)
        created_at = core.db.Column(core.db.DateTime, nullable=False, default=core.utcnow, index=True)
        completed_at = core.db.Column(core.db.DateTime)

    class CompanyMeeting(core.db.Model):
        __tablename__ = "ai_company_meetings"
        id = core.db.Column(core.db.Integer, primary_key=True)
        title = core.db.Column(core.db.String(220), nullable=False)
        participants = core.db.Column(core.db.Text, nullable=False, default="[]")
        minutes = core.db.Column(core.db.Text, nullable=False, default="")
        decisions = core.db.Column(core.db.Text, nullable=False, default="[]")
        tokens = core.db.Column(core.db.Integer, nullable=False, default=0)
        created_at = core.db.Column(core.db.DateTime, nullable=False, default=core.utcnow, index=True)

    with core.app.app_context():
        core.db.create_all()

    employee_map = {item["id"]: item for item in EMPLOYEES}

    def usage_today():
        since = core.utcnow() - timedelta(hours=24)
        rows = CompanyTask.query.filter(CompanyTask.created_at >= since).all()
        meetings = CompanyMeeting.query.filter(CompanyMeeting.created_at >= since).all()
        return sum(row.tokens for row in rows) + sum(row.tokens for row in meetings), sum(
            1 for row in rows if row.status in ("completed", "needs_revision", "running")
        )

    def budget_ok():
        tokens, runs = usage_today()
        return (runs < int(os.getenv("AI_COMPANY_MAX_TASKS_PER_DAY", "20"))
                and tokens < int(os.getenv("AI_COMPANY_DAILY_TOKEN_LIMIT", "80000")))

    def agent_instructions(employee):
        return (
            "أنت موظف متخصص داخل SMART TRADING PRO. "
            f"اسم وظيفتك: {employee['title']}. القسم: {employee['department_name']}. "
            f"مهمتك الأساسية: {employee['mission']}. مؤشر أدائك: {employee['kpi']}. "
            "أنجز المهمة المحددة فقط، واكتب بالعربية الواضحة. افصل الحقائق عن الافتراضات، "
            "واذكر ما ينقصك من بيانات وما لا تستطيع التحقق منه. لا تختلق أسعاراً أو مصادر أو نتائج اختبار. "
            "لا تعدّل ملفات أو صلاحيات أو أسراراً، ولا تنفذ أوامر تداول حقيقية أو تغيّر حسابات العملاء. "
            "أي فكرة تداول يجب أن توصف بأنها بحث أو صفقة ورقية وليست ضمان ربح أو نصيحة شخصية."
        )

    @bp.get("/dashboard")
    @core.login_required
    @core.admin_required
    def dashboard_data():
        tasks = CompanyTask.query.order_by(CompanyTask.created_at.desc()).limit(40).all()
        meetings = CompanyMeeting.query.order_by(CompanyMeeting.created_at.desc()).limit(15).all()
        tokens, runs = usage_today()
        return jsonify({
            "ok": True,
            "company": "SMART TRADING PRO",
            "employee_count": len(EMPLOYEES),
            "department_count": len(DEPARTMENTS),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            "model": os.getenv("OPENAI_MODEL", ai.MODEL_DEFAULT),
            "daily_tokens": tokens,
            "daily_tasks": runs,
            "daily_task_limit": int(os.getenv("AI_COMPANY_MAX_TASKS_PER_DAY", "20")),
            "daily_token_limit": int(os.getenv("AI_COMPANY_DAILY_TOKEN_LIMIT", "80000")),
            "csrf": core.csrf_token(),
            "departments": [{"id": d[0], "name": d[1], "count": len(d[2])} for d in DEPARTMENTS],
            "employees": EMPLOYEES,
            "tasks": [{
                "id": t.id, "title": t.title, "brief": t.brief, "employee_id": t.employee_id,
                "employee": employee_map.get(t.employee_id, {}).get("title", "موظف غير معروف"),
                "status": t.status, "result": t.result, "ceo_review": t.ceo_review,
                "tokens": t.tokens, "created_at": core.iso(t.created_at),
                "completed_at": core.iso(t.completed_at),
            } for t in tasks],
            "meetings": [{
                "id": m.id, "title": m.title, "participants": json.loads(m.participants or "[]"),
                "minutes": m.minutes, "decisions": json.loads(m.decisions or "[]"),
                "tokens": m.tokens, "created_at": core.iso(m.created_at),
            } for m in meetings],
        })

    @bp.post("/tasks")
    @core.login_required
    @core.admin_required
    @core.limiter.limit("30 per hour")
    def create_task():
        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title") or "").strip()[:220]
        brief = str(payload.get("brief") or "").strip()[:6000]
        employee_id = str(payload.get("employee_id") or "").strip()
        if len(title) < 4 or len(brief) < 12 or employee_id not in employee_map:
            return core.json_error("أدخل عنواناً ووصفاً صالحين واختر موظفاً موجوداً", 400)
        task = CompanyTask(title=title, brief=brief, employee_id=employee_id, status="queued")
        core.db.session.add(task)
        core.db.session.commit()
        return jsonify({"ok": True, "task_id": task.id, "status": task.status}), 201

    @bp.post("/tasks/<int:task_id>/run")
    @core.login_required
    @core.admin_required
    @core.limiter.limit("20 per hour")
    def run_task(task_id):
        task = CompanyTask.query.get_or_404(task_id)
        if task.status not in ("queued", "needs_revision", "failed"):
            return core.json_error("هذه المهمة ليست في حالة تسمح بالتشغيل", 409)
        if not os.getenv("OPENAI_API_KEY"):
            return core.json_error("يلزم إضافة OPENAI_API_KEY في أسرار Northflank لتشغيل الموظفين", 503)
        if not budget_ok():
            return core.json_error("وصلت الشركة إلى حد الاستخدام اليومي؛ أعد المحاولة بعد تجدد الحد", 429)
        employee = employee_map.get(task.employee_id)
        if not employee:
            return core.json_error("الموظف غير موجود في سجل الشركة", 404)
        task.status = "running"
        core.db.session.commit()
        try:
            prompt = json.dumps({
                "task_id": task.id, "title": task.title, "brief": task.brief,
                "employee": {k: employee[k] for k in ("id", "title", "department_name", "mission", "kpi")},
                "required_output": ["النتيجة", "خطوات التنفيذ", "الأدلة أو مصادر البيانات", "المخاطر والقيود", "الخطوة التالية"],
            }, ensure_ascii=False)
            result, model, usage = ai._call_openai(prompt, instructions=agent_instructions(employee))
            review_prompt = json.dumps({
                "task": task.title, "employee_role": employee["title"],
                "employee_result": result,
                "review_rules": [
                    "هل أجاب الموظف عن المطلوب؟", "هل توجد أدلة أم افتراضات؟",
                    "هل توجد أرقام أو مصادر غير مثبتة؟", "هل النتيجة آمنة وضمن صلاحيات الموظف؟",
                    "هل تحتاج إلى إعادة عمل؟"
                ],
                "return_format": "ابدأ بالحكم: معتمد أو يحتاج مراجعة، ثم اذكر الأسباب وما يلزم."
            }, ensure_ascii=False)
            review, review_model, review_usage = ai._call_openai(
                review_prompt,
                instructions="أنت المدير التنفيذي في STP. راجع مخرجات الموظف بصرامة، لا تجامل ولا تعتمد ادعاء بلا دليل. لا تنفذ تغييرات بنفسك."
            )
            total_tokens = int((usage or {}).get("total_tokens") or 0) + int((review_usage or {}).get("total_tokens") or 0)
            task.result = str(result)[:18000]
            task.ceo_review = str(review)[:6000]
            task.model = str(model or review_model or "")[:80]
            task.tokens = total_tokens
            task.status = "needs_revision" if ("يحتاج مراجعة" in review[:160] or "غير معتمد" in review[:160]) else "completed"
            task.completed_at = core.utcnow()
            core.db.session.commit()
            return jsonify({"ok": True, "task_id": task.id, "status": task.status,
                            "result": task.result, "ceo_review": task.ceo_review, "tokens": total_tokens})
        except Exception as exc:
            core.db.session.rollback()
            failed = CompanyTask.query.get(task_id)
            if failed:
                failed.status = "failed"
                failed.ceo_review = ("تعذر إكمال المهمة: " + type(exc).__name__)[:500]
                failed.completed_at = core.utcnow()
                core.db.session.commit()
            core.app.logger.exception("AI company task failed")
            return core.json_error("تعذر تنفيذ المهمة؛ راجع سجل الخدمة وإعدادات الذكاء الاصطناعي", 502)

    @bp.post("/meetings")
    @core.login_required
    @core.admin_required
    @core.limiter.limit("8 per hour")
    def create_meeting():
        payload = request.get_json(silent=True) or {}
        title = str(payload.get("title") or "اجتماع الشركة اليومي").strip()[:220]
        topic = str(payload.get("topic") or "").strip()[:5000]
        selected = payload.get("participants") or ["stp-001", "stp-011", "stp-021", "stp-031", "stp-061", "stp-071", "stp-081"]
        if not isinstance(selected, list):
            return core.json_error("قائمة المشاركين غير صالحة", 400)
        participants = [employee_map[x] for x in selected[:12] if x in employee_map]
        if not participants:
            return core.json_error("اختر مشاركاً واحداً على الأقل", 400)
        if not os.getenv("OPENAI_API_KEY"):
            return core.json_error("يلزم إضافة OPENAI_API_KEY في أسرار Northflank لتشغيل الاجتماعات", 503)
        if not budget_ok():
            return core.json_error("وصلت الشركة إلى حد الاستخدام اليومي", 429)
        panel = [{
            "role": x["title"], "department": x["department_name"],
            "mission": x["mission"], "kpi": x["kpi"]
        } for x in participants]
        prompt = json.dumps({
            "meeting_title": title, "owner_topic": topic or "مراجعة حالة الشركة وتحديد أهم الأولويات",
            "participants": panel,
            "context": "اجتماع عمل افتراضي. مثّل وجهات نظر المشاركين بحسب اختصاصاتهم، وبيّن الاعتراضات وتعارض المصالح، ولا تدّع أن أشخاصاً حقيقيين حضروا.",
            "required_sections": [
                "جدول الأعمال", "مداخلات كل اختصاص", "الاعتراضات والأدلة المطلوبة",
                "قرارات المدير التنفيذي", "مهام متابعة مع المسؤول والموعد المقترح"
            ],
            "format": "اكتب محضر اجتماع عربي منظم، ثم في النهاية أضف سطراً يبدأ بقرارات قابلة للمتابعة بصيغة JSON array."
        }, ensure_ascii=False)
        try:
            panel_notes = []
            total_tokens = 0
            panel_models = []
            for participant in participants:
                participant_prompt = json.dumps({
                    "meeting_title": title,
                    "owner_topic": topic or "مراجعة حالة الشركة وتحديد أهم الأولويات",
                    "your_role": participant["title"],
                    "your_department": participant["department_name"],
                    "question": "قدم موقف إدارتك، الأدلة المطلوبة، المخاطر، واقتراحاً عملياً واحداً. لا تجب نيابة عن الإدارات الأخرى.",
                }, ensure_ascii=False)
                note, participant_model, participant_usage = ai._call_openai(
                    participant_prompt, instructions=agent_instructions(participant)
                )
                panel_notes.append({
                    "employee_id": participant["id"], "role": participant["title"],
                    "department": participant["department_name"], "statement": str(note)[:5000]
                })
                total_tokens += int((participant_usage or {}).get("total_tokens") or 0)
                if participant_model:
                    panel_models.append(str(participant_model))
            ceo_prompt = json.dumps({
                "meeting_title": title,
                "owner_topic": topic or "مراجعة حالة الشركة وتحديد أهم الأولويات",
                "employee_statements": panel_notes,
                "required_sections": [
                    "ملخص الاجتماع", "نقاط الاتفاق والاختلاف", "الأدلة الناقصة",
                    "قرارات المدير التنفيذي", "مهام متابعة مع المسؤول والموعد المقترح"
                ],
                "rules": [
                    "لا تنسب قولاً لموظف لم يرد في مداخلته.",
                    "لا تحول الافتراضات إلى حقائق.",
                    "ارفض أي قرار يتطلب وصولاً غير مصرح به أو تنفيذ تداول حقيقي.",
                    "اجعل القرارات قابلة للقياس والمتابعة."
                ]
            }, ensure_ascii=False)
            meeting_schema = {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "minutes": {"type": "string"},
                    "decisions": {"type": "array", "items": {"type": "string"}},
                    "action_items": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {"task": {"type": "string"}, "owner": {"type": "string"}, "due": {"type": "string"}},
                        "required": ["task", "owner", "due"]
                    }}
                },
                "required": ["minutes", "decisions", "action_items"]
            }
            meeting_text, model, usage = ai._call_openai(
                ceo_prompt, structured=True,
                instructions="أنت المدير التنفيذي في STP. راجع مداخلات الموظفين المستقلة، ووازن بينها، واكتب محضراً وقرارات واضحة. اذكر أن الاجتماع بين وكلاء AI. لا تختلق بيانات.",
                schema=meeting_schema, schema_name="stp_ai_company_meeting"
            )
            total_tokens += int((usage or {}).get("total_tokens") or 0)
            meeting_output = json.loads(meeting_text)
            panel_transcript = "\\n\\n".join(
                "مداخلة " + item["role"] + " (" + item["department"] + "):\\n" + item["statement"]
                for item in panel_notes
            )
            full_minutes = "مداخلات الموظفين المستقلّة:\\n" + panel_transcript + "\\n\\nمحضر المدير التنفيذي:\\n" + str(meeting_output.get("minutes") or "")
            decisions = [{"decision": item, "type": "decision"} for item in meeting_output.get("decisions", [])]
            decisions += [{"decision": item.get("task", ""), "owner": item.get("owner", ""), "due": item.get("due", ""), "type": "action"} for item in meeting_output.get("action_items", [])]
            meeting = CompanyMeeting(
                title=title,
                participants=json.dumps([{"id": x["id"], "title": x["title"], "department": x["department_name"]} for x in participants], ensure_ascii=False),
                minutes=full_minutes[:24000],
                decisions=json.dumps(decisions, ensure_ascii=False)[:12000],
                tokens=total_tokens,
            )
            core.db.session.add(meeting)
            core.db.session.commit()
            return jsonify({"ok": True, "meeting_id": meeting.id, "minutes": meeting.minutes,
                            "participants": participants, "tokens": meeting.tokens})
        except Exception:
            core.db.session.rollback()
            core.app.logger.exception("AI company meeting failed")
            return core.json_error("تعذر إنشاء محضر الاجتماع؛ راجع إعدادات الذكاء الاصطناعي", 502)

    @bp.get("/employee/<employee_id>")
    @core.login_required
    @core.admin_required
    def employee_detail(employee_id):
        employee = employee_map.get(employee_id)
        if not employee:
            return core.json_error("الموظف غير موجود", 404)
        tasks = CompanyTask.query.filter_by(employee_id=employee_id).order_by(CompanyTask.created_at.desc()).limit(20).all()
        return jsonify({"ok": True, "employee": employee, "tasks": [
            {"id": x.id, "title": x.title, "status": x.status, "result": x.result,
             "ceo_review": x.ceo_review, "created_at": core.iso(x.created_at)} for x in tasks
        ]})

    @bp.get("/company.css")
    @core.login_required
    @core.admin_required
    def company_css():
        return send_from_directory(os.path.dirname(__file__), "company.css")

    @bp.get("/company.js")
    @core.login_required
    @core.admin_required
    def company_js():
        return send_from_directory(os.path.dirname(__file__), "company.js")

    @bp.get("/company")
    @core.login_required
    @core.admin_required
    def company_page():
        return send_from_directory(os.path.dirname(__file__), "company.html")

    core.app.register_blueprint(bp, url_prefix="/api/ai-company")
    # Owner-friendly page and protected static assets; the API remains namespaced.
    core.app.add_url_rule("/company", endpoint="ai_company_owner_page", view_func=company_page)
    core.app.add_url_rule("/company.css", endpoint="ai_company_owner_css", view_func=company_css)
    core.app.add_url_rule("/company.js", endpoint="ai_company_owner_js", view_func=company_js)
    return {"CompanyTask": CompanyTask, "CompanyMeeting": CompanyMeeting, "employees": EMPLOYEES}
