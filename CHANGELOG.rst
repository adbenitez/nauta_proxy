Nauta Proxy
***********

0.7.0
-----

- if an SMTP client try to send a message bigger than a few KB, don't read whole message at once, to avoid timeouts. `4a0ef49`_
- allow to select folder to empty. `ccedbaf`_
- emptying a folder and checking server stats now also works with the proxy stopped. `b907260`_
- add "Chat-Version" header to classic emails. `c25b088`_
- ignore some mailing list headers to get mailing list displayed on Delta Chat. `c906ed4`_
