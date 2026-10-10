(function () {
  if (window.__smartTradingLanguageLoaded) return;
  window.__smartTradingLanguageLoaded = true;

  function mountLanguagePicker() {
    if (document.getElementById("st-language-wrap")) return;
    const style = document.createElement("style");
    style.textContent = `
      #st-language-wrap{display:flex;align-items:center;gap:7px;z-index:90;margin-inline-start:8px}
      #st-language-wrap .st-lang-label{font-size:11px;color:#9db4ca;white-space:nowrap}
      #google_translate_element{max-width:190px;overflow:hidden}
      #google_translate_element .goog-te-gadget{font:12px system-ui,sans-serif!important;color:#c5d6e7!important}
      #google_translate_element .goog-te-gadget span{display:none!important}
      #google_translate_element select{width:auto;max-width:190px;min-height:34px;padding:5px 24px 5px 8px;border:1px solid #29435d;border-radius:9px;background:#0b1b2c;color:#f1f6fd;font-size:12px}
      .goog-te-banner-frame{display:none!important}body{top:0!important}
      @media(max-width:520px){#st-language-wrap{margin-inline-start:3px}#st-language-wrap .st-lang-label{display:none}#google_translate_element select{max-width:125px;font-size:11px}}
    `;
    document.head.appendChild(style);
    const wrap = document.createElement("div");
    wrap.id = "st-language-wrap";
    wrap.setAttribute("aria-label", "Choose website language");
    wrap.innerHTML = '<span class="st-lang-label">🌐 اللغة</span><div id="google_translate_element"></div>';
    const header = document.querySelector(".top-actions") || document.querySelector(".topbar") || document.body;
    header.appendChild(wrap);

    window.googleTranslateElementInit = function () {
      if (!window.google || !google.translate || !google.translate.TranslateElement) return;
      new google.translate.TranslateElement({
        pageLanguage: "ar",
        autoDisplay: false,
        layout: google.translate.TranslateElement.InlineLayout.SIMPLE
      }, "google_translate_element");
    };
    const script = document.createElement("script");
    script.src = "https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit";
    script.async = true;
    script.onerror = function () {
      const el = document.getElementById("google_translate_element");
      if (el) el.textContent = "الترجمة غير متاحة حالياً";
    };
    document.head.appendChild(script);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountLanguagePicker, {once:true});
  else mountLanguagePicker();
})();