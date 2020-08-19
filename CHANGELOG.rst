Changelog
*********

0.10.0
------
- fixed server stats, script was expecting bytes but server was sending KB
- added option to expunge a folder, to help purge folders with the new auto-delete feature in DC clients
- added auto-expunge inbox periodically
- added new mode "Lite+" that removes the "Chat-Version" header from outgoing messages


0.9.0
-----
- better code organization
- fixed autocrypt header parsing and improved parsing for other headers
- process headers only if an outgoing message is detected
- reduce deceived amount of bytes per request to avoid timeouts when sending "big" attachments
- added option to upgrade app without havig to use the command line
- refresh other stats before starting to check server stats


0.8.0
-----
- **Chat-Version** header is not added to classic emails anymore
- mailing lists are not displayed anymore


0.7.1
-----
- fix bug when receiving classic emails. `ffe0318`_


0.7.0
-----
- if an SMTP client try to send a message bigger than a few KB, don't read whole message at once, to avoid timeouts. `4a0ef49`_
- allow to select folder to empty. `ccedbaf`_
- emptying a folder and checking server stats now also works with the proxy stopped. `b907260`_
- add "Chat-Version" header to classic emails. `c25b088`_
- ignore some mailing list headers to get mailing list displayed on Delta Chat. `c906ed4`_
