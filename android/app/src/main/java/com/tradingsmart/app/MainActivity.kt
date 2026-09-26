package com.tradingsmart.app
import android.os.Bundle
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
class MainActivity: ComponentActivity() {
 private lateinit var web: WebView
 override fun onCreate(savedInstanceState: Bundle?) {
  super.onCreate(savedInstanceState)
  web=WebView(this)
  web.settings.javaScriptEnabled=true
  web.settings.domStorageEnabled=true
  web.settings.loadsImagesAutomatically=true
  web.webViewClient=WebViewClient()
  web.loadUrl("https://web--mudarib-abo-saud--bn5qcyddt9b4.code.run/")
  setContentView(web)
 }
 override fun onBackPressed(){ if(web.canGoBack()) web.goBack() else super.onBackPressed() }
}
