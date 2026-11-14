"""Prewritten multilingual evergreen trading education for the public blog.

Content is educational, avoids performance promises, and is seeded idempotently.
"""
LANGUAGES = ("ar", "en", "es", "de", "id", "pt", "tr", "fr", "hi")

TOPICS = {
    "risk-management": {
        "ar": "إدارة مخاطر التداول",
        "en": "Trading Risk Management",
        "es": "Gestión del riesgo en trading",
        "de": "Risikomanagement beim Trading",
        "id": "Manajemen Risiko Trading",
        "pt": "Gestão de risco no trading",
        "tr": "İşlem Risk Yönetimi",
        "fr": "Gestion du risque en trading",
        "hi": "ट्रेडिंग में जोखिम प्रबंधन",
    },
    "stop-loss": {
        "ar": "كيف تحدد وقف الخسارة",
        "en": "How to Set a Stop-Loss",
        "es": "Cómo colocar un stop-loss",
        "de": "So setzt du einen Stop-Loss",
        "id": "Cara Menentukan Stop-Loss",
        "pt": "Como definir um stop-loss",
        "tr": "Zarar Durdur Nasıl Belirlenir?",
        "fr": "Comment définir un stop-loss",
        "hi": "स्टॉप-लॉस कैसे तय करें",
    },
    "position-sizing": {
        "ar": "حساب حجم الصفقة",
        "en": "How to Calculate Position Size",
        "es": "Cómo calcular el tamaño de una posición",
        "de": "Positionsgröße richtig berechnen",
        "id": "Cara Menghitung Ukuran Posisi",
        "pt": "Como calcular o tamanho da posição",
        "tr": "Pozisyon Büyüklüğü Nasıl Hesaplanır?",
        "fr": "Calculer la taille d'une position",
        "hi": "पोज़िशन का आकार कैसे तय करें",
    },
    "trend-analysis": {
        "ar": "تحليل الاتجاه في الأسواق",
        "en": "How to Read Market Trends",
        "es": "Cómo analizar las tendencias del mercado",
        "de": "Markttrends richtig erkennen",
        "id": "Cara Membaca Tren Pasar",
        "pt": "Como identificar tendências de mercado",
        "tr": "Piyasa Trendi Nasıl Okunur?",
        "fr": "Comment lire les tendances du marché",
        "hi": "बाज़ार के रुझान को कैसे समझें",
    },
    "volume-analysis": {
        "ar": "استخدام حجم التداول في التحليل",
        "en": "How to Use Trading Volume",
        "es": "Cómo utilizar el volumen de negociación",
        "de": "Handelsvolumen richtig nutzen",
        "id": "Cara Menggunakan Volume Perdagangan",
        "pt": "Como usar o volume de negociação",
        "tr": "İşlem Hacmi Nasıl Kullanılır?",
        "fr": "Utiliser le volume des échanges",
        "hi": "ट्रेडिंग वॉल्यूम का उपयोग कैसे करें",
    },
}

