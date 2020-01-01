Nauta Proxy
===========

Allows to setup a local proxy to do MITM to Delta Chat and the Nauta email server, to save data traffic and provide some stats.

You must configure your Delta Chat application as follow:

* IMAP server: 127.0.0.1
* IMAP port: 8082
* SMTP server: 127.0.0.1
* SMTP port: 8081

**NOTE:** This package is intended to be installed inside Termux on Android.


Instructions
------------

1. Install Termux, Termux:API and Termux:Widget apks.
2. Open Termux and execute: `pkg install termux-api python && pip install nauta_proxy`
3. After that a notificiation should be dispalyed, tap the notification or the "Start" button to run the proxy.
   Also the command `nauta-proxy` will be available, and script `Nauta-Proxy` will be available in your Termux widget.
4. Tap the Nauta Proxy notification or the "Options" button to see the app's menu.
