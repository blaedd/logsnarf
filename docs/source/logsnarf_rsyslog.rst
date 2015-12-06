==================
RSYSLOG
==================

format more easily used by logsnarf, and BigQuery. No claims are made regarding the optimality of these configurations,
but should serve as a starting point for those interested.

mm_normalize
============
This performs some feature extraction on ssh and dhcp logs. Populating the additional fields and subrecords.

.. literalinclude:: examples/lognorm.rulebase

rsyslog
=======
This configuration fragment provides a ruleset that runs incoming logs through the mm_normalize module, performs some
sanity checking on log times (largely for devices without an internal RTC, who always provide bad times on boot, until
time is synchronized), generates a table name for logsnarf, and populates some of the JSON fields manually from syslog
fields. The easiest way to use this is to assign the ruleset to an input then initializing the input with the rulebase.
For example::

   input(type="imudp" port="514" ruleset="remote")

This needs to be declared after the rulebase, as per normal, however.

.. literalinclude:: examples/logsnarf-rsyslog.conf