COPY = {
    "ar": {
        "summary": "دليل عملي لفهم {topic} وبناء خطة تداول أكثر انضباطاً، مع خطوات واضحة وأخطاء شائعة يجب تجنبها.",
        "p1": "يُعد موضوع «{topic}» جزءاً أساسياً من إعداد المتداول. الفكرة ليست التنبؤ بكل حركة في السوق، بل وضع قواعد مسبقة تساعدك على اتخاذ قرار مفهوم وقياس نتيجته. ابدأ بتحديد سبب الدخول، والشرط الذي يبطل الفكرة، والمدة التي تتوقع أن تحتاجها الصفقة.",
        "p2": "قبل التنفيذ، اكتب خطتك وحدد مقدار الخسارة المقبول، ثم راجع البيانات على أكثر من عينة تاريخية. لا تغيّر القواعد لمجرد أن صفقة واحدة انتهت بنتيجة غير متوقعة، ولا تعتمد على مؤشر منفرد دون سياق السعر والسيولة.",
        "p3": "تذكّر أن الأسواق متغيرة وأن الأمثلة التعليمية لا تضمن نتائج مستقبلية. استخدم حساباً تجريبياً عند اختبار أي أسلوب، واحتفظ بسجل يوضح سبب القرار والنتيجة والتكاليف.",
        "steps": "خطوات تطبيقية",
        "points": ["اكتب شروط الدخول والخروج قبل فتح الصفقة.", "حدد المخاطر والتكاليف والسيناريو الذي يلغي الفكرة.", "اختبر القواعد على بيانات كافية ثم راجع النتائج دورياً."],
        "warning": "هذا المحتوى تعليمي فقط، ولا يمثل توصية شراء أو بيع أو ضماناً للربح.",
    },
    "en": {
        "summary": "A practical guide to {topic}, with a repeatable trading process, useful checks, and common mistakes to avoid.",
        "p1": "{topic} is part of a disciplined trading process. The goal is not to predict every market move; it is to define rules before acting so each decision can be reviewed. Write down the reason for entry, the condition that invalidates the idea, and the expected holding period.",
        "p2": "Before placing a trade, document the plan and the acceptable loss, then review the method across a meaningful historical sample. Do not rewrite your rules because of one unexpected outcome, and avoid relying on a single indicator without price and liquidity context.",
        "p3": "Markets change, and educational examples cannot guarantee future results. Use a demo account when evaluating a method and keep a journal of the rationale, outcome, and trading costs.",
        "steps": "Practical checklist",
        "points": ["Define entry and exit conditions before opening a trade.", "Account for risk, costs, and the condition that invalidates the setup.", "Test the rules on sufficient data and review them regularly."],
        "warning": "This material is for education only. It is not a buy or sell recommendation or a promise of profit.",
    },
    "es": {
        "summary": "Guía práctica sobre {topic}, con un proceso repetible, comprobaciones útiles y errores frecuentes que conviene evitar.",
        "p1": "{topic} forma parte de una operativa disciplinada. El objetivo no es predecir cada movimiento, sino definir reglas antes de actuar para poder revisar cada decisión. Anota el motivo de entrada, la condición que invalida la idea y el tiempo previsto de la operación.",
        "p2": "Antes de operar, documenta el plan y la pérdida aceptable; después, evalúa el método con una muestra histórica suficiente. No cambies las reglas por un único resultado inesperado ni dependas de un indicador aislado sin contexto de precio y liquidez.",
        "p3": "Los mercados cambian y los ejemplos educativos no garantizan resultados futuros. Utiliza una cuenta demo para evaluar cualquier método y registra el motivo, el resultado y los costes de cada operación.",
        "steps": "Lista práctica",
        "points": ["Define las condiciones de entrada y salida antes de operar.", "Considera el riesgo, los costes y la condición que invalida la estrategia.", "Prueba las reglas con datos suficientes y revísalas periódicamente."],
        "warning": "Este contenido es educativo y no constituye una recomendación de compra o venta ni garantiza beneficios.",
    },
    "de": {
        "summary": "Ein praxisnaher Leitfaden zu {topic} mit einem wiederholbaren Ablauf, wichtigen Prüfungen und typischen Fehlern.",
        "p1": "{topic} gehört zu einem disziplinierten Handelsprozess. Es geht nicht darum, jede Marktbewegung vorherzusagen, sondern Regeln vor der Entscheidung festzulegen. Notiere den Einstiegsgrund, die Bedingung für eine ungültige Idee und den geplanten Zeithorizont.",
        "p2": "Dokumentiere vor dem Handel den Plan und den akzeptablen Verlust. Prüfe die Methode anschließend anhand einer ausreichend großen historischen Stichprobe. Ändere Regeln nicht wegen eines einzelnen unerwarteten Ergebnisses und nutze Indikatoren nie ohne Preis- und Liquiditätskontext.",
        "p3": "Märkte verändern sich; Lernbeispiele garantieren keine zukünftigen Ergebnisse. Teste Methoden zunächst im Demokonto und protokolliere Begründung, Ergebnis und Handelskosten.",
        "steps": "Praktische Checkliste",
        "points": ["Lege Ein- und Ausstiegsbedingungen vor dem Trade fest.", "Berücksichtige Risiko, Kosten und das Ungültigkeitssignal.", "Teste die Regeln mit genügend Daten und überprüfe sie regelmäßig."],
        "warning": "Dieser Inhalt dient ausschließlich Bildungszwecken und ist weder eine Kauf- oder Verkaufsempfehlung noch eine Gewinngarantie.",
    },
    "id": {
        "summary": "Panduan praktis tentang {topic}, dengan proses trading yang konsisten, pemeriksaan penting, dan kesalahan umum yang perlu dihindari.",
        "p1": "{topic} merupakan bagian dari proses trading yang disiplin. Tujuannya bukan menebak setiap pergerakan pasar, melainkan menetapkan aturan sebelum mengambil tindakan agar keputusan dapat dievaluasi. Catat alasan masuk, kondisi yang membatalkan ide, dan perkiraan durasi posisi.",
        "p2": "Sebelum melakukan transaksi, tulis rencana dan batas kerugian yang dapat diterima. Uji metode menggunakan sampel data historis yang memadai. Jangan mengubah aturan hanya karena satu hasil yang tidak terduga, dan jangan memakai satu indikator tanpa konteks harga serta likuiditas.",
        "p3": "Pasar selalu berubah dan contoh edukasi tidak menjamin hasil di masa depan. Gunakan akun demo untuk menguji metode dan catat alasan, hasil, serta biaya setiap transaksi.",
        "steps": "Daftar pemeriksaan",
        "points": ["Tentukan syarat masuk dan keluar sebelum membuka posisi.", "Perhitungkan risiko, biaya, dan kondisi yang membatalkan setup.", "Uji aturan dengan data yang cukup dan tinjau secara berkala."],
        "warning": "Konten ini hanya untuk edukasi, bukan rekomendasi beli atau jual dan bukan jaminan keuntungan.",
    },
    "pt": {
        "summary": "Um guia prático sobre {topic}, com um processo repetível, verificações úteis e erros comuns que devem ser evitados.",
        "p1": "{topic} faz parte de uma rotina disciplinada de negociação. O objetivo não é prever cada movimento do mercado, mas definir regras antes de agir para que cada decisão possa ser avaliada. Registre o motivo da entrada, a condição que invalida a ideia e o prazo esperado da operação.",
        "p2": "Antes de operar, documente o plano e a perda aceitável. Depois, avalie o método com uma amostra histórica suficiente. Não altere as regras por causa de um único resultado inesperado e não dependa de um indicador isolado sem considerar preço e liquidez.",
        "p3": "Os mercados mudam e exemplos educativos não garantem resultados futuros. Use uma conta de demonstração para testar métodos e registre a justificativa, o resultado e os custos de cada operação.",
        "steps": "Lista prática",
        "points": ["Defina as condições de entrada e saída antes da operação.", "Considere risco, custos e a condição que invalida a configuração.", "Teste as regras com dados suficientes e revise os resultados regularmente."],
        "warning": "Este conteúdo é apenas educativo; não é recomendação de compra ou venda nem garantia de lucro.",
    },
    "tr": {
        "summary": "{topic} hakkında tekrarlanabilir bir işlem süreci, önemli kontroller ve kaçınılması gereken yaygın hataları içeren pratik rehber.",
        "p1": "{topic}, disiplinli bir işlem sürecinin parçasıdır. Amaç piyasadaki her hareketi tahmin etmek değil, karar vermeden önce kurallar belirleyerek sonuçları değerlendirebilmektir. İşleme giriş nedenini, fikri geçersiz kılan koşulu ve beklenen pozisyon süresini yazın.",
        "p2": "İşlemden önce planınızı ve kabul edilebilir kaybı belirleyin. Yöntemi yeterli büyüklükte tarihsel veriyle inceleyin. Tek bir beklenmedik sonuç nedeniyle kuralları değiştirmeyin; fiyat ve likidite bağlamı olmadan tek bir göstergeye güvenmeyin.",
        "p3": "Piyasalar değişir ve eğitim amaçlı örnekler gelecekteki sonuçları garanti etmez. Yöntemleri deneme hesabında test edin; gerekçeyi, sonucu ve işlem maliyetlerini kaydedin.",
        "steps": "Uygulama kontrol listesi",
        "points": ["İşleme girmeden önce giriş ve çıkış koşullarını belirleyin.", "Riski, maliyetleri ve kurulumu geçersiz kılan koşulu hesaba katın.", "Kuralları yeterli veriyle test edin ve düzenli olarak gözden geçirin."],
        "warning": "Bu içerik yalnızca eğitim amaçlıdır; alım veya satım tavsiyesi ya da kâr garantisi değildir.",
    },
    "fr": {
        "summary": "Un guide pratique sur {topic}, avec une méthode reproductible, des vérifications utiles et les erreurs courantes à éviter.",
        "p1": "{topic} fait partie d'une démarche de trading disciplinée. Le but n'est pas de prévoir chaque mouvement du marché, mais de définir des règles avant d'agir afin de pouvoir évaluer chaque décision. Notez la raison de l'entrée, la condition qui invalide l'idée et la durée envisagée.",
        "p2": "Avant toute opération, consignez le plan et la perte acceptable. Évaluez ensuite la méthode sur un échantillon historique suffisant. Ne modifiez pas vos règles après un seul résultat inattendu et ne vous fiez pas à un indicateur isolé sans contexte de prix et de liquidité.",
        "p3": "Les marchés évoluent et les exemples pédagogiques ne garantissent aucun résultat futur. Testez une méthode sur un compte de démonstration et consignez le raisonnement, le résultat et les frais.",
        "steps": "Liste de vérification",
        "points": ["Définissez les conditions d'entrée et de sortie avant l'opération.", "Prenez en compte le risque, les frais et le signal d'invalidation.", "Testez les règles sur suffisamment de données et révisez-les régulièrement."],
        "warning": "Ce contenu est fourni à titre éducatif uniquement. Il ne constitue pas un conseil d'achat ou de vente ni une garantie de gain.",
    },
    "hi": {
        "summary": "{topic} पर व्यावहारिक मार्गदर्शिका, जिसमें दोहराई जा सकने वाली ट्रेडिंग प्रक्रिया, ज़रूरी जाँच और आम गलतियों से बचने के तरीके शामिल हैं।",
        "p1": "{topic} अनुशासित ट्रेडिंग प्रक्रिया का एक हिस्सा है। उद्देश्य बाज़ार की हर चाल का अनुमान लगाना नहीं, बल्कि निर्णय से पहले नियम तय करना है ताकि हर फैसले की समीक्षा की जा सके। एंट्री का कारण, उस शर्त को लिखें जो विचार को अमान्य करती है, और अपेक्षित अवधि तय करें।",
        "p2": "ट्रेड से पहले योजना और स्वीकार्य नुकसान लिखें। फिर पर्याप्त ऐतिहासिक डेटा पर तरीके की जाँच करें। एक अप्रत्याशित परिणाम के कारण नियम न बदलें और कीमत तथा लिक्विडिटी के संदर्भ के बिना किसी एक इंडिकेटर पर निर्भर न रहें।",
        "p3": "बाज़ार बदलते रहते हैं और शैक्षिक उदाहरण भविष्य के परिणामों की गारंटी नहीं देते। किसी तरीके को डेमो खाते पर जाँचें और कारण, परिणाम तथा ट्रेडिंग लागत का रिकॉर्ड रखें।",
        "steps": "व्यावहारिक जाँच सूची",
        "points": ["ट्रेड खोलने से पहले एंट्री और एग्ज़िट की शर्तें तय करें।", "जोखिम, लागत और सेटअप को अमान्य करने वाली स्थिति शामिल करें।", "पर्याप्त डेटा पर नियमों का परीक्षण करें और नियमित समीक्षा करें।"],
        "warning": "यह सामग्री केवल शिक्षा के लिए है; यह खरीद या बिक्री की सलाह अथवा लाभ की गारंटी नहीं है।",
    },
}

def build_blog_seed():
    rows = []
    for topic_slug, localized_titles in TOPICS.items():
        for language in LANGUAGES:
            topic = localized_titles[language]
            copy = COPY[language]
            title = topic + " | SMART TRADING PRO"
            summary = copy["summary"].format(topic=topic)
            body = "\n\n".join([
                copy["p1"].format(topic=topic),
                copy["p2"].format(topic=topic),
                copy["steps"] + ":\n" + "\n".join("• " + item for item in copy["points"]),
                copy["p3"],
                copy["warning"],
            ])
            slug = topic_slug + "-" + language
            rows.append({
                "kind": "blog",
                "title": title,
                "slug": slug,
                "summary": summary,
                "body": body,
                "published": True,
                "language": language,
                "meta_title": (topic + " | SMART TRADING PRO")[:70],
                "meta_description": summary[:170],
                "canonical_slug": topic_slug,
            })
    return rows

def seed_blog_articles(article_model, database):
    """Insert missing localized articles without overwriting editor changes."""
    inserted = 0
    for item in build_blog_seed():
        exists = article_model.query.filter_by(slug=item["slug"]).first()
        if exists:
            continue
        database.session.add(article_model(**item))
        inserted += 1
    if inserted:
        database.session.commit()
    return inserted
