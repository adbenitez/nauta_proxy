Nauta Proxy
***********

0.7.0
-----

- if an SMTP client try to send a message bigger than a few KB, don't read whole message at once, to avoid timeouts. `4a0ef49`_
