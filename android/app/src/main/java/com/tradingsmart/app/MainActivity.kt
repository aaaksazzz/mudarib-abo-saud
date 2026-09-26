package com.tradingsmart.app

import android.annotation.SuppressLint
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.webkit.WebResourceRequest
import android.webkit.WebResourceError
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity

class MainActivity : ComponentActivity() {
    private lateinit var web: WebView
    private lateinit var errorView: LinearLayout

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.rgb(7, 17, 31))
        }

        errorView = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = android.view.Gravity.CENTER
            setPadding(40, 40, 40, 40)
            visibility = View.GONE
        }

        val title = TextView(this).apply {
            text = "التداول ذكي"
            textSize = 28f
            setTextColor(Color.WHITE)
            gravity = android.view.Gravity.CENTER
        }

        val message = TextView(this).apply {
            text = "تعذر الاتصال بالموقع حالياً"
            textSize = 16f
            setTextColor(Color.LTGRAY)
            gravity = android.view.Gravity.CENTER
            setPadding(0, 20, 0, 24)
        }

        val retry = Button(this).apply {
            text = "إعادة المحاولة"
            setOnClickListener { loadSite() }
        }

        errorView.addView(title)
        errorView.addView(message)
        errorView.addView(retry)
        root.addView(errorView, LinearLayout.LayoutParams(-1, -1))

        web = WebView(this)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            cacheMode = WebSettings.LOAD_DEFAULT
            mediaPlaybackRequiresUserGesture = false
            builtInZoomControls = false
            displayZoomControls = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = "$userAgentString TradingSmartAndroid/1.0"
        }
        web.setBackgroundColor(Color.rgb(7, 17, 31))
        web.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                errorView.visibility = View.GONE
                web.visibility = View.VISIBLE
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                if (request?.isForMainFrame == true) showError()
            }

            override fun onReceivedHttpError(view: WebView?, request: WebResourceRequest?, errorResponse: android.webkit.WebResourceResponse?) {
                if (request?.isForMainFrame == true && (errorResponse?.statusCode ?: 200) >= 500) showError()
            }
        }

        root.addView(web, LinearLayout.LayoutParams(-1, 0, 1f))
        setContentView(root)
        loadSite()
    }

    private fun loadSite() {
        errorView.visibility = View.GONE
        web.visibility = View.VISIBLE
        web.loadUrl("https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/")
    }

    private fun showError() {
        web.visibility = View.GONE
        errorView.visibility = View.VISIBLE
    }

    @Deprecated("Deprecated in Android SDK")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        web.stopLoading()
        web.destroy()
        super.onDestroy()
    }
}